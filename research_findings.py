"""Profile-driven candidate retrieval built on the existing search primitives."""

from __future__ import annotations

import json
import os
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
from research_profile import effective_search_mode
from source_discovery import (candidate_role, discover_sources, discovery_evidence, document_group, focus_evidence,
                              interleave, preference_terms, source_round_robin)


GENERIC_DATE_RE = re.compile(
    r"\b(?:\d{1,4}\s*(?:BCE|BC|CE|AD)|(?:BCE|BC|CE|AD)\s*\d{1,4})\b",
    re.IGNORECASE,
)


def _json_size(payload: dict[str, Any]) -> int:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if os.linesep != "\n":
        serialized = serialized.replace("\n", os.linesep)
    return len(serialized.encode("utf-8"))


def _compact_duplicate_check(candidate: dict[str, Any]) -> dict[str, Any]:
    duplicate = candidate.get("duplicate_check", {})
    return {
        "status": duplicate.get("status"),
        "confidence": duplicate.get("confidence"),
        "reason": duplicate.get("reason"),
        "matched_id": duplicate.get("matched_id"),
        "python_disposition": duplicate.get("python_disposition"),
        "auto_exclude": bool(duplicate.get("auto_exclude")),
        "requires_editorial_review": bool(
            duplicate.get("requires_editorial_review")
        ),
        "review_matches": list(duplicate.get("review_matches", [])),
    }


def _compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return the one-pass editorial view; full evidence stays in the full JSON."""
    return {
        "chunk_id": candidate.get("chunk_id"),
        "title": candidate.get("title"),
        "retrieval_excerpt": candidate.get("what_happened"),
        "selection_status": "unreviewed",
        "candidate_role": candidate.get('candidate_role', 'source_passage'),
        "passage_role": "unreviewed",
        "retrieval": candidate.get("retrieval", {}),
        "scope_review": {key: value for key, value in candidate.get('scope_review', {}).items()
                         if key not in {'research_area', 'focus_people'}},
        "person": list(candidate.get("person", [])),
        "topics": list(candidate.get("topics", [])),
        "date": candidate.get("date"),
        "source": candidate.get("source"),
        "source_type": candidate.get("index_source_type")
        or candidate.get("source_type"),
        "relative_path": candidate.get("relative_path"),
        "page_start": candidate.get("page_start"),
        "page_end": candidate.get("page_end"),
        "chunk_no": candidate.get("chunk_no"),
        "retrieval_score": candidate.get("retrieval_score"),
        "full_context_ref": {
            "chunk_id": candidate.get("chunk_id"),
            "field": "verified_context",
        },
        "duplicate_check": _compact_duplicate_check(candidate),
        "semantic_review": candidate.get("semantic_review", {}),
    }


def _collect_comparison_contexts(
    verified: list[dict[str, Any]], emitted: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Keep one full canonical row for every off-batch semantic comparison."""
    emitted_ids = {
        str(item.get("chunk_id")) for item in emitted if item.get("chunk_id")
    }
    referenced_ids = {
        str(match.get("matched_chunk_id"))
        for item in emitted
        for match in item.get("semantic_review", {}).get("candidate_matches", [])
        if match.get("matched_chunk_id")
    }
    missing_context_ids = referenced_ids - emitted_ids
    contexts: list[dict[str, Any]] = []
    for item in verified:
        chunk_id = str(item.get("chunk_id") or "")
        if chunk_id not in missing_context_ids:
            continue
        # The hidden row is stored once as evidence for links from the emitted
        # batch. Its own pair-review graph is intentionally omitted: retaining
        # it would create new links outside this evidence closure.
        canonical = dict(item)
        canonical.pop("semantic_review", None)
        contexts.append(canonical)
    return contexts


