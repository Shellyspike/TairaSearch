"""Finding deduplication and publication-journal operations."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from text_utils import normalize_text, unique_normalized


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


def _evidence_readable(text: str) -> bool:
    """Stricter than index text_quality because final claims need clear OCR."""
    unexpected_controls = sum(
        unicodedata.category(char) == "Cc" and ord(char) not in (9, 10, 13)
        for char in text
    )
    unassigned = sum(unicodedata.category(char) == "Cn" for char in text)
    if unexpected_controls or unassigned >= max(5, len(text) // 100):
        return False
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


def save_result(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


USED_FIELDS = [
    "id", "type", "persons", "topics", "short_description", "source", "date_used"
]
USED_TYPES = {"event", "interpretation"}
EXPLORATION_CHECKPOINT_VERSION = 1
EXPLORATION_REGISTRATION_VERSION = 1


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def research_profile_fingerprint(profile: dict[str, Any]) -> str:
    """Identify the exact profile whose exploration progress is being resumed."""
    return hashlib.sha256(_canonical_json(profile)).hexdigest()


def validate_exploration_checkpoint(value: Any) -> dict[str, Any]:
    """Validate and normalize a checkpoint embedded in a research/publication JSON."""
    if not isinstance(value, dict) or value.get("version") != EXPLORATION_CHECKPOINT_VERSION:
        raise ValueError("exploration_checkpoint: неизвестная или отсутствующая версия")
    generation = value.get("generation")
    cycle = value.get("cycle")
    if type(generation) is not int or generation < 1:
        raise ValueError("exploration_checkpoint.generation должен быть положительным целым")
    if type(cycle) is not int or cycle < 1:
        raise ValueError("exploration_checkpoint.cycle должен быть положительным целым")
    profile_fingerprint = value.get("profile_fingerprint")
    if not isinstance(profile_fingerprint, str) or len(profile_fingerprint) != 64:
        raise ValueError("exploration_checkpoint.profile_fingerprint повреждён")
    parent = value.get("parent_checkpoint_id")
    if parent is not None and (not isinstance(parent, str) or len(parent) != 64):
        raise ValueError("exploration_checkpoint.parent_checkpoint_id повреждён")
    next_lane = value.get("next_lane", 0)
    if type(next_lane) is not int or next_lane not in (0, 1):
        raise ValueError("exploration_checkpoint.next_lane должен быть 0 или 1")
    seen = value.get("seen")
    if not isinstance(seen, list):
        raise ValueError("exploration_checkpoint.seen должен быть массивом")
    normalized_seen: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(seen, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"exploration_checkpoint.seen[{index}] должен быть объектом")
        chunk_id = item.get("chunk_id")
        text_hash = item.get("text_hash")
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError(f"exploration_checkpoint.seen[{index}].chunk_id повреждён")
        if not isinstance(text_hash, str) or not text_hash:
            raise ValueError(f"exploration_checkpoint.seen[{index}].text_hash повреждён")
        if chunk_id in seen_ids:
            raise ValueError(f"exploration_checkpoint содержит повторный chunk_id {chunk_id}")
        seen_ids.add(chunk_id)
        normalized_seen.append({"chunk_id": chunk_id, "text_hash": text_hash})
    normalized_seen.sort(key=lambda item: item["chunk_id"])
    rejected = value.get("rejected", [])
    if not isinstance(rejected, list):
        raise ValueError("exploration_checkpoint.rejected должен быть массивом")
    normalized_rejected: list[dict[str, str]] = []
    rejected_ids: set[str] = set()
    for index, item in enumerate(rejected, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"exploration_checkpoint.rejected[{index}] должен быть объектом"
            )
        chunk_id = item.get("chunk_id")
        text_hash = item.get("text_hash")
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError(
                f"exploration_checkpoint.rejected[{index}].chunk_id повреждён"
            )
        if not isinstance(text_hash, str) or not text_hash:
            raise ValueError(
                f"exploration_checkpoint.rejected[{index}].text_hash повреждён"
            )
        if chunk_id in rejected_ids:
            raise ValueError(
                f"exploration_checkpoint содержит повторно отклонённый chunk_id {chunk_id}"
            )
        if chunk_id in seen_ids:
            raise ValueError(
                f"exploration_checkpoint не может одновременно показать и отклонить {chunk_id}"
            )
        rejected_ids.add(chunk_id)
        normalized_rejected.append({"chunk_id": chunk_id, "text_hash": text_hash})
    normalized_rejected.sort(key=lambda item: item["chunk_id"])
    core = {
        "version": EXPLORATION_CHECKPOINT_VERSION,
        "generation": generation,
        "cycle": cycle,
        "profile_fingerprint": profile_fingerprint,
        "parent_checkpoint_id": parent,
        "next_lane": next_lane,
        "seen": normalized_seen,
        "rejected": normalized_rejected,
    }
    expected_id = hashlib.sha256(_canonical_json(core)).hexdigest()
    if value.get("checkpoint_id") != expected_id:
        raise ValueError("exploration_checkpoint.checkpoint_id не соответствует содержимому")
    return {**core, "checkpoint_id": expected_id}


def make_exploration_checkpoint(
    *, generation: int, cycle: int, profile: dict[str, Any],
    parent_checkpoint_id: str | None, seen: dict[str, str], next_lane: int = 0,
    discovery_paths: list[str] | None = None,
    rejected: dict[str, str] | None = None,
) -> dict[str, Any]:
    core = {
        "version": EXPLORATION_CHECKPOINT_VERSION,
        "generation": generation,
        "cycle": cycle,
        "profile_fingerprint": research_profile_fingerprint({
            "profile": profile,
            "discovery_paths": discovery_paths or [],
        }),
        "parent_checkpoint_id": parent_checkpoint_id,
        "next_lane": next_lane,
        "seen": [
            {"chunk_id": chunk_id, "text_hash": seen[chunk_id]}
            for chunk_id in sorted(seen)
        ],
        "rejected": [
            {"chunk_id": chunk_id, "text_hash": (rejected or {})[chunk_id]}
            for chunk_id in sorted(rejected or {})
        ],
    }
    return {**core, "checkpoint_id": hashlib.sha256(_canonical_json(core)).hexdigest()}


def _manifest_fingerprint(payload: dict[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("exploration_checkpoint_registration", None)
    return hashlib.sha256(_canonical_json(unsigned)).hexdigest()


def _validate_checkpoint_registration(payload: dict[str, Any]) -> None:
    registration = payload.get("exploration_checkpoint_registration")
    checkpoint = validate_exploration_checkpoint(payload.get("exploration_checkpoint"))
    if not isinstance(registration, dict) or registration.get("version") != EXPLORATION_REGISTRATION_VERSION:
        raise ValueError("exploration_checkpoint не подтверждён record-publication")
    if registration.get("publication_id") != payload.get("publication_id"):
        raise ValueError("регистрация exploration_checkpoint относится к другому выпуску")
    if registration.get("checkpoint_id") != checkpoint["checkpoint_id"]:
        raise ValueError("регистрация exploration_checkpoint относится к другой закладке")
    if registration.get("manifest_fingerprint") != _manifest_fingerprint(payload):
        raise ValueError("манифест изменён после регистрации exploration_checkpoint")


def _atomic_write_json(payload: dict[str, Any], path: Path) -> None:
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


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
    if "exploration_checkpoint" in payload:
        validate_exploration_checkpoint(payload["exploration_checkpoint"])
    if "exploration_checkpoint_registration" in payload:
        _validate_checkpoint_registration(payload)
    cards = payload.get("cards")
    if not isinstance(cards, list) or not cards:
        raise ValueError(f"{manifest_path}: ожидается непустой массив cards")

    # New mode-aware editions require a separate evidence-backed scope decision.
    # Legacy manifests omit search_mode and retain exact recovery semantics.
    mode = payload.get('search_mode')
    if mode is not None and (not isinstance(mode, str) or mode not in {'open', 'focused_people'}):
        raise ValueError('Неизвестный search_mode в манифесте')
    selected_people = payload.get('focus_people', [])
    if mode == 'focused_people' and (not isinstance(selected_people, list) or not selected_people
            or not all(isinstance(person, str) and person.strip() for person in selected_people)):
        raise ValueError('focused_people требует имена focus_people в манифесте')

    validated_cards: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            raise ValueError(f"{manifest_path}: cards[{index}] должен быть объектом")
        if mode is not None:
            scope = card.get('scope_review', {})
            if not isinstance(scope, dict) or scope.get('status') != 'accepted' or not isinstance(scope.get('reason'), str) or not scope['reason'].strip():
                raise ValueError('scope_review: требуется accepted и причина; pending/uncertain не публикуются')
            evidence = scope.get('evidence')
            if not isinstance(evidence, list) or not evidence or not all(
                isinstance(item, dict) and isinstance(item.get('chunk_id'), str) and item['chunk_id'].strip()
                and isinstance(item.get('quote'), str) and item['quote'].strip() for item in evidence
            ):
                raise ValueError('scope_review: требуются точные evidence chunk_id/quote')
            if mode == 'focused_people' and scope.get('focus_person') not in selected_people:
                raise ValueError('scope_review: подтвердите связь с выбранным focus_person')
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
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    checkpoint_registered = (
        "exploration_checkpoint" not in payload
        or "exploration_checkpoint_registration" in payload
    )
    missing_ids, conflicting_ids = _publication_registration_issues(
        events, _read_used_rows(used_path)
    )
    return {
        "publication_id": publication_id,
        "card_count": len(cards),
        "prepared": True,
        "registered": checkpoint_registered and not missing_ids and not conflicting_ids,
        "exploration_checkpoint_registered": checkpoint_registered,
        "missing_registration_ids": missing_ids,
        "conflicting_registration_ids": conflicting_ids,
        "delivery": "unconfirmed",
    }


def render_registered_publication_from_json(
    manifest_path: Path, used_path: Path
) -> tuple[str, str]:
    """Return the exact saved card Markdown only after journal registration."""
    publication_id, cards, events = _load_publication_manifest(manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if (
        "exploration_checkpoint" in payload
        and "exploration_checkpoint_registration" not in payload
    ):
        raise ValueError(
            f"{manifest_path}: exploration_checkpoint не подтверждён "
            "успешным record-publication"
        )
    missing_ids, conflicting_ids = _publication_registration_issues(
        events, _read_used_rows(used_path)
    )
    if missing_ids or conflicting_ids:
        details = []
        if missing_ids:
            details.append(f"отсутствуют ID: {', '.join(missing_ids)}")
        if conflicting_ids:
            details.append(
                "ID зарегистрированы с другим содержанием: "
                + ", ".join(conflicting_ids)
            )
        raise ValueError(
            f"{manifest_path}: выпуск не полностью зарегистрирован; "
            + "; ".join(details)
        )
    return publication_id, "\n\n".join(str(card["card_markdown"]) for card in cards)


def record_publication_from_json(
    manifest_path: Path,
    used_path: Path,
    pending_queue_path: Path | None = None,
) -> tuple[str, int, int]:
    """Record the exact finalized cards stored in a durable local manifest."""
    publication_id, _cards, events = _load_publication_manifest(manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if pending_queue_path is not None:
        _validate_pending_publication_order(pending_queue_path, used_path, events)
    if (
        "exploration_checkpoint" in payload
        and "exploration_checkpoint_registration" not in payload
    ):
        checkpoint = validate_exploration_checkpoint(payload["exploration_checkpoint"])
        latest, _latest_path = load_latest_registered_exploration_checkpoint(
            manifest_path.parent, used_path
        )
        if latest is None:
            valid_parent = (
                checkpoint["generation"] == 1
                and checkpoint["parent_checkpoint_id"] is None
            )
        else:
            valid_parent = checkpoint["checkpoint_id"] == latest["checkpoint_id"] or (
                checkpoint["generation"] == latest["generation"] + 1
                and checkpoint["parent_checkpoint_id"] == latest["checkpoint_id"]
            )
        if not valid_parent:
            raise ValueError(
                "exploration_checkpoint не продолжает последнюю "
                "зарегистрированную закладку"
            )

    added, skipped = append_used(events, used_path)
    if "exploration_checkpoint" in payload:
        checkpoint = validate_exploration_checkpoint(payload["exploration_checkpoint"])
        registration = {
            "version": EXPLORATION_REGISTRATION_VERSION,
            "publication_id": publication_id,
            "checkpoint_id": checkpoint["checkpoint_id"],
        }
        unsigned = dict(payload)
        unsigned.pop("exploration_checkpoint_registration", None)
        registration["manifest_fingerprint"] = hashlib.sha256(
            _canonical_json(unsigned)
        ).hexdigest()
        expected = {**unsigned, "exploration_checkpoint_registration": registration}
        if payload != expected:
            _atomic_write_json(expected, manifest_path)
    if pending_queue_path is not None:
        prune_pending_editorial_queue(pending_queue_path, used_path)
    return publication_id, added, skipped


def load_latest_registered_exploration_checkpoint(
    manifests_path: Path, used_path: Path
) -> tuple[dict[str, Any] | None, Path | None]:
    """Return the newest unambiguous checkpoint sealed by record-publication.

    File dates and names are deliberately ignored. Generation is part of a
    content-addressed checkpoint, and every contributing manifest must still
    match both its registration seal and the existing publication journal.
    """
    manifests_path = manifests_path.expanduser().resolve()
    if not manifests_path.exists():
        return None, None
    if not manifests_path.is_dir():
        raise ValueError(
            f"--resume-exploration-from ожидает каталог манифестов: {manifests_path}"
        )
    journal_rows = _read_used_rows(used_path)
    checkpoints: list[tuple[dict[str, Any], Path]] = []
    for path in sorted(manifests_path.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: повреждён JSON publication manifest: {exc}") from exc
        if not isinstance(payload, dict) or "exploration_checkpoint" not in payload:
            continue
        checkpoint = validate_exploration_checkpoint(payload["exploration_checkpoint"])
        if "exploration_checkpoint_registration" not in payload:
            # A prepared or failed edition must not advance persistent progress.
            continue
        _validate_checkpoint_registration(payload)
        _publication_id, _cards, events = _load_publication_manifest(path)
        missing_ids, conflicting_ids = _publication_registration_issues(
            events, journal_rows
        )
        if missing_ids or conflicting_ids:
            raise ValueError(
                f"{path}: exploration_checkpoint помечен зарегистрированным, "
                "но карточки не совпадают с used_finds.csv"
            )
        checkpoints.append((checkpoint, path))
    if not checkpoints:
        return None, None
    ids_by_generation: dict[int, set[str]] = {}
    for checkpoint, _path in checkpoints:
        ids_by_generation.setdefault(checkpoint["generation"], set()).add(
            checkpoint["checkpoint_id"]
        )
    conflicts = [
        generation for generation, ids in ids_by_generation.items() if len(ids) > 1
    ]
    if conflicts:
        raise ValueError(
            "Обнаружены расходящиеся зарегистрированные exploration_checkpoint "
            f"одного поколения: {', '.join(map(str, sorted(conflicts)))}"
        )
    latest_generation = max(ids_by_generation)
    checkpoint_id = next(iter(ids_by_generation[latest_generation]))
    matches = [
        (checkpoint, path)
        for checkpoint, path in checkpoints
        if checkpoint["checkpoint_id"] == checkpoint_id
    ]
    return matches[-1]


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


def _used_values_for_event(event: dict[str, Any]) -> dict[str, str]:
    chunk_id = normalize_text(str(event.get("chunk_id", "")))
    finding_type = normalize_text(str(event.get("type", "event"))).casefold()
    if finding_type not in USED_TYPES:
        raise ValueError(f"{chunk_id}: type должен быть event или interpretation")
    return {
        "id": chunk_id,
        "type": finding_type,
        "persons": _join_used_values(event.get("person", [])),
        "topics": _join_used_values(event.get("topics", [])),
        "short_description": normalize_text(
            str(event.get("what_happened", event.get("title", "")))
        )[:500],
        "source": normalize_text(str(event.get("source", ""))),
    }


def _used_row_matches_event(row: dict[str, str], event: dict[str, Any]) -> bool:
    expected = _used_values_for_event(event)
    return all(
        normalize_text(row.get(field, "")) == value
        for field, value in expected.items()
    )


def _publication_registration_issues(
    events: list[dict[str, Any]], rows: list[dict[str, str]]
) -> tuple[list[str], list[str]]:
    rows_by_id = {normalize_text(row["id"]): row for row in rows}
    missing: list[str] = []
    conflicting: list[str] = []
    for event in events:
        chunk_id = normalize_text(str(event.get("chunk_id", "")))
        row = rows_by_id.get(chunk_id)
        if row is None:
            missing.append(chunk_id)
        elif not _used_row_matches_event(row, event):
            conflicting.append(chunk_id)
    return missing, conflicting


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


@contextmanager
def _pending_queue_lock(queue_path: Path, *, timeout: float = 15.0):
    """Serialize read/check/replace cycles for the existing editorial queue."""
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = queue_path.with_name(f".{queue_path.name}.lock")
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
                        f"Не удалось получить блокировку редакционной очереди "
                        f"за {timeout:g} с: {lock_path}"
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


def _read_pending_editorial_queue(queue_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(queue_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{queue_path}: повреждён JSON редакционной очереди: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{queue_path}: ожидается JSON-объект")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError(f"{queue_path}: ожидается массив items")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{queue_path}: items[{index}] должен быть объектом")
        if not normalize_text(str(item.get("chunk_id", ""))):
            raise ValueError(f"{queue_path}: items[{index}] не содержит chunk_id")
    return payload


def append_pending_editorial_candidates(
    queue_path: Path,
    used_path: Path,
    candidates: list[dict[str, Any]],
) -> tuple[int, int, int]:
    """Append new technical candidates to the existing FIFO queue exactly once.

    The candidate order is retained.  Publication and queue locks use the same
    order as pruning so a concurrent registration cannot reintroduce a
    published chunk and concurrent producers cannot overwrite one another.
    """
    queue_path = queue_path.expanduser().resolve()
    used_path = used_path.expanduser().resolve()
    if not queue_path.is_file():
        raise ValueError(f"Редакционная очередь не найдена: {queue_path}")
    with _publication_lock(used_path):
        published_ids = {
            normalize_text(row["id"]) for row in _read_used_rows(used_path)
        }
        with _pending_queue_lock(queue_path):
            payload = _read_pending_editorial_queue(queue_path)
            items = payload["items"]
            existing_ids = {
                normalize_text(str(item.get("chunk_id", ""))) for item in items
            }
            added = 0
            skipped = 0
            for candidate in candidates:
                chunk_id = normalize_text(str(candidate.get("chunk_id", "")))
                if not chunk_id:
                    raise ValueError("Кандидат очереди не содержит chunk_id")
                if chunk_id in published_ids or chunk_id in existing_ids:
                    skipped += 1
                    continue
                items.append(
                    {
                        "chunk_id": chunk_id,
                        "relative_path": normalize_text(
                            str(candidate.get("relative_path", ""))
                        ),
                        "state": "pending_context",
                        "reason": "technical_candidate_from_research_findings",
                    }
                )
                existing_ids.add(chunk_id)
                added += 1
            if added:
                _atomic_write_json({**payload, "items": items}, queue_path)
            return len(items), added, skipped


def pending_editorial_batch(
    queue_path: Path, used_path: Path, *, limit: int = 5
) -> tuple[list[dict[str, Any]], int, int]:
    """Return the FIFO prefix after removing already-published entries."""
    if limit < 1:
        raise ValueError("Лимит редакционной очереди должен быть положительным")
    _kept, removed = prune_pending_editorial_queue(queue_path, used_path)
    queue_path = queue_path.expanduser().resolve()
    with _pending_queue_lock(queue_path):
        payload = _read_pending_editorial_queue(queue_path)
        items = payload["items"]
        return [dict(item) for item in items[:limit]], len(items), removed


def discard_pending_editorial_candidates(
    queue_path: Path, used_path: Path, chunk_ids: list[str]
) -> tuple[int, int]:
    """Remove unusable queue entries without registering them as published."""
    queue_path = queue_path.expanduser().resolve()
    used_path = used_path.expanduser().resolve()
    requested = {
        normalize_text(str(chunk_id)) for chunk_id in chunk_ids if chunk_id
    }
    if not requested:
        return len(_read_pending_editorial_queue(queue_path)["items"]), 0
    with _publication_lock(used_path):
        with _pending_queue_lock(queue_path):
            payload = _read_pending_editorial_queue(queue_path)
            items = payload["items"]
            kept = [
                item
                for item in items
                if normalize_text(str(item.get("chunk_id", ""))) not in requested
            ]
            removed = len(items) - len(kept)
            if removed:
                _atomic_write_json({**payload, "items": kept}, queue_path)
            return len(kept), removed


def _validate_pending_publication_order(
    queue_path: Path, used_path: Path, events: list[dict[str, Any]]
) -> None:
    """Reject a new registration that skips an earlier FIFO queue entry."""
    queue_path = queue_path.expanduser().resolve()
    used_path = used_path.expanduser().resolve()
    with _publication_lock(used_path):
        published_ids = {
            normalize_text(row["id"]) for row in _read_used_rows(used_path)
        }
        event_ids = [
            normalize_text(str(event.get("chunk_id", ""))) for event in events
        ]
        unregistered_ids = [
            chunk_id for chunk_id in event_ids if chunk_id not in published_ids
        ]
        if not unregistered_ids:
            return
        with _pending_queue_lock(queue_path):
            payload = _read_pending_editorial_queue(queue_path)
            active_ids = [
                normalize_text(str(item.get("chunk_id", "")))
                for item in payload["items"]
                if normalize_text(str(item.get("chunk_id", "")))
                not in published_ids
            ]
            expected = active_ids[: len(unregistered_ids)]
            if unregistered_ids != expected:
                raise ValueError(
                    "Выпуск нарушает FIFO редакционной очереди: ожидаются "
                    + ", ".join(expected)
                )


def prune_pending_editorial_queue(
    queue_path: Path, used_path: Path
) -> tuple[int, int]:
    """Remove journaled chunk IDs while preserving every unresolved queue item.

    The publication lock is acquired before the queue lock in every call. Queue
    writers must use ``_pending_queue_lock`` and atomic replacement as well; this
    prevents a concurrent reserve/update from being overwritten by pruning.
    """
    queue_path = queue_path.expanduser().resolve()
    used_path = used_path.expanduser().resolve()
    if not queue_path.exists():
        return 0, 0
    with _publication_lock(used_path):
        published_ids = {
            normalize_text(row["id"]) for row in _read_used_rows(used_path)
        }
        with _pending_queue_lock(queue_path):
            if not queue_path.exists():
                return 0, 0
            payload = _read_pending_editorial_queue(queue_path)
            items = payload["items"]
            kept = [
                item
                for item in items
                if normalize_text(str(item.get("chunk_id", "")))
                not in published_ids
            ]
            removed = len(items) - len(kept)
            if removed:
                _atomic_write_json({**payload, "items": kept}, queue_path)
            return len(kept), removed


def append_used(events: list[dict[str, Any]], used_path: Path) -> tuple[int, int]:
    with _publication_lock(used_path):
        existing = _read_used_rows(used_path)
        existing_by_id = {
            normalize_text(record["id"]): record for record in existing
        }
        rows: list[dict[str, str]] = []
        skipped = 0
        for event in events:
            values = _used_values_for_event(event)
            chunk_id = values["id"]
            if not chunk_id:
                skipped += 1
                continue
            previous = existing_by_id.get(chunk_id)
            if previous is not None:
                if not _used_row_matches_event(previous, event):
                    raise ValueError(
                        f"{chunk_id}: ID уже зарегистрирован с другим содержанием"
                    )
                skipped += 1
                continue
            row = {**values, "date_used": date.today().isoformat()}
            rows.append(row)
            existing_by_id[chunk_id] = row
        if rows:
            _atomic_write_used_rows([*existing, *rows], used_path)
        return len(rows), skipped

