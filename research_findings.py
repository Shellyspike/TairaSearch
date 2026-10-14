"""Profile-driven candidate retrieval built on the existing search primitives."""

from __future__ import annotations

import json
import re
import sqlite3
from argparse import Namespace
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from daily_five import (
    _evidence_readable,
    _auto_excluded,
    attach_semantic_reviews,
    candidate_pair_check,
    duplicate_check,
    load_used_finds,
    source_group,
)
from text_utils import normalize_text, unique_normalized


GENERIC_DATE_RE = re.compile(
    r"\b(?:\d{1,4}\s*(?:BCE|BC|CE|AD)|(?:BCE|BC|CE|AD)\s*\d{1,4})\b",
    re.IGNORECASE,
)


def _quoted_query(terms: list[str]) -> str:
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)


def _search_args(
    profile: dict[str, Any], interest: dict[str, Any], top: int
) -> Namespace:
    return Namespace(
        query=_quoted_query(interest["terms"]),
        topic=[],
        person=[],
        source_type=list(profile["material_types"]),
        exclude_source_type=[],
        source=list(profile["include_sources"]),
        exclude_source=list(profile["exclude_sources"]),
        quality=["good"],
        top=top,
        offset=0,
        json=False,
        include_duplicates=False,
    )


def _find_term(text: str, terms: list[str]) -> tuple[int, str] | None:
    folded = text.casefold()
    matches = [
        (folded.find(term.casefold()), term)
        for term in terms
        if term and folded.find(term.casefold()) >= 0
    ]
    return min(matches, default=None, key=lambda item: (item[0], -len(item[1])))


def _matched_people(text: str, profile: dict[str, Any]) -> list[str]:
    folded = text.casefold()
    compact = "".join(folded.split())
    result: list[str] = []
    for person in profile["focus_people"]:
        if any(
            alias.casefold() in folded
            or "".join(alias.casefold().split()) in compact
            for alias in person["aliases"]
        ):
            result.append(person["name"])
    return result


def _evidence(
    text: str, interests: list[dict[str, Any]], profile: dict[str, Any], limit: int = 620
) -> tuple[str | None, str | None, list[str]]:
    normalized = normalize_text(text)
    matches: list[tuple[int, str]] = []
    for interest in interests:
        match = _find_term(normalized, interest["terms"])
        if match:
            matches.append(match)
    if not matches:
        return None, None, []
    position, term = min(matches, key=lambda item: (item[0], -len(item[1])))
    start = max(0, position - limit // 3)
    end = min(len(normalized), start + limit)
    excerpt = normalized[start:end].strip()
    if start:
        excerpt = "…" + excerpt
    if end < len(normalized):
        excerpt += "…"
    if (
        len(excerpt) < 60
        or excerpt.count("の事") >= 4
        or excerpt.count("事") >= 12
    ):
        return None, None, []
    return excerpt, term, _matched_people(excerpt, profile)


def _generic_date(text: str) -> str | None:
    match = GENERIC_DATE_RE.search(text)
    return match.group(0) if match else None


def _collapse_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: -item["retrieval_score"]):
        duplicate = any(
            candidate_pair_check(prior, candidate)["action"] == "collapse"
            for prior in kept
        )
        if not duplicate:
            kept.append(candidate)
    return kept


def _select_diverse(
    candidates: list[dict[str, Any]], count: int, profile: dict[str, Any]
) -> list[dict[str, Any]]:
    eligible = [item for item in candidates if not _auto_excluded(item)]
    selected: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    people_counts: Counter[str] = Counter()
    avoid_people = profile["finding_preferences"]["avoid_person_repetition"]

    def choose(max_per_source: int) -> None:
        while len(selected) < count:
            best: dict[str, Any] | None = None
            best_score = float("-inf")
            for candidate in eligible:
                source_key = candidate["source_group"]
                if candidate in selected or source_counts[source_key] >= max_per_source:
                    continue
                score = candidate["retrieval_score"]
                score += sum(
                    0.5 for topic in candidate["topics"] if topic_counts[topic] == 0
                )
                score -= source_counts[source_key] * 1.5
                score -= sum(topic_counts[topic] for topic in candidate["topics"]) * 0.7
                if avoid_people:
                    score -= sum(people_counts[name] for name in candidate["person"]) * 0.8
                if score > best_score:
                    best = candidate
                    best_score = score
            if best is None:
                return
            selected.append(best)
            source_counts[best["source_group"]] += 1
            topic_counts.update(best["topics"])
            people_counts.update(best["person"])

    choose(1)
    if len(selected) < count:
        choose(2)
    return selected


