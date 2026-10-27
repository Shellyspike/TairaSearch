"""Read-only, language-independent exploration alongside thematic FTS retrieval.

This is a recall lane, not a story classifier. It offers source passages for
scope/evidence/editorial review even when their actors have no configured name.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from collections import Counter, deque
from typing import Any, Callable, Iterable

from daily_five import source_group


def document_group(candidate: dict) -> str:
    path = candidate.get('relative_path', '').replace('\\', '/')
    parts = path.split('/')
    if len(parts) >= 3 and parts[0].casefold() == 'acquired':
        return '/'.join(parts[:2])
    return re.sub(r'_(?:extracted|searchable)(?:_utf8)?$', '', source_group(candidate['source']))


def candidate_role(path: str, excerpt: str) -> str:
    name = path.replace('\\', '/').rsplit('/', 1)[-1].casefold()
    return 'navigation' if name in {'metadata.md', 'metadata.json', 'readme.md'} or re.match(
        r'^(?:bibliography|references|index to|table of contents)\b', excerpt, re.I
    ) else 'source_passage'


def preference_terms(profile: dict[str, Any]) -> list[str]:
    """Free-text preferences supply soft lexical probes, never a language gate."""
    return sorted({word.casefold()
                   for kind in profile['finding_preferences'].get('preferred_kinds', [])
                   for word in re.findall(r'[^\W_]{3,}', kind, re.UNICODE)})


def spread_indices(length: int) -> Iterable[int]:
    """Breadth-first interval midpoints cover every position exactly once."""
    intervals = deque([(0, length)])
    while intervals:
        start, stop = intervals.popleft()
        if start >= stop:
            continue
        middle = (start + stop) // 2
        yield middle
        intervals.extend([(start, middle), (middle + 1, stop)])


def source_round_robin(rows: list[dict[str, Any]], group: Callable) -> list[dict[str, Any]]:
    queues: dict[str, deque] = {}
    for row in rows:
        queues.setdefault(group(row), deque()).append(row)
    result = []
    while queues:
        for key in list(queues):
            result.append(queues[key].popleft())
            if not queues[key]:
                del queues[key]
    return result


def interleave(*lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reserve opportunities for each lane; an FTS score cannot drown recall."""
    queues = [deque(lane) for lane in lanes]
    result = []
    seen = set()
    while any(queues):
        for queue in queues:
            if queue:
                row = queue.popleft()
                if row['chunk_id'] not in seen:
                    result.append(row)
                    seen.add(row['chunk_id'])
    return result


