#!/usr/bin/env python3
"""Search the local TairaSearch SQLite index."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from text_utils import make_preview, normalize_text, unique_normalized


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = PROJECT_DIR / "taira_index.sqlite3"
DEFAULT_USED_FINDS = PROJECT_DIR / "used_finds.csv"


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def load_mapping(path: Path) -> dict[str, list[str]]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: ожидается JSON-объект")
    result: dict[str, list[str]] = {}
    for key, variants in value.items():
        if not isinstance(key, str) or not isinstance(variants, list):
            raise ValueError(f"{path}: значения должны быть списками")
        result[key] = [str(item) for item in variants]
    return result


def split_csv_values(value: str | None) -> list[str]:
    if not value:
        return []
    return unique_normalized(re.split(r"[;,、|]+", value))


def load_used_finds(path: Path) -> list[dict[str, Any]]:
    """Read manual find records used for optional lexical reranking."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            return []
        records: list[dict[str, Any]] = []
        for row in reader:
            if not any((value or "").strip() for value in row.values()):
                continue
            records.append(
                {
                    "id": normalize_text(row.get("id", "")),
                    "persons": split_csv_values(row.get("persons")),
                    "topics": split_csv_values(row.get("topics")),
                    "short_description": normalize_text(
                        row.get("short_description", "")
                    ),
                    "source": normalize_text(row.get("source", "")),
                }
            )
    return records


def _description_similarity(description: str, text: str) -> float:
    if not description or not text:
        return 0.0
    tokens = unique_normalized(
        re.findall(r"[0-9A-Za-zА-Яа-яЁё一-龯々ぁ-ゖァ-ヺー]{2,}", description)
    )
    token_coverage = (
        sum(token in text for token in tokens) / len(tokens) if tokens else 0.0
    )
    compact = description.replace(" ", "")
    grams = {compact[index : index + 3] for index in range(max(0, len(compact) - 2))}
    gram_coverage = (
        sum(gram in text for gram in grams) / len(grams) if grams else 0.0
    )
    return max(token_coverage, gram_coverage)


def used_finds_penalty(
    record: dict[str, Any], used_finds: list[dict[str, Any]]
) -> float:
    """Return a soft lexical similarity penalty; never excludes a result."""
    if not used_finds:
        return 0.0
    text = record["normalized_text"]
    aliases = {normalize_text(value) for value in record["aliases"]}
    topics = {normalize_text(value) for value in record["topics"]}
    source = normalize_text(record["source"])
    penalties: list[float] = []
    for used in used_finds:
        penalty = 0.0
        if used["id"] and used["id"] == normalize_text(record["chunk_id"]):
            penalty += 4.0
        person_hits = sum(
            person in aliases or person in text for person in used["persons"]
        )
        penalty += min(person_hits, 2) * 0.8
        topic_hits = sum(
            topic in topics or topic in text for topic in used["topics"]
        )
        penalty += min(topic_hits, 2) * 0.55
        used_source = used["source"]
        if used_source and source:
            if used_source == source:
                penalty += 0.75
            elif used_source in source or source in used_source:
                penalty += 0.35
        penalty += 1.5 * _description_similarity(
            used["short_description"], text
        )
        penalties.append(penalty)
    return max(penalties, default=0.0)


def get_meta(connection: sqlite3.Connection) -> dict[str, str]:
    return {row[0]: row[1] for row in connection.execute("SELECT key, value FROM meta")}


