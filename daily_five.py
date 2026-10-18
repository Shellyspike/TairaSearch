"""Rule-based daily selection of five source-grounded Taira episodes."""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from argparse import Namespace
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

from metadata_utils import person_variants
from text_utils import normalize_text, unique_normalized


NICHES = (
    "illness",
    "horse",
    "music",
    "dream",
    "omen",
    "fire",
    "feast",
    "travel",
    "captivity",
    "violence",
    "family",
)
MILITARY_NICHES = {"captivity", "violence"}
HUMAN_NICHES = {
    "illness", "horse", "music", "dream", "omen", "fire", "feast", "travel", "family"
}
TOPIC_LABELS = {
    "illness": "болезнь и лечение",
    "horse": "лошади и верховая езда",
    "music": "музыка и исполнение",
    "dream": "сны",
    "omen": "знамения и необычные явления",
    "fire": "пожары",
    "feast": "пиры и застолья",
    "travel": "дорога и перемещения",
    "captivity": "плен и заключение",
    "violence": "насилие и столкновения",
    "family": "семья и родственные отношения",
}
PERSON_RU = {
    "清盛": "Киёмори",
    "重盛": "Сигэмори",
    "宗盛": "Мунэмори",
    "知盛": "Томомори",
    "重衡": "Сигэхира",
    "維盛": "Корэмори",
    "資盛": "Сукэмори",
    "忠度": "Таданори",
    "経盛": "Цунэмори",
    "教盛": "Норимори",
    "頼盛": "Ёримори",
    "時忠": "Токитада",
    "敦盛": "Ацумори",
    "徳子": "Токуко",
}
WHY_INTERESTING = {
    "illness": "Показывает телесный опыт, лечение и повседневную уязвимость представителей Тайра.",
    "horse": "Даёт небольшой эпизод о мобильности, церемонии или обращении с лошадьми.",
    "music": "Показывает культурную и церемониальную сторону жизни, не сводимую к политике и войне.",
    "dream": "Фиксирует сон или его толкование как часть исторического нарратива.",
    "omen": "Показывает, как необычные явления понимались и записывались современниками.",
    "fire": "Локальный эпизод позволяет увидеть материальную среду и реакцию на бедствие.",
    "feast": "Даёт бытовой или церемониальный эпизод вокруг еды, питья и собрания.",
    "travel": "Показывает маршрут, поездку или перемещение конкретного человека.",
    "captivity": "Даёт локально подтверждённый эпизод плена, задержания или ссылки.",
    "violence": "Фиксирует конкретное столкновение; отбирается с ограничением на военные сюжеты.",
    "family": "Показывает родственные и домашние связи, которые часто теряются в политической истории.",
}
DATE_RE = re.compile(
    r"(?:仁安|嘉応|承安|安元|治承|養和|寿永|元暦|文治|建久|承久)"
    r"[元一二三四五六七八九十百\d]+年"
    r"(?:[一二三四五六七八九十\d]+月)?(?:[一二三四五六七八九十\d]+日)?"
)
WESTERN_DATE_RE = re.compile(r"(?:11|12)\d{2}年(?:\d{1,2}月)?(?:\d{1,2}日)?")
KNOWN_PLACES = (
    "福原", "京都", "鎌倉", "熊野", "高野山", "南都", "奈良", "伊勢", "宇治",
    "一ノ谷", "一の谷", "屋島", "壇ノ浦", "比叡山", "六波羅", "大宰府",
)
WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё一-龯々ぁ-ゖァ-ヺー]{2,}")
SEMANTIC_DECISIONS = (
    "confirmed_repeat",
    "probable_repeat_review",
    "new_angle",
    "new_finding",
)
MAX_HISTORY_REVIEW_MATCHES = 3


