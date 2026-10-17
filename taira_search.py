#!/usr/bin/env python3
"""BM25/FTS5 search and neighbouring-context CLI for local research corpora."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

from metadata_utils import load_people, load_source_types, person_variants
from search_schema import (
    ensure_search_schema,
    prepare_fts_text,
    search_schema_is_current,
)
from text_utils import make_preview, normalize_text, unique_normalized


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = PROJECT_DIR / "taira_index.sqlite3"
DEFAULT_ALIASES = PROJECT_DIR / "aliases.json"
DEFAULT_TOPICS = PROJECT_DIR / "topics.json"
DEFAULT_PEOPLE = PROJECT_DIR / "people.json"
DEFAULT_SOURCE_TYPES = PROJECT_DIR / "source_types.json"
DEFAULT_USED_FINDS = PROJECT_DIR / "used_finds.csv"
DEFAULT_RESEARCH_PROFILE = PROJECT_DIR / "research_profile.json"
DEFAULT_DAILY_OUTPUT = PROJECT_DIR / "daily_five_candidates.json"
DEFAULT_RESEARCH_OUTPUT = PROJECT_DIR / "research_candidates.json"
DEFAULT_EVENT_CARDS = PROJECT_DIR / "event_cards.json"
DEFAULT_SOURCE_NOTES = PROJECT_DIR / "source_notes.json"
SOURCE_TYPES = ("historical", "scholarship", "literary", "other")
QUALITIES = ("good", "garbled", "no_text")
JAPANESE_RUN_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
SIMPLE_NEAR_RE = re.compile(
    r"^\s*(\S+)\s+NEAR(?:/(\d+))?\s+(\S+)\s*$", re.IGNORECASE
)


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def load_mapping(path: Path, label: str) -> dict[str, list[str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Не найден {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ошибка JSON в {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"{path}: ожидается JSON-объект")
    result: dict[str, list[str]] = {}
    for key, values in raw.items():
        if not isinstance(key, str) or not isinstance(values, list):
            raise RuntimeError(f"{path}: ожидаются списки строк")
        if not all(isinstance(value, str) for value in values):
            raise RuntimeError(f"{path}: ожидаются списки строк")
        result[key] = values
    return result


def fts_phrase(value: str) -> str:
    prepared = prepare_fts_text(normalize_text(value))
    return '"' + prepared.replace('"', '""') + '"'


def _compile_segment(segment: str) -> str:
    return JAPANESE_RUN_RE.sub(lambda match: fts_phrase(match.group(0)), segment)


def compile_fts_query(raw: str) -> str:
    """Preserve FTS5 syntax and adapt Japanese words to the CJK token index."""
    raw = raw.strip()
    near = SIMPLE_NEAR_RE.fullmatch(raw)
    if near:
        distance = int(near.group(2) or 10)
        return f"NEAR({fts_phrase(near.group(1))} {fts_phrase(near.group(3))}, {distance})"

    parts: list[str] = []
    position = 0
    for match in re.finditer(r'"((?:[^"]|"")*)"', raw):
        parts.append(_compile_segment(raw[position : match.start()]))
        phrase = match.group(1).replace('""', '"')
        parts.append(fts_phrase(phrase))
        position = match.end()
    parts.append(_compile_segment(raw[position:]))
    return "".join(parts)


def extract_terms(raw: str | None) -> list[str]:
    if not raw:
        return []
    operators = {"AND", "OR", "NOT", "NEAR"}
    terms: list[str] = []
    for token in re.findall(r"[\w\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]+", raw):
        if token.upper() not in operators and not token.isdigit():
            terms.append(normalize_text(token))
    return unique_normalized(terms)


def make_snippet(text: str, terms: list[str], limit: int = 520) -> str:
    compact = normalize_text(text)
    folded = compact.casefold()
    positions = [
        folded.find(term.casefold())
        for term in terms
        if term and folded.find(term.casefold()) >= 0
    ]
    if not positions:
        return make_preview(compact, limit)
    start = max(0, min(positions) - limit // 3)
    end = min(len(compact), start + limit)
    snippet = compact[start:end].strip()
    return ("…" if start else "") + snippet + ("…" if end < len(compact) else "")


def _placeholders(count: int) -> str:
    return ",".join("?" for _ in range(count))


def build_search_plan(
    args: argparse.Namespace,
    topics: dict[str, list[str]],
    people: dict[str, dict[str, Any]],
    *,
    events_only: bool,
) -> tuple[str | None, list[str], list[str], list[str], list[Any]]:
    expressions: list[str] = []
    snippet_terms = extract_terms(args.query)
    if args.query:
        expressions.append(f"({compile_fts_query(args.query)})")

    for topic_name in args.topic:
        if topic_name not in topics:
            raise ValueError(
                f"Неизвестная тема {topic_name!r}. Доступны: {', '.join(sorted(topics))}"
            )
        terms = unique_normalized(topics[topic_name])
        expressions.append("(" + " OR ".join(fts_phrase(term) for term in terms) + ")")
        snippet_terms.extend(terms)

    person_labels: list[str] = []
    person_expression: list[str] = []
    for requested in args.person:
        canonical, variants = person_variants(people, requested)
        person_labels.append(canonical)
        person_expression.extend(fts_phrase(term) for term in variants)
        snippet_terms.extend(variants)
    if person_expression:
        expressions.append("(" + " OR ".join(unique_normalized(person_expression)) + ")")

    clauses: list[str] = []
    params: list[Any] = []
    if not args.include_duplicates:
        clauses.append("c.is_duplicate=0")
    if person_labels:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(c.people_json) p "
            f"WHERE p.value IN ({_placeholders(len(person_labels))}))"
        )
        params.extend(person_labels)
    if events_only:
        clauses.append("c.people_json <> '[]'")
    for topic_name in args.topic:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(c.topics_json) t WHERE t.value=?)"
        )
        params.append(topic_name)
    if args.source_type:
        clauses.append(f"c.source_type IN ({_placeholders(len(args.source_type))})")
        params.extend(args.source_type)
    if args.exclude_source_type:
        clauses.append(
            f"c.source_type NOT IN ({_placeholders(len(args.exclude_source_type))})"
        )
        params.extend(args.exclude_source_type)
    if args.quality:
        clauses.append(f"c.text_quality IN ({_placeholders(len(args.quality))})")
        params.extend(args.quality)
    for source in args.source:
        clauses.append("instr(py_casefold(c.source), ?) > 0")
        params.append(source.casefold())
    for source in args.exclude_source:
        clauses.append("instr(py_casefold(c.source), ?) = 0")
        params.append(source.casefold())
    return (
        " AND ".join(expressions) if expressions else None,
        clauses,
        unique_normalized(snippet_terms),
        person_labels,
        params,
    )


def search_database(
    connection: sqlite3.Connection,
    args: argparse.Namespace,
    topics: dict[str, list[str]],
    people: dict[str, dict[str, Any]],
    *,
    events_only: bool = False,
) -> list[dict[str, Any]]:
    match, clauses, snippet_terms, _person_labels, filter_params = build_search_plan(
        args, topics, people, events_only=events_only
    )
    where = " AND ".join(clauses) if clauses else "1=1"
    if match:
        sql = f"""
            SELECT c.*,
                   bm25(chunks_fts, 0.0, 1.0, 0.2, 2.5, 2.0) AS raw_bm25
            FROM chunks_fts
            JOIN chunks c ON c.chunk_id=chunks_fts.chunk_id
            WHERE chunks_fts MATCH ? AND {where}
            ORDER BY raw_bm25, c.relative_path, c.chunk_no
            LIMIT ? OFFSET ?
        """
        rows = connection.execute(
            sql, [match, *filter_params, args.top, args.offset]
        ).fetchall()
    else:
        sql = f"""
            SELECT c.*, 0.0 AS raw_bm25
            FROM chunks c
            WHERE {where}
            ORDER BY c.source, c.relative_path, c.chunk_no
            LIMIT ? OFFSET ?
        """
        rows = connection.execute(sql, [*filter_params, args.top, args.offset]).fetchall()

    meta = dict(connection.execute("SELECT key, value FROM meta"))
    corpus_root = meta.get("corpus_root", "")
    results: list[dict[str, Any]] = []
    for rank, row in enumerate(rows, start=args.offset + 1):
        original = row["original_text"]
        relative_path = row["relative_path"]
        result = {
            "rank": rank,
            "chunk_id": row["chunk_id"],
            "score": -float(row["raw_bm25"]),
            "source": row["source"],
            "filename": row["filename"],
            "path": str(Path(corpus_root) / Path(relative_path)) if corpus_root else relative_path,
            "relative_path": relative_path,
            "page_start": row["page_start"],
            "page_end": row["page_end"],
            "chunk_no": row["chunk_no"],
            "people": json.loads(row["people_json"]),
            "topics": json.loads(row["topics_json"]),
            "source_type": row["source_type"],
            "text_quality": row["text_quality"],
            "snippet": make_snippet(original, snippet_terms),
        }
        results.append(result)
    return results


def format_pages(start: int | None, end: int | None) -> str:
    if start is None:
        return "—"
    if end is None or end == start:
        return str(start)
    return f"{start}–{end}"


def print_results(results: list[dict[str, Any]], *, json_output: bool) -> None:
    if json_output:
        for result in results:
            print(json.dumps(result, ensure_ascii=False))
        return
    if not results:
        print("Ничего не найдено.")
        return
    for result in results:
        print(f"[{result['rank']}] score={result['score']:.6f}  chunk_id={result['chunk_id']}")
        print(
            f"source: {result['source']}  type: {result['source_type']}  "
            f"quality: {result['text_quality']}"
        )
        print(f"file: {result['filename']}")
        print(f"path: {result['path']}")
        print(
            f"page: {format_pages(result['page_start'], result['page_end'])}  "
            f"chunk: {result['chunk_no']}"
        )
        print(f"people: {', '.join(result['people']) or '—'}")
        print(f"topics: {', '.join(result['topics']) or '—'}")
        print(f"snippet: {result['snippet']}")
        print("-----")


def context_rows(
    connection: sqlite3.Connection, chunk_id: str, before: int, after: int
) -> list[dict[str, Any]]:
    target = connection.execute(
        "SELECT * FROM chunks WHERE chunk_id=?", (chunk_id,)
    ).fetchone()
    if target is None:
        raise ValueError(f"Chunk не найден: {chunk_id}")
    rows = connection.execute(
        """
        SELECT * FROM chunks
        WHERE relative_path=? AND chunk_no BETWEEN ? AND ?
        ORDER BY chunk_no
        """,
        (
            target["relative_path"],
            max(1, int(target["chunk_no"]) - before),
            int(target["chunk_no"]) + after,
        ),
    ).fetchall()
    meta = dict(connection.execute("SELECT key, value FROM meta"))
    corpus_root = meta.get("corpus_root", "")
    return [
        {
            "target": row["chunk_id"] == chunk_id,
            "chunk_id": row["chunk_id"],
            "source": row["source"],
            "filename": row["filename"],
            "path": str(Path(corpus_root) / Path(row["relative_path"]))
            if corpus_root
            else row["relative_path"],
            "page_start": row["page_start"],
            "page_end": row["page_end"],
            "chunk_no": row["chunk_no"],
            "people": json.loads(row["people_json"]),
            "topics": json.loads(row["topics_json"]),
            "source_type": row["source_type"],
            "text_quality": row["text_quality"],
            "text": row["original_text"],
        }
        for row in rows
    ]


def print_context(rows: list[dict[str, Any]], *, json_output: bool) -> None:
    if json_output:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
        return
    for row in rows:
        marker = "TARGET" if row["target"] else "CONTEXT"
        print(
            f"[{marker}] {row['chunk_id']}  chunk={row['chunk_no']}  "
            f"page={format_pages(row['page_start'], row['page_end'])}"
        )
        print(f"source: {row['source']}  file: {row['filename']}")
        print(row["text"])
        print("-----")


def add_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Путь к SQLite")
    parser.add_argument("--aliases", default=str(DEFAULT_ALIASES))
    parser.add_argument("--topics-config", default=str(DEFAULT_TOPICS))
    parser.add_argument("--people-config", default=str(DEFAULT_PEOPLE))
    parser.add_argument("--source-types-config", default=str(DEFAULT_SOURCE_TYPES))


def add_search_arguments(parser: argparse.ArgumentParser) -> None:
    add_config_arguments(parser)
    parser.add_argument("--query", help="Текст или выражение SQLite FTS5")
    parser.add_argument("--topic", action="append", default=[], help="Тема; можно повторять")
    parser.add_argument("--person", action="append", default=[], help="Персонаж; можно повторять")
    parser.add_argument(
        "--source-type", action="append", choices=SOURCE_TYPES, default=[]
    )
    parser.add_argument(
        "--exclude-source-type", action="append", choices=SOURCE_TYPES, default=[]
    )
    parser.add_argument("--source", action="append", default=[], help="Включить источник")
    parser.add_argument(
        "--exclude-source", action="append", default=[], help="Исключить источник"
    )
    parser.add_argument("--quality", action="append", choices=QUALITIES, default=[])
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true", help="Вывести JSON Lines")
    parser.add_argument("--include-duplicates", action="store_true")


def _paths_refer_to_same_file(left: Path, right: Path) -> bool:
    """Compare normalized paths and existing aliases such as links/hard links."""
    left_resolved = left.expanduser().resolve(strict=False)
    right_resolved = right.expanduser().resolve(strict=False)
    if os.path.normcase(os.fspath(left_resolved)) == os.path.normcase(
        os.fspath(right_resolved)
    ):
        return True
    try:
        return left_resolved.samefile(right_resolved)
    except (FileNotFoundError, OSError):
        return False


def validate_research_output_path(args: argparse.Namespace) -> None:
    """Prevent candidate JSON from replacing any input needed by the command."""
    output = Path(args.output)
    editorial_output = (
        Path(args.editorial_output)
        if args.editorial_output
        else output.with_name(f"{output.stem}.editorial.json")
    )
    protected_inputs = [
        ("--db", Path(args.db)),
        ("--profile", Path(args.profile)),
        ("--used-finds", Path(args.used_finds)),
        ("--aliases", Path(args.aliases)),
        ("--topics-config", Path(args.topics_config)),
        ("--people-config", Path(args.people_config)),
        ("--source-types-config", Path(args.source_types_config)),
    ]
    protected_inputs.extend(
        ("--continue-from", Path(path)) for path in args.continue_from
    )
    for label, candidate_output in (
        ("--output", output),
        ("--editorial-output", editorial_output),
    ):
        for option, input_path in protected_inputs:
            if _paths_refer_to_same_file(candidate_output, input_path):
                raise ValueError(
                    f"Небезопасный {label}: путь совпадает с критичным входным "
                    f"файлом {option} после нормализации: "
                    f"{input_path.expanduser().resolve(strict=False)}"
                )
    if _paths_refer_to_same_file(output, editorial_output):
        raise ValueError("--output и --editorial-output должны быть разными файлами")


def check_publication_access(db_path: Path, used_path: Path) -> dict[str, Any]:
    """Prove read and atomic-write access without touching the journal or lock."""
    db_path = db_path.expanduser().resolve()
    used_path = used_path.expanduser().resolve()
    if not db_path.is_file():
        raise RuntimeError(f"Индекс не найден: {db_path}")
    try:
        connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            cursor = connection.execute("SELECT 1")
            try:
                cursor.fetchone()
            finally:
                cursor.close()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Нет доступа на чтение SQLite {db_path}: {exc}") from exc

    if used_path.exists():
        try:
            with used_path.open("rb") as stream:
                stream.read(1)
        except OSError as exc:
            raise RuntimeError(
                f"Нет доступа на чтение журнала {used_path}: {exc}"
            ) from exc
    parent = used_path.parent
    source_path: Path | None = None
    target_path: Path | None = None
    try:
        descriptor, source_name = tempfile.mkstemp(
            prefix=".taira-write-check.", suffix=".tmp", dir=parent
        )
        source_path = Path(source_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(b"tairasearch-write-check\n")
            stream.flush()
            os.fsync(stream.fileno())
        descriptor, target_name = tempfile.mkstemp(
            prefix=".taira-rename-check.", suffix=".tmp", dir=parent
        )
        os.close(descriptor)
        target_path = Path(target_name)
        os.replace(source_path, target_path)
        source_path = None
        if target_path.read_bytes() != b"tairasearch-write-check\n":
            raise RuntimeError(
                "Проверка атомарного переименования вернула неверные данные"
            )
    except OSError as exc:
        raise RuntimeError(
            "Каталог журнала недоступен для безопасной записи и атомарного "
            f"переименования: {parent}. Проверьте, что этот путь присутствует в "
            "эффективных writable roots именно текущего окружения Codex, а не "
            f"только в config.toml. Исходная ошибка: {exc}"
        ) from exc
    finally:
        if source_path is not None:
            source_path.unlink(missing_ok=True)
        if target_path is not None:
            target_path.unlink(missing_ok=True)
    return {
        "status": "ok",
        "python": sys.executable,
        "sqlite_read": str(db_path),
        "journal_read": str(used_path),
        "journal_directory_atomic_write": str(parent),
        "journal_and_lock_unchanged": True,
        "environment_note": (
            "This result applies only to the process environment that ran the check."
        ),
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Локальный FTS5-поиск по корпусу")
    subparsers = parser.add_subparsers(dest="command", required=True)
    search_parser = subparsers.add_parser("search", help="Поиск с BM25 и фильтрами")
    add_search_arguments(search_parser)
    events_parser = subparsers.add_parser(
        "events", help="Поиск только по чанкам с настроенными персонажами"
    )
    add_search_arguments(events_parser)
    context_parser = subparsers.add_parser("context", help="Соседние чанки документа")
    add_config_arguments(context_parser)
    context_parser.add_argument("chunk_id")
    context_parser.add_argument("--before", type=int, default=1)
    context_parser.add_argument("--after", type=int, default=1)
    context_parser.add_argument("--json", action="store_true")
    daily_parser = subparsers.add_parser(
        "daily-five", help="Автоматически отобрать пять новых эпизодов Тайра"
    )
    add_config_arguments(daily_parser)
    daily_parser.add_argument(
        "--mode", choices=("historical-events",), default="historical-events"
    )
    daily_parser.add_argument("--used-finds", default=str(DEFAULT_USED_FINDS))
    daily_parser.add_argument("--top-per-topic", type=int, default=20)
    daily_parser.add_argument("--pool-size", type=int, default=120)
    daily_parser.add_argument("--output", default=str(DEFAULT_DAILY_OUTPUT))
    daily_parser.add_argument(
        "--from-json",
        help="Только переоформить существующий daily-five JSON без нового поиска",
    )
    daily_parser.add_argument("--cards-config", default=str(DEFAULT_EVENT_CARDS))
    daily_parser.add_argument("--source-notes-config", default=str(DEFAULT_SOURCE_NOTES))
    daily_parser.add_argument("--dry-run", action="store_true")
    daily_parser.add_argument("--json", action="store_true")
    research_parser = subparsers.add_parser(
        "research-findings",
        help="Отобрать находки по локальному исследовательскому профилю",
    )
    add_config_arguments(research_parser)
    research_parser.add_argument("--profile", default=str(DEFAULT_RESEARCH_PROFILE))
    research_parser.add_argument("--used-finds", default=str(DEFAULT_USED_FINDS))
    research_parser.add_argument("--count", type=int)
    research_parser.add_argument("--top-per-interest", type=int, default=30)
    research_parser.add_argument("--pool-size", type=int, default=160)
    research_parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Максимум кандидатов final + alternates в одной партии",
    )
    research_parser.add_argument(
        "--continue-from",
        action="append",
        default=[],
        help=(
            "Предыдущий JSON research-findings; можно повторять для следующей "
            "партии без уже просмотренных chunk_id"
        ),
    )
    research_parser.add_argument("--output", default=str(DEFAULT_RESEARCH_OUTPUT))
    research_parser.add_argument(
        "--editorial-output",
        help=(
            "Компактный редакционный JSON; по умолчанию рядом с --output "
            "с суффиксом .editorial.json"
        ),
    )
    research_parser.add_argument(
        "--preview",
        action="store_true",
        help="Пробная подборка; журнал только читается и никогда не изменяется",
    )
    research_parser.add_argument("--json", action="store_true")
    research_context_parser = subparsers.add_parser(
        "research-context",
        help="Собрать полный контекст выбранных кандидатов одним пакетом",
    )
    research_context_parser.add_argument(
        "result", help="Полный research-findings JSON"
    )
    research_context_parser.add_argument(
        "--chunk-id",
        action="append",
        default=[],
        help="Выбранный chunk_id; можно повторять",
    )
    research_context_parser.add_argument(
        "--include-required-review",
        action="store_true",
        help="Добавить всех кандидатов, требующих semantic_review",
    )
    research_context_parser.add_argument("--output", required=True)
    access_parser = subparsers.add_parser(
        "check-publication-access",
        help="Проверить чтение SQLite и безопасную запись рядом с used_finds.csv",
    )
    access_parser.add_argument("--db", default=str(DEFAULT_DB))
    access_parser.add_argument("--used-finds", default=str(DEFAULT_USED_FINDS))
    access_parser.add_argument("--json", action="store_true")
    mark_parser = subparsers.add_parser(
        "mark-used", help="Явно добавить daily-five JSON или chunk_id в used_finds.csv"
    )
    add_config_arguments(mark_parser)
    mark_parser.add_argument("target", help="Путь к daily-five JSON или chunk_id")
    mark_parser.add_argument("--used-finds", default=str(DEFAULT_USED_FINDS))
    publication_parser = subparsers.add_parser(
        "record-publication",
        help="Атомарно записать выбранные карточки из локального JSON",
    )
    publication_parser.add_argument("manifest", help="JSON с готовыми карточками")
    publication_parser.add_argument("--used-finds", default=str(DEFAULT_USED_FINDS))
    return parser


def load_runtime(args: argparse.Namespace) -> tuple[
    sqlite3.Connection,
    dict[str, list[str]],
    dict[str, dict[str, Any]],
]:
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        raise RuntimeError(f"Индекс не найден: {db_path}. Сначала запустите build_index.py")
    aliases = load_mapping(Path(args.aliases).expanduser().resolve(), "aliases.json")
    topics = load_mapping(
        Path(args.topics_config).expanduser().resolve(), "topics.json"
    )
    people = load_people(Path(args.people_config).expanduser().resolve())
    source_types = load_source_types(
        Path(args.source_types_config).expanduser().resolve()
    )
    def configure(connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row
        connection.create_function(
            "py_casefold", 1, lambda value: str(value).casefold(), deterministic=True
        )

    # Search must remain read-only, but the index is not immutable: the builder
    # uses WAL mode and a committed update may still live in the -wal sidecar.
    # mode=ro makes SQLite follow that WAL while still rejecting writes.
    try:
        connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise RuntimeError(
            "Не удалось открыть индекс только для чтения с учётом SQLite WAL: "
            f"{db_path}. Проверьте доступ к базе и файлам "
            f"{db_path.name}-wal/{db_path.name}-shm: {exc}"
        ) from exc
    configure(connection)
    connection.execute("PRAGMA query_only=ON")
    if search_schema_is_current(connection):
        return connection, topics, people

    # Legacy indexes still retain the previous automatic migration behaviour.
    connection.close()
    connection = sqlite3.connect(db_path)
    configure(connection)
    migration = ensure_search_schema(
        connection,
        db_path,
        aliases=aliases,
        topics=topics,
        people=people,
        source_types=source_types,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )
    if migration["backup_path"]:
        print(f"Резервная копия: {migration['backup_path']}", file=sys.stderr)
    return connection, topics, people


def main(argv: list[str] | None = None) -> int:
    configure_console()
    parser = make_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "top") and not 1 <= args.top <= 500:
        parser.error("--top должен быть от 1 до 500")
    if hasattr(args, "offset") and args.offset < 0:
        parser.error("--offset не может быть отрицательным")
    if args.command == "context" and (args.before < 0 or args.after < 0):
        parser.error("--before/--after не могут быть отрицательными")
    if args.command == "daily-five":
        if not 1 <= args.top_per_topic <= 100:
            parser.error("--top-per-topic должен быть от 1 до 100")
        if not 10 <= args.pool_size <= 500:
            parser.error("--pool-size должен быть от 10 до 500")
    if args.command == "research-findings":
        if args.count is not None and not 1 <= args.count <= 20:
            parser.error("--count должен быть от 1 до 20")
        if not 1 <= args.top_per_interest <= 100:
            parser.error("--top-per-interest должен быть от 1 до 100")
        if not 10 <= args.pool_size <= 500:
            parser.error("--pool-size должен быть от 10 до 500")
        if not 1 <= args.batch_size <= 100:
            parser.error("--batch-size должен быть от 1 до 100")
        if args.count is not None and args.batch_size < args.count:
            parser.error("--batch-size не может быть меньше --count")
    if args.command == "research-context":
        if not args.chunk_id and not args.include_required_review:
            parser.error(
                "research-context требует --chunk-id или --include-required-review"
            )
        if _paths_refer_to_same_file(Path(args.result), Path(args.output)):
            parser.error("--output не должен перезаписывать исходный полный JSON")
    connection: sqlite3.Connection | None = None
    try:
        if args.command == "research-findings":
            validate_research_output_path(args)
        if args.command == "record-publication":
            from daily_five import record_publication_from_json

            manifest_path = Path(args.manifest).expanduser().resolve()
            if not manifest_path.is_file():
                raise ValueError(f"Манифест публикации не найден: {manifest_path}")
            used_path = Path(args.used_finds).expanduser().resolve()
            publication_id, added, skipped = record_publication_from_json(
                manifest_path, used_path
            )
            print(f"Пакет публикации: {publication_id}")
            print(f"Манифест для восстановления: {manifest_path}")
            print(
                f"Добавлено в {used_path}: {added}; уже было/пропущено: {skipped}"
            )
            print(
                "Журнал зарегистрирован; доставка карточек в чат этой командой "
                "не выполняется и не подтверждается."
            )
            return 0

        if args.command == "check-publication-access":
            result = check_publication_access(Path(args.db), Path(args.used_finds))
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print("Проверка прав публикации: OK")
                print(f"SQLite доступна только для чтения: {result['sqlite_read']}")
                print(
                    "Безопасная запись и атомарное переименование доступны: "
                    f"{result['journal_directory_atomic_write']}"
                )
                print("used_finds.csv и lock-файл не изменялись.")
            return 0

        if args.command == "research-context":
            from daily_five import save_result
            from research_findings import build_research_context_packet

            result_path = Path(args.result).expanduser().resolve()
            payload = json.loads(result_path.read_text(encoding="utf-8-sig"))
            if (
                not isinstance(payload, dict)
                or payload.get("mode") != "research-findings"
            ):
                raise ValueError(f"{result_path}: ожидается полный research-findings JSON")
            packet = build_research_context_packet(
                payload,
                args.chunk_id,
                include_required_review=args.include_required_review,
            )
            output = Path(args.output).expanduser().resolve()
            save_result(packet, output)
            print(f"Сохранено: {output}")
            print(f"Кандидатов с полным контекстом: {len(packet['candidates'])}")
            return 0

        connection, topics, people = load_runtime(args)
        if args.command in {"search", "events"}:
            has_filter = any(
                [
                    args.query,
                    args.topic,
                    args.person,
                    args.source_type,
                    args.exclude_source_type,
                    args.source,
                    args.exclude_source,
                    args.quality,
                ]
            )
            if not has_filter:
                parser.error("задайте --query или хотя бы один фильтр")
            results = search_database(
                connection,
                args,
                topics,
                people,
                events_only=args.command == "events",
            )
            print_results(results, json_output=args.json)
        elif args.command == "context":
            rows = context_rows(connection, args.chunk_id, args.before, args.after)
            print_context(rows, json_output=args.json)
        elif args.command == "daily-five":
            from daily_five import (
                apply_presentation_cards,
                build_daily_five,
                print_daily_result,
                save_result,
            )

            if args.from_json:
                if args.dry_run:
                    raise ValueError("--from-json нельзя совмещать с --dry-run")
                input_path = Path(args.from_json).expanduser().resolve()
                result = json.loads(input_path.read_text(encoding="utf-8-sig"))
                if not isinstance(result, dict) or not isinstance(result.get("final"), list):
                    raise ValueError(f"{input_path}: это не daily-five JSON")
            else:
                result = build_daily_five(
                    connection,
                    topics,
                    people,
                    Path(args.used_finds).expanduser().resolve(),
                    search_function=search_database,
                    context_function=context_rows,
                    top_per_topic=args.top_per_topic,
                    pool_size=args.pool_size,
                    dry_run=args.dry_run,
                )
            if not args.dry_run:
                result = apply_presentation_cards(
                    result,
                    connection,
                    context_function=context_rows,
                    cards_path=Path(args.cards_config).expanduser().resolve(),
                    source_notes_path=Path(args.source_notes_config).expanduser().resolve(),
                )
            if not args.dry_run:
                output = Path(args.output).expanduser().resolve()
                save_result(result, output)
                print(f"Сохранено: {output}", file=sys.stderr if args.json else sys.stdout)
            print_daily_result(result, json_output=args.json)
        elif args.command == "research-findings":
            from daily_five import save_result
            from research_findings import (
                build_editorial_packet,
                build_research_findings,
                load_continuation_chunk_ids,
                print_research_result,
            )
            from research_profile import load_research_profile

            profile_path = Path(args.profile).expanduser().resolve()
            profile = load_research_profile(profile_path)
            excluded_chunk_ids = load_continuation_chunk_ids(
                [Path(path).expanduser().resolve() for path in args.continue_from],
                profile,
            )
            result = build_research_findings(
                connection,
                topics,
                people,
                profile,
                Path(args.used_finds).expanduser().resolve(),
                search_function=search_database,
                context_function=context_rows,
                count=args.count,
                top_per_interest=args.top_per_interest,
                pool_size=args.pool_size,
                batch_size=args.batch_size,
                preview=args.preview,
                excluded_chunk_ids=excluded_chunk_ids,
            )
            output = Path(args.output).expanduser().resolve()
            editorial_output = (
                Path(args.editorial_output).expanduser().resolve()
                if args.editorial_output
                else output.with_name(f"{output.stem}.editorial.json")
            )
            result["artifacts"] = {
                "full_result": str(output),
                "editorial_packet": str(editorial_output),
            }
            editorial_packet = build_editorial_packet(result)
            save_result(result, output)
            save_result(editorial_packet, editorial_output)
            print(f"Сохранено: {output}", file=sys.stderr if args.json else sys.stdout)
            print(
                f"Компактный пакет: {editorial_output}",
                file=sys.stderr if args.json else sys.stdout,
            )
            print_research_result(result, json_output=args.json)
        else:
            from daily_five import mark_used_chunk, mark_used_from_json

            used_path = Path(args.used_finds).expanduser().resolve()
            target_path = Path(args.target).expanduser()
            if target_path.is_file():
                added, skipped = mark_used_from_json(target_path.resolve(), used_path)
            else:
                added, skipped = mark_used_chunk(
                    connection,
                    args.target,
                    used_path,
                    context_function=context_rows,
                )
            print(f"Добавлено в {used_path}: {added}; уже было/пропущено: {skipped}")
        return 0
    except (RuntimeError, ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