def print_database_stats(connection: sqlite3.Connection, db_path: Path) -> None:
    meta = get_meta(connection)
    total_chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    unique_chunks = connection.execute(
        "SELECT COUNT(*) FROM chunks WHERE is_duplicate=0"
    ).fetchone()[0]
    duplicate_chunks = total_chunks - unique_chunks
    statuses = dict(
        connection.execute(
            "SELECT status, COUNT(*) FROM files GROUP BY status ORDER BY status"
        ).fetchall()
    )
    print("Статистика TairaSearch")
    print(f"Корпус: {meta.get('corpus_root', '—')}")
    print(f"Последнее построение (UTC): {meta.get('last_build_utc', '—')}")
    print(f"Файлов найдено: {meta.get('files_found', '—')}")
    print(f"Обработано: {meta.get('files_processed', '—')}")
    print(f"Пропущено: {meta.get('files_skipped', '—')}")
    print(f"PDF без текста: {meta.get('pdf_without_text', '—')}")
    print(f"Chunk'ов: {unique_chunks}")
    print(f"Точных chunk-дублей: {duplicate_chunks}")
    print(f"Все дубли по последней сборке: {meta.get('duplicates', duplicate_chunks)}")
    print(f"Статусы файлов: {json.dumps(statuses, ensure_ascii=False)}")
    extensions = json.loads(meta.get("extensions_json", "{}"))
    print(f"Расширения: {json.dumps(extensions, ensure_ascii=False)}")
    print(f"Режим поиска: {meta.get('fts_mode', 'substring_fallback')}")
    print(f"SQLite: {db_path}")


def expand_token(token: str, aliases: dict[str, list[str]]) -> list[str]:
    normalized_token = normalize_text(token)
    for canonical, variants in aliases.items():
        group = unique_normalized([canonical, *variants])
        if normalized_token in group:
            return group
    return [normalized_token] if normalized_token else []


def build_groups(
    query: str | None,
    topic_names: list[str],
    aliases: dict[str, list[str]],
    topics: dict[str, list[str]],
) -> tuple[list[list[str]], list[str]]:
    groups: list[list[str]] = []
    display_terms: list[str] = []
    if query:
        for token in query.split():
            group = expand_token(token, aliases)
            if group:
                groups.append(group)
                display_terms.extend(group)
    for topic_name in topic_names:
        if topic_name not in topics:
            available = ", ".join(sorted(topics))
            raise ValueError(f"Неизвестная тема '{topic_name}'. Доступны: {available}")
        group = unique_normalized(topics[topic_name])
        if group:
            groups.append(group)
            display_terms.extend(group)
    return groups, unique_normalized(display_terms)


