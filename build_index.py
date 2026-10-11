#!/usr/bin/env python3
"""Build or incrementally update the local TairaSearch SQLite index."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from metadata_utils import (
    classify_source_type,
    classify_text_quality,
    detect_people,
    load_people,
    load_source_types,
)
from parsers import (
    PdfPartialReadError,
    PdfProcessingError,
    chunk_units,
    ensure_pdf_support,
    parse_file,
)
from search_schema import FTS_MODE, ensure_search_schema, upsert_fts_chunk
from text_utils import (
    derive_source,
    detect_labels,
    make_preview,
    normalize_text,
    sha256_text,
    stable_chunk_id,
)


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CORPUS = PROJECT_DIR / "sample_corpus"
DEFAULT_DB = PROJECT_DIR / "taira_index.sqlite3"
DEFAULT_DRIVE_CSV = PROJECT_DIR / "drive_index.csv"
DEFAULT_DRIVE_JSONL = PROJECT_DIR / "drive_index.jsonl"
DEFAULT_LOG = PROJECT_DIR / "index_errors.log"
DEFAULT_PEOPLE = PROJECT_DIR / "people.json"
DEFAULT_SOURCE_TYPES = PROJECT_DIR / "source_types.json"
SUPPORTED_EXTENSIONS = {".txt", ".md", ".json", ".pdf"}
SCHEMA_VERSION = "1"
INDEX_FORMAT_VERSION = "2026-09-22.1"
BUILD_SUCCEEDED = "succeeded"
BUILD_COMPLETED_WITH_ERRORS = "completed_with_errors"
BUILD_FAILED = "failed"
BUILD_INTERRUPTED = "interrupted"


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def load_mapping(path: Path, label: str) -> dict[str, list[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Не найден {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ошибка JSON в {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path}: ожидается JSON-объект")
    result: dict[str, list[str]] = {}
    for key, variants in value.items():
        if not isinstance(key, str) or not isinstance(variants, list):
            raise RuntimeError(f"{path}: значения должны быть списками строк")
        if not all(isinstance(item, str) for item in variants):
            raise RuntimeError(f"{path}: найдено нестроковое значение")
        result[key] = variants
    return result


def mapping_fingerprint(*paths: Path) -> str:
    material = [INDEX_FORMAT_VERSION]
    for path in paths:
        material.append(path.read_text(encoding="utf-8-sig"))
    return sha256_text("\x1e".join(material))


def create_schema(connection: sqlite3.Connection) -> str:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS files (
            relative_path TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            extension TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            indexed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            chunk_id TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            filename TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            page_start INTEGER,
            page_end INTEGER,
            chunk_no INTEGER NOT NULL,
            original_text TEXT NOT NULL,
            normalized_text TEXT NOT NULL,
            preview TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            topics_json TEXT NOT NULL,
            search_terms_json TEXT NOT NULL,
            text_hash TEXT NOT NULL,
            is_duplicate INTEGER NOT NULL DEFAULT 0,
            source_type TEXT NOT NULL DEFAULT 'other',
            people_json TEXT NOT NULL DEFAULT '[]',
            text_quality TEXT NOT NULL DEFAULT 'good',
            FOREIGN KEY (relative_path) REFERENCES files(relative_path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS chunks_path_idx ON chunks(relative_path);
        CREATE INDEX IF NOT EXISTS chunks_hash_idx ON chunks(text_hash);
        CREATE INDEX IF NOT EXISTS chunks_source_idx ON chunks(source);
        """
    )
    return FTS_MODE


def delete_chunks_for_path(connection: sqlite3.Connection, relative_path: str) -> None:
    chunk_ids = [
        row[0]
        for row in connection.execute(
            "SELECT chunk_id FROM chunks WHERE relative_path=?", (relative_path,)
        )
    ]
    if chunk_ids and table_exists(connection, "chunks_fts"):
        connection.executemany(
            "DELETE FROM chunks_fts WHERE chunk_id=?", ((item,) for item in chunk_ids)
        )
    connection.execute("DELETE FROM chunks WHERE relative_path=?", (relative_path,))


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name=? LIMIT 1", (name,)
        ).fetchone()
        is not None
    )