def build_research_findings(
    connection: sqlite3.Connection,
    topics: dict[str, list[str]],
    people: dict[str, dict[str, Any]],
    profile: dict[str, Any],
    used_finds_path: Path,
    *,
    search_function: Callable[..., list[dict[str, Any]]],
    context_function: Callable[..., list[dict[str, Any]]],
    count: int | None = None,
    top_per_interest: int = 30,
    pool_size: int = 160,
    preview: bool = False,
) -> dict[str, Any]:
    """Retrieve candidates without changing the index, profile, or journal."""
    requested_count = profile["max_results"] if count is None else count
    if not 1 <= requested_count <= 20:
        raise ValueError("count должен быть от 1 до 20")
    used = load_used_finds(used_finds_path)
    by_chunk: dict[str, dict[str, Any]] = {}
    interest_hits: dict[str, int] = {}
    for interest in profile["interests"]:
        rows = search_function(
            connection,
            _search_args(profile, interest, top_per_interest),
            topics,
            people,
            events_only=False,
        )
        interest_hits[interest["id"]] = len(rows)
        for row in rows:
            candidate = by_chunk.setdefault(
                row["chunk_id"],
                {**row, "matched_interests": [], "retrieval_score": 0.0},
            )
            candidate["matched_interests"].append(interest["id"])
            candidate["retrieval_score"] += interest["weight"] / max(row["rank"], 1)

    interest_by_id = {item["id"]: item for item in profile["interests"]}
    ranked_pool = sorted(
        by_chunk.values(),
        key=lambda item: (-item["retrieval_score"], -item["score"], item["chunk_id"]),
    )[:pool_size]
    verified: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    focus_mentions: Counter[str] = Counter()
    verified_interest_mentions: Counter[str] = Counter()
    include_unlisted = profile["finding_preferences"]["include_unlisted_people"]
    for raw in ranked_pool:
        context = context_function(connection, raw["chunk_id"], 1, 1)
        target = next((row for row in context if row["target"]), None)
        if target is None or target["text_quality"] != "good":
            rejected["quality_or_context"] += 1
            continue
        matched_interests = [
            interest_by_id[item] for item in raw["matched_interests"]
        ]
        excerpt, matched_term, matched_focus_people = _evidence(
            target["text"], matched_interests, profile
        )
        if excerpt is None or matched_term is None:
            rejected["interest_not_in_target_chunk"] += 1
            continue
        if not _evidence_readable(excerpt):
            rejected["unreliable_local_ocr"] += 1
            continue
        if (
            profile["focus_people"]
            and not include_unlisted
            and not matched_focus_people
        ):
            rejected["focus_person_not_in_target_chunk"] += 1
            continue
        focus_mentions.update(matched_focus_people)
        candidate_people = unique_normalized(
            [*matched_focus_people, *target.get("people", [])]
        )
        interest_ids = [item["id"] for item in matched_interests]
        verified_interest_mentions.update(interest_ids)
        primary_interest = max(
            matched_interests,
            key=lambda item: (item["weight"], -interest_ids.index(item["id"])),
        )
        names = ", ".join(candidate_people)
        title = (
            f"{names} — {primary_interest['label']}"
            if names
            else primary_interest["label"]
        )
        event = {
            "title": title,
            "person": candidate_people,
            "date": _generic_date(excerpt),
            "place": None,
            "what_happened": excerpt,
            "why_interesting": (
                f"Matches the saved research interest: {primary_interest['label']}. "
                "Interpret only from the verified source context."
            ),
            "source": target["source"],
            "source_group": source_group(target["source"]),
            "source_type": target["source_type"],
            "index_source_type": target["source_type"],
            "filename": target["filename"],
            "path": target["path"],
            "relative_path": raw["relative_path"],
            "page_start": target["page_start"],
            "page_end": target["page_end"],
            "chunk_no": target["chunk_no"],
            "chunk_id": target["chunk_id"],
            "topics": interest_ids,
            "primary_topic": primary_interest["id"],
            "text_quality": target["text_quality"],
            "verified_context": {
                "status": "ok",
                "matched_term": matched_term,
                "chunks_loaded": len(context),
                "chunks": [
                    {
                        "target": row["target"],
                        "chunk_id": row["chunk_id"],
                        "chunk_no": row["chunk_no"],
                        "page_start": row["page_start"],
                        "page_end": row["page_end"],
                        "text": row["text"],
                    }
                    for row in context
                ],
            },
            "retrieval_score": round(raw["retrieval_score"], 6),
        }
        event["duplicate_check"] = duplicate_check(event, used)
        if event["duplicate_check"]["status"] == "duplicate":
            rejected["used_duplicate"] += 1
        verified.append(event)

    verified = _collapse_candidates(verified)
    attach_semantic_reviews(verified)
    verified.sort(
        key=lambda item: (
            item["duplicate_check"]["status"] != "clear",
            -item["retrieval_score"],
            item["source"],
        )
    )
    final = _select_diverse(verified, requested_count, profile)
    final_ids = {item["chunk_id"] for item in final}
    alternates = [item for item in verified if item["chunk_id"] not in final_ids][:20]
    missing_people = [
        item["name"]
        for item in profile["focus_people"]
        if focus_mentions[item["name"]] == 0
    ]
    missing_interests = [
        item["id"]
        for item in profile["interests"]
        if verified_interest_mentions[item["id"]] == 0
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
        "mode": "research-findings",
        "preview": preview,
        "profile": profile,
        "filters": {
            "material_types": profile["material_types"],
            "quality": ["good"],
            "count": requested_count,
        },
        "coverage": {
            "search_hits": interest_hits,
            "verified_interest_mentions": dict(verified_interest_mentions),
            "interests_without_hits": missing_interests,
            "focus_people_mentions": dict(focus_mentions),
            "focus_people_without_hits": missing_people,
            "note": (
                "No hit means the indexed corpus did not support that preference; "
                "it is not evidence that the subject is absent from the original corpus."
            ),
        },
        "stats": {
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


def print_research_result(result: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    coverage = result["coverage"]
    print(f"Профиль: {result['profile']['name']}")
    print(f"Область: {result['profile']['research_area']}")
    print(f"Найдено кандидатов: {len(result['final'])}")
    if coverage["interests_without_hits"]:
        print(
            "Нет совпадений по интересам: "
            + ", ".join(coverage["interests_without_hits"])
        )
    if coverage["focus_people_without_hits"]:
        print(
            "Не найдены в проверенных кандидатах: "
            + ", ".join(coverage["focus_people_without_hits"])
        )
    for number, item in enumerate(result["final"], start=1):
        print(f"\n{number}. {item['title']}")
        print(item["what_happened"])
        print(f"Источник: {item['relative_path']} · {item['chunk_id']}")
    if result["preview"]:
        print("\nПробная подборка: журнал публикаций не изменялся.")
