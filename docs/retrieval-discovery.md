# Source exploration and search modes

Thematic FTS is one recall route, not the definition of a worthwhile story.
Unknown actors and ordinary incidents often contain none of a profile's terms.
Both routes produce **unreviewed leads**, never automatically accepted stories.

## Profile and onboarding

New profiles explicitly save `search_mode`:

- `open`: discover passages across the permitted library, including unnamed
  people. Focus people receive a selection bonus, not an eligibility requirement.
- `focused_people`: a readable target paragraph must contain a configured alias.
  Bibliographies and names found only in neighbouring chunks do not qualify.
  The AI must then verify that a selected person is substantively involved;
  presence of a name is not proof of the relationship.

An explicit focused mode without `focus_people` fails with an instruction to
choose people through the agent. Switching modes edits only the confirmed
profile, needs no index rebuild, and starts a new preview/continuation chain.
Do not change an active user's profile or automation without consent.

Compatibility: an absent mode preserves the old `include_unlisted_people`
policy (`true` → open, `false` → selected people when present). The loader does
not insert a field or rewrite a file. The legacy empty-people/false combination
keeps thematic-only behaviour until the user chooses a mode. Explicit mode wins
over the deprecated boolean. Existing continuation still validates the entire
normalized profile; changing modes cannot reuse an old chain silently.

## Discovery algorithm

1. Retain weighted FTS retrieval by interests and its top-per-interest budget.
2. Inventory eligible chunk metadata/hashes read-only, independently of FTS.
   Apply material types, source include/exclude, good quality and technical
   duplicate filtering. Preserve the existing include-source AND semantics;
   excludes win. Do not reinterpret those existing filters during this change.
3. Group acquired works separately instead of treating all `acquired/` books
   as one source. Identical document hash sequences share a turn, and equal
   chunks within a work are not additional opportunities.
4. Within each document, visit interval midpoints breadth first: middle,
   quarters, eighths, and so on. This deterministic finite traversal reaches
   every eligible position without favouring chapter one. Across sources,
   prefer those with fewer already exposed positions and take turns.
5. `preferred_kinds` supplies soft FTS probes using words extracted from the
   user's free text. Within a source, alternate lexical hits with spread
   exploration. Report actual probe hits and excerpt matches. There is no
   hardcoded list of story words, named collections or story numbers.
   **Lexical hints are not semantic preference understanding**: Russian wishes
   may have no lexical overlap with Japanese evidence. Uniform exploration still
   runs; the AI applies the actual preferences to full evidence.
6. Interleave thematic and discovery opportunities within both the work pool
   and the emitted batch. Resume the route turn for single-slot batches.
   A high thematic score cannot consume every discovery slot. Unused route
   capacity passes to the other route. Context/evidence/OCR/person rules and
   semantic duplicate review still apply before emission.

Discovery chooses a readable paragraph rather than centering every excerpt on
a famous name. The full target and neighbours are stored unchanged, with IDs,
pages and source positions. No thematic match means `primary_topic: null`, not
an invented interest assignment. `scope_review.status: pending` explicitly
requires the agent to reject unrelated and uncertain passages. The library can
contain material outside the profile: exploration is permission to **inspect**,
not permission to publish it.

## Continuation, scope and boundedness

Existing exposed-ID/exact-collapse continuation remains supported. A versioned
discovery supplement remembers route turns and pre-editorial rejections with
their text hashes. A rejected target does not repeatedly consume discovery
budget; changed content becomes eligible again. This state never suppresses a
thematic candidate. Verified but unexposed passages remain eligible and only
targets count as visits, not neighbouring evidence. Unknown/corrupt state
versions fail visibly. On an evolving index positional order can change; this
is a live read-only view, not a claim of snapshot continuity across runs.
One invocation uses a consistent read transaction and follows committed WAL.
Old schemas fail without migration; explicit indexing is a separate operation.

The per-invocation context budget remains `pool_size`, and output remains
`batch_size`. Metadata inventory is linear in library size; only the bounded
pool loads full contexts. Larger libraries require more batches: neither one
preview nor a daily edition promises every story. There is no special quota
for any named work.

For a source audit the agent may use repeated `--discovery-path PREFIX` options
(relative paths, OR semantics). This only narrows the exploration route and
never overrides profile filters; ordinary thematic retrieval remains active.
Continue with the same prefixes, or start a new chain. It is a manual inspection
tool, not a persistent rule requiring a book in every edition.

## Handoff, publication and diagnostics

Full and compact candidates carry `retrieval` methods/reason/preference hints,
`scope_review`, source, chunk ID and a reference to the lossless context.
The compact profile carries mode, people and preferred kinds. Raw excerpts
remain unreviewed, regardless of the legacy `final`/`alternates` section name.

Before editorial acceptance, the agent records evidence for research-area scope,
and in person mode a selected person's substantive role. This is separate from
source verification, novelty and reader interest. New mode-aware publication
manifests save root `search_mode` and `focus_people` (names), and per-card:

```json
{
  "scope_review": {
    "status": "accepted",
    "reason": "Evidence-based scope decision by the researcher",
    "focus_person": "Selected person, required only for focused_people",
    "evidence": [{"chunk_id": "ch_example", "quote": "Exact source quotation"}]
  }
}
```

The publication validator rejects pending/uncertain scope and missing evidence
before taking the journal lock; person mode also requires a selected name.
It checks the contract, not the historical truth of the AI's judgment. Legacy
manifests omit the mode and still record/render identically, without rewriting.

`coverage.retrieval_methods` counts checked/emitted candidates per route
(overlaps counted in each). `coverage.discovery` lists every indexed path's
available/eligible counts, filter reasons, source group, checked/emitted
counts, emitted positions and omission reason. No lexical hits is not an empty
library. A source may be absent due to hard filters, duplicate representation,
context rejection or the current bounded schedule; continue or inspect that
source explicitly. These are recall diagnostics, not proof of story quality or
complete topical coverage.

The regression suite uses synthetic incidents, people, source bans, large and
small books, multilingual preferences and mode switching. Real-library audit
artifacts belong under ignored `work/` and must never enter a PR or release.
