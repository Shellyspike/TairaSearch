#!/usr/bin/env python3
"""Safe, reproducible staging of Codex-discovered public sources.

Codex owns discovery, bibliographic judgement, and editorial review.  This
module owns the deterministic boundary: duplicate checks, bounded downloads,
format-specific extraction, immutable originals, a local journal, explicit
promotion, and optional invocation of the existing incremental indexer.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from parsers import PdfProcessingError, decode_text_bytes, parse_pdf
from research_profile import load_research_profile
from text_utils import normalize_text


PROJECT_DIR = Path(__file__).resolve().parent
JOURNAL_VERSION = 1
MANIFEST_VERSION = 1
POLICY_VERSION = 1
SUPPORTED_FORMATS = {"pdf", "html", "txt", "md", "xml", "tei", "epub"}
CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/epub+zip": "epub",
    "application/xhtml+xml": "html",
    "application/xml": "xml",
    "text/html": "html",
    "text/markdown": "md",
    "text/plain": "txt",
    "text/xml": "xml",
}
FORMAT_EXTENSIONS = {
    "pdf": ".pdf",
    "html": ".html",
    "txt": ".txt",
    "md": ".md",
    "xml": ".xml",
    "tei": ".xml",
    "epub": ".epub",
}
DEFAULT_MAX_FILES = 10
DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 50 * 1024 * 1024
DEFAULT_MIN_TEXT_CHARS = 200
MAX_EPUB_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


class AcquisitionError(RuntimeError):
    """A safe, user-facing acquisition failure."""


class DuplicateSourceError(AcquisitionError):
    """The candidate is already represented locally."""


@dataclass(frozen=True)
class Limits:
    max_files: int = DEFAULT_MAX_FILES
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS


class VisibleTextParser(HTMLParser):
    """Small dependency-free extractor that excludes non-content elements."""

    BLOCK_TAGS = {
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "main",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
    }
    IGNORED_TAGS = {"head", "nav", "noscript", "script", "style", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.casefold()
        if tag in self.IGNORED_TAGS:
            self.ignored_depth += 1
        elif not self.ignored_depth and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.IGNORED_TAGS:
            self.ignored_depth = max(0, self.ignored_depth - 1)
        elif not self.ignored_depth and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return clean_extracted_text(" ".join(self.parts))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise AcquisitionError("Разрешены только обычные HTTP/HTTPS URL")
    if not parsed.hostname or parsed.username or parsed.password:
        raise AcquisitionError("URL должен содержать публичный хост без учётных данных")
    host = parsed.hostname.casefold()
    port = parsed.port
    netloc = host if port is None else f"{host}:{port}"
    path = parsed.path or "/"
    return urllib.parse.urlunsplit(
        (parsed.scheme.casefold(), netloc, path, parsed.query, "")
    )


def normalize_identifier(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def normalize_doi(value: str) -> str:
    value = normalize_identifier(value)
    value = re.sub(r"^(?:doi:|https?://(?:dx\.)?doi\.org/)", "", value)
    return value.rstrip(".,;)")


def normalized_title(value: str) -> str:
    return re.sub(r"[^\w]+", " ", normalize_text(value).casefold()).strip()


def safe_slug(value: str, fallback: str = "source") -> str:
    value = normalize_text(value)
    value = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-._")
    return value[:80] or fallback


def clean_extracted_text(value: str) -> str:
    value = html.unescape(value).replace("\x00", "")
    value = re.sub(r"[ \t\f\v]+", " ", value)
    value = re.sub(r"\s*\n\s*", "\n", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise AcquisitionError(f"Не найден {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AcquisitionError(f"Повреждён JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AcquisitionError(f"{path}: ожидается JSON-объект")
    return value


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def normalized_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def ensure_distinct_files(paths: dict[str, Path | None]) -> None:
    seen: dict[Path, str] = {}
    for label, raw_path in paths.items():
        if raw_path is None:
            continue
        path = normalized_path(raw_path)
        previous = seen.get(path)
        if previous is not None:
            raise AcquisitionError(
                f"Небезопасное совпадение путей после нормализации: "
                f"{previous} и {label} указывают на {path}"
            )
        seen[path] = label


def path_contains(parent: Path, child: Path) -> bool:
    try:
        normalized_path(child).relative_to(normalized_path(parent))
        return True
    except ValueError:
        return False


@contextlib.contextmanager
def journal_lock(path: Path, timeout: float = 10.0) -> Iterable[None]:
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        except FileExistsError as exc:
            if time.monotonic() >= deadline:
                raise AcquisitionError(f"Журнал занят другим процессом: {path}") from exc
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(descriptor)
        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()


def load_journal(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": JOURNAL_VERSION, "entries": []}
    value = read_json_object(path, "журнал загрузок")
    if value.get("version") != JOURNAL_VERSION or not isinstance(
        value.get("entries"), list
    ):
        raise AcquisitionError(f"Неподдерживаемый формат журнала: {path}")
    if not all(isinstance(item, dict) for item in value["entries"]):
        raise AcquisitionError(f"Повреждены записи журнала: {path}")
    return value


def append_journal(path: Path, entry: dict[str, Any]) -> None:
    with journal_lock(path):
        journal = load_journal(path)
        entries = journal["entries"]
        same_run = next(
            (
                item
                for item in entries
                if item.get("source_id") == entry.get("source_id")
                and item.get("status") == entry.get("status")
                and item.get("content_sha256") == entry.get("content_sha256")
            ),
            None,
        )
        if same_run is None:
            entries.append(entry)
            write_json_atomic(path, journal)


def load_manifest(path: Path) -> list[dict[str, Any]]:
    value = read_json_object(path, "манифест кандидатов")
    if value.get("version") != MANIFEST_VERSION:
        raise AcquisitionError(
            f"{path}: поддерживается version={MANIFEST_VERSION}"
        )
    raw_sources = value.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise AcquisitionError(f"{path}: sources должен быть непустым массивом")
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for number, raw in enumerate(raw_sources, start=1):
        if not isinstance(raw, dict):
            raise AcquisitionError(f"sources[{number}]: ожидается объект")
        title = normalize_text(str(raw.get("title", "")))
        author = normalize_text(str(raw.get("author", "")))
        url = canonical_url(str(raw.get("url", "")))
        declared_format = normalize_text(str(raw.get("format", ""))).casefold()
        if declared_format not in SUPPORTED_FORMATS:
            raise AcquisitionError(
                f"sources[{number}]: неподдерживаемый format {declared_format!r}"
            )
        access = normalize_text(str(raw.get("access", ""))).casefold()
        if access not in {"open", "public-domain", "authorized"}:
            raise AcquisitionError(
                f"sources[{number}]: access должен быть open, public-domain или authorized"
            )
        if not title or not author:
            raise AcquisitionError(f"sources[{number}]: обязательны title и author")
        aliases = raw.get("title_variants", [])
        if not isinstance(aliases, list) or not all(
            isinstance(item, str) for item in aliases
        ):
            raise AcquisitionError(f"sources[{number}].title_variants: список строк")
        filename = safe_slug(
            str(raw.get("filename") or Path(urllib.parse.urlsplit(url).path).name),
            f"source-{number}",
        )
        doi = normalize_doi(str(raw.get("doi", "")))
        identity = doi or url or f"{title}\x1f{author}"
        source_id = safe_slug(
            str(raw.get("id", "")),
            hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        )
        if source_id in seen_ids:
            raise AcquisitionError(f"Повторяющийся source id: {source_id}")
        seen_ids.add(source_id)
        result.append(
            {
                "id": source_id,
                "title": title,
                "author": author,
                "year": normalize_text(str(raw.get("year", ""))),
                "url": url,
                "doi": doi,
                "format": declared_format,
                "filename": filename,
                "title_variants": [normalize_text(item) for item in aliases if item.strip()],
                "language": normalize_text(str(raw.get("language", ""))),
                "repository": normalize_text(str(raw.get("repository", ""))),
                "access": access,
                "reuse_terms": normalize_text(str(raw.get("reuse_terms", ""))),
                "interest_id": normalize_text(str(raw.get("interest_id", ""))),
                "why_useful": normalize_text(str(raw.get("why_useful", ""))),
            }
        )
    return result


def validate_manifest_against_profile(
    candidates: list[dict[str, Any]], profile: dict[str, Any]
) -> None:
    interest_ids = {str(item["id"]) for item in profile["interests"]}
    for candidate in candidates:
        interest_id = candidate["interest_id"]
        if not interest_id:
            raise AcquisitionError(
                f"{candidate['id']}: нужен interest_id из research_profile.json"
            )
        if interest_id not in interest_ids:
            raise AcquisitionError(
                f"{candidate['id']}: interest_id {interest_id!r} отсутствует в профиле"
            )


def load_policy(path: Path | None) -> tuple[bool, Limits]:
    if path is None:
        return False, Limits()
    value = read_json_object(path, "политика загрузок")
    if value.get("version") != POLICY_VERSION:
        raise AcquisitionError(f"{path}: поддерживается version={POLICY_VERSION}")
    allowed = value.get("automatic_downloads") is True

    def positive_int(name: str, default: int) -> int:
        raw = value.get(name, default)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            raise AcquisitionError(f"{path}: {name} должен быть положительным целым")
        return raw

    return allowed, Limits(
        max_files=positive_int("max_files_per_run", DEFAULT_MAX_FILES),
        max_file_bytes=positive_int("max_file_bytes", DEFAULT_MAX_FILE_BYTES),
        max_total_bytes=positive_int("max_total_bytes", DEFAULT_MAX_TOTAL_BYTES),
        min_text_chars=positive_int("min_text_chars", DEFAULT_MIN_TEXT_CHARS),
    )


def candidate_keys(candidate: dict[str, Any]) -> dict[str, set[str]]:
    titles = {
        normalized_title(value)
        for value in [candidate["title"], *candidate["title_variants"]]
        if normalized_title(value)
    }
    filenames = {Path(candidate["filename"]).name.casefold()}
    url_path_name = Path(urllib.parse.urlsplit(candidate["url"]).path).name.casefold()
    if url_path_name:
        filenames.add(url_path_name)
    return {
        "urls": {candidate["url"]},
        "dois": {candidate["doi"]} if candidate["doi"] else set(),
        "titles": titles,
        "authors": {normalized_title(candidate["author"])},
        "filenames": filenames,
    }


def journal_duplicate(candidate: dict[str, Any], journal: dict[str, Any]) -> str | None:
    keys = candidate_keys(candidate)
    for entry in journal["entries"]:
        if entry.get("status") not in {"staged", "promoted", "already_staged"}:
            continue
        if entry.get("url") in keys["urls"]:
            return f"тот же URL уже записан ({entry.get('source_id', '?')})"
        if entry.get("doi") and entry.get("doi") in keys["dois"]:
            return f"тот же DOI уже записан ({entry.get('source_id', '?')})"
        if (
            normalized_title(str(entry.get("title", ""))) in keys["titles"]
            and normalized_title(str(entry.get("author", ""))) in keys["authors"]
        ):
            return (
                "то же название и автор уже записаны "
                f"({entry.get('source_id', '?')})"
            )
        if str(entry.get("filename", "")).casefold() in keys["filenames"]:
            return f"то же имя файла уже записано ({entry.get('source_id', '?')})"
    return None


def sqlite_duplicate(candidate: dict[str, Any], db_path: Path | None) -> str | None:
    if db_path is None or not db_path.exists():
        return None
    keys = candidate_keys(candidate)
    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise AcquisitionError(f"Не удалось открыть индекс только для чтения: {exc}") from exc
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "files" not in tables:
            raise AcquisitionError(f"{db_path}: нет таблицы files")
        for row in connection.execute("SELECT relative_path, filename FROM files"):
            indexed_name = str(row[1]).casefold()
            if indexed_name in keys["filenames"]:
                return f"имя файла уже есть в индексе: {row[0]}"
        if "chunks" in tables:
            exact_tokens = [candidate["doi"], candidate["url"]]
            for token in exact_tokens:
                if not token:
                    continue
                row = connection.execute(
                    "SELECT relative_path FROM chunks WHERE lower(original_text) LIKE ? LIMIT 1",
                    (f"%{token.casefold()}%",),
                ).fetchone()
                if row:
                    return f"метаданные найдены в тексте индекса: {row[0]}"
            author = normalized_title(candidate["author"])
            if len(author) >= 3:
                for title in [title for title in keys["titles"] if len(title) >= 16]:
                    row = connection.execute(
                        """
                        SELECT relative_path FROM chunks
                        WHERE lower(original_text) LIKE ?
                          AND lower(original_text) LIKE ?
                        LIMIT 1
                        """,
                        (f"%{title}%", f"%{author}%"),
                    ).fetchone()
                    if row:
                        return (
                            "название и автор найдены в тексте индекса: "
                            f"{row[0]}"
                        )
    except sqlite3.Error as exc:
        raise AcquisitionError(f"Ошибка чтения индекса {db_path}: {exc}") from exc
    finally:
        connection.close()
    return None


def duplicate_reason(
    candidate: dict[str, Any], journal: dict[str, Any], db_path: Path | None
) -> str | None:
    return journal_duplicate(candidate, journal) or sqlite_duplicate(candidate, db_path)


def check_candidates(
    candidates: list[dict[str, Any]], journal_path: Path, db_path: Path | None
) -> dict[str, Any]:
    journal = load_journal(journal_path)
    items: list[dict[str, Any]] = []
    for candidate in candidates:
        reason = duplicate_reason(candidate, journal, db_path)
        items.append(
            {
                "source_id": candidate["id"],
                "title": candidate["title"],
                "author": candidate["author"],
                "url": candidate["url"],
                "status": "duplicate" if reason else "eligible",
                "reason": reason,
            }
        )
    return {
        "version": 1,
        "created_at": utc_now(),
        "operation": "check",
        "items": items,
        "summary": {
            "eligible": sum(item["status"] == "eligible" for item in items),
            "duplicates": sum(item["status"] == "duplicate" for item in items),
        },
    }


def download_bytes(url: str, maximum: int) -> tuple[bytes, str, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TairaSearch/0.4 (+local research library)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final_url = canonical_url(response.geturl())
            declared = response.headers.get("Content-Length")
            if declared:
                try:
                    if int(declared) > maximum:
                        raise AcquisitionError(
                            f"файл больше лимита {maximum} байт (Content-Length={declared})"
                        )
                except ValueError:
                    pass
            content_type = response.headers.get_content_type().casefold()
            output = bytearray()
            while True:
                piece = response.read(min(64 * 1024, maximum + 1 - len(output)))
                if not piece:
                    break
                output.extend(piece)
                if len(output) > maximum:
                    raise AcquisitionError(f"файл больше лимита {maximum} байт")
            return bytes(output), final_url, content_type
    except AcquisitionError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AcquisitionError(f"ошибка загрузки: {exc}") from exc


def extract_html(data: bytes) -> str:
    parser = VisibleTextParser()
    parser.feed(decode_text_bytes(data))
    parser.close()
    return parser.text()


def extract_xml(data: bytes) -> str:
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise AcquisitionError(f"повреждён XML/TEI: {exc}") from exc
    return clean_extracted_text(" ".join(root.itertext()))


def extract_epub(data: bytes) -> str:
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(data)) as archive:
            expanded_size = sum(info.file_size for info in archive.infolist())
            if expanded_size > MAX_EPUB_UNCOMPRESSED_BYTES:
                raise AcquisitionError(
                    "распакованный EPUB превышает безопасный лимит "
                    f"{MAX_EPUB_UNCOMPRESSED_BYTES} байт"
                )
            names = sorted(
                name
                for name in archive.namelist()
                if Path(name).suffix.casefold() in {".html", ".htm", ".xhtml", ".xml"}
                and not name.casefold().endswith("container.xml")
            )
            if not names:
                raise AcquisitionError("EPUB не содержит HTML/XHTML текста")
            pieces = [extract_html(archive.read(name)) for name in names]
    except zipfile.BadZipFile as exc:
        raise AcquisitionError("повреждён EPUB/ZIP контейнер") from exc
    return clean_extracted_text("\n\n".join(piece for piece in pieces if piece))


def pdf_quality(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        parsed = parse_pdf(path)
    except PdfProcessingError as exc:
        raise AcquisitionError(str(exc)) from exc
    if parsed.warnings:
        raise AcquisitionError(
            "PDF прочитан частично; предыдущая/полная версия не должна заменяться: "
            + "; ".join(parsed.warnings[:3])
        )
    if parsed.pdf_without_text or not parsed.units:
        raise AcquisitionError("PDF не содержит пригодного текстового слоя")
    page_count = parsed.page_count or 1
    targets = {
        "beginning": 1,
        "middle": max(1, (page_count + 1) // 2),
        "end": page_count,
    }
    samples: dict[str, dict[str, Any]] = {}
    for label, target in targets.items():
        nearest = min(
            parsed.units,
            key=lambda unit: abs((unit.page_start or target) - target),
        )
        distance = abs((nearest.page_start or target) - target)
        allowance = max(1, page_count // 10)
        chars = len(re.sub(r"\s+", "", nearest.text))
        samples[label] = {
            "target_page": target,
            "text_page": nearest.page_start,
            "nonspace_chars": chars,
        }
        if distance > allowance or chars < 20:
            raise AcquisitionError(
                f"PDF не прошёл проверку текста в секции {label} (страница {target})"
            )
    text = clean_extracted_text("\n\n".join(unit.text for unit in parsed.units))
    return text, {"page_count": page_count, "pdf_samples": samples}


def detect_format(
    declared: str, content_type: str, final_url: str, data: bytes
) -> str:
    content_format = CONTENT_TYPES.get(content_type.split(";", 1)[0].casefold())
    extension = Path(urllib.parse.urlsplit(final_url).path).suffix.casefold().lstrip(".")
    if extension == "htm":
        extension = "html"
    if extension == "xhtml":
        extension = "html"
    if extension in SUPPORTED_FORMATS and extension != declared:
        raise AcquisitionError(
            f"формат URL {extension} не совпадает с заявленным {declared}"
        )
    if content_format and content_format != declared and not {
        content_format,
        declared,
    } <= {"xml", "tei"}:
        raise AcquisitionError(
            f"Content-Type указывает {content_format}, заявлен {declared}"
        )
    signatures = {
        "pdf": data.startswith(b"%PDF-"),
        "epub": data.startswith(b"PK"),
    }
    if declared in signatures and not signatures[declared]:
        raise AcquisitionError(f"содержимое не похоже на {declared.upper()}")
    return declared


def extract_source(
    data: bytes, source_format: str, original_path: Path
) -> tuple[str, dict[str, Any]]:
    if source_format == "pdf":
        return pdf_quality(original_path)
    if source_format == "html":
        return extract_html(data), {}
    if source_format in {"xml", "tei"}:
        return extract_xml(data), {}
    if source_format == "epub":
        return extract_epub(data), {}
    return clean_extracted_text(decode_text_bytes(data)), {}


def stage_candidates(
    candidates: list[dict[str, Any]],
    *,
    staging_root: Path,
    journal_path: Path,
    db_path: Path | None,
    limits: Limits,
) -> dict[str, Any]:
    if len(candidates) > limits.max_files:
        raise AcquisitionError(
            f"Манифест содержит {len(candidates)} файлов, лимит запуска {limits.max_files}"
        )
    staging_root.mkdir(parents=True, exist_ok=True)
    journal = load_journal(journal_path)
    total_bytes = 0
    items: list[dict[str, Any]] = []
    for candidate in candidates:
        base = {
            "source_id": candidate["id"],
            "title": candidate["title"],
            "author": candidate["author"],
            "url": candidate["url"],
        }
        reason = duplicate_reason(candidate, journal, db_path)
        if reason:
            items.append({**base, "status": "duplicate", "reason": reason})
            continue
        source_dir = staging_root / candidate["id"]
        metadata_path = source_dir / "metadata.json"
        if metadata_path.exists():
            existing = read_json_object(metadata_path, "metadata staging")
            if (
                existing.get("source_id") != candidate["id"]
                or existing.get("url") != candidate["url"]
                or existing.get("title") != candidate["title"]
            ):
                items.append(
                    {
                        **base,
                        "status": "error",
                        "reason": (
                            f"source_id {candidate['id']} уже занят другим "
                            "staging-источником"
                        ),
                    }
                )
                continue
            recovered_entry = {
                "recorded_at": utc_now(),
                "status": "staged",
                "source_id": candidate["id"],
                "title": candidate["title"],
                "author": candidate["author"],
                "doi": candidate["doi"],
                "url": candidate["url"],
                "final_url": existing.get("final_url", candidate["url"]),
                "filename": existing.get("original_file", candidate["filename"]),
                "content_sha256": existing.get("content_sha256", ""),
                "local_directory": str(source_dir),
            }
            append_journal(journal_path, recovered_entry)
            items.append(
                {
                    **base,
                    "status": "already_staged",
                    "reason": "готовая staging-копия уже существует",
                    "local_directory": str(source_dir),
                    "content_sha256": existing.get("content_sha256"),
                }
            )
            continue
        temporary = Path(tempfile.mkdtemp(prefix=f".{candidate['id']}.", dir=staging_root))
        try:
            data, final_url, content_type = download_bytes(
                candidate["url"], limits.max_file_bytes
            )
            total_bytes += len(data)
            if total_bytes > limits.max_total_bytes:
                raise AcquisitionError(
                    f"суммарный размер превысил лимит {limits.max_total_bytes} байт"
                )
            source_format = detect_format(
                candidate["format"], content_type, final_url, data
            )
            extension = FORMAT_EXTENSIONS[source_format]
            original_name = safe_slug(Path(candidate["filename"]).stem, candidate["id"])
            original_path = temporary / f"original-{original_name}{extension}"
            original_path.write_bytes(data)
            extracted, details = extract_source(data, source_format, original_path)
            useful_chars = len(re.sub(r"\s+", "", extracted))
            if useful_chars < limits.min_text_chars:
                raise AcquisitionError(
                    f"извлечено только {useful_chars} знаков, минимум {limits.min_text_chars}"
                )
            extracted_path = temporary / "extracted.txt"
            extracted_path.write_text(extracted + "\n", encoding="utf-8", newline="\n")
            metadata = {
                "version": 1,
                "source_id": candidate["id"],
                **{key: value for key, value in candidate.items() if key != "id"},
                "downloaded_at": utc_now(),
                "final_url": final_url,
                "content_type": content_type,
                "content_sha256": sha256_bytes(data),
                "size_bytes": len(data),
                "original_file": original_path.name,
                "extracted_file": extracted_path.name,
                "quality": {
                    "status": "ready_for_review",
                    "extracted_chars": len(extracted),
                    "nonspace_chars": useful_chars,
                    **details,
                },
            }
            write_json_atomic(temporary / "metadata.json", metadata)
            try:
                temporary.replace(source_dir)
            except FileExistsError:
                raise AcquisitionError("staging-папка появилась во время загрузки")
            entry = {
                "recorded_at": utc_now(),
                "status": "staged",
                "source_id": candidate["id"],
                "title": candidate["title"],
                "author": candidate["author"],
                "doi": candidate["doi"],
                "url": candidate["url"],
                "final_url": final_url,
                "filename": original_path.name,
                "content_sha256": metadata["content_sha256"],
                "local_directory": str(source_dir),
            }
            append_journal(journal_path, entry)
            journal["entries"].append(entry)
            items.append(
                {
                    **base,
                    "status": "staged",
                    "local_directory": str(source_dir),
                    "original_file": str(source_dir / original_path.name),
                    "extracted_file": str(source_dir / "extracted.txt"),
                    "metadata_file": str(source_dir / "metadata.json"),
                    "content_sha256": metadata["content_sha256"],
                    "size_bytes": len(data),
                    "quality": metadata["quality"],
                }
            )
        except Exception as exc:
            items.append({**base, "status": "error", "reason": str(exc)})
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    summary = {
        status: sum(item["status"] == status for item in items)
        for status in ("staged", "already_staged", "duplicate", "error")
    }
    return {
        "version": 1,
        "created_at": utc_now(),
        "operation": "stage",
        "items": items,
        "summary": summary,
    }


def choose_promoted_files(metadata: dict[str, Any], source_dir: Path) -> list[Path]:
    original = source_dir / str(metadata["original_file"])
    extracted = source_dir / str(metadata["extracted_file"])
    if not original.is_file() or not extracted.is_file():
        raise AcquisitionError(f"Неполная staging-папка: {source_dir}")
    # PDF/TXT/Markdown are already indexable. Other originals are retained beside
    # an extracted TXT that the existing indexer understands.
    if metadata["format"] in {"pdf", "txt", "md"}:
        return [original]
    return [original, extracted]


def promote_sources(
    source_ids: list[str],
    *,
    staging_root: Path,
    corpus: Path,
    journal_path: Path,
    db_path: Path | None,
    run_index: bool,
) -> dict[str, Any]:
    if not corpus.is_dir():
        raise AcquisitionError(f"Папка корпуса недоступна: {corpus}")
    items: list[dict[str, Any]] = []
    for source_id in source_ids:
        source_id = safe_slug(source_id)
        source_dir = staging_root / source_id
        metadata = read_json_object(source_dir / "metadata.json", "metadata staging")
        if metadata.get("source_id") != source_id:
            raise AcquisitionError(f"Несовпадение source_id в {source_dir}")
        destination = corpus / "acquired" / source_id
        if destination.exists():
            provenance_path = destination / "source-metadata"
            if not provenance_path.is_file():
                raise AcquisitionError(
                    f"Папка назначения уже существует без provenance: {destination}"
                )
            promoted_metadata = read_json_object(
                provenance_path, "metadata перенесённого источника"
            )
            if promoted_metadata.get("content_sha256") != metadata.get(
                "content_sha256"
            ):
                raise AcquisitionError(
                    f"Папка назначения содержит другую версию: {destination}"
                )
            items.append(
                {
                    "source_id": source_id,
                    "status": "already_promoted",
                    "destination": str(destination),
                }
            )
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{source_id}.", dir=destination.parent))
        try:
            for path in choose_promoted_files(metadata, source_dir):
                shutil.copy2(path, temporary / path.name)
            # Keep provenance beside the promoted source without feeding it to the
            # existing JSON text parser as a second, artificial document.
            write_json_atomic(temporary / "source-metadata", metadata)
            temporary.replace(destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        entry = {
            "recorded_at": utc_now(),
            "status": "promoted",
            "source_id": source_id,
            "title": metadata.get("title", ""),
            "author": metadata.get("author", ""),
            "doi": metadata.get("doi", ""),
            "url": metadata.get("url", ""),
            "filename": metadata.get("original_file", ""),
            "content_sha256": metadata.get("content_sha256", ""),
            "local_directory": str(destination),
        }
        append_journal(journal_path, entry)
        items.append(
            {
                "source_id": source_id,
                "status": "promoted",
                "destination": str(destination),
            }
        )

    index_result: dict[str, Any] | None = None
    if run_index and items:
        if db_path is None:
            raise AcquisitionError("Для --index нужен --db")
        command = [
            sys.executable,
            str(PROJECT_DIR / "build_index.py"),
            str(corpus),
            "--db",
            str(db_path),
        ]
        completed = subprocess.run(command, check=False)
        index_result = {
            "command": command,
            "exit_code": completed.returncode,
            "status": "succeeded" if completed.returncode == 0 else "failed",
            "message": (
                "Индекс обновлён"
                if completed.returncode == 0
                else "Материалы перенесены, но build_index.py завершился с ошибкой; "
                "staging и журнал сохранены для диагностики"
            ),
        }
    index_error = int(bool(index_result and index_result["exit_code"] != 0))
    return {
        "version": 1,
        "created_at": utc_now(),
        "operation": "promote",
        "items": items,
        "index": index_result,
        "summary": {
            "promoted": sum(item["status"] == "promoted" for item in items),
            "already_promoted": sum(
                item["status"] == "already_promoted" for item in items
            ),
            "error": index_error,
        },
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Проверить и безопасно пополнить локальную исследовательскую библиотеку."
    )
    subcommands = root.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--manifest", required=True, type=Path)
        command.add_argument("--profile", required=True, type=Path)
        command.add_argument("--journal", required=True, type=Path)
        command.add_argument("--db", type=Path)
        command.add_argument("--report", required=True, type=Path)

    check = subcommands.add_parser("check", help="Проверить манифест и дубли без загрузки")
    common(check)

    stage = subcommands.add_parser("stage", help="Загрузить одобренные источники в staging")
    common(stage)
    stage.add_argument("--staging", required=True, type=Path)
    stage.add_argument(
        "--approve-downloads",
        action="store_true",
        help="Подтвердить разовую загрузку перечисленных источников",
    )
    stage.add_argument(
        "--policy",
        type=Path,
        help="Локальная политика с заранее разрешённым автоматическим режимом",
    )

    promote = subcommands.add_parser(
        "promote", help="Перенести явно одобренные staging-источники в корпус"
    )
    promote.add_argument("--source-id", action="append", required=True)
    promote.add_argument("--staging", required=True, type=Path)
    promote.add_argument("--corpus", required=True, type=Path)
    promote.add_argument("--journal", required=True, type=Path)
    promote.add_argument("--db", type=Path)
    promote.add_argument("--report", required=True, type=Path)
    promote.add_argument("--approve", action="store_true")
    promote.add_argument("--index", action="store_true")
    return root


def print_report(report: dict[str, Any], report_path: Path) -> None:
    write_json_atomic(report_path, report)
    summary = report.get("summary", {})
    print(f"Операция: {report['operation']}")
    print("; ".join(f"{key}: {value}" for key, value in summary.items()))
    print(f"Отчёт: {report_path}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    arguments = parser().parse_args(argv)
    try:
        if arguments.command in {"check", "stage"}:
            protected = {
                "--manifest": arguments.manifest,
                "--profile": arguments.profile,
                "--journal": arguments.journal,
                "--db": arguments.db,
                "--report": arguments.report,
            }
            if arguments.command == "stage":
                protected["--policy"] = arguments.policy
            ensure_distinct_files(protected)
            # Profile validation is intentional: discovery must remain tied to the
            # confirmed universal interests, even though Python does not choose queries.
            profile = load_research_profile(arguments.profile)
            candidates = load_manifest(arguments.manifest)
            validate_manifest_against_profile(candidates, profile)
            db_path = arguments.db.resolve() if arguments.db else None
            if arguments.command == "check":
                report = check_candidates(candidates, arguments.journal, db_path)
            else:
                automatic, limits = load_policy(arguments.policy)
                if not arguments.approve_downloads and not automatic:
                    raise AcquisitionError(
                        "Загрузка не разрешена: нужен --approve-downloads после явного "
                        "согласия пользователя или локальная --policy с automatic_downloads=true"
                    )
                report = stage_candidates(
                    candidates,
                    staging_root=arguments.staging,
                    journal_path=arguments.journal,
                    db_path=db_path,
                    limits=limits,
                )
        else:
            ensure_distinct_files(
                {
                    "--journal": arguments.journal,
                    "--db": arguments.db,
                    "--report": arguments.report,
                }
            )
            if path_contains(arguments.staging, arguments.corpus) or path_contains(
                arguments.corpus, arguments.staging
            ):
                raise AcquisitionError(
                    "Staging и корпус должны быть отдельными, не вложенными папками"
                )
            if not arguments.approve:
                raise AcquisitionError(
                    "Перенос не разрешён: после проверки нужен явный флаг --approve"
                )
            report = promote_sources(
                arguments.source_id,
                staging_root=arguments.staging,
                corpus=arguments.corpus,
                journal_path=arguments.journal,
                db_path=arguments.db,
                run_index=arguments.index,
            )
        print_report(report, arguments.report)
        if report.get("summary", {}).get("error", 0):
            return 1
        return 0
    except (AcquisitionError, OSError, sqlite3.Error) as exc:
        print(f"Ошибка пополнения библиотеки: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
