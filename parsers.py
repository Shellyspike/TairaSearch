"""Read-only parsers for the corpus formats supported by TairaSearch."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from text_utils import clean_original_text, split_text


PAGE_SUFFIX_RE = re.compile(r"(?:^|[_-])(\d{4,8})$")
PREFERRED_TEXT_KEYS = {
    "contenttext",
    "content_text",
    "text",
    "content",
    "body",
    "transcription",
    "ocr",
    "value",
}
IGNORED_STRING_KEYS = {
    "url",
    "uri",
    "path",
    "filename",
    "file_name",
    "mime",
    "mime_type",
    "id",
}


@dataclass(frozen=True)
class TextUnit:
    text: str
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class ParsedDocument:
    units: list[TextUnit]
    pdf_without_text: bool = False
    warnings: tuple[str, ...] = ()
    page_count: int | None = None


def decode_text_bytes(data: bytes) -> str:
    if not data:
        return ""
    encodings = ["utf-8-sig", "utf-16", "cp932", "shift_jis", "cp1251"]
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def infer_page_number(path: Path) -> int | None:
    match = PAGE_SUFFIX_RE.search(path.stem)
    if not match:
        return None
    number = int(match.group(1))
    return number if number > 0 else None


def _collect_json_strings(value: object, key: str | None = None) -> list[str]:
    if isinstance(value, str):
        if key and key.casefold() in IGNORED_STRING_KEYS:
            return []
        return [value] if value.strip() else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_collect_json_strings(item, key))
        return result
    if isinstance(value, dict):
        preferred: list[str] = []
        for child_key, child_value in value.items():
            if child_key.casefold() in PREFERRED_TEXT_KEYS:
                preferred.extend(_collect_json_strings(child_value, child_key))
        if preferred:
            return preferred
        result = []
        for child_key, child_value in value.items():
            result.extend(_collect_json_strings(child_value, child_key))
        return result
    return []


def parse_json(path: Path) -> ParsedDocument:
    raw = decode_text_bytes(path.read_bytes())
    value = json.loads(raw)
    text = "\n".join(_collect_json_strings(value))
    page = infer_page_number(path)
    cleaned = clean_original_text(text)
    return ParsedDocument([TextUnit(cleaned, page, page)] if cleaned else [])


def parse_plain_text(path: Path) -> ParsedDocument:
    text = clean_original_text(decode_text_bytes(path.read_bytes()))
    page = infer_page_number(path)
    return ParsedDocument([TextUnit(text, page, page)] if text else [])


def parse_pdf(
    path: Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ParsedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - depends on installation
        raise RuntimeError("Для PDF установите зависимости: pip install -r requirements.txt") from exc

    reader = PdfReader(str(path), strict=False)
    page_count = len(reader.pages)
    if progress_callback:
        progress_callback(0, page_count)
    progress_step = max(25, round(page_count / 250) * 25)
    units: list[TextUnit] = []
    warnings: list[str] = []
    total_nonspace = 0
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            text = clean_original_text(page.extract_text() or "")
        except Exception as exc:  # a broken page must not hide the rest of the PDF
            warnings.append(f"Страница {page_no}: {exc}")
            text = ""
        useful = len(re.sub(r"\s+", "", text))
        if useful:
            total_nonspace += useful
            units.append(TextUnit(text, page_no, page_no))
        if progress_callback and (
            page_no == page_count or page_no % progress_step == 0
        ):
            progress_callback(page_no, page_count)
    if total_nonspace < 20:
        return ParsedDocument(
            [],
            pdf_without_text=True,
            warnings=tuple(warnings),
            page_count=page_count,
        )
    return ParsedDocument(
        units, warnings=tuple(warnings), page_count=page_count
    )


def parse_file(
    path: Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ParsedDocument:
    extension = path.suffix.casefold()
    if extension in {".txt", ".md"}:
        return parse_plain_text(path)
    if extension == ".json":
        return parse_json(path)
    if extension == ".pdf":
        return parse_pdf(path, progress_callback=progress_callback)
    raise ValueError(f"Неподдерживаемое расширение: {extension or '[без расширения]'}")


def chunk_units(
    units: list[TextUnit],
    *,
    target: int = 2200,
    minimum: int = 1500,
    maximum: int = 3000,
) -> list[TextUnit]:
    if not units:
        return []
    has_pages = any(unit.page_start is not None for unit in units)
    if not has_pages:
        output: list[TextUnit] = []
        for unit in units:
            output.extend(
                TextUnit(piece, None, None)
                for piece in split_text(
                    unit.text, target=target, minimum=minimum, maximum=maximum
                )
            )
        return output

    output: list[TextUnit] = []
    pending: list[TextUnit] = []

    def flush() -> None:
        if not pending:
            return
        combined = "\n\n".join(item.text for item in pending if item.text).strip()
        if combined:
            start = pending[0].page_start
            end = pending[-1].page_end
            if len(combined) <= maximum:
                output.append(TextUnit(combined, start, end))
            else:
                output.extend(
                    TextUnit(piece, start, end)
                    for piece in split_text(
                        combined, target=target, minimum=minimum, maximum=maximum
                    )
                )
        pending.clear()

    for unit in units:
        if not unit.text.strip():
            continue
        proposed_length = sum(len(item.text) for item in pending) + len(unit.text)
        if pending and (len(pending) >= 2 or proposed_length > maximum):
            flush()
        pending.append(unit)
    flush()
    return output