def discover_sources(connection: sqlite3.Connection, profile: dict[str, Any],
                     excluded: set[str], preference_hits: set[str], group: Callable,
                     rejections: dict[str, str] | None = None,
                     paths: list[str] | None = None) -> tuple[list[dict], dict]:
    """Inventory only metadata/hashes; fetch full passages through normal context.

    Source/type/quality/technical-duplicate rules equal the existing search rules.
    A previous rejection applies only to the same chunk content hash; it never
    consumes a thematic candidate or an unexposed, context-verified passage.
    """
    rejections = rejections or {}
    documents: dict[str, list[dict]] = {}
    diagnostics: dict[str, dict] = {}
    for record in connection.execute(
        'SELECT chunk_id, source, filename, relative_path, chunk_no, source_type, '
        'text_quality, is_duplicate, text_hash FROM chunks ORDER BY relative_path, chunk_no'
    ):
        row = dict(record)
        path = row['relative_path']
        diagnostic = diagnostics.setdefault(path, dict(available=0, eligible=0, previously_exposed=0, filtered=Counter()))
        diagnostic['available'] += 1
        source = row['source'].casefold()
        reason = None
        if row['source_type'] not in profile['material_types']:
            reason = 'material_type'
        elif any(value.casefold() not in source for value in profile['include_sources']):
            reason = 'include_sources'
        elif any(value.casefold() in source for value in profile['exclude_sources']):
            reason = 'exclude_sources'
        elif row['text_quality'] != 'good':
            reason = 'quality'
        elif row['is_duplicate']:
            reason = 'technical_duplicate'
        elif paths and not any(path.startswith(prefix.replace('\\', '/')) for prefix in paths):
            reason = 'discovery_path'
        elif path.replace('\\', '/').rsplit('/', 1)[-1].casefold() in {'metadata.md', 'metadata.json', 'readme.md'}:
            reason = 'navigation_file'
        if reason:
            diagnostic['filtered'][reason] += 1
            continue
        diagnostic['eligible'] += 1
        diagnostic['previously_exposed'] += row['chunk_id'] in excluded
        documents.setdefault(path, []).append(row)

    # Identical full documents under different paths must not buy extra turns.
    # Group other representations using the same source grouping as the old lane.
    fingerprints: dict[str, str] = {}
    grouped: dict[str, dict[str, dict]] = {}
    for path, rows in documents.items():
        fingerprint = hashlib.sha256('\n'.join(row['text_hash'] for row in rows).encode()).hexdigest()
        canonical = fingerprints.setdefault(fingerprint, group(rows[0]))
        diagnostics[path]['source_group'] = canonical
        bucket = grouped.setdefault(canonical, {})
        for row in rows:
            bucket.setdefault(row['text_hash'], row)

    queues = {}
    prior_counts = Counter()
    for key, by_hash in grouped.items():
        rows = sorted(by_hash.values(), key=lambda row: (row['chunk_no'], row['relative_path']))
        prior_counts[key] = sum(row['chunk_id'] in excluded for row in rows)
        documents_in_group: dict[str, list] = {}
        for row in rows:
            documents_in_group.setdefault(row['relative_path'], []).append(row)
        document_queues = {}
        document_visits = Counter()
        for path, document in documents_in_group.items():
            document_visits[path] = sum(row['chunk_id'] in excluded for row in document)
            spread = [document[index] for index in spread_indices(len(document))]
            unseen = [row for row in spread if row['chunk_id'] not in excluded
                      and rejections.get(row['chunk_id']) != row['text_hash']]
            preferred = [row for row in unseen if row['chunk_id'] in preference_hits]
            document_queues[path] = deque(interleave(preferred, unseen))
        source_rows = []
        while any(document_queues.values()):
            for path in sorted(document_queues, key=lambda path: (document_visits[path], path)):
                if document_queues[path]:
                    source_rows.append(document_queues[path].popleft())
                    document_visits[path] += 1
        queues[key] = deque(source_rows)

    result = []
    while any(queues.values()):
        for key in sorted(queues, key=lambda key: (prior_counts[key], key)):
            if not queues[key]:
                continue
            row = queues[key].popleft()
            result.append({**row, 'rank': len(result) + 1, 'score': 0.0,
                           'matched_interests': [], 'retrieval_score': 0.0,
                           'retrieval_methods': ['source_exploration'] +
                           (['preference_lexical'] if row['chunk_id'] in preference_hits else []),
                           'discovery_source_group': key})
            prior_counts[key] += 1
    return result, dict(sources=diagnostics, source_groups=len(grouped),
                        eligible_chunks=sum(len(rows) for rows in grouped.values()),
                        preference_lexical_hits=len(preference_hits),
                        preference_semantics='Lexical hints only; scope, story kind and interest require AI review.')


def discovery_evidence(text: str, profile: dict, limit: int = 620) -> tuple[str | None, list[str]]:
    """Choose a readable paragraph, not a query-centered excerpt of an index.

    Blank paragraphs and headings work across languages. No fixed story words,
    named works, story numbers or topic translations are baked into retrieval.
    Full neighboring chunks remain mandatory and lossless in verified_context.
    """
    paragraphs = [part.strip() for part in re.split(r'\n\s*\n', text)
                  if len(part.strip()) >= 60
                  and not re.match(r'^(?:[#=|]|https?://|\[\[)', part.strip())]
    if not paragraphs:
        return None, []
    terms = preference_terms(profile)
    paragraph = max(paragraphs, key=lambda part: (sum(term in part.casefold() for term in terms),
                                                min(len(part), limit)))
    excerpt = ' '.join(paragraph.split())[:limit]
    matches = [term for term in terms if term in paragraph.casefold()]
    return excerpt, matches


def focus_evidence(text: str, profile: dict) -> str | None:
    """A target paragraph must carry a name; AI still verifies its substantive role."""
    aliases = [alias.casefold() for person in profile['focus_people'] for alias in person['aliases']]
    if re.match(r'^\s*(?:bibliography|references|index to|table of contents)\b', text, re.I):
        return None
    paragraphs = [part for part in re.split(r'\n\s*\n', text)
                  if any(alias in part.casefold() for alias in aliases)]
    for paragraph in paragraphs:
        excerpt, _ = discovery_evidence(paragraph, profile, limit=max(len(paragraph), 620))
        if not excerpt:
            continue
        positions = [excerpt.casefold().find(alias) for alias in aliases if alias in excerpt.casefold()]
        if positions:
            start = max(0, min(positions) - 200)
            return excerpt[start:start + 620]
    return None