def load_used_finds(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        records: list[dict[str, Any]] = []
        for row in reader:
            if not any((value or "").strip() for value in row.values()):
                continue
            records.append(
                {
                    "id": normalize_text(row.get("id", "")),
                    "type": normalize_text(row.get("type", "")),
                    "persons": _split_values(row.get("persons", "")),
                    "topics": _split_values(row.get("topics", "")),
                    "description": normalize_text(row.get("short_description", "")),
                    "source": normalize_text(row.get("source", "")),
                }
            )
    return records


def _split_values(value: str) -> list[str]:
    return unique_normalized(re.split(r"[;,、|]+", value or ""))


def _compact(value: str) -> str:
    return "".join(normalize_text(value).casefold().split())


def _grams(value: str, size: int = 3) -> set[str]:
    compact = _compact(value)
    if len(compact) <= size:
        return {compact} if compact else set()
    return {compact[index : index + size] for index in range(len(compact) - size + 1)}


def _lexical_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    sequence = SequenceMatcher(None, _compact(left), _compact(right)).ratio()
    left_words = set(WORD_RE.findall(normalize_text(left)))
    right_words = set(WORD_RE.findall(normalize_text(right)))
    word_jaccard = (
        len(left_words & right_words) / len(left_words | right_words)
        if left_words and right_words
        else 0.0
    )
    left_grams = _grams(left)
    right_grams = _grams(right)
    gram_jaccard = (
        len(left_grams & right_grams) / len(left_grams | right_grams)
        if left_grams and right_grams
        else 0.0
    )
    return max(sequence, word_jaccard, gram_jaccard)


def candidate_pair_check(
    left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any]:
    """Decide whether two candidates may be collapsed without semantic guesswork.

    ``collapse`` is deliberately limited to the same chunk or near-identical
    evidence from the same document/work.  Positional proximity and shared
    labels only create a ``review`` relation; they never delete a candidate.
    """
    left_text = normalize_text(str(left.get("what_happened", "")))
    right_text = normalize_text(str(right.get("what_happened", "")))
    exact_text = bool(
        left_text
        and right_text
        and left_text.casefold() == right_text.casefold()
    )
    lexical = _lexical_similarity(left_text, right_text)
    left_id = normalize_text(str(left.get("chunk_id", "")))
    right_id = normalize_text(str(right.get("chunk_id", "")))
    same_id = bool(left_id and left_id == right_id)
    if same_id and exact_text:
        return {
            "action": "collapse",
            "confidence": 1.0,
            "reason": "exact same chunk_id and normalized evidence",
        }

    shared_topics = sorted(set(left.get("topics", [])) & set(right.get("topics", [])))
    shared_people = sorted(set(left.get("person", [])) & set(right.get("person", [])))
    same_path = bool(
        left.get("relative_path")
        and left.get("relative_path") == right.get("relative_path")
    )
    same_source = bool(
        left.get("source_group")
        and left.get("source_group") == right.get("source_group")
    )
    chunk_distance: int | None = None
    if same_path and left.get("chunk_no") is not None and right.get("chunk_no") is not None:
        chunk_distance = abs(int(left["chunk_no"]) - int(right["chunk_no"]))

    same_scope = same_path or same_source
    if exact_text and same_scope:
        return {
            "action": "collapse",
            "confidence": round(lexical, 3),
            "reason": "exact normalized evidence in the same document or source group",
        }

    review_reasons: list[str] = []
    if same_id:
        review_reasons.append(
            "same positional chunk_id but non-identical evidence"
        )
    if same_path and chunk_distance is not None and chunk_distance <= 2 and shared_topics:
        review_reasons.append("nearby chunks in the same document with a shared topic")
    if same_source and shared_topics and shared_people:
        review_reasons.append("same source group with shared people and topics")
    if lexical >= 0.45 and (same_scope or shared_topics or shared_people):
        review_reasons.append(f"material similarity {lexical:.2f}")
    if review_reasons:
        return {
            "action": "review",
            "confidence": round(lexical, 3),
            "reason": "; ".join(review_reasons),
        }
    return {
        "action": "distinct",
        "confidence": round(lexical, 3),
        "reason": "no strong technical evidence that the candidates are the same finding",
    }


def attach_semantic_reviews(
    candidates: list[dict[str, Any]], *, limit: int = 3
) -> list[dict[str, Any]]:
    """Attach bounded comparison links without duplicating full source context.

    Every compared candidate already exists as a top-level row in the full
    result.  Keeping another copy of ``verified_context`` under every pair made
    large batches quadratic in size and encouraged agents to reread identical
    passages.  The link below carries the supported thesis and enough metadata
    to find the canonical top-level row instead.
    """
    for candidate in candidates:
        candidate_matches: list[dict[str, Any]] = []
        for other in candidates:
            if other is candidate:
                continue
            pair = candidate_pair_check(candidate, other)
            if pair["action"] != "review":
                continue
            candidate_matches.append(
                {
                    "matched_chunk_id": other.get("chunk_id"),
                    "confidence": pair["confidence"],
                    "reason": pair["reason"],
                    "candidate": {
                        "title": other.get("title"),
                        "person": list(other.get("person", [])),
                        "topics": list(other.get("topics", [])),
                        "date": other.get("date"),
                        "source": other.get("source"),
                        "source_type": other.get("index_source_type")
                        or other.get("source_type"),
                        "relative_path": other.get("relative_path"),
                        "chunk_id": other.get("chunk_id"),
                        "what_happened": other.get("what_happened"),
                        "context_ref": {
                            "chunk_id": other.get("chunk_id"),
                            "field": "verified_context",
                        },
                    },
                }
            )
        candidate_matches.sort(
            key=lambda item: (
                -float(item["confidence"]),
                str(item["matched_chunk_id"] or ""),
            )
        )
        candidate_matches = candidate_matches[:limit]
        duplicate = candidate.get("duplicate_check", {})
        history_matches = list(duplicate.get("review_matches", []))
        required = bool(
            duplicate.get("requires_editorial_review") or candidate_matches
        )
        candidate["semantic_review"] = {
            "required": required,
            "decision_owner": "codex" if required else "python_technical_rules",
            "allowed_decisions": list(SEMANTIC_DECISIONS),
            "history_matches": history_matches,
            "candidate_matches": candidate_matches,
            "instruction": (
                "Compare supported claims, actions, objects, outcomes, and source roles. "
                "Shared people, topics, dates, or sources are not a duplicate verdict."
            ),
        }
    return candidates


def _auto_excluded(candidate: dict[str, Any]) -> bool:
    decision = candidate.get("duplicate_check", {})
    return bool(
        decision.get("auto_exclude", decision.get("status") == "duplicate")
    )


def _claim_type(candidate: dict[str, Any]) -> str:
    explicit = normalize_text(str(candidate.get("type", ""))).casefold()
    if explicit in {"event", "interpretation"}:
        return explicit
    source_type = normalize_text(
        str(candidate.get("index_source_type") or candidate.get("source_type") or "")
    ).casefold()
    return "interpretation" if source_type == "scholarship" else "event"


def _history_match(
    candidate: dict[str, Any], record: dict[str, Any]
) -> dict[str, Any] | None:
    candidate_id = normalize_text(str(candidate.get("chunk_id", "")))
    record_id = normalize_text(str(record.get("id", "")))
    candidate_claim = normalize_text(str(candidate.get("what_happened", "")))
    prior_claim = normalize_text(str(record.get("description", "")))
    exact_id = bool(candidate_id and candidate_id == record_id)
    exact_claim = bool(
        candidate_claim
        and prior_claim
        and candidate_claim.casefold() == prior_claim.casefold()
    )
    verified_context = candidate.get("verified_context", {})
    context_chunks = (
        verified_context.get("chunks", [])
        if isinstance(verified_context, dict)
        else []
    )
    context_chunk_ids = {
        normalize_text(str(item.get("chunk_id", "")))
        for item in context_chunks
        if isinstance(item, dict) and item.get("chunk_id")
    }
    nearby_published_chunk = bool(record_id and record_id in context_chunk_ids)

    candidate_people = set(candidate.get("person", []))
    candidate_topics = set(candidate.get("topics", []))
    people_overlap = sorted(candidate_people & set(record.get("persons", [])))
    topics_overlap = sorted(candidate_topics & set(record.get("topics", [])))
    candidate_source = normalize_text(
        str(candidate.get("source_group") or candidate.get("source") or "")
    )
    prior_source = normalize_text(str(record.get("source", "")))
    same_source = bool(
        prior_source
        and candidate_source
        and source_group(prior_source) == source_group(candidate_source)
    )
    source_similarity = _lexical_similarity(candidate_source, prior_source)
    related_source_name = bool(source_similarity >= 0.45)
    candidate_date = normalize_text(str(candidate.get("date") or ""))
    same_date = bool(
        candidate_date
        and candidate_date.casefold() in prior_claim.casefold()
    )
    material = " ".join(
        [str(candidate.get("title", "")), candidate_claim]
    ).strip()
    lexical = max(
        _lexical_similarity(candidate_claim, prior_claim),
        _lexical_similarity(material, prior_claim),
    )
    candidate_type = _claim_type(candidate)
    prior_type = normalize_text(str(record.get("type", ""))).casefold() or "unknown"
    possible_new_angle = bool(
        candidate_type == "interpretation" and prior_type != "interpretation"
    )

    reasons: list[str] = []
    if exact_id:
        reasons.append("exact chunk_id")
    if exact_claim:
        reasons.append("exact normalized published claim")
    if nearby_published_chunk:
        reasons.append("published chunk_id appears in verified neighbouring context")
    if people_overlap:
        reasons.append("shared people: " + ", ".join(people_overlap))
    if topics_overlap:
        reasons.append("shared topics: " + ", ".join(topics_overlap))
    if same_source:
        reasons.append("same source group")
    elif related_source_name:
        reasons.append(f"related source name {source_similarity:.2f}")
    if same_date:
        reasons.append("same stated date")
    if lexical >= 0.28:
        reasons.append(f"claim similarity {lexical:.2f}")
    if possible_new_angle:
        reasons.append("scholarship may add an interpretation to a known event")

    anchor_count = sum(
        [bool(people_overlap), bool(topics_overlap), same_source or related_source_name, same_date]
    )
    plausible = bool(
        exact_id
        or exact_claim
        or nearby_published_chunk
        or lexical >= 0.28
        or anchor_count >= 2
        or topics_overlap
    )
    if not plausible:
        return None
    score = lexical
    score += 0.12 * bool(people_overlap)
    score += 0.08 * bool(topics_overlap)
    score += 0.10 * bool(same_source)
    score += 0.05 * bool(related_source_name and not same_source)
    score += 0.10 * bool(same_date)
    score += 0.25 * nearby_published_chunk
    if exact_claim:
        strength = "confirmed"
        score = 1.0
    elif exact_id:
        strength = "strong"
        score = max(score, 0.95)
    elif nearby_published_chunk:
        strength = "strong"
        score = max(score, 0.85)
    elif lexical >= 0.60 or (lexical >= 0.38 and anchor_count >= 2):
        strength = "strong"
    elif lexical >= 0.28 or anchor_count >= 2:
        strength = "moderate"
    else:
        strength = "weak"
    return {
        "matched_id": record_id or None,
        "strength": strength,
        "match_score": round(min(score, 1.0), 3),
        "reason": "; ".join(reasons) or "weak shared topic",
        "signals": {
            "lexical_similarity": round(lexical, 3),
            "shared_people": people_overlap,
            "shared_topics": topics_overlap,
            "same_source_group": same_source,
            "source_name_similarity": round(source_similarity, 3),
            "same_date": same_date,
            "exact_chunk_id": exact_id,
            "exact_claim": exact_claim,
            "published_chunk_in_verified_context": nearby_published_chunk,
            "positional_id_claim_changed": bool(exact_id and not exact_claim),
        },
        "candidate_claim_type": candidate_type,
        "prior_claim_type": prior_type,
        "possible_new_angle": possible_new_angle,
        "prior": {
            "id": record_id or None,
            "type": prior_type,
            "persons": list(record.get("persons", [])),
            "topics": list(record.get("topics", [])),
            "description": prior_claim,
            "source": prior_source,
        },
    }


def duplicate_check(candidate: dict[str, Any], used: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [
        match
        for record in used
        if (match := _history_match(candidate, record)) is not None
    ]
    matches.sort(
        key=lambda item: (
            item["strength"] != "confirmed",
            -item["match_score"],
            str(item["matched_id"] or ""),
        )
    )
    matches = matches[:MAX_HISTORY_REVIEW_MATCHES]
    confirmed = next(
        (item for item in matches if item["strength"] == "confirmed"), None
    )
    best = confirmed or (matches[0] if matches else None)
    status = "duplicate" if confirmed else "duplicate_risk" if matches else "clear"
    return {
        "status": status,
        "confidence": best["match_score"] if best else 0.0,
        "reason": (
            best["reason"]
            if best
            else "no plausible match in used_finds.csv"
            if used
            else "not found in used_finds.csv"
        ),
        "matched_id": best["matched_id"] if best else None,
        "python_disposition": (
            "confirmed_repeat"
            if confirmed
            else "needs_semantic_review"
            if matches
            else "no_plausible_history_match"
        ),
        "auto_exclude": bool(confirmed),
        "requires_editorial_review": bool(matches and not confirmed),
        "allowed_semantic_decisions": list(SEMANTIC_DECISIONS),
        "review_matches": matches,
    }


def source_subtype(source: str) -> str:
    compact = _compact(source)
    if any(_compact(name) in compact for name in ("玉葉", "Gyokuyō", "吉記", "Kikki", "山槐記", "兵範記", "中右記")):
        return "contemporary_diary"
    if any(_compact(name) in compact for name in ("吾妻鏡", "AzumaKagami")):
        return "later_chronicle"
    if any(_compact(name) in compact for name in ("平家物語", "源平盛衰記", "平治物語")):
        return "war_tale"
    return "other"


def source_group(source: str) -> str:
    """Collapse scans/editions of the same named work for diversity rules."""
    compact = _compact(source)
    groups = (
        ("玉葉", ("玉葉", "Gyokuyō", "Gyokuyo")),
        ("吉記", ("吉記", "Kikki")),
        ("山槐記", ("山槐記", "Sankaiki")),
        ("兵範記", ("兵範記", "Heihanki")),
        ("中右記", ("中右記",)),
        ("吾妻鏡", ("吾妻鏡", "AzumaKagami")),
        ("平家物語", ("平家物語",)),
        ("源平盛衰記", ("源平盛衰記",)),
        ("平治物語", ("平治物語",)),
    )
    for canonical, variants in groups:
        if any(_compact(variant) in compact for variant in variants):
            return canonical
    return normalize_text(source)


def _find_date(text: str) -> str | None:
    match = DATE_RE.search(text) or WESTERN_DATE_RE.search(text)
    return match.group(0) if match else None


def _find_place(text: str) -> str | None:
    return next((place for place in KNOWN_PLACES if place in text), None)


def _occurrences(text: str, term: str) -> list[int]:
    result: list[int] = []
    start = 0
    while term and (position := text.find(term, start)) >= 0:
        result.append(position)
        start = position + max(1, len(term))
    return result


def _linked_evidence(
    text: str,
    persons: list[str],
    topic_terms: list[str],
    people: dict[str, dict[str, Any]],
    limit: int = 480,
) -> tuple[str | None, list[str], int | None]:
    normalized = normalize_text(text)
    compact_chars: list[str] = []
    original_positions: list[int] = []
    for index, char in enumerate(normalized):
        if not char.isspace():
            compact_chars.append(char.casefold())
            original_positions.append(index)
    compact_text = "".join(compact_chars)
    person_terms: list[str] = []
    for person in persons:
        try:
            _canonical, variants = person_variants(people, person)
            person_terms.extend(variants)
        except ValueError:
            person_terms.append(person)
    person_terms = unique_normalized(person_terms)
    useful_topic_terms = unique_normalized(topic_terms)
    # Single-character family terms such as 子 are too ambiguous for an
    # unattended event decision. Longer alternatives remain available.
    if any(len(_compact(term)) >= 2 for term in useful_topic_terms):
        useful_topic_terms = [term for term in useful_topic_terms if len(_compact(term)) >= 2]

    pairs: list[tuple[int, int, int, str, str]] = []
    for person_term in person_terms:
        person_compact = _compact(person_term)
        if not person_compact:
            continue
        for topic_term in useful_topic_terms:
            topic_compact = _compact(topic_term)
            if not topic_compact or topic_compact in person_compact:
                continue
            # Chunk-level co-occurrence alone is not evidence of one episode.
            # Keep only tight local links; this also prevents adjacent dated
            # diary entries from being merged into one event.
            distance_limit = 60 if len(topic_compact) == 1 else 80
            for person_position in _occurrences(compact_text, person_compact):
                person_end = person_position + len(person_compact)
                for topic_position in _occurrences(compact_text, topic_compact):
                    topic_end = topic_position + len(topic_compact)
                    if not (person_end <= topic_position or topic_end <= person_position):
                        continue
                    gap = max(person_position, topic_position) - min(person_end, topic_end)
                    if gap <= distance_limit:
                        pairs.append(
                            (
                                gap,
                                -len(topic_compact),
                                min(person_position, topic_position),
                                person_term,
                                topic_term,
                            )
                        )
    if not pairs or not original_positions:
        return None, [], None
    gap, _negative_length, pair_start, person_term, topic_term = min(pairs)
    person_position = compact_text.find(_compact(person_term), pair_start)
    topic_position = compact_text.find(_compact(topic_term), pair_start)
    pair_end = max(
        person_position + len(_compact(person_term)),
        topic_position + len(_compact(topic_term)),
    )
    compact_start = max(0, min(person_position, topic_position) - 130)
    compact_end = min(len(original_positions), max(pair_end + 260, compact_start + limit))
    original_start = original_positions[compact_start]
    original_end = original_positions[compact_end - 1] + 1
    evidence = normalized[original_start:original_end].strip()
    if original_start:
        evidence = "…" + evidence
    if original_end < len(normalized):
        evidence += "…"
    # Tables of contents often contain both a name and a keyword, but do not
    # constitute evidence of a local episode.
    if (
        evidence.count("の事") >= 4
        or evidence.count("事") >= 12
        or ("の事" in evidence and len(evidence) < 180)
    ):
        return None, [], None
    return evidence, [person_term, topic_term], gap


def _evidence_readable(text: str) -> bool:
    """Stricter than index text_quality because final claims need clear OCR."""
    japanese = sum(
        "\u3040" <= char <= "\u30ff" or "\u3400" <= char <= "\u9fff"
        for char in text
    )
    ascii_letters = sum(char.isascii() and char.isalpha() for char in text)
    replacement = text.count("\ufffd") + text.count("〓")
    if replacement >= 5:
        return False
    if japanese >= 50 and ascii_letters > max(20, int(japanese * 0.12)):
        return False
    return True


def _search_args(topic: str, top: int) -> Namespace:
    return Namespace(
        query=None,
        topic=[topic],
        person=[],
        source_type=["historical", "literary"],
        exclude_source_type=["scholarship"],
        source=[],
        exclude_source=[],
        quality=["good"],
        top=top,
        offset=0,
        json=False,
        include_duplicates=False,
    )


def _collapse_neighbours(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: -item["retrieval_score"]):
        duplicate_neighbour = any(
            candidate_pair_check(prior, candidate)["action"] == "collapse"
            for prior in kept
        )
        if not duplicate_neighbour:
            kept.append(candidate)
    return kept


def _select_diverse(candidates: list[dict[str, Any]], count: int = 5) -> list[dict[str, Any]]:
    eligible = [item for item in candidates if not _auto_excluded(item)]
    selected: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    people_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()

    def choose(max_per_source: int) -> None:
        while len(selected) < count:
            best: dict[str, Any] | None = None
            best_score = float("-inf")
            military_count = sum(item["primary_topic"] in MILITARY_NICHES for item in selected)
            human_count = sum(item["primary_topic"] in HUMAN_NICHES for item in selected)
            for candidate in eligible:
                source_key = candidate["source_group"]
                if candidate in selected or source_counts[source_key] >= max_per_source:
                    continue
                military = candidate["primary_topic"] in MILITARY_NICHES
                if military and military_count >= 2:
                    continue
                new_people = sum(people_counts[person] == 0 for person in candidate["person"])
                primary_topic = candidate["primary_topic"]
                new_topics = int(topic_counts[primary_topic] == 0)
                score = candidate["retrieval_score"]
                score += min(new_people, 2) * 0.55 + min(new_topics, 2) * 0.45
                if primary_topic in HUMAN_NICHES and human_count < 2:
                    score += 1.0
                score -= source_counts[source_key] * 1.8
                score -= topic_counts[primary_topic] * 1.5
                if score > best_score:
                    best_score = score
                    best = candidate
            if best is None:
                return
            selected.append(best)
            source_counts[best["source_group"]] += 1
            people_counts.update(best["person"])
            topic_counts.update([best["primary_topic"]])

    choose(1)
    if len(selected) < count:
        choose(2)
    return selected


def build_daily_five(
    connection: sqlite3.Connection,
    topics: dict[str, list[str]],
    people: dict[str, dict[str, Any]],
    used_finds_path: Path,
    *,
    search_function: Callable[..., list[dict[str, Any]]],
    context_function: Callable[..., list[dict[str, Any]]],
    top_per_topic: int = 20,
    pool_size: int = 120,
    dry_run: bool = False,
) -> dict[str, Any]:
    used = load_used_finds(used_finds_path)
    niches = [name for name in NICHES if name in topics]
    by_chunk: dict[str, dict[str, Any]] = {}
    niche_counts: dict[str, int] = {}
    for niche in niches:
        rows = search_function(
            connection, _search_args(niche, top_per_topic), topics, people, events_only=True
        )
        niche_counts[niche] = len(rows)
        for row in rows:
            candidate = by_chunk.setdefault(
                row["chunk_id"],
                {
                    **row,
                    "matched_niches": [],
                    "retrieval_score": 0.0,
                },
            )
            candidate["matched_niches"].append(niche)
            candidate["retrieval_score"] += 1.0 / max(row["rank"], 1)

    ranked_pool = sorted(
        by_chunk.values(),
        key=lambda item: (-item["retrieval_score"], -item["score"], item["chunk_id"]),
    )[:pool_size]
    verified: list[dict[str, Any]] = []
    rejected = Counter()
    for raw in ranked_pool:
        context = context_function(connection, raw["chunk_id"], 1, 1)
        target = next((row for row in context if row["target"]), None)
        if target is None or target["text_quality"] != "good":
            rejected["quality_or_context"] += 1
            continue
        persons = list(target["people"])
        matched_niches = [name for name in raw["matched_niches"] if name in target["topics"]]
        if not persons or not matched_niches:
            rejected["person_topic_not_in_target_chunk"] += 1
            continue
        primary_topic = matched_niches[0]
        evidence, evidence_terms, evidence_gap = _linked_evidence(
            target["text"], persons, topics[primary_topic], people
        )
        if evidence is None or not evidence_terms:
            rejected["person_topic_not_locally_linked"] += 1
            continue
        if not _evidence_readable(evidence):
            rejected["unreliable_local_ocr"] += 1
            continue
        linked_alias = evidence_terms[0]
        linked_people: list[str] = []
        for person in persons:
            try:
                _canonical, variants = person_variants(people, person)
            except ValueError:
                variants = [person]
            if _compact(linked_alias) in {_compact(value) for value in variants}:
                linked_people.append(person)
        if not linked_people:
            rejected["linked_person_not_resolved"] += 1
            continue
        event = {
            "title": f"{', '.join(linked_people)} — {TOPIC_LABELS.get(primary_topic, primary_topic)}",
            "person": linked_people,
            "date": _find_date(evidence),
            "place": _find_place(evidence),
            "what_happened": evidence,
            "why_interesting": WHY_INTERESTING.get(
                primary_topic, "Локальный эпизод, связанный с конкретным представителем Тайра."
            ),
            "source": target["source"],
            "source_group": source_group(target["source"]),
            "source_type": source_subtype(target["source"]),
            "index_source_type": target["source_type"],
            "filename": target["filename"],
            "path": target["path"],
            "relative_path": raw["relative_path"],
            "page_start": target["page_start"],
            "page_end": target["page_end"],
            "chunk_no": target["chunk_no"],
            "chunk_id": target["chunk_id"],
            "topics": matched_niches,
            "primary_topic": primary_topic,
            "text_quality": target["text_quality"],
            "verified_context": {
                "status": "ok",
                "chunks_loaded": len(context),
                "before": sum(row["chunk_no"] < target["chunk_no"] for row in context),
                "after": sum(row["chunk_no"] > target["chunk_no"] for row in context),
                "evidence_terms": evidence_terms,
                "max_term_gap_chars": evidence_gap,
                "note": "person and topic are locally linked in the target chunk; context ±1 loaded",
            },
            "retrieval_score": round(raw["retrieval_score"], 6),
        }
        event["duplicate_check"] = duplicate_check(event, used)
        if event["duplicate_check"]["status"] == "duplicate":
            rejected["used_duplicate"] += 1
        verified.append(event)

    verified = _collapse_neighbours(verified)
    attach_semantic_reviews(verified)
    verified.sort(
        key=lambda item: (
            item["duplicate_check"]["status"] != "clear",
            -item["retrieval_score"],
            item["source"],
        )
    )
    final = [] if dry_run else _select_diverse(verified, 5)
    final_ids = {item["chunk_id"] for item in final}
    alternates = [item for item in verified if item["chunk_id"] not in final_ids][
        : (20 if dry_run else 15)
    ]
    review_stats = {
        "candidates_requiring_editorial_review": sum(
            bool(item["semantic_review"]["required"]) for item in verified
        ),
        "history_match_candidates": sum(
            bool(item["semantic_review"]["history_matches"]) for item in verified
        ),
        "candidate_pair_relations": sum(
            len(item["semantic_review"]["candidate_matches"]) for item in verified
        )
        // 2,
    }
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "historical-events",
        "dry_run": dry_run,
        "filters": {
            "source_type": ["historical", "literary"],
            "exclude_source_type": ["scholarship"],
            "quality": ["good"],
            "requires_taira_person": True,
            "niches": niches,
        },
        "stats": {
            "niche_hits": niche_counts,
            "unique_pool": len(by_chunk),
            "pool_checked": len(ranked_pool),
            "verified_candidates": len(verified),
            "used_finds_records": len(used),
            "rejected": dict(rejected),
            "final_count": len(final),
            "alternate_count": len(alternates),
            "semantic_review": review_stats,
        },
        "final": final,
        "alternates": alternates,
    }


def save_result(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Не найден {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: ожидается JSON-объект")
    return payload


def _fallback_card(event: dict[str, Any]) -> dict[str, Any]:
    people = event.get("person", [])
    names = ", ".join(PERSON_RU.get(str(item), str(item)) for item in people)
    topic = event.get("primary_topic") or next(iter(event.get("topics", [])), "эпизод")
    label = TOPIC_LABELS.get(topic, topic)
    evidence_terms = event.get("verified_context", {}).get("evidence_terms", [])
    term = evidence_terms[-1] if evidence_terms else label
    quote = normalize_text(str(event.get("what_happened", "")))[:500]
    return {
        "title_ru": f"{names or 'Персонаж Тайра'} упомянут в эпизоде о теме «{label}»",
        "summary_ru": (
            f"В локальном контексте источника «{event.get('source', '—')}» "
            f"{names or 'персонаж Тайра'} назван рядом с выражением «{term}». "
            "Более конкретное действие нельзя сформулировать без риска домысла; "
            "проверочный фрагмент сохранён ниже."
        ),
        "why_interesting_ru": (
            "Это потенциально полезная находка-указатель, но её содержательная "
            "интерпретация требует ручного чтения источника."
        ),
        "source_quote": quote,
        "date": event.get("date"),
        "place": event.get("place"),
        "card_status": "needs_manual_review",
    }


def apply_presentation_cards(
    result: dict[str, Any],
    connection: sqlite3.Connection,
    *,
    context_function: Callable[..., list[dict[str, Any]]],
    cards_path: Path,
    source_notes_path: Path,
) -> dict[str, Any]:
    """Enrich a completed retrieval result without changing retrieval/ranking."""
    cards = _load_object(cards_path, "event_cards.json")
    source_notes = _load_object(source_notes_path, "source_notes.json")
    final = list(result.get("final", []))
    alternates = list(result.get("alternates", []))
    retrieval_final_ids = list(result.get("retrieval_final_chunk_ids") or [])
    if not retrieval_final_ids:
        retrieval_final_ids = [str(item.get("chunk_id", "")) for item in final]
    previous_presentation = result.get("presentation", {})
    previous_changes = (
        previous_presentation.get("replacements", [])
        if isinstance(previous_presentation, dict)
        else []
    )
    changes: list[dict[str, str]] = [
        dict(item) for item in previous_changes if isinstance(item, dict)
    ]

    for index, event in enumerate(list(final)):
        card = cards.get(str(event.get("chunk_id", "")), {})
        if not isinstance(card, dict) or card.get("usable", True):
            continue
        replacement_id = str(card.get("replacement_chunk_id", ""))
        replacement_index = next(
            (
                item_index
                for item_index, item in enumerate(alternates)
                if item.get("chunk_id") == replacement_id
            ),
            None,
        )
        if replacement_index is None:
            continue
        replacement = alternates.pop(replacement_index)
        rejected = dict(event)
        rejected["presentation_rejection"] = str(card.get("reason", "недостаточный контекст"))
        alternates.append(rejected)
        final[index] = replacement
        change = {
            "removed_chunk_id": str(event.get("chunk_id", "")),
            "replacement_chunk_id": replacement_id,
            "reason": str(card.get("reason", "недостаточный контекст")),
        }
        if change not in changes:
            changes.append(change)

    for event in final:
        chunk_id = str(event.get("chunk_id", ""))
        card = cards.get(chunk_id)
        if not isinstance(card, dict) or not card.get("title_ru"):
            card = _fallback_card(event)
        source_key = str(event.get("source_group", event.get("source", "")))
        source_info = source_notes.get(source_key, {})
        if not isinstance(source_info, dict):
            source_info = {}
        event["title_ru"] = str(card["title_ru"])
        event["summary_ru"] = str(card["summary_ru"])
        event["why_interesting_ru"] = str(card["why_interesting_ru"])
        event["source_quote"] = normalize_text(str(card["source_quote"]))[:500]
        event["date"] = card.get("date", event.get("date"))
        event["place"] = card.get("place", event.get("place"))
        event["people"] = list(event.get("person", []))
        event["source_title_ru"] = source_info.get("title_ru")
        event["source_author_ru"] = source_info.get("author_ru")
        event["source_closeness_ru"] = source_info.get(
            "closeness_ru",
            {
                "contemporary_diary": "современный событиям дневник",
                "later_chronicle": "более поздняя хроника",
                "war_tale": "воинская повесть",
            }.get(event.get("source_type"), "другой тип источника"),
        )
        event["source_note"] = source_info.get(
            "note_ru", "Тип и близость источника требуют ручной проверки."
        )
        event["card_status"] = str(card.get("card_status", "verified_context_summary"))
        context = context_function(connection, chunk_id, 1, 1)
        event.setdefault("verified_context", {})["chunks"] = [
            {
                "target": row["target"],
                "chunk_id": row["chunk_id"],
                "chunk_no": row["chunk_no"],
                "page_start": row["page_start"],
                "page_end": row["page_end"],
                "text": row["text"],
            }
            for row in context
        ]

    result["retrieval_final_chunk_ids"] = retrieval_final_ids
    result["final"] = final
    result["alternates"] = alternates[:15]
    result["presentation"] = {
        "cards_config": str(cards_path),
        "source_notes_config": str(source_notes_path),
        "replacements": changes,
        "note": "Retrieval/ranking unchanged; cards summarize verified local context.",
    }
    result.setdefault("stats", {})["final_count"] = len(final)
    result["stats"]["alternate_count"] = len(result["alternates"])
    result["stats"]["presentation_replacements"] = len(changes)
    return result


def _page_label(event: dict[str, Any]) -> str:
    start, end = event.get("page_start"), event.get("page_end")
    if start is None:
        return "—"
    return str(start) if end is None or end == start else f"{start}–{end}"


def print_daily_result(result: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    stats = result["stats"]
    if result["dry_run"]:
        print("DAILY-FIVE DRY RUN")
        print("Ниши: " + ", ".join(result["filters"]["niches"]))
        print("Найдено по нишам: " + json.dumps(stats["niche_hits"], ensure_ascii=False))
        print(
            f"Уникальный пул: {stats['unique_pool']}; проверено: {stats['pool_checked']}; "
            f"после context/дублей: {stats['verified_candidates']}"
        )
        print("Отброшено: " + json.dumps(stats["rejected"], ensure_ascii=False))
        print("\nЛучшие оставшиеся кандидаты:")
        rows = result["alternates"]
    else:
        rows = result["final"]
        if not rows:
            print("По текущим фильтрам подходящих новых находок не найдено.")
            return
        if len(rows) < 5:
            print(
                f"Найдено подходящих новых находок: {len(rows)}; "
                "результат не дополнен до пяти домыслами."
            )
        for number, event in enumerate(rows, start=1):
            print(f"\n### {number}. {event.get('title_ru', event['title'])}")
            print("\nЧто случилось")
            print(event.get("summary_ru", event["what_happened"]))
            print("\nПочему это интересно")
            print(event.get("why_interesting_ru", event["why_interesting"]))
            print("\nЧто именно говорит источник")
            print(f"«{event.get('source_quote', event['what_happened'])}»")
            print("\nИсточник")
            source_line = event.get("source_title_ru") or event["source"]
            if event.get("date"):
                source_line += f", {event['date']}"
            print(source_line)
            print(event.get("source_note", ""))
            print("\nНасколько близок источник")
            print(event.get("source_closeness_ru", event["source_type"]))
            duplicate = event["duplicate_check"]
            print("\nПроверка дубля")
            if duplicate["status"] == "clear":
                print("В used_finds.csv совпадений не найдено.")
            else:
                print(f"{duplicate['status']}: {duplicate['reason']}")
            print("\nСлужебные данные")
            print(
                f"Файл: {event['filename']}; стр.: {_page_label(event)}; "
                f"chunk: {event['chunk_id']}"
            )
            print(f"Путь: {event['path']}")
            print("-----")
        return
    for number, event in enumerate(rows, start=1):
        print(f"\n{number}. {event['title']}")
        print("Что произошло (дословный локальный фрагмент):")
        print(event["what_happened"])
        print(f"Почему интересно: {event['why_interesting']}")
        print(f"Источник: {event['source']}")
        print(f"Тип: {event['source_type']}")
        print(f"Файл: {event['filename']}")
        print(f"Путь: {event['path']}")
        print(f"Страница: {_page_label(event)}; chunk_id: {event['chunk_id']}")
        print(f"Проверка контекста: {event['verified_context']['status'].upper()}")
        duplicate = event["duplicate_check"]
        print(f"Проверка дублей: {duplicate['status']} — {duplicate['reason']}")
        print("-----")


USED_FIELDS = [
    "id", "type", "persons", "topics", "short_description", "source", "date_used"
]
USED_TYPES = {"event", "interpretation"}


def mark_used_from_json(json_path: Path, used_path: Path) -> tuple[int, int]:
    payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
    events = payload.get("final") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        raise ValueError(f"{json_path}: ожидается объект daily-five с массивом final")
    return append_used(events, used_path)


def _load_publication_manifest(
    manifest_path: Path,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate a publication manifest and return its cards and journal rows."""
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{manifest_path}: ожидается JSON-объект")
    publication_id = normalize_text(str(payload.get("publication_id", "")))
    if not publication_id:
        raise ValueError(f"{manifest_path}: отсутствует publication_id")
    cards = payload.get("cards")
    if not isinstance(cards, list) or not cards:
        raise ValueError(f"{manifest_path}: ожидается непустой массив cards")

    validated_cards: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            raise ValueError(f"{manifest_path}: cards[{index}] должен быть объектом")
        card_markdown = card.get("card_markdown")
        if not isinstance(card_markdown, str) or not card_markdown.strip():
            raise ValueError(
                f"{manifest_path}: cards[{index}] должен содержать card_markdown"
            )
        finding_id = normalize_text(str(card.get("id") or card.get("chunk_id") or ""))
        finding_type = normalize_text(str(card.get("type", ""))).casefold()
        description = normalize_text(
            str(
                card.get("short_description")
                or card.get("what_happened")
                or card.get("title")
                or ""
            )
        )
        source = normalize_text(str(card.get("source", "")))
        if not finding_id:
            raise ValueError(f"{manifest_path}: cards[{index}] не содержит id")
        if finding_type not in USED_TYPES:
            raise ValueError(
                f"{manifest_path}: cards[{index}].type должен быть event "
                "или interpretation"
            )
        if not description:
            raise ValueError(
                f"{manifest_path}: cards[{index}] не содержит short_description"
            )
        if not source:
            raise ValueError(f"{manifest_path}: cards[{index}] не содержит source")
        events.append(
            {
                "chunk_id": finding_id,
                "type": finding_type,
                "person": card.get("persons") or card.get("person", []),
                "topics": card.get("topics", []),
                "what_happened": description,
                "source": source,
            }
        )
        validated_cards.append(card)

    return publication_id, validated_cards, events


def publication_status_from_json(
    manifest_path: Path, used_path: Path
) -> dict[str, Any]:
    """Report durable preparation/registration state without claiming delivery."""
    publication_id, cards, events = _load_publication_manifest(manifest_path)
    registered_ids = {row["id"] for row in _read_used_rows(used_path)}
    card_ids = [event["chunk_id"] for event in events]
    missing_ids = [
        finding_id for finding_id in card_ids if finding_id not in registered_ids
    ]
    return {
        "publication_id": publication_id,
        "card_count": len(cards),
        "prepared": True,
        "registered": not missing_ids,
        "missing_registration_ids": missing_ids,
        "delivery": "unconfirmed",
    }


def render_registered_publication_from_json(
    manifest_path: Path, used_path: Path
) -> tuple[str, str]:
    """Return the exact saved card Markdown only after journal registration."""
    publication_id, cards, events = _load_publication_manifest(manifest_path)
    registered_ids = {row["id"] for row in _read_used_rows(used_path)}
    missing_ids = [
        event["chunk_id"]
        for event in events
        if event["chunk_id"] not in registered_ids
    ]
    if missing_ids:
        raise ValueError(
            f"{manifest_path}: выпуск не полностью зарегистрирован; "
            f"отсутствуют ID: {', '.join(missing_ids)}"
        )
    return publication_id, "\n\n".join(str(card["card_markdown"]) for card in cards)


def record_publication_from_json(
    manifest_path: Path, used_path: Path
) -> tuple[str, int, int]:
    """Record the exact finalized cards stored in a durable local manifest."""
    publication_id, _cards, events = _load_publication_manifest(manifest_path)

    added, skipped = append_used(events, used_path)
    return publication_id, added, skipped


def mark_used_chunk(
    connection: sqlite3.Connection,
    chunk_id: str,
    used_path: Path,
    *,
    context_function: Callable[..., list[dict[str, Any]]],
) -> tuple[int, int]:
    rows = context_function(connection, chunk_id, 0, 0)
    if not rows:
        raise ValueError(f"Chunk не найден: {chunk_id}")
    row = rows[0]
    event = {
        "chunk_id": row["chunk_id"],
        "person": row["people"],
        "topics": row["topics"],
        "what_happened": normalize_text(row["text"])[:500],
        "source": row["source"],
    }
    return append_used([event], used_path)


def _read_used_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != USED_FIELDS:
            raise ValueError(
                f"{path}: ожидаются столбцы {', '.join(USED_FIELDS)}"
            )
        rows: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"{path}:{line_number}: лишние столбцы CSV")
            values = {field: row.get(field, "") or "" for field in USED_FIELDS}
            if not any(value.strip() for value in values.values()):
                continue
            finding_id = normalize_text(values["id"])
            if not finding_id:
                raise ValueError(f"{path}:{line_number}: пустой id")
            if finding_id in seen_ids:
                raise ValueError(f"{path}:{line_number}: повторяющийся id {finding_id}")
            seen_ids.add(finding_id)
            rows.append(values)
    return rows


def _join_used_values(value: Any) -> str:
    if isinstance(value, str):
        return normalize_text(value)
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return "; ".join(
            item for item in (normalize_text(str(item)) for item in value) if item
        )
    return normalize_text(str(value))


def _atomic_write_used_rows(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=USED_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


@contextmanager
def _publication_lock(used_path: Path, *, timeout: float = 15.0):
    """Serialize the complete CSV read/check/write cycle across processes."""
    used_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = used_path.with_name(f".{used_path.name}.lock")
    lock_stream = lock_path.open("a+b")
    if lock_stream.seek(0, os.SEEK_END) == 0:
        lock_stream.write(b"\0")
        lock_stream.flush()
    lock_stream.seek(0)
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while not acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Не удалось получить блокировку журнала за {timeout:g} с: "
                        f"{lock_path}"
                    ) from exc
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            lock_stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        lock_stream.close()


def append_used(events: list[dict[str, Any]], used_path: Path) -> tuple[int, int]:
    with _publication_lock(used_path):
        existing = _read_used_rows(used_path)
        existing_ids = {normalize_text(record["id"]) for record in existing}
        rows: list[dict[str, str]] = []
        skipped = 0
        for event in events:
            chunk_id = normalize_text(str(event.get("chunk_id", "")))
            if not chunk_id or chunk_id in existing_ids:
                skipped += 1
                continue
            finding_type = normalize_text(str(event.get("type", "event"))).casefold()
            if finding_type not in USED_TYPES:
                raise ValueError(
                    f"{chunk_id}: type должен быть event или interpretation"
                )
            rows.append(
                {
                    "id": chunk_id,
                    "type": finding_type,
                    "persons": _join_used_values(event.get("person", [])),
                    "topics": _join_used_values(event.get("topics", [])),
                    "short_description": normalize_text(
                        str(event.get("what_happened", event.get("title", "")))
                    )[:500],
                    "source": normalize_text(str(event.get("source", ""))),
                    "date_used": date.today().isoformat(),
                }
            )
            existing_ids.add(chunk_id)
        if rows:
            _atomic_write_used_rows([*existing, *rows], used_path)
        return len(rows), skipped