def discover_files(root: Path, log_error: Any) -> list[Path]:
    result: list[Path] = []

    def onerror(error: OSError) -> None:
        log_error("WALK_ERROR", Path(error.filename or root), str(error))

    for current, _dirs, filenames in os.walk(root, onerror=onerror, followlinks=False):
        current_path = Path(current)
        for filename in filenames:
            result.append(current_path / filename)
    result.sort(key=lambda item: str(item).casefold())
    return result


def relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def format_pages_count(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        word = "страница"
    elif count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14}:
        word = "страницы"
    else:
        word = "страниц"
    return f"{count} {word}"


def collect_file_stats(
    paths: list[Path], error_callback: Any
) -> dict[Path, os.stat_result]:
    stats: dict[Path, os.stat_result] = {}
    for path in paths:
        try:
            stats[path] = path.stat()
        except OSError as exc:
            error_callback("STAT_ERROR", path, repr(exc))
    return stats


def print_scan_summary(
    all_files: list[Path],
    supported: list[Path],
    extensions: Counter[str],
    file_stats: dict[Path, os.stat_result],
) -> None:
    print(f"Найдено файлов: {len(all_files)}")
    print(f"Найдено поддерживаемых файлов: {len(supported)}")
    for extension, label in (
        (".txt", "TXT"),
        (".json", "JSON"),
        (".pdf", "PDF"),
        (".md", "MD"),
    ):
        print(f"{label}: {extensions.get(extension, 0)}")
    print(
        "Общий размер поддерживаемых файлов: "
        + format_size(sum(file_stats[path].st_size for path in supported if path in file_stats))
    )


class ProgressReporter:
    def __init__(self, total: int, every: int, verbose: bool) -> None:
        self.total = total
        self.every = every
        self.verbose = verbose
        self.started = time.monotonic()
        self.live_line = False
        self.current_index = 0
        self.current_path = ""

    def clear_live_line(self) -> None:
        if self.live_line:
            print("\r" + (" " * 160) + "\r", end="", flush=True)
            self.live_line = False

    def before_file(self, index: int, relative_path: str) -> None:
        self.current_index = index
        self.current_path = relative_path
        if self.verbose:
            print(f"[{index}/{self.total}] {relative_path}", flush=True)
        elif sys.stdout.isatty():
            label = f"[{index}/{self.total}] Текущий файл: {relative_path}"
            print("\r" + label[:158].ljust(158), end="", flush=True)
            self.live_line = True

    def pdf_progress(self, filename: str, page: int, total: int) -> None:
        if page == 0:
            if self.verbose:
                print(f"  PDF, {format_pages_count(total)}", flush=True)
            return
        if total < 50 and not self.verbose:
            return
        self.clear_live_line()
        print(f"{filename}: страница {page}/{total}", flush=True)
        if not self.verbose and sys.stdout.isatty():
            self.before_file(self.current_index, self.current_path)

    def verbose_result(self, detail: str, status: str, seconds: float) -> None:
        if not self.verbose:
            return
        if detail:
            print(f"  {detail}")
        print(f"  {status}, {seconds:.1f} сек", flush=True)

    def summary(self, completed: int, current_path: str, counts: dict[str, int]) -> None:
        if completed % self.every != 0 and completed != self.total:
            return
        self.clear_live_line()
        elapsed = time.monotonic() - self.started
        percentage = (completed / self.total * 100) if self.total else 100.0
        print(f"[{completed}/{self.total}] {percentage:.1f}%")
        print(f"Текущий файл: {current_path}")
        print(f"Chunks: {counts['chunks']}")
        print(f"Дублей: {counts['duplicates']}")
        print(f"PDF без текста: {counts['pdf_no_text']}")
        print(f"Ошибок: {counts['errors']}")
        print(f"Прошло: {format_duration(elapsed)}")
        if completed >= max(5, self.every) and elapsed >= 3 and completed < self.total:
            remaining = elapsed / completed * (self.total - completed)
            print(f"Осталось примерно: {format_duration(remaining)}")
        print(flush=True)


