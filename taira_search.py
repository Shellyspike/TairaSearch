#!/usr/bin/env python3
"""BM25/FTS5 search and neighbouring-context CLI for TairaSearch."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
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
DEFAULT_DAILY_OUTPUT = PROJECT_DIR / "daily_five_candidates.json"
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


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Локальный FTS5-поиск по корпусу Тайра")
    subparsers = parser.add_subparsers(dest="command", required=True)
    search_parser = subparsers.add_parser("search", help="Поиск с BM25 и фильтрами")
    add_search_arguments(search_parser)
    events_parser = subparsers.add_parser(
        "events", help="Поиск только по чанкам с персонажами Тайра"
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

    # An up-to-date search index is read-only data.  Immutable mode prevents
    # SQLite from trying to create a -journal file, which is important for
    # scheduled/read-only runs and also makes accidental writes impossible.
    connection = sqlite3.connect(f"{db_path.as_uri()}?immutable=1", uri=True)
    configure(connection)
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
    connection: sqlite3.Connection | None = None
    try:
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
