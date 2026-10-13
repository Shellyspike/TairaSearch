# TairaSearch 0.3 semantic deduplication audit

This document preserves the measured 0.2 behaviour and records the implemented
0.3 correction. The SQLite schema, `chunk_id`, `used_finds.csv`, and active
Codex automations remain unchanged.

Run the offline synthetic benchmark with:

```powershell
python run_dedup_audit.py --check
python -m unittest tests.test_dedup_audit -v
```

`--check` validates both the frozen historical baseline and the separately
declared current expectations. It never rewrites the baseline to make a code
change pass.

## Frozen 0.2 behaviour

- `text_utils.stable_chunk_id()` hashes the relative path, page range, and
  chunk number. It is a location identifier, not a text or finding identifier.
- `build_index.py` detects only exact duplicates of `text_hash` plus
  `normalized_text`. OCR corrections, paraphrases, and translations differ.
- `daily_five.load_used_finds()` compares ID, people, topics, summary, and
  source; the saved `event`/`interpretation` type is not retained for matching.
- `daily_five.duplicate_check()` treats an exact chunk ID as a duplicate. It
  otherwise adds lexical similarity and fixed bonuses for shared people,
  topics, source group, and a limited date pattern. Thresholds are `0.78` for
  `duplicate` and `0.52` for `duplicate_risk`.
- Generic dates such as `80 CE` can be extracted during research retrieval but
  are not recognised by the publication-history comparison.
- `source_group()` has aliases for a few Japanese works. Other editions,
  translations, or alternative titles group only when their strings match.
- `research_findings._collapse_candidates()` drops nearby chunks from the same
  file when they merely share a topic. This can remove distinct events.
- Final selection accepts only `clear`; `duplicate_risk` is not preserved as an
  uncertainty for Codex.
- The publication journal is atomic and idempotent by ID, but that ID is the
  position-based chunk ID. After reindexing, only summary heuristics connect a
  finding to its old row.

## Implemented 0.3 behaviour

- `candidate_pair_check()` collapses only an exact `chunk_id` or near-identical
  evidence in the same source scope. Proximity and a shared topic now create a
  review relation instead of deleting either candidate. Both `daily_five` and
  `research_findings` use the same rule.
- Publication-history matching auto-excludes only an exact `chunk_id` or exact
  normalized published claim. Person, topic, date, source, OCR-like text
  similarity, and source-name similarity can shortlist a match but never
  confirm it by accumulating label bonuses.
- Every retained candidate can carry a bounded `semantic_review` packet with
  matched journal rows, comparable candidates, feature reasons, evidence
  locators, and the available context. `duplicate_risk` remains eligible for
  selection rather than disappearing before editorial review.
- Scholarship is marked as a possible new angle, not automatically novel. The
  public Codex prompt must compare the actual conclusion and choose one of the
  four semantic classes below.
- Python still makes reproducible technical decisions. Codex decides semantic
  identity when OCR, reindexing, paraphrase, translation, or a possible new
  interpretation leaves reasonable uncertainty.

## Semantic decision rules

| Class | Meaning | Action |
| --- | --- | --- |
| `confirmed_repeat` | The same event or scholarly conclusion, with no meaningful supported addition and strong matching evidence. | Suppress with a visible reason. |
| `probable_repeat_review` | The core claim appears the same, but OCR, translation, edition, or limited context prevents certainty. | Preserve both excerpts for Codex review. |
| `new_angle` | A known event gains a supported material detail, different outcome, or independent scholarly conclusion. | Keep and record the relation to the known finding. |
| `new_finding` | The action, object, outcome, or context differs. Shared names, topics, or dates are insufficient. | Keep as a normal candidate. |

For scholarship, the finding is the paper's conclusion, not merely its
publication. A later paper repeating the conclusion is a repeat; a supported
argument that changes the interpretation is a new angle. When deterministic
rules cannot decide, Python must retain the uncertainty for Codex.

## Reproducible benchmark

The 13 fictional Japan and Rome cases live in
`examples/dedup-benchmark/cases.json`.