def build_editorial_packet(result: dict[str, Any]) -> dict[str, Any]:
    """Build a compact first-pass handoff while retaining the lossless result."""
    packet: dict[str, Any] = {
        "mode": "research-findings-editorial",
        "generated_at_utc": result.get("generated_at_utc"),
        "full_result_ref": result.get("artifacts", {}).get("full_result"),
        "profile": {
            "name": result.get("profile", {}).get("name"),
            "research_area": result.get("profile", {}).get("research_area"),
            "result_language": result.get("profile", {}).get("result_language"),
            "max_results": result.get("profile", {}).get("max_results"),
            "search_mode": effective_search_mode(result['profile']),
            "focus_people": result['profile'].get('focus_people', []),
            "finding_preferences": result['profile'].get('finding_preferences', {}),
        },
        "coverage": result.get("coverage", {}),
        "stats": result.get("stats", {}),
        "final": [_compact_candidate(item) for item in result.get("final", [])],
        "alternates": [
            _compact_candidate(item) for item in result.get("alternates", [])
        ],
        "comparison_context_count": len(result.get("comparison_contexts", [])),
        "candidate_pool": [item['chunk_id'] for item in result.get('final', []) + result.get('alternates', [])],
        "continuation": result.get("continuation", {}),
        "workflow": {
            "first_pass": "Review this packet once; do not print the full result.",
            "full_context": (
                "Request one consolidated research-context packet for finalists "
                "and candidates requiring semantic review."
            ),
        },
    }
    full_bytes = _json_size(result)
    packet["size"] = {
        "full_result_bytes": full_bytes,
        "editorial_packet_bytes": 0,
        "reduction_percent": 0.0,
    }
    # The size block contributes to the file it measures. A few fixed-point
    # passes make the reported byte count match the serialized packet.
    for _ in range(3):
        compact_bytes = _json_size(packet)
        packet["size"]["editorial_packet_bytes"] = compact_bytes
        packet["size"]["reduction_percent"] = (
            round((1 - compact_bytes / full_bytes) * 100, 1)
            if full_bytes
            else 0.0
        )
    return packet


def build_research_context_packet(
    result: dict[str, Any],
    selected_chunk_ids: list[str],
    *,
    include_required_review: bool = False,
) -> dict[str, Any]:
    """Select full canonical candidate rows in one consolidated packet."""
    visible_candidates = {
        str(item.get("chunk_id")): item
        for section in ("final", "alternates")
        for item in result.get(section, [])
        if isinstance(item, dict) and item.get("chunk_id")
    }
    candidates = dict(visible_candidates)
    candidates.update(
        {
            str(item.get("chunk_id")): item
            for item in result.get("comparison_contexts", [])
            if isinstance(item, dict) and item.get("chunk_id")
        }
    )
    requested = {str(chunk_id) for chunk_id in selected_chunk_ids if chunk_id}
    if include_required_review:
        requested.update(
            chunk_id
            for chunk_id, item in visible_candidates.items()
            if bool(item.get("semantic_review", {}).get("required"))
        )
    missing = sorted(requested - candidates.keys())
    if missing:
        raise ValueError(
            "В полном research-findings JSON нет chunk_id: " + ", ".join(missing)
        )

    # Include linked comparisons, including canonical rows outside the emitted
    # batch, so the editor sees both full claims without a repeated search.
    linked: set[str] = set()
    for chunk_id in requested:
        review = candidates[chunk_id].get("semantic_review", {})
        linked.update(
            str(match.get("matched_chunk_id"))
            for match in review.get("candidate_matches", [])
            if match.get("matched_chunk_id") in candidates
        )
    included = requested | linked
    ordered = [
        item
        for section in ("final", "alternates", "comparison_contexts")
        for item in result.get(section, [])
        if str(item.get("chunk_id")) in included
    ]
    return {
        "mode": "research-findings-context",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_generated_at_utc": result.get("generated_at_utc"),
        "selected_chunk_ids": sorted(set(selected_chunk_ids)),
        "required_review_included": include_required_review,
        "linked_comparison_chunk_ids": sorted(linked - requested),
        "candidates": ordered,
    }