def fts_phrase(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def candidate_rows(
    connection: sqlite3.Connection,
    groups: list[list[str]],
    source: str | None,
    limit: int,
    fts_mode: str,
) -> list[sqlite3.Row]:
    source_clause = ""
    source_params: list[Any] = []
    if source:
        source_clause = " AND instr(py_casefold(c.source), ?) > 0"
        source_params.append(source.casefold())

    use_trigram = (
        fts_mode == "trigram"
        and groups
        and all(all(len(term) >= 3 for term in group) for group in groups)
    )
    candidate_limit = max(1000, min(50000, limit * 500))
    duplicate_clause = "1=1" if source else "c.is_duplicate=0"
    if use_trigram:
        match_query = " AND ".join(
            "(" + " OR ".join(fts_phrase(term) for term in group) + ")"
            for group in groups
        )
        sql = (
            "SELECT c.*, bm25(chunks_fts) AS fts_rank "
            "FROM chunks_fts JOIN chunks c ON c.chunk_id=chunks_fts.chunk_id "
            "WHERE chunks_fts MATCH ? AND " + duplicate_clause
            + source_clause
            + " ORDER BY fts_rank LIMIT ?"
        )
        try:
            return connection.execute(
                sql, [match_query, *source_params, candidate_limit]
            ).fetchall()
        except sqlite3.OperationalError as fts_error:
            # A malformed/unsupported MATCH expression falls through to the
            # always-correct substring query below.
            _fallback_reason = str(fts_error)

    clauses = [duplicate_clause]
    params: list[Any] = []
    for group in groups:
        clauses.append(
            "(" + " OR ".join("instr(c.normalized_text, ?) > 0" for _ in group) + ")"
        )
        params.extend(group)
    sql = "SELECT c.*, 0.0 AS fts_rank FROM chunks c WHERE " + " AND ".join(clauses)
    sql += source_clause + " ORDER BY c.source, c.relative_path, c.chunk_no LIMIT ?"
    params.extend(source_params)
    params.append(candidate_limit)
    return connection.execute(sql, params).fetchall()


def relevance_score(row: sqlite3.Row, groups: list[list[str]], query: str | None) -> float:
    text = row["normalized_text"]
    score = 0.0
    for group in groups:
        occurrences = max(text.count(term) for term in group)
        longest = max((len(term) for term in group if term in text), default=1)
        score += 2.0 + min(occurrences, 8) * 0.45 + min(longest, 12) * 0.05
    if query:
        phrase = normalize_text(query)
        if phrase and phrase in text:
            score += 2.0
    try:
        score += max(0.0, -float(row["fts_rank"])) * 0.05
    except (ValueError, TypeError, IndexError):
        score += 0.0
    return score


def make_search_preview(text: str, terms: list[str], limit: int = 420) -> str:
    compact = normalize_text(text)
    positions = [compact.find(term) for term in terms if term and compact.find(term) >= 0]
    if not positions:
        return make_preview(compact, limit)
    center = min(positions)
    start = max(0, center - limit // 3)
    end = min(len(compact), start + limit)
    snippet = compact[start:end].strip()
    return ("…" if start else "") + snippet + ("…" if end < len(compact) else "")


def diversify(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    remaining = list(rows)
    selected: list[dict[str, Any]] = []
    file_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    while remaining and len(selected) < limit:
        best_index = 0
        best_adjusted = float("-inf")
        for index, row in enumerate(remaining):
            file_key = row["relative_path"]
            source_key = row["source"]
            adjacent = any(
                item["relative_path"] == file_key
                and abs(item["chunk_no"] - row["chunk_no"]) <= 1
                for item in selected
            )
            penalty = file_counts[file_key] * 2.3 + source_counts[source_key] * 0.35
            if adjacent:
                penalty += 2.7
            adjusted = row["score"] - penalty
            if adjusted > best_adjusted:
                best_adjusted = adjusted
                best_index = index
        chosen = remaining.pop(best_index)
        selected.append(chosen)
        file_counts[chosen["relative_path"]] += 1
        source_counts[chosen["source"]] += 1
    return selected


def search(
    connection: sqlite3.Connection,
    groups: list[list[str]],
    display_terms: list[str],
    *,
    query: str | None,
    source: str | None,
    limit: int,
    diversify_results: bool,
    used_finds: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    meta = get_meta(connection)
    rows = candidate_rows(
        connection, groups, source, limit, meta.get("fts_mode", "substring_fallback")
    )
    results: list[dict[str, Any]] = []
    corpus_root = Path(meta.get("corpus_root", ""))
    seen_hashes: set[str] = set()
    for row in rows:
        if source and row["text_hash"] in seen_hashes:
            continue
        seen_hashes.add(row["text_hash"])
        record = dict(row)
        record["aliases"] = json.loads(record.pop("aliases_json"))
        record["topics"] = json.loads(record.pop("topics_json"))
        record["search_terms"] = json.loads(record.pop("search_terms_json"))
        record["hash"] = record.pop("text_hash")
        record["path"] = str(corpus_root / Path(record["relative_path"]))
        record["preview"] = make_search_preview(record["original_text"], display_terms)
        base_score = relevance_score(row, groups, query)
        penalty = used_finds_penalty(record, used_finds or [])
        record["used_finds_penalty"] = penalty
        record["score"] = base_score - penalty
        results.append(record)
    results.sort(key=lambda item: (-item["score"], item["relative_path"], item["chunk_no"]))
    if diversify_results:
        return diversify(results, limit)
    return results[:limit]


def format_pages(start: int | None, end: int | None) -> str:
    if start is None:
        return "—"
    if end is None or end == start:
        return str(start)
    return f"{start}–{end}"


def print_results(results: list[dict[str, Any]]) -> None:
    if not results:
        print("Ничего не найдено.")
        return
    for number, row in enumerate(results, start=1):
        print(
            f"{number}. {row['source']} | {row['filename']} | "
            f"стр. {format_pages(row['page_start'], row['page_end'])}"
        )
        print(f"   {row['preview']}")
        print(f"   {row['path']}")


def export_results(results: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "chunk_id",
        "source",
        "filename",
        "relative_path",
        "path",
        "page_start",
        "page_end",
        "chunk_no",
        "aliases",
        "topics",
        "preview",
        "search_terms",
        "hash",
        "score",
        "used_finds_penalty",
    ]
    suffix = output.suffix.casefold()
    if suffix == ".csv":
        with output.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for result in results:
                row = {field: result.get(field, "") for field in fields}
                row["aliases"] = "; ".join(result["aliases"])
                row["topics"] = "; ".join(result["topics"])
                row["search_terms"] = "; ".join(result["search_terms"])
                writer.writerow(row)
    elif suffix in {".jsonl", ".ndjson"}:
        with output.open("w", encoding="utf-8", newline="\n") as stream:
            for result in results:
                row = {field: result.get(field) for field in fields}
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    else:
        raise ValueError("Формат --output должен быть .csv, .jsonl или .ndjson")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Поиск по локальному индексу Тайра.")
    parser.add_argument("query", nargs="?", help="Слова для поиска")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Путь к SQLite")
    parser.add_argument(
        "--aliases", default=str(PROJECT_DIR / "aliases.json"), help="Файл алиасов"
    )
    parser.add_argument(
        "--topics", default=str(PROJECT_DIR / "topics.json"), help="Файл тем"
    )
    parser.add_argument(
        "--topic", action="append", default=[], help="Тематическая группа; можно повторять"
    )
    parser.add_argument("--source", help="Подстрока в названии источника")
    parser.add_argument("--limit", type=int, default=10, help="Число результатов")
    parser.add_argument("--output", help="Экспорт в .csv или .jsonl")
    parser.add_argument("--diversify", action="store_true", help="Разнообразить выдачу")
    parser.add_argument(
        "--used-finds",
        nargs="?",
        const=str(DEFAULT_USED_FINDS),
        help=(
            "Мягко понижать похожие уже использованные находки; "
            "без пути используется used_finds.csv проекта"
        ),
    )
    parser.add_argument("--stats", action="store_true", help="Показать статистику индекса")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console()
    parser = make_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        print(f"Индекс не найден: {db_path}\nСначала запустите build_index.py.", file=sys.stderr)
        return 1
    if args.limit < 1:
        parser.error("--limit должен быть положительным")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.create_function("py_casefold", 1, lambda value: str(value).casefold(), deterministic=True)
    try:
        if args.stats:
            print_database_stats(connection, db_path)
            if not args.query and not args.topic:
                return 0
        if not args.query and not args.topic:
            parser.error("задайте поисковую строку, --topic или --stats")
        aliases = load_mapping(Path(args.aliases).expanduser().resolve())
        topics = load_mapping(Path(args.topics).expanduser().resolve())
        used_finds = (
            load_used_finds(Path(args.used_finds).expanduser().resolve())
            if args.used_finds
            else []
        )
        groups, display_terms = build_groups(args.query, args.topic, aliases, topics)
        results = search(
            connection,
            groups,
            display_terms,
            query=args.query,
            source=args.source,
            limit=args.limit,
            diversify_results=args.diversify,
            used_finds=used_finds,
        )
        print_results(results)
        if args.output:
            output = Path(args.output).expanduser().resolve()
            export_results(results, output)
            print(f"\nЭкспортировано: {output}")
        return 0
    except (ValueError, OSError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