| Case | Expected | 0.2 baseline | Current branch | Current assessment |
| --- | --- | --- | --- | --- |
| `jp-01-exact-chunk-id` | confirmed repeat | `duplicate` | `duplicate` | correct technical exclusion |
| `jp-02-same-story-neighbouring-chunks` | confirmed repeat | `collapsed` | `kept_for_review` | underconfident; Codex receives both excerpts |
| `rome-01-distinct-neighbouring-events` | new finding | `collapsed` | `kept_for_review` | false collapse removed |
| `jp-03-paraphrase-across-books` | probable repeat | `duplicate_risk` | `kept_for_review` | correct handoff |
| `rome-02-paraphrase-across-languages` | probable repeat | `clear` | `kept_for_review` | cross-language review surfaced |
| `rome-03-light-ocr-correction` | confirmed repeat | `duplicate` | `kept_for_review` | deliberately conservative |
| `rome-04-heavy-ocr-and-reindex` | probable repeat | `clear` | `kept_for_review` | OCR/reindex review surfaced |
| `jp-04-same-person-theme-different-event` | new finding | `duplicate` | `kept_for_review` | false history veto removed |
| `jp-05-new-interpretation-of-known-event` | new angle | `clear` | `kept_for_review` | possible new angle represented |
| `rome-05-repeated-interpretation` | probable repeat | `clear` | `kept_for_review` | conclusion comparison requested |
| `rome-06-new-detail-about-known-event` | new angle | `clear` | `kept_for_review` | added detail represented |
| `jp-06-same-person-topic-date-different-event` | new finding | `duplicate` | `kept_for_review` | false history veto removed |
| `rome-07-same-person-topic-source-different-event` | new finding | `duplicate` | `kept_for_review` | false history veto removed |

Baseline totals: 4 correct, 4 false repeats, 3 missed repeats, and 2 new angles
whose relation is not represented. Current totals: 5 correct technical or
review handoffs, 4 new findings preserved for review, 2 new angles pending
review, and 2 confirmed repeats handled conservatively rather than suppressed.
No known new finding in the fixture is automatically removed. This deliberately
adversarial fixture is a regression benchmark, not an estimate of production
error prevalence.

## Identity layers

| Layer | Current representation | Decision for the next step |
| --- | --- | --- |
| Document | Relative path and source string | Do not add an ID yet; evaluate a document fingerprint later. |
| Content version | Per-chunk `text_hash` | Keep for technical change detection; do not introduce document versions yet. |
| Fragment | Positional `chunk_id` plus exact content hash | Use both signals; do not replace `chunk_id`. |
| Historical finding | No separate entity; CSV ID is the chunk ID | Useful eventually, but only after the no-migration approach is measured. |
| Relation to an older finding | Not stored structurally | First expose it in review output; plan persistence separately if justified. |

Treat `chunk_id` as an evidence locator, not as a permanent event identifier.
Changing it now would break compatibility without solving semantic identity.

## Minimal design choice

Three options were compared:

1. Retune weights and thresholds. Cheap, but the same shared-label features
   cause false repeats while translations and OCR still cause misses.
2. Deterministic shortlist plus Codex adjudication. **Implemented.** Python
   handles strong technical matches and exposes evidence and feature reasons;
   Codex classifies uncertain semantic relations using full context. SQLite and
   CSV remain unchanged initially.
3. A new finding registry, embeddings, or a vector database. Potentially useful
   later, but it needs migration and is not justified by this first benchmark.

The first three small changes are implemented independently: conservative
within-run collapsing, transparent `semantic_review` data, and a four-class
public editorial prompt. Active automations were not changed.

Before any production switch, run the branch on copies of the index and journal
and compare selected IDs and search accessibility. Persistent relations between
findings remain a separate future migration: existing CSV rows must remain
readable as legacy chunk references and must never be silently rewritten.

## Remaining limitations

- Python does not understand historical meaning. It deliberately produces some
  underconfident review pairs, including near-identical OCR cases.
- Cross-language discovery relies on available shared metadata or other weak
  signals; unrelated records with only a broad topic can create review noise,
  while a translation with no shared signal can still be missed.
- A journal row stores only its published summary, not the original full
  evidence. Codex can compare that summary with current context but cannot
  reconstruct evidence that was never saved.
- The four-class decision is present in public prompt instructions, not enforced
  by a model API or persisted in SQLite/CSV. Human review remains required.
- Current benchmark expectations validate candidate preservation and handoff;
  they do not claim deterministic semantic classification by Python.

## Small card-quality rubric

Codex scores each criterion `0–2` and cites the supporting evidence:

| Criterion | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Novelty | unsupported repetition | new angle on known material | distinct finding or substantial conclusion |
| Substance | only a topic/mention | an action or claim is present | action, participants, and consequence/meaning are clear |
| Reliability | unsupported assertion | supported with caveats | source type and fact/inference boundary are explicit |
| Specificity | generic wording | some verifiable detail | who/what/where/when is as concrete as the source permits |
| Reader interest | search-process summary | understandable detail | human story, conflict, or idea without invented drama |

Hard gates override the total: every card needs a verifiable fragment link;
historical or scholarly uncertainty must remain uncertainty; zero reliability or
specificity requires revision or rejection. `7/10` is a trial threshold to
calibrate on reviewed cards, not a substitute for editorial judgement.

Python remains responsible for reproducible retrieval and transparent technical
rules. Codex remains responsible for semantic and editorial decisions when the
evidence is genuinely uncertain.