def load_continuation_chunk_ids(
    paths: list[Path], profile: dict[str, Any]
) -> set[str]:
    """Load run-local continuation state from earlier research result files."""
    excluded: set[str] = set()
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as exc:
            raise RuntimeError(f"Не найден предыдущий результат: {path}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Ошибка JSON в предыдущем результате {path}: {exc}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("mode") != "research-findings":
            raise ValueError(
                f"{path}: --continue-from ожидает результат research-findings"
            )
        if payload.get("profile") != profile:
            raise ValueError(
                f"{path}: профиль предыдущего результата отличается от текущего"
            )

        continuation = payload.get("continuation", {})
        if continuation and not isinstance(continuation, dict):
            raise ValueError(f"{path}: повреждено состояние continuation")
        has_stored_state = isinstance(continuation, dict) and (
            "exclude_on_next_run" in continuation
        )
        stored = continuation.get("exclude_on_next_run", []) if has_stored_state else []
        if has_stored_state:
            if not isinstance(stored, list) or not all(
                isinstance(item, str) and item for item in stored
            ):
                raise ValueError(f"{path}: повреждено состояние continuation")
            excluded.update(stored)
            continue

        # Compatibility with 0.2/0.3 result files created before continuation
        # metadata existed. Only candidates exposed to the editor are skipped;
        # unseen verified candidates remain available.
        for section in ("final", "alternates"):
            rows = payload.get(section, [])
            if not isinstance(rows, list):
                raise ValueError(f"{path}: поле {section} должно быть массивом")
            for row in rows:
                if isinstance(row, dict) and row.get("chunk_id"):
                    excluded.add(str(row["chunk_id"]))
    return excluded


def _quoted_query(terms: list[str]) -> str:
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)


