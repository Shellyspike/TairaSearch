# TairaSearch 0.3 semantic deduplication audit

This document records the unchanged 0.2 behaviour and proposes the next small,
testable step. The audit does not change retrieval rules, the SQLite schema,
`chunk_id`, `used_finds.csv`, or Codex automations.

Run the offline synthetic benchmark with:

```powershell
python run_dedup_audit.py --check
python -m unittest tests.test_dedup_audit -v
```

`--check` detects an unexpected change to the frozen baseline. Known mistakes
remain visible in the report; a successful exit does not declare those
decisions correct.

## Confirmed 0.2 behaviour

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

| Case | Expected | Current 0.2 result | Finding and proposed direction |
| --- | --- | --- | --- |
| `jp-01-exact-chunk-id` | confirmed repeat | `duplicate` | Correct; retain exact ID as a strong signal. |
| `jp-02-same-story-neighbouring-chunks` | confirmed repeat | `collapsed` | Correct result, unsafe reason; require claim/text overlap, not proximity alone. |
| `rome-01-distinct-neighbouring-events` | new finding | `collapsed` | False repeat; remove unconditional position/topic collapse. |
| `jp-03-paraphrase-across-books` | probable repeat | `duplicate_risk` | Correct uncertainty; pass the pair to Codex instead of discarding it. |
| `rome-02-paraphrase-across-languages` | probable repeat | `clear` | Missed repeat; compare the supported claim during editorial review. |
| `rome-03-light-ocr-correction` | confirmed repeat | `duplicate` | Correct through high text/source similarity. |
| `rome-04-heavy-ocr-and-reindex` | probable repeat | `clear` | Missed repeat after ID, OCR, and edition changes; create a review shortlist. |
| `jp-04-same-person-theme-different-event` | new finding | `duplicate` | False repeat; shared labels must not be an automatic veto. |
| `jp-05-new-interpretation-of-known-event` | new angle | `clear` | Candidate survives but its relation to the known event is lost. |
| `rome-05-repeated-interpretation` | probable repeat | `clear` | Missed cross-language repetition of a scholarly conclusion. |
| `rome-06-new-detail-about-known-event` | new angle | `clear` | Candidate survives but the additional detail is not represented as a relation. |
| `jp-06-same-person-topic-date-different-event` | new finding | `duplicate` | False repeat; entities and dates should shortlist, not decide. |
| `rome-07-same-person-topic-source-different-event` | new finding | `duplicate` | False repeat; compare action, object, and outcome. |

Baseline totals: 4 correct, 4 false repeats, 3 missed repeats, and 2 new angles
whose relation is not represented. Four of the six semantically publishable
stress cases are incorrectly suppressed. This deliberately adversarial fixture
is a regression benchmark, not an estimate of production error prevalence.

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
2. Deterministic shortlist plus Codex adjudication. **Recommended.** Python
   handles strong technical matches and exposes evidence and feature reasons;
   Codex classifies uncertain semantic relations using full context. SQLite and
   CSV remain unchanged initially.
3. A new finding registry, embeddings, or a vector database. Potentially useful
   later, but it needs migration and is not justified by this first benchmark.

Small follow-up changes should be reviewed independently:

1. Fix only within-run candidate collapsing. Nearby position and shared topics
   may create a comparison pair but must not delete the second candidate without
   substantial claim/text overlap.
2. Add transparent `dedup_review` data to search output: the matched legacy row,
   numeric features, and both excerpts. Make `duplicate_risk` visible to Codex.
3. Test a four-class Codex instruction on the demo only. Do not change active
   automations.
4. Compare results on copies of an index and existing journal before any
   production switch.
5. Only if relations must persist across runs, prepare a separate journal
   migration plan. Existing CSV rows must remain readable as legacy chunk
   references and must never be silently rewritten.

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
