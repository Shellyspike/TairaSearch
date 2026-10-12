"""SQLite FTS5 schema, migration and synchronization helpers."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from metadata_utils import classify_source_type, classify_text_quality, detect_people
from text_utils import detect_labels


FTS_SCHEMA_VERSION = "2"
ANNOTATION_SCHEMA_VERSION = "2"
FTS_MODE = "fts5_unicode61_cjk"


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x3040 <= code <= 0x30FF
        or 0x31F0 <= code <= 0x31FF
    )


def prepare_fts_text(text: str) -> str:
    """Turn Japanese into character tokens while retaining other word tokens.

    FTS5 unicode61 then supports one- and two-character Japanese searches and
    treats proximity in Japanese as an intuitive character distance.
    """
    tokens: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            tokens.append("".join(buffer))
            buffer.clear()

    for char in text or "":
        if _is_cjk(char):
            flush()
            tokens.append(char)
        elif char.isalnum() or char in {"_", "'"}:
            buffer.append(char)
        else:
            flush()
    flush()
    return " ".join(tokens)


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name=? LIMIT 1", (name,)
    ).fetchone() is not None


def chunk_columns(connection: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in connection.execute("PRAGMA table_info(chunks)")}


def search_schema_is_current(connection: sqlite3.Connection) -> bool:
    """Return whether searches can run without changing the database.

    Search commands normally need only read access. Keeping this check
    separate from ``ensure_search_schema`` lets an up-to-date index stay in a
    read-only connection while legacy indexes retain their migration path.
    """
    columns = chunk_columns(connection)
    if {"source_type", "people_json", "text_quality"} - columns:
        return False
    try:
        meta = dict(connection.execute("SELECT key, value FROM meta"))
    except sqlite3.Error:
        return False
    fts_sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='chunks_fts'"
    ).fetchone()
    fts_sql = str(fts_sql_row[0]) if fts_sql_row else ""
    return (
        meta.get("fts_schema_version") == FTS_SCHEMA_VERSION
        and meta.get("annotation_schema_version") == ANNOTATION_SCHEMA_VERSION
        and "search_text" in fts_sql
        and "people_json" not in fts_sql
    )


def backup_database(connection: sqlite3.Connection, db_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.pre-fts5-v2-{stamp}.bak")
    destination = sqlite3.connect(backup_path)
    try:
        connection.backup(destination)
    finally:
        destination.close()
    return backup_path


def _json_list(value: str) -> list[str]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in decoded] if isinstance(decoded, list) else []


def fts_values(
    chunk_id: str,
    search_text: str,
    preview: str,
    aliases_json: str,
    topics_json: str,
) -> tuple[str, str, str, str, str]:
    aliases = " ".join(_json_list(aliases_json))
    topics = " ".join(_json_list(topics_json))
    return (
        chunk_id,
        prepare_fts_text(search_text),
        prepare_fts_text(preview),
        prepare_fts_text(aliases),
        prepare_fts_text(topics),
    )


def upsert_fts_chunk(
    connection: sqlite3.Connection,
    chunk_id: str,
    search_text: str,
    preview: str,
    aliases_json: str,
    topics_json: str,
) -> None:
    connection.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (chunk_id,))
    connection.execute(
        """
        INSERT INTO chunks_fts(chunk_id, search_text, preview, aliases, topics)
        VALUES(?, ?, ?, ?, ?)
        """,
        fts_values(chunk_id, search_text, preview, aliases_json, topics_json),
    )


def _create_fts(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS chunks_fts")
    connection.execute(
        """
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            chunk_id UNINDEXED,
            search_text,
            preview,
            aliases,
            topics,
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )


def _annotated_rows(
    rows: Iterable[sqlite3.Row],
    aliases: dict[str, list[str]],
    topics: dict[str, list[str]],
    people: dict[str, dict[str, Any]],
    source_types: dict[str, list[str]],
) -> Iterable[tuple[Any, ...]]:
    for row in rows:
        alias_labels, alias_terms = detect_labels(row["normalized_text"], aliases)
        topic_labels, topic_terms = detect_labels(row["normalized_text"], topics)
        people_labels = detect_people(row["normalized_text"], people)
        search_terms = sorted(
            set(alias_labels + alias_terms + topic_labels + topic_terms + people_labels)
        )
        yield (
            json.dumps(alias_labels, ensure_ascii=False),
            json.dumps(topic_labels, ensure_ascii=False),
            json.dumps(search_terms, ensure_ascii=False),
            classify_source_type(
                row["source"], row["filename"], row["relative_path"], source_types
            ),
            json.dumps(people_labels, ensure_ascii=False),
            classify_text_quality(row["normalized_text"]),
            row["id"],
        )


