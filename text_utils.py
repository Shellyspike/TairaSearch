"""Нормализация, разбиение текста и словарные метки для TairaSearch."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Iterable


ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
SPACE_RE = re.compile(r"[ \t\u3000]+")
ALL_SPACE_RE = re.compile(r"\s+")
SOURCE_PREFIX_RE = re.compile(r"^\s*\d+\s*[—–-]\s*")


def normalize_text(text: str) -> str:
    """Return a stable one-line representation suitable for hashes/search."""
    text = unicodedata.normalize("NFKC", text or "")
    text = ZERO_WIDTH_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return ALL_SPACE_RE.sub(" ", text).strip()


def clean_original_text(text: str) -> str:
    """Normalize line endings while retaining readable paragraph breaks."""
    text = unicodedata.normalize("NFC", text or "")
    text = ZERO_WIDTH_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    cleaned: list[str] = []
    for line in lines:
        if line or (cleaned and cleaned[-1]):
            cleaned.append(line)
    return "\n".join(cleaned).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_chunk_id(
    relative_path: str,
    page_start: int | None,
    page_end: int | None,
    chunk_no: int,
) -> str:
    identity = "\x1f".join(
        [
            unicodedata.normalize("NFC", PurePosixPath(relative_path).as_posix()),
            "" if page_start is None else str(page_start),
            "" if page_end is None else str(page_end),
            str(chunk_no),
        ]
    )
    return "ch_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def split_text(
    text: str,
    *,
    target: int = 2200,
    minimum: int = 1500,
    maximum: int = 3000,
    overlap: int = 180,
) -> list[str]:
    """Split near paragraph/sentence boundaries, keeping a small overlap."""
    text = clean_original_text(text)
    if not text:
        return []
    if len(text) <= maximum:
        return [text]

    chunks: list[str] = []
    start = 0
    length = len(text)
    soft_boundaries = set("\n。！？.!?；;、, ")
    while start < length:
        hard_end = min(start + maximum, length)
        if hard_end == length:
            end = length
        else:
            low = min(start + minimum, hard_end)
            preferred = min(start + target, hard_end)
            end = -1
            for index in range(preferred, low - 1, -1):
                if text[index - 1] in soft_boundaries:
                    end = index
                    break
            if end < 0:
                for index in range(preferred + 1, hard_end + 1):
                    if text[index - 1] in soft_boundaries:
                        end = index
                        break
            if end < 0:
                end = hard_end
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        new_start = max(0, end - overlap)
        if new_start <= start:
            new_start = end
        start = new_start
    return chunks


def make_preview(text: str, limit: int = 800) -> str:
    compact = normalize_text(text)
    if len(compact) <= limit:
        return compact
    cut = compact[:limit]
    boundary = max(cut.rfind("。"), cut.rfind("."), cut.rfind(" "))
    if boundary >= int(limit * 0.65):
        cut = cut[: boundary + 1]
    return cut.rstrip() + "…"


def detect_labels(text: str, groups: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Return canonical labels and the concrete variants found in text."""
    normalized = normalize_text(text)
    compact = ALL_SPACE_RE.sub("", normalized)
    labels: list[str] = []
    terms: set[str] = set()
    for label, variants in groups.items():
        candidates = list(dict.fromkeys([label, *variants]))
        found = []
        for term in candidates:
            normalized_term = normalize_text(term)
            compact_term = ALL_SPACE_RE.sub("", normalized_term)
            if normalized_term and (
                normalized_term in normalized
                or (compact_term and compact_term in compact)
            ):
                found.append(term)
        if found:
            labels.append(label)
            terms.update(found)
    return sorted(labels), sorted(terms)


def derive_source(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    raw = path.parts[0] if len(path.parts) > 1 else Path(path.name).stem
    source = SOURCE_PREFIX_RE.sub("", raw).strip()
    return source or raw


def unique_normalized(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output