def load_discovery_state(paths: list[Path]) -> dict:
    """Called after the ordinary continuation/profile validation, including legacy files."""
    state = {'rejections': {}, 'next_lane': 0}
    for path in paths:
        previous = json.loads(path.read_text(encoding='utf-8-sig')).get('continuation', {})
        version = previous.get('discovery_state_version')
        if version is None:
            continue
        if version != 1:
            raise ValueError(f'{path}: неизвестная версия discovery continuation')
        rejections = previous.get('discovery_rejections', {})
        turn = previous.get('discovery_next_lane', 0)
        if not isinstance(rejections, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in rejections.items()
        ) or type(turn) is not int or turn not in (0, 1):
            raise ValueError(f'{path}: повреждено состояние discovery continuation')
        state['rejections'].update(rejections)
        state['next_lane'] = turn
    return state


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
                if effective_search_mode(profile) == 'open':
                    score += 0.25 * len(set(candidate['person']) &
                        {person['name'] for person in profile.get('focus_people', [])})
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
    batch_size: int = 25,
    preview: bool = False,
    excluded_chunk_ids: set[str] | None = None,
    discovery_rejections: dict[str, str] | None = None,
    discovery_next_lane: int = 0,
    discovery_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Retrieve candidates without changing the index, profile, or journal."""
    requested_count = profile["max_results"] if count is None else count
    if not 1 <= requested_count <= 20:
        raise ValueError("count должен быть от 1 до 20")
    if not requested_count <= batch_size <= 100:
        raise ValueError("batch_size должен быть не меньше count и не больше 100")
    used = load_used_finds(used_finds_path)
    excluded_before = set(excluded_chunk_ids or ())
    by_chunk: dict[str, dict[str, Any]] = {}
    mode = effective_search_mode(profile)
    discovery_rejections = dict(discovery_rejections or {})
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
                {**row, "matched_interests": [], "retrieval_score": 0.0, "retrieval_methods": ["thematic_fts"]},
            )
            candidate["matched_interests"].append(interest["id"])
            candidate["retrieval_score"] += interest["weight"] / max(row["rank"], 1)

    interest_by_id = {item["id"]: item for item in profile["interests"]}
    ranked_unseen = sorted(
        (
            item
            for item in by_chunk.values()
            if str(item["chunk_id"]) not in excluded_before
        ),
        key=lambda item: (-item["retrieval_score"], -item["score"], item["chunk_id"]),
    )
    # Exploration is independent of name/topic vocabulary, but never of hard filters.
    # A soft preference probe is optional; lack of lexical overlap (e.g. Russian
    # preferences and Japanese evidence) cannot suppress uniform exploration.
    preferences = preference_terms(profile)
    preference_hits: set[str] = set()
    if preferences:
        preference_args = _search_args(profile, {'terms': preferences}, pool_size)
        preference_hits = {row['chunk_id'] for row in search_function(
            connection, preference_args, topics, people, events_only=False)}
    discovery_rows, discovery_stats = (discover_sources(
        connection, profile, excluded_before, preference_hits, document_group,
        discovery_rejections, discovery_paths) if connection is not None else ([], {'sources': {}}))
    exploration_by_id = {row['chunk_id']: row for row in discovery_rows}
    for row in ranked_unseen:
        discovery = exploration_by_id.get(row['chunk_id'])
        if discovery:
            row['retrieval_methods'] = list(dict.fromkeys(row['retrieval_methods'] + discovery['retrieval_methods']))
    # Keep the thematic metadata for overlapping IDs in either lane.
    discovery_rows = [by_chunk.get(row['chunk_id'], row) for row in discovery_rows]
    ranked_unseen = interleave(ranked_unseen, discovery_rows)
    ranked_pool = ranked_unseen[:pool_size]
    verified: list[dict[str, Any]] = []
    python_rejected_ids: set[str] = set()
    rejected: Counter[str] = Counter()
    focus_mentions: Counter[str] = Counter()
    verified_interest_mentions: Counter[str] = Counter()
    for raw in ranked_pool:
        context = context_function(connection, raw["chunk_id"], 1, 1)
        target = next((row for row in context if row["target"]), None)
        if target is None or target["text_quality"] != "good":
            rejected["quality_or_context"] += 1
            python_rejected_ids.add(str(raw["chunk_id"]))
            continue
        # An FTS alias/annotation hit is not necessarily target-text evidence.
        # Exploration may retain the passage, but may not inherit an unproved topic.
        matched_interests = [interest_by_id[item] for item in raw['matched_interests']
                             if _find_term(normalize_text(target['text']), interest_by_id[item]['terms'])]
        discovery = 'source_exploration' in raw['retrieval_methods']
        excerpt, matched_term, matched_focus_people = _evidence(
            target['text'], matched_interests, profile)
        preference_matches = []
        if mode == 'focused_people' and profile['focus_people']:
            # Search a paragraph actually containing an alias, not a name in a
            # neighboring chunk or an unrelated query-centered excerpt.
            excerpt = focus_evidence(target['text'], profile)
            matched_focus_people = _matched_people(excerpt or '', profile)
        elif excerpt is None and discovery and mode == 'open':
            excerpt, preference_matches = discovery_evidence(target['text'], profile)
            matched_focus_people = _matched_people(excerpt or '', profile)
        if excerpt is None:
            rejected['interest_not_in_target_chunk' if not discovery else 'no_readable_discovery_passage'] += 1
            python_rejected_ids.add(str(raw['chunk_id']))
            if discovery:
                discovery_rejections[raw['chunk_id']] = exploration_by_id[raw['chunk_id']]['text_hash']
            continue
        if not _evidence_readable(excerpt):
            rejected["unreliable_local_ocr"] += 1
            python_rejected_ids.add(str(raw["chunk_id"]))
            continue
        if (
            profile["focus_people"]
            and mode == "focused_people"
            and not matched_focus_people
        ):
            rejected["focus_person_not_in_target_chunk"] += 1
            python_rejected_ids.add(str(raw["chunk_id"]))
            continue
        focus_mentions.update(matched_focus_people)
        candidate_people = unique_normalized(
            [*matched_focus_people, *target.get("people", [])]
        )
        interest_ids = [item["id"] for item in matched_interests]
        verified_interest_mentions.update(interest_ids)
        primary_interest = (max(matched_interests,
            key=lambda item: (item['weight'], -interest_ids.index(item['id'])))
            if matched_interests else None)
        names = ', '.join(candidate_people)
        label = primary_interest['label'] if primary_interest else 'Source passage for scope and story review'
        title = f'{names} — {label}' if names else label
        event = {
            "title": title,
            "person": candidate_people,
            "date": _generic_date(excerpt),
            "place": None,
            "what_happened": excerpt,
            "retrieval_excerpt": excerpt,
            "candidate_role": candidate_role(raw['relative_path'], excerpt),
            "passage_role": "unreviewed",
            "selection_status": "unreviewed",
            "why_interesting": (
                f"Retrieval route: {', '.join(raw['retrieval_methods'])}. "
                "Interpret only from the verified source context."
            ),
            "source": target["source"],
            "source_group": document_group({**raw, "source": target["source"]}),
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
            "primary_topic": primary_interest['id'] if primary_interest else None,
            "retrieval": {
                "methods": raw['retrieval_methods'],
                "reason": ('Topical term evidence' if matched_interests else
                           'Source-balanced exploration of a previously unexposed document position'),
                "matched_term": matched_term,
                "preference_lexical_matches": preference_matches,
                "preference_probe_hit": raw['chunk_id'] in preference_hits,
                "preferred_kinds": profile['finding_preferences'].get('preferred_kinds', []),
                "source_position": target['chunk_no'],
            },
            "scope_review": {
                "status": "pending",
                "search_mode": mode,
                "research_area": profile['research_area'],
                "focus_people": profile['focus_people'],
                "required": "Verify substantive connection to the research area" +
                    (' and a selected person; a name alone is insufficient' if mode == 'focused_people' else '') +
                    '; reject unrelated or uncertain passages before editorial acceptance',
            },
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

    verified_ids = {item['chunk_id'] for item in verified}
    for raw in ranked_pool:
        if raw['chunk_id'] not in verified_ids and raw['chunk_id'] in exploration_by_id:
            discovery_rejections[raw['chunk_id']] = exploration_by_id[raw['chunk_id']]['text_hash']
    verified_before_collapse = verified
    verified = _collapse_candidates(verified_before_collapse)
    kept_ids = {str(item["chunk_id"]) for item in verified}
    collapsed_ids = {
        str(item["chunk_id"])
        for item in verified_before_collapse
        if str(item["chunk_id"]) not in kept_ids
    }
    attach_semantic_reviews(verified)
    verified.sort(
        key=lambda item: (
            item["duplicate_check"]["status"] != "clear",
            -item["retrieval_score"],
            item["source"],
        )
    )
    thematic = [item for item in verified if 'thematic_fts' in item['retrieval']['methods']]
    exploration = [item for item in verified if 'source_exploration' in item['retrieval']['methods']]
    order = {row['chunk_id']: i for i, row in enumerate(discovery_rows)}
    exploration.sort(key=lambda item: order[item['chunk_id']])
    lanes = [source_round_robin(thematic, document_group), exploration]
    if discovery_next_lane:
        lanes.reverse()
    batch = interleave(*lanes)[:batch_size]
    final = _select_diverse(batch, min(requested_count, len(batch)), profile)
    final_ids = {item['chunk_id'] for item in final}
    alternates = [item for item in batch if item['chunk_id'] not in final_ids]
    comparison_contexts = _collect_comparison_contexts(
        verified, [*final, *alternates]
    )
    batch_chunk_ids = [str(item["chunk_id"]) for item in [*final, *alternates]]
    # Only candidates actually exposed to Codex and exact technical collapses are
    # consumed. A row rejected before editorial review may be a context neighbour
    # or become useful at another retrieval depth, so it must remain searchable.
    exclude_on_next_run = excluded_before | set(batch_chunk_ids) | collapsed_ids
    verified_not_emitted = max(0, len(verified) - len(batch_chunk_ids))
    beyond_pool = max(0, len(ranked_unseen) - len(ranked_pool))
    missing_people = [
        item["name"]
        for item in profile["focus_people"]
        if focus_mentions[item["name"]] == 0
    ]
    missing_interests = [
        item["id"]
        for item in profile["interests"]
        if interest_hits[item["id"]] == 0
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
    for path, info in discovery_stats['sources'].items():
        info['checked'] = sum(row['relative_path'] == path for row in ranked_pool)
        info['emitted'] = sum(row['relative_path'] == path for row in batch)
        info['emitted_chunk_nos'] = [row['chunk_no'] for row in batch if row['relative_path'] == path]
        info['omission_reason'] = (None if info['emitted'] else
            'hard_filter_or_navigation' if not info['eligible'] else
            'not_in_this_batch; use continuation (aliases may share a document turn)')
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "research-findings",
        "preview": preview,
        "profile": profile,
        "filters": {
            "discovery_paths": discovery_paths or [],
            "material_types": profile["material_types"],
            "quality": ["good"],
            "count": requested_count,
        },
        "coverage": {
            "search_hits": interest_hits,
            "search_mode": mode,
            "discovery": discovery_stats,
            "retrieval_methods": {
                method: {'checked': sum(method in row['retrieval_methods'] for row in ranked_pool),
                         'emitted': sum(method in row['retrieval']['methods'] for row in batch)}
                for method in ['thematic_fts', 'source_exploration', 'preference_lexical']
            },
            "verified_interest_mentions": dict(verified_interest_mentions),
            "interests_without_hits": missing_interests,
            "focus_people_mentions": dict(focus_mentions),
            "focus_people_without_hits": missing_people,
            "note": (
                "Zero search_hits means the configured retrieval found no indexed "
                "match at its current depth. A zero verified count can also mean that "
                "matches were filtered or appeared in an earlier batch. Neither is "
                "evidence that the subject is absent from the original corpus."
            ),
        },
        "stats": {
            "unique_pool": len(ranked_unseen) + len(set(by_chunk) & excluded_before),
            "excluded_from_previous_batches": max(len(set(by_chunk) & excluded_before),
                sum(info['previously_exposed'] for info in discovery_stats['sources'].values())),
            "pool_checked": len(ranked_pool),
            "batch_size": batch_size,
            "verified_candidates": len(verified),
            "used_finds_records": len(used),
            "rejected": dict(rejected),
            "final_count": len(final),
            "alternate_count": len(alternates),
            "semantic_review": review_stats,
        },
        "final": final,
        "alternates": alternates,
        "comparison_contexts": comparison_contexts,
        "continuation": {
            "seen_before_count": len(excluded_before),
            "discovery_state_version": 1,
            "discovery_rejections": discovery_rejections,
            "discovery_next_lane": (discovery_next_lane + len(batch)) % 2,
            "candidate_chunk_ids": batch_chunk_ids,
            "python_rejected_chunk_ids": sorted(python_rejected_ids),
            "collapsed_duplicate_chunk_ids": sorted(collapsed_ids),
            "exclude_on_next_run": sorted(exclude_on_next_run),
            "verified_candidates_not_emitted": verified_not_emitted,
            "retrieved_chunks_beyond_pool": beyond_pool,
            "has_more_in_current_retrieval": bool(verified_not_emitted or beyond_pool),
            "note": (
                "Pass this result to --continue-from to request another batch "
                "without repeating candidates already exposed to Codex. "
                "Pre-editorial rejects and context-only chunks stay eligible; only "
                "exposed candidates and exact technical collapses are consumed. "
                "Increase --top-per-interest or --pool-size only when the current retrieval "
                "does not contain enough new candidates."
            ),
        },
    }


def print_research_result(result: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    coverage = result["coverage"]
    print(f"Профиль: {result['profile']['name']}")
    print(f"Область: {result['profile']['research_area']}")
    print(f"Python-шортлист: {len(result['final'])}")
    continuation = result.get("continuation", {})
    if continuation.get("seen_before_count"):
        print(
            "Исключено ранее просмотренных/технически отклонённых chunk_id: "
            f"{continuation['seen_before_count']}"
        )
    if coverage["interests_without_hits"]:
        print(
            "Нет поисковых совпадений на текущей глубине: "
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
    if continuation.get("candidate_chunk_ids"):
        print(
            "Для следующей непересекающейся партии передайте этот JSON через "
            "--continue-from."
        )
