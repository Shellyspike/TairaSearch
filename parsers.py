"""Read-only parsers for the corpus formats supported by TairaSearch."""

from __future__ import annotations

import json
import codecs
import re
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import ModuleType
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


class PdfProcessingError(RuntimeError):
    """Base error with a stable diagnostic code for PDF failures."""

    error_code = "PDF_ERROR"


class PdfDependencyError(PdfProcessingError):
    """The supported pypdf dependency is unavailable."""

    error_code = "PDF_DEPENDENCY_ERROR"


class PdfReadError(PdfProcessingError):
    """The PDF container cannot be opened or its page tree cannot be read."""

    error_code = "PDF_READ_ERROR"


class PdfEncryptedError(PdfProcessingError):
    """The PDF requires a password before text can be extracted."""

    error_code = "PDF_ENCRYPTED"


class PdfPartialReadError(PdfProcessingError):
    """At least one PDF page failed, so the extracted document is incomplete."""

    error_code = "PDF_PARTIAL_READ"


class TextDecodingError(UnicodeError):
    """Text bytes could not be decoded without an unsafe guess."""


def _load_pypdf() -> tuple[ModuleType, str]:
    try:
        module = import_module("pypdf")
    except ModuleNotFoundError as exc:
        if exc.name != "pypdf":
            raise
        raise PdfDependencyError(
            "Поддержка PDF недоступна: пакет pypdf не установлен. "
            "Активируйте виртуальное окружение и выполните "
            "`python -m pip install -r requirements.txt`."
        ) from exc

    version = str(getattr(module, "__version__", "unknown"))
    match = re.match(r"^(\d+)", version)
    if match and not 5 <= int(match.group(1)) < 7:
        raise PdfDependencyError(
            f"Установлена неподдерживаемая версия pypdf {version}; "
            "требуется pypdf>=5.0,<7. "
            "Выполните `python -m pip install -r requirements.txt`."
        )
    if not hasattr(module, "PdfReader"):
        raise PdfDependencyError(
            "Установленный пакет pypdf не содержит PdfReader. "
            "Переустановите зависимости из requirements.txt."
        )
    return module, version


def ensure_pdf_support() -> str:
    """Validate the PDF backend without opening or changing an index."""

    _, version = _load_pypdf()
    return version


def _pdf_error_detail(exc: Exception) -> str:
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _script_confidence(text: str, encoding: str) -> float:
    if not text or any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        return 0.0
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    if encoding == "cp1251":
        matching = sum("\u0400" <= char <= "\u052f" for char in letters)
    else:
        matching = sum(
            "\u3040" <= char <= "\u30ff"
            or "\u3400" <= char <= "\u9fff"
            or "\uff61" <= char <= "\uff9f"
            for char in letters
        )
    return matching / len(letters) if matching >= 2 else 0.0


def _bom_encoding(data: bytes) -> str | None:
    if data.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if data.startswith(codecs.BOM_UTF32_LE) or data.startswith(codecs.BOM_UTF32_BE):
        raise TextDecodingError("UTF-32 не поддерживается; укажите поддерживаемую кодировку")
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return "utf-16"
    return None


def _probable_utf16_without_bom(data: bytes) -> str | None:
    if len(data) < 4 or len(data) % 2:
        return None
    even = data[0::2]
    odd = data[1::2]
    even_nuls = even.count(0) / len(even)
    odd_nuls = odd.count(0) / len(odd)
    if odd_nuls >= 0.30 and even_nuls <= 0.05:
        return "utf-16-le"
    if even_nuls >= 0.30 and odd_nuls <= 0.05:
        return "utf-16-be"
    return None


def decode_text_bytes(data: bytes, *, encoding: str | None = None) -> str:
    if not data:
        return ""
    if encoding:
        try:
            codecs.lookup(encoding)
            return data.decode(encoding, errors="strict")
        except (UnicodeDecodeError, LookupError) as exc:
            raise TextDecodingError(
                f"Не удалось декодировать текст как {encoding}: {exc}"
            ) from exc

    bom = _bom_encoding(data)
    if bom:
        return data.decode(bom, errors="strict")
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        pass

    utf16 = _probable_utf16_without_bom(data)
    if utf16:
        try:
            return data.decode(utf16, errors="strict")
        except UnicodeDecodeError:
            pass

    candidates_by_text: dict[str, tuple[float, str, str]] = {}
    for legacy_encoding in ("cp932", "shift_jis", "cp1251"):
        try:
            decoded = data.decode(legacy_encoding, errors="strict")
        except UnicodeDecodeError:
            continue
        confidence = _script_confidence(decoded, legacy_encoding)
        if confidence:
            previous = candidates_by_text.get(decoded)
            candidate = (confidence, legacy_encoding, decoded)
            if previous is None or candidate[0] > previous[0]:
                candidates_by_text[decoded] = candidate
    candidates = list(candidates_by_text.values())
    candidates.sort(key=lambda item: item[0], reverse=True)
    if candidates and (
        len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= 0.10
    ):
        return candidates[0][2]
    choices = ", ".join(item[1] for item in candidates) or "нет надёжных кандидатов"
    raise TextDecodingError(
        "Кодировка текста неоднозначна или не поддерживается "
        f"({choices}). Укажите encoding явно."
    )


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


def parse_json(path: Path, *, encoding: str | None = None) -> ParsedDocument:
    raw = decode_text_bytes(path.read_bytes(), encoding=encoding)
    value = json.loads(raw)
    text = "\n".join(_collect_json_strings(value))
    page = infer_page_number(path)
    cleaned = clean_original_text(text)
    return ParsedDocument([TextUnit(cleaned, page, page)] if cleaned else [])


def parse_plain_text(path: Path, *, encoding: str | None = None) -> ParsedDocument:
    text = clean_original_text(decode_text_bytes(path.read_bytes(), encoding=encoding))
    page = infer_page_number(path)
    return ParsedDocument([TextUnit(text, page, page)] if text else [])


def parse_pdf(
    path: Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ParsedDocument:
    module, _ = _load_pypdf()
    try:
        reader = module.PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception as exc:
                raise PdfEncryptedError(
                    f"PDF защищён паролем и не может быть прочитан: {path.name} "
                    f"({_pdf_error_detail(exc)})"
                ) from exc
            if not unlocked:
                raise PdfEncryptedError(
                    f"PDF защищён паролем и не может быть прочитан: {path.name}"
                )
        page_count = len(reader.pages)
    except PdfProcessingError:
        raise
    except Exception as exc:
        raise PdfReadError(
            f"Не удалось прочитать PDF {path.name}: {_pdf_error_detail(exc)}"
        ) from exc

    if progress_callback:
        progress_callback(0, page_count)
    progress_step = max(25, round(page_count / 250) * 25)
    units: list[TextUnit] = []
    warnings: list[str] = []
    total_nonspace = 0
    for page_no in range(1, page_count + 1):
        try:
            page = reader.pages[page_no - 1]
            text = clean_original_text(page.extract_text() or "")
        except Exception as exc:  # a broken page must not hide the rest of the PDF
            warnings.append(f"Страница {page_no}: {_pdf_error_detail(exc)}")
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
    *,
    encoding: str | None = None,
) -> ParsedDocument:
    extension = path.suffix.casefold()
    if extension in {".txt", ".md"}:
        return parse_plain_text(path, encoding=encoding)
    if extension == ".json":
        return parse_json(path, encoding=encoding)
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