def ensure_search_schema(
    connection: sqlite3.Connection,
    db_path: Path,
    *,
    aliases: dict[str, list[str]],
    topics: dict[str, list[str]],
    people: dict[str, dict[str, Any]],
    source_types: dict[str, list[str]],
    refresh_metadata: bool = False,
    create_backup: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Apply an additive migration and rebuild only the derived FTS table."""
    progress = progress or (lambda _message: None)
    columns = chunk_columns(connection)
    missing = {"source_type", "people_json", "text_quality"} - columns
    meta = dict(connection.execute("SELECT key, value FROM meta"))
    fts_sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='chunks_fts'"
    ).fetchone()
    fts_sql = str(fts_sql_row[0]) if fts_sql_row else ""
    fts_outdated = (
        meta.get("fts_schema_version") != FTS_SCHEMA_VERSION
        or "search_text" not in fts_sql
        or "people_json" in fts_sql
    )
    row_count = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    migration_needed = bool(missing or fts_outdated)
    backup_path: Path | None = None
    if migration_needed and row_count and create_backup:
        progress("Создаю резервную копию SQLite перед миграцией…")
        backup_path = backup_database(connection, db_path)

    for name, definition in (
        ("source_type", "TEXT NOT NULL DEFAULT 'other'"),
        ("people_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("text_quality", "TEXT NOT NULL DEFAULT 'good'"),
    ):
        if name in missing:
            connection.execute(f"ALTER TABLE chunks ADD COLUMN {name} {definition}")

    annotation_outdated = meta.get("annotation_schema_version") != ANNOTATION_SCHEMA_VERSION
    metadata_refresh = bool(missing or refresh_metadata or annotation_outdated)
    if metadata_refresh:
        progress(f"Обновляю metadata для {row_count} чанков…")
        rows = connection.execute(
            """
            SELECT id, source, filename, relative_path, normalized_text
            FROM chunks ORDER BY id
            """
        )
        batch: list[tuple[Any, ...]] = []
        for values in _annotated_rows(rows, aliases, topics, people, source_types):
            batch.append(values)
            if len(batch) >= 500:
                connection.executemany(
                    """
                    UPDATE chunks
                    SET aliases_json=?, topics_json=?, search_terms_json=?,
                        source_type=?, people_json=?, text_quality=?
                    WHERE id=?
                    """,
                    batch,
                )
                batch.clear()
        if batch:
            connection.executemany(
                """
                UPDATE chunks
                SET aliases_json=?, topics_json=?, search_terms_json=?,
                    source_type=?, people_json=?, text_quality=?
                WHERE id=?
                """,
                batch,
            )

    if fts_outdated or metadata_refresh:
        progress(f"Строю FTS5 для {row_count} чанков из существующей SQLite…")
        _create_fts(connection)
        rows = connection.execute(
            """
            SELECT chunk_id, normalized_text, preview, aliases_json, topics_json
            FROM chunks ORDER BY id
            """
        )
        batch = []
        for row in rows:
            batch.append(fts_values(*row))
            if len(batch) >= 500:
                connection.executemany(
                    """
                    INSERT INTO chunks_fts(chunk_id, search_text, preview, aliases, topics)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    batch,
                )
                batch.clear()
        if batch:
            connection.executemany(
                """
                INSERT INTO chunks_fts(chunk_id, search_text, preview, aliases, topics)
                VALUES(?, ?, ?, ?, ?)
                """,
                batch,
            )

    connection.executemany(
        "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
        (
            ("fts_schema_version", FTS_SCHEMA_VERSION),
            ("annotation_schema_version", ANNOTATION_SCHEMA_VERSION),
            ("fts_mode", FTS_MODE),
        ),
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS chunks_source_type_idx ON chunks(source_type)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS chunks_quality_idx ON chunks(text_quality)"
    )
    connection.commit()
    return {
        "migrated": migration_needed,
        "metadata_refreshed": metadata_refresh,
        "backup_path": backup_path,
        "row_count": row_count,
        "fts_mode": FTS_MODE,
    }
