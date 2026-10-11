"""Configurable metadata classification for TairaSearch chunks."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from text_utils import normalize_text


ESCAPED_UNICODE_RE = re.compile(r"#U[0-9A-Fa-f]{4,6}")


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


def load_people(path: Path) -> dict[str, dict[str, Any]]:
    """Load a person mapping while accepting a deliberately simple JSON shape."""
    raw = load_json_object(path, "people.json")
    result: dict[str, dict[str, Any]] = {}
    for canonical, value in raw.items():
        if not isinstance(canonical, str):
            raise RuntimeError(f"{path}: имя персонажа должно быть строкой")
        romanized = ""
        aliases: list[str]
        if isinstance(value, str):
            romanized = value
            aliases = [canonical]
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            aliases = list(value)
        elif isinstance(value, dict):
            romanized_value = value.get("romanized", "")
            aliases_value = value.get("aliases", [])
            if not isinstance(romanized_value, str) or not isinstance(aliases_value, list):
                raise RuntimeError(f"{path}: неверная запись персонажа {canonical!r}")
            if not all(isinstance(item, str) for item in aliases_value):
                raise RuntimeError(f"{path}: aliases для {canonical!r} должны быть строками")
            romanized = romanized_value
            aliases = list(aliases_value)
        else:
            raise RuntimeError(f"{path}: неверная запись персонажа {canonical!r}")
        variants = list(dict.fromkeys([canonical, *aliases, romanized]))
        result[canonical] = {
            "romanized": romanized,
            "aliases": [item for item in variants if normalize_text(item)],
        }
    return result


def load_source_types(path: Path) -> dict[str, list[str]]:
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


def person_variants(people: dict[str, dict[str, Any]], name: str) -> tuple[str, list[str]]:
    needle = normalize_text(name).casefold()
    for canonical, record in people.items():
        variants = [normalize_text(item) for item in record["aliases"]]
        if needle in {item.casefold() for item in variants}:
            return canonical, variants
    raise ValueError(f"Неизвестный персонаж {name!r}. Доступны: {', '.join(people)}")


def detect_people(text: str, people: dict[str, dict[str, Any]]) -> list[str]:
    haystack = normalize_text(text).casefold()
    compact_haystack = "".join(haystack.split())
    found: list[str] = []
    for canonical, record in people.items():
        if any(
            normalize_text(alias).casefold() in haystack
            or "".join(normalize_text(alias).casefold().split()) in compact_haystack
            for alias in record["aliases"]
            if normalize_text(alias)
        ):
            found.append(canonical)
    return found


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
    if ESCAPED_UNICODE_RE.search(normalized):
        return "garbled"
    if replacement + controls >= max(3, int(length * 0.01)):
        return "garbled"
    if private_or_unassigned >= max(8, int(length * 0.05)):
        return "garbled"
    return "good"