def upsert_file(
    connection: sqlite3.Connection,
    relative_path: str,
    path: Path,
    stat: os.stat_result,
    status: str,
    error: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO files(relative_path, filename, extension, size, mtime_ns,
                          status, error, indexed_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(relative_path) DO UPDATE SET
            filename=excluded.filename,
            extension=excluded.extension,
            size=excluded.size,
            mtime_ns=excluded.mtime_ns,
            status=excluded.status,
            error=excluded.error,
            indexed_at=excluded.indexed_at
        """,
        (
            relative_path,
            path.name,
            path.suffix.casefold(),
            stat.st_size,
            stat.st_mtime_ns,
            status,
            error,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def write_drive_exports(
    connection: sqlite3.Connection, csv_path: Path, jsonl_path: Path
) -> int:
    rows = connection.execute(
        """
        SELECT chunk_id, source, filename, relative_path, page_start, page_end,
               chunk_no, aliases_json, topics_json, people_json, source_type,
               text_quality, preview, normalized_text, search_terms_json, text_hash
        FROM chunks
        WHERE is_duplicate=0
        ORDER BY source, relative_path, chunk_no
        """
    ).fetchall()
    fields = [
        "chunk_id",
        "source",
        "filename",
        "path",
        "page_start",
        "page_end",
        "chunk_no",
        "aliases",
        "topics",
        "people",
        "source_type",
        "text_quality",
        "preview",
        "search_text",
        "search_terms",
        "hash",
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "chunk_id": row[0],
                    "source": row[1],
                    "filename": row[2],
                    "path": row[3],
                    "page_start": row[4] if row[4] is not None else "",
                    "page_end": row[5] if row[5] is not None else "",
                    "chunk_no": row[6],
                    "aliases": "; ".join(json.loads(row[7])),
                    "topics": "; ".join(json.loads(row[8])),
                    "people": "; ".join(json.loads(row[9])),
                    "source_type": row[10],
                    "text_quality": row[11],
                    "preview": row[12],
                    "search_text": row[13],
                    "search_terms": "; ".join(json.loads(row[14])),
                    "hash": row[15],
                }
            )
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            record = dict(zip(fields, row))
            record["aliases"] = json.loads(record["aliases"])
            record["topics"] = json.loads(record["topics"])
            record["people"] = json.loads(record["people"])
            record["search_terms"] = json.loads(record["search_terms"])
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(rows)


def build_index(args: argparse.Namespace) -> dict[str, Any]:
    corpus_input = Path(args.corpus).expanduser()
    print(f"Корпус: {corpus_input}", flush=True)
    print("Этап 1/3: поиск файлов...", flush=True)
    try:
        corpus_available = corpus_input.is_dir()
    except OSError:
        corpus_available = False
    if not corpus_available:
        raise RuntimeError(
            "папка корпуса недоступна:\n"
            f"{corpus_input}\n\n"
            "Проверьте, что Google Drive for Desktop запущен и диск G: подключён."
        )
    corpus = corpus_input.resolve()
    db_path = Path(args.db).expanduser().resolve()
    aliases_path = Path(args.aliases).expanduser().resolve()
    topics_path = Path(args.topics).expanduser().resolve()
    people_path = Path(args.people).expanduser().resolve()
    source_types_path = Path(args.source_types).expanduser().resolve()
    log_path = Path(args.log).expanduser().resolve()
    drive_csv = Path(args.drive_csv).expanduser().resolve()
    drive_jsonl = Path(args.drive_jsonl).expanduser().resolve()

    discovery_errors: list[tuple[str, Path, str]] = []

    def collect_discovery_error(kind: str, path: Path, message: str) -> None:
        discovery_errors.append((kind, path, message))

    all_files = discover_files(corpus, collect_discovery_error)
    extensions = Counter(path.suffix.casefold() or "[без расширения]" for path in all_files)
    supported = [path for path in all_files if path.suffix.casefold() in SUPPORTED_EXTENSIONS]
    file_stats = collect_file_stats(supported, collect_discovery_error)
    print_scan_summary(all_files, supported, extensions, file_stats)
    if discovery_errors:
        print(f"Ошибок доступа/metadata при сканировании: {len(discovery_errors)}")
    if args.scan_only:
        print("\nРежим --scan-only: содержимое файлов не читалось, индекс не изменён.")
        return {
            "scan_only": True,
            "files_found": len(all_files),
            "supported_files": len(supported),
            "extensions": dict(sorted(extensions.items())),
            "total_size": sum(stat.st_size for stat in file_stats.values()),
        }

    pdf_count = sum(path.suffix.casefold() == ".pdf" for path in supported)
    if pdf_count:
        pdf_version = ensure_pdf_support()
        print(
            f"PDF: найдено {pdf_count}; pypdf {pdf_version} готов к обработке.",
            flush=True,
        )

    print("Начинаю индексацию...", flush=True)
    print("Этап 2/3: индексация содержимого...", flush=True)
    aliases = load_mapping(aliases_path, "aliases.json")
    topics = load_mapping(topics_path, "topics.json")
    people = load_people(people_path)
    source_types = load_source_types(source_types_path)
    config_hash = mapping_fingerprint(
        aliases_path, topics_path, people_path, source_types_path
    )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_stream = log_path.open("w", encoding="utf-8", newline="\n")
    log_stream.write(
        f"TairaSearch indexing log — {datetime.now(timezone.utc).isoformat()}\n"
    )

    def log_error(kind: str, path: Path, message: str) -> None:
        log_stream.write(f"[{kind}] {path}\n{message.strip()}\n\n")
        log_stream.flush()

    for kind, path, message in discovery_errors:
        log_error(kind, path, message)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    create_schema(connection)
    prior_schema = connection.execute(
        "SELECT value FROM meta WHERE key='schema_version'"
    ).fetchone()
    prior_config = connection.execute(
        "SELECT value FROM meta WHERE key='config_hash'"
    ).fetchone()
    full_rebuild = bool(args.rebuild)
    if prior_schema and prior_schema[0] != SCHEMA_VERSION:
        full_rebuild = True
    migration = ensure_search_schema(
        connection,
        db_path,
        aliases=aliases,
        topics=topics,
        people=people,
        source_types=source_types,
        refresh_metadata=bool(
            prior_config and prior_config[0] != config_hash and not full_rebuild
        ),
        create_backup=True,
        progress=lambda message: print(message, flush=True),
    )
    if migration["backup_path"]:
        print(f"Резервная копия: {migration['backup_path']}", flush=True)
    fts_mode = str(migration["fts_mode"])
    fts_available = table_exists(connection, "chunks_fts")
    connection.executemany(
        "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
        (
            ("schema_version", SCHEMA_VERSION),
            ("config_hash", config_hash),
            ("corpus_root", str(corpus)),
        ),
    )
    connection.commit()

    relative_supported = {relative_posix(path, corpus) for path in supported}
    indexed_paths = {
        str(row[0])
        for row in connection.execute("SELECT relative_path FROM files").fetchall()
    }
    missing_kept = sorted(indexed_paths - relative_supported, key=str.casefold)
    if missing_kept:
        message = (
            "В индексе сохранено документов, не найденных при текущем "
            f"сканировании: {len(missing_kept)}. Автоматическое удаление отключено."
        )
        print(message, flush=True)
        log_error("MISSING_FILES_KEPT", corpus, message)

    text_stems = {
        (str(path.parent).casefold(), path.stem.casefold())
        for path in supported
        if path.suffix.casefold() == ".txt"
    }
    processed_this_run = 0
    unchanged = 0
    errors = 0
    empty_files = 0
    paired_json = 0
    interrupted = False
    completed = 0
    problems: list[dict[str, Any]] = [
        {
            "kind": kind,
            "path": str(path),
            "reason": message,
            "last_good_kept": False,
        }
        for kind, path, message in discovery_errors
        if kind == "WALK_ERROR"
    ]
    reporter = ProgressReporter(len(supported), args.progress_every, args.verbose)

    def progress_counts() -> dict[str, int]:
        raw_chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        exact_duplicates_now = connection.execute(
            """
            SELECT COALESCE(SUM(group_size - 1), 0)
            FROM (
                SELECT COUNT(*) AS group_size
                FROM chunks
                GROUP BY text_hash, normalized_text
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        paired_now = connection.execute(
            "SELECT COUNT(*) FROM files WHERE status='paired_json'"
        ).fetchone()[0]
        return {
            "chunks": raw_chunks,
            "duplicates": exact_duplicates_now + paired_now,
            "pdf_no_text": connection.execute(
                "SELECT COUNT(*) FROM files WHERE status='pdf_no_text'"
            ).fetchone()[0],
            "errors": errors
            + sum(
                1
                for kind, _path, _message in discovery_errors
                if kind == "WALK_ERROR"
            ),
        }

    for index, path in enumerate(supported, start=1):
        relative_path = relative_posix(path, corpus)
        reporter.before_file(index, relative_path)
        file_started = time.monotonic()
        savepoint_active = False
        existing: sqlite3.Row | None = None
        try:
            existing = connection.execute(
                "SELECT size, mtime_ns, status FROM files WHERE relative_path=?",
                (relative_path,),
            ).fetchone()
            stat = file_stats.get(path)
            if stat is None:
                errors += 1
                last_good_kept = bool(
                    existing
                    and existing[2] in {"ok", "empty", "pdf_no_text", "paired_json"}
                )
                reason = next(
                    (
                        message
                        for kind, error_path, message in discovery_errors
                        if kind == "STAT_ERROR" and error_path == path
                    ),
                    "Не удалось прочитать metadata файла.",
                )
                problems.append(
                    {
                        "kind": "STAT_ERROR",
                        "path": relative_path,
                        "reason": reason,
                        "last_good_kept": last_good_kept,
                    }
                )
                if last_good_kept:
                    log_error(
                        "LAST_GOOD_KEPT",
                        path,
                        "Metadata файла недоступны; последняя корректная версия "
                        "документа и её FTS-записи сохранены.",
                    )
                completed += 1
                reporter.verbose_result("", "ОШИБКА stat", time.monotonic() - file_started)
                if completed % args.progress_every == 0 or completed == len(supported):
                    reporter.summary(completed, relative_path, progress_counts())
                continue

            if path.suffix.casefold() == ".json" and (
                str(path.parent).casefold(), path.stem.casefold()
            ) in text_stems:
                paired_json += 1
                connection.execute("SAVEPOINT one_file")
                savepoint_active = True
                delete_chunks_for_path(connection, relative_path)
                upsert_file(
                    connection,
                    relative_path,
                    path,
                    stat,
                    "paired_json",
                    "Пропущен: рядом есть одноимённый TXT OCR.",
                )
                connection.execute("RELEASE one_file")
                savepoint_active = False
                connection.commit()
                completed += 1
                reporter.verbose_result(
                    "JSON с одноимённым TXT",
                    "SKIP: технический дубль",
                    time.monotonic() - file_started,
                )
                if completed % args.progress_every == 0 or completed == len(supported):
                    reporter.summary(completed, relative_path, progress_counts())
                continue

            if (
                not full_rebuild
                and existing
                and existing[0] == stat.st_size
                and existing[1] == stat.st_mtime_ns
                and existing[2] in {"ok", "empty", "pdf_no_text"}
                ):
                if existing[2] == "pdf_no_text":
                    log_error(
                        "PDF_NO_TEXT",
                        path,
                        "PDF без извлекаемого текстового слоя; OCR не запускался (статус сохранён).",
                    )
                unchanged += 1
                completed += 1
                reporter.verbose_result(
                    "", "SKIP: без изменений", time.monotonic() - file_started
                )
                if completed % args.progress_every == 0 or completed == len(supported):
                    reporter.summary(completed, relative_path, progress_counts())
                continue

            parsed = parse_file(
                path,
                progress_callback=(
                    lambda page, total, name=path.name: reporter.pdf_progress(
                        name, page, total
                    )
                ),
            )
            for warning in parsed.warnings:
                log_error("PDF_PAGE_ERROR", path, warning)
            if path.suffix.casefold() == ".pdf" and parsed.warnings:
                raise PdfPartialReadError(
                    "PDF прочитан не полностью: ошибок страниц — "
                    f"{len(parsed.warnings)}. Неполная версия не записана в индекс."
                )
            chunks = chunk_units(parsed.units)
            connection.execute("SAVEPOINT one_file")
            savepoint_active = True
            delete_chunks_for_path(connection, relative_path)
            status_label = "OK"
            if parsed.pdf_without_text:
                upsert_file(connection, relative_path, path, stat, "pdf_no_text")
                log_error("PDF_NO_TEXT", path, "PDF без извлекаемого текстового слоя; OCR не запускался.")
                status_label = "PDF без текста"
            elif not chunks:
                empty_files += 1
                upsert_file(connection, relative_path, path, stat, "empty")
                log_error("EMPTY_TEXT", path, "Не найден индексируемый текст.")
                status_label = "пустой текст"
            else:
                upsert_file(connection, relative_path, path, stat, "ok")
                source = derive_source(relative_path)
                inserted_chunks = 0
                for chunk_no, chunk in enumerate(chunks, start=1):
                    normalized = normalize_text(chunk.text)
                    if not normalized:
                        continue
                    alias_labels, alias_terms = detect_labels(normalized, aliases)
                    topic_labels, topic_terms = detect_labels(normalized, topics)
                    people_labels = detect_people(normalized, people)
                    source_type = classify_source_type(
                        source, path.name, relative_path, source_types
                    )
                    text_quality = classify_text_quality(normalized)
                    search_terms = sorted(
                        set(
                            alias_labels
                            + alias_terms
                            + topic_labels
                            + topic_terms
                            + people_labels
                        )
                    )
                    chunk_id = stable_chunk_id(
                        relative_path,
                        chunk.page_start,
                        chunk.page_end,
                        chunk_no,
                    )
                    values = (
                        chunk_id,
                        source,
                        path.name,
                        relative_path,
                        chunk.page_start,
                        chunk.page_end,
                        chunk_no,
                        chunk.text,
                        normalized,
                        make_preview(chunk.text, 800),
                        json.dumps(alias_labels, ensure_ascii=False),
                        json.dumps(topic_labels, ensure_ascii=False),
                        json.dumps(search_terms, ensure_ascii=False),
                        sha256_text(normalized),
                        source_type,
                        json.dumps(people_labels, ensure_ascii=False),
                        text_quality,
                    )
                    connection.execute(
                        """
                        INSERT INTO chunks(
                            chunk_id, source, filename, relative_path,
                            page_start, page_end, chunk_no, original_text,
                            normalized_text, preview, aliases_json, topics_json,
                            search_terms_json, text_hash, source_type,
                            people_json, text_quality
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        values,
                    )
                    if fts_available:
                        upsert_fts_chunk(
                            connection,
                            chunk_id,
                            normalized,
                            make_preview(chunk.text, 800),
                            json.dumps(alias_labels, ensure_ascii=False),
                            json.dumps(topic_labels, ensure_ascii=False),
                        )
                    inserted_chunks += 1
            connection.execute("RELEASE one_file")
            savepoint_active = False
            connection.commit()
            processed_this_run += 1
            completed += 1
            detail_parts = []
            if parsed.page_count is not None:
                detail_parts.append(f"PDF, {format_pages_count(parsed.page_count)}")
            else:
                detail_parts.append(path.suffix.lstrip(".").upper())
            detail_parts.append(f"chunks: {inserted_chunks if chunks else 0}")
            reporter.verbose_result(
                "; ".join(detail_parts),
                status_label,
                time.monotonic() - file_started,
            )
        except KeyboardInterrupt:
            if savepoint_active:
                try:
                    connection.execute("ROLLBACK TO one_file")
                    connection.execute("RELEASE one_file")
                except sqlite3.Error as rollback_error:
                    log_error("ROLLBACK_ERROR", path, repr(rollback_error))
            connection.rollback()
            reporter.clear_live_line()
            interrupted = True
            break
        except Exception as exc:
            if savepoint_active:
                try:
                    connection.execute("ROLLBACK TO one_file")
                    connection.execute("RELEASE one_file")
                except sqlite3.Error as rollback_error:
                    log_error("ROLLBACK_ERROR", path, repr(rollback_error))
            else:
                connection.rollback()
            errors += 1
            message = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            error_kind = (
                exc.error_code if isinstance(exc, PdfProcessingError) else "FILE_ERROR"
            )
            log_error(error_kind, path, message)
            last_good_statuses = {"ok", "empty", "pdf_no_text", "paired_json"}
            last_good_kept = bool(
                existing is not None and existing[2] in last_good_statuses
            )
            if last_good_kept:
                log_error(
                    "LAST_GOOD_KEPT",
                    path,
                    "Ошибка повторной обработки; последняя корректная версия "
                    "документа и её FTS-записи сохранены.",
                )
            elif path in file_stats:
                upsert_file(
                    connection,
                    relative_path,
                    path,
                    file_stats[path],
                    "error",
                    str(exc),
                )
            problems.append(
                {
                    "kind": error_kind,
                    "path": relative_path,
                    "reason": str(exc) or type(exc).__name__,
                    "last_good_kept": last_good_kept,
                }
            )
            connection.commit()
            completed += 1
            reporter.verbose_result(
                "", f"ОШИБКА: {exc}", time.monotonic() - file_started
            )

        if completed and (
            completed % args.progress_every == 0 or completed == len(supported)
        ):
            reporter.summary(completed, relative_path, progress_counts())

    reporter.clear_live_line()
    print("Этап 3/3: финализация индекса и экспорт...", flush=True)

    connection.execute("UPDATE chunks SET is_duplicate=0")
    connection.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY text_hash, normalized_text
                       ORDER BY
                           CASE WHEN page_start IS NULL THEN 1 ELSE 0 END,
                           relative_path COLLATE NOCASE,
                           chunk_no,
                           id
                   ) AS duplicate_rank
            FROM chunks
        )
        UPDATE chunks
        SET is_duplicate=1
        WHERE id IN (SELECT id FROM ranked WHERE duplicate_rank > 1)
        """
    )
    exact_duplicates = connection.execute(
        "SELECT COUNT(*) FROM chunks WHERE is_duplicate=1"
    ).fetchone()[0]
    chunk_count = connection.execute(
        "SELECT COUNT(*) FROM chunks WHERE is_duplicate=0"
    ).fetchone()[0]
    pdf_no_text = connection.execute(
        "SELECT COUNT(*) FROM files WHERE status='pdf_no_text'"
    ).fetchone()[0]
    processed_current = connection.execute(
        "SELECT COUNT(*) FROM files WHERE status IN ('ok', 'pdf_no_text')"
    ).fetchone()[0]
    paired_current = connection.execute(
        "SELECT COUNT(*) FROM files WHERE status='paired_json'"
    ).fetchone()[0]
    skipped = len(all_files) - processed_current
    unsupported_files = max(len(all_files) - len(supported), 0)
    unattempted_files = max(len(supported) - completed, 0)
    skipped_this_run = unchanged + paired_json + unsupported_files + unattempted_files
    problem_count = len(problems)
    previous_versions_kept = sum(
        1 for problem in problems if problem["last_good_kept"]
    )
    if interrupted:
        build_status = BUILD_INTERRUPTED
    elif problem_count:
        build_status = BUILD_COMPLETED_WITH_ERRORS
    else:
        build_status = BUILD_SUCCEEDED

    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "config_hash": config_hash,
        "corpus_root": str(corpus),
        "last_build_utc": now,
        "files_found": str(len(all_files)),
        "files_processed": str(processed_current),
        "files_skipped": str(max(skipped, 0)),
        "pdf_without_text": str(pdf_no_text),
        "chunks": str(chunk_count),
        "duplicates": str(exact_duplicates + paired_current),
        "extensions_json": json.dumps(dict(sorted(extensions.items())), ensure_ascii=False),
        "fts_mode": fts_mode,
        "build_status": build_status,
        "successful_files": str(processed_this_run),
        "skipped_files": str(skipped_this_run),
        "problematic_files": str(problem_count),
        "previous_versions_kept": str(previous_versions_kept),
        "missing_files_kept": str(len(missing_kept)),
    }
    exported = write_drive_exports(connection, drive_csv, drive_jsonl)
    connection.executemany(
        "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", metadata.items()
    )
    connection.commit()
    connection.close()
    log_stream.close()

    return {
        **metadata,
        "processed_this_run": processed_this_run,
        "unchanged": unchanged,
        "errors": problem_count,
        "problems": problems,
        "successful_files": processed_this_run,
        "skipped_files": skipped_this_run,
        "problematic_files": problem_count,
        "previous_versions_kept": previous_versions_kept,
        "paired_json": paired_json,
        "exact_duplicates": exact_duplicates,
        "exported": exported,
        "extensions": dict(sorted(extensions.items())),
        "db_path": str(db_path),
        "drive_csv": str(drive_csv),
        "drive_jsonl": str(drive_jsonl),
        "log_path": str(log_path),
        "interrupted": interrupted,
        "completed": completed,
        "supported_files": len(supported),
        "missing_kept": len(missing_kept),
    }


def print_stats(stats: dict[str, Any]) -> None:
    print(f"\nСтатус сборки: {stats['build_status']}")
    print(f"Успешно обработано: {stats['successful_files']}")
    print(f"Пропущено в этом запуске: {stats['skipped_files']}")
    print(f"Проблемных файлов/путей: {stats['problematic_files']}")
    print(
        "Сохранена предыдущая корректная версия: "
        f"{stats['previous_versions_kept']}"
    )
    print(f"Файлов найдено: {stats['files_found']}")
    print(f"Обработано в текущем индексе: {stats['files_processed']}")
    print(f"Обработано заново в этом запуске: {stats['processed_this_run']}")
    print(f"Без изменений: {stats['unchanged']}")
    print(f"Не найдено при сканировании, сохранено: {stats['missing_kept']}")
    print(f"PDF без текста: {stats['pdf_without_text']}")
    print(f"Chunk'ов (без дублей): {stats['chunks']}")
    print(f"Дублей: {stats['duplicates']}")
    print(f"Расширения: {json.dumps(stats['extensions'], ensure_ascii=False)}")
    print(f"Режим поиска: {stats['fts_mode']}")
    print(f"SQLite: {stats['db_path']}")
    print(f"CSV: {stats['drive_csv']}")
    print(f"JSONL: {stats['drive_jsonl']}")
    print(f"Лог: {stats['log_path']}")
    if stats["problems"]:
        print("\nПричины проблем:")
        for problem in stats["problems"]:
            reason = " ".join(str(problem["reason"]).splitlines())
            kept = (
                " — сохранена предыдущая корректная версия"
                if problem["last_good_kept"]
                else ""
            )
            print(f"- [{problem['kind']}] {problem['path']}: {reason}{kept}")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Построить или обновить локальный поисковый индекс корпуса Тайра."
    )
    parser.add_argument(
        "corpus",
        nargs="?",
        default=str(DEFAULT_CORPUS),
        help=f"Папка корпуса (по умолчанию: {DEFAULT_CORPUS})",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Путь к SQLite")
    parser.add_argument(
        "--aliases", default=str(PROJECT_DIR / "aliases.json"), help="Файл алиасов"
    )
    parser.add_argument(
        "--topics", default=str(PROJECT_DIR / "topics.json"), help="Файл тем"
    )
    parser.add_argument(
        "--people", default=str(DEFAULT_PEOPLE), help="Файл персонажей"
    )
    parser.add_argument(
        "--source-types",
        default=str(DEFAULT_SOURCE_TYPES),
        help="Файл правил классификации источников",
    )
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="Файл лога")
    parser.add_argument("--drive-csv", default=str(DEFAULT_DRIVE_CSV))
    parser.add_argument("--drive-jsonl", default=str(DEFAULT_DRIVE_JSONL))
    parser.add_argument(
        "--rebuild", action="store_true", help="Принудительно перестроить все файлы"
    )
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="Только найти файлы и показать объём, не создавая индекс",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Печатать каждый файл и результат его обработки",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        metavar="N",
        help="Показывать подробную сводку каждые N файлов (по умолчанию: 25)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console()
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.progress_every < 1:
        parser.error("--progress-every должен быть положительным числом")
    try:
        stats = build_index(args)
    except KeyboardInterrupt:
        print(f"\nСтатус сборки: {BUILD_INTERRUPTED}", file=sys.stderr)
        print("Операция остановлена пользователем. База не изменена.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Статус сборки: {BUILD_FAILED}", file=sys.stderr)
        print("Проблемных файлов/путей: 1", file=sys.stderr)
        reason = " ".join(str(exc).splitlines())
        print(f"- [CRITICAL_ERROR] {reason}", file=sys.stderr)
        return 1
    if stats.get("scan_only"):
        return 0
    print_stats(stats)
    if stats.get("interrupted"):
        print("\nИндексация остановлена пользователем.")
        print(
            f"Полностью обработано: {stats['completed']} / "
            f"{stats['supported_files']} файлов."
        )
        print("Результат сохранён.")
        print("Для продолжения запустите build_index.py снова.")
        return 130
    if stats["build_status"] == BUILD_COMPLETED_WITH_ERRORS:
        print(
            "\nИндексация завершена с ошибками отдельных файлов. "
            "Проверьте причины выше и журнал.",
            file=sys.stderr,
        )
        return 1
    if stats["build_status"] != BUILD_SUCCEEDED:
        print(
            f"\nНеожиданный статус сборки: {stats['build_status']}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
