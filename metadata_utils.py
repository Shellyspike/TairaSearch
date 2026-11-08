"""Configurable metadata classification for TairaSearch chunks."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from text_utils import normalize_text


ESCAPED_UNICODE_RE = re.compile(r"#U[0-9A-Fa-f]{4,6}")
TYPE_ONE_GLYPH_RE = re.compile(r"(?:/TypeOne\d+){3,}")
EXPECTED_TEXT_SCRIPTS = {
    "CJK",
    "HIRAGANA",
    "KATAKANA",
    "HANGUL",
    "LATIN",
    "MODIFIER",
}


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Не найден {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ошибка JSON в {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path}: ожидается JSON-объект")
    return value


def load_source_types(path: Path | None) -> dict[str, list[str]]:
    """Load optional library-specific source classification rules."""
    if path is None:
        return {}
    raw = load_json_object(path, "source_types.json")
    allowed = {"historical", "scholarship", "literary", "other"}
    result: dict[str, list[str]] = {}
    for source_type, patterns in raw.items():
        if source_type not in allowed or not isinstance(patterns, list):
            raise RuntimeError(
                f"{path}: допустимы historical/scholarship/literary/other со списками"
            )
        if not all(isinstance(item, str) for item in patterns):
            raise RuntimeError(f"{path}: шаблоны должны быть строками")
        result[source_type] = patterns
    return result


def classify_source_type(
    source: str,
    filename: str,
    relative_path: str,
    source_types: dict[str, list[str]],
) -> str:
    haystack = normalize_text(" ".join([source, filename, relative_path])).casefold()
    for source_type in ("historical", "literary", "scholarship", "other"):
        for pattern in source_types.get(source_type, []):
            if normalize_text(pattern).casefold() in haystack:
                return source_type
    # An unclassified PDF is much more likely to be a modern article than a
    # primary-source OCR. Explicit config patterns always take precedence.
    if Path(filename).suffix.casefold() == ".pdf":
        return "scholarship"
    return "other"


def classify_text_quality(text: str) -> str:
    """Conservative heuristic: ambiguous text remains good and searchable."""
    normalized = normalize_text(text)
    if not normalized:
        return "no_text"
    length = max(len(normalized), 1)
    replacement = normalized.count("\ufffd")
    controls = sum(
        1
        for char in normalized
        if unicodedata.category(char) in {"Cc", "Cs"} and char not in "\n\r\t"
    )
    private_or_unassigned = sum(
        1 for char in normalized if unicodedata.category(char) in {"Co", "Cn"}
    )
    alphabetic = 0
    unexpected_scripts: set[str] = set()
    unexpected_letters = 0
    for char in normalized:
        if not char.isalpha():
            continue
        alphabetic += 1
        script = unicodedata.name(char, "UNKNOWN").split()[0]
        if script not in EXPECTED_TEXT_SCRIPTS:
            unexpected_scripts.add(script)
            unexpected_letters += 1
    if ESCAPED_UNICODE_RE.search(normalized):
        return "garbled"
    if TYPE_ONE_GLYPH_RE.search(normalized):
        return "garbled"
    if replacement + controls >= max(3, int(length * 0.01)):
        return "garbled"
    if private_or_unassigned >= max(8, int(length * 0.05)):
        return "garbled"
    if (
        len(unexpected_scripts) >= 5
        and unexpected_letters >= max(20, int(alphabetic * 0.1))
    ):
        return "garbled"
    return "good"
