# TairaSearch roadmap

TairaSearch keeps deterministic local retrieval and Codex editorial reasoning
as two visible, separately testable parts.

## 0.1 — published foundation

- [x] Exact public-release allowlist and leak checks.
- [x] PDF dependency diagnostics and recovery-safe document replacement.
- [x] Truthful build statuses and non-zero exits for processing failures.
- [x] Offline multilingual corpus, five-candidate demo, and Codex walkthrough.
- [x] Atomic, idempotent CSV journal update from durable card JSON.
- [x] Python 3.11 Windows/Linux CI, README, and MIT licence.

## 0.1.1 — independent-review fixes

- [x] Read-only SQLite search that follows committed WAL updates instead of
  treating a mutable index as immutable.
- [x] Windows/Linux interprocess locking for the complete publication-journal
  read/check/write cycle.
- [x] One-request Codex app quick starts in Russian and English.
- [x] Richer synthetic event and scholarship fixtures plus improved AI cards.
- [x] Editorial prompts that favour supported human-scale stories and clearly
  separate source report, literary narrative, scholarship, and inference.
- [ ] Review the separate daily-automation proposal on real open-source
  material before changing any active automation.

## 0.2 — universal research onboarding

- [x] Add a local, ignored research profile created and updated by Codex after
  a short natural-language interview.
- [x] Add profile-driven retrieval that reuses FTS5, context, diversity, and
  publication-history checks without changing the SQLite schema or `chunk_id`.
- [x] Keep legacy `daily-five`, presentation cards, CLI contracts, and the AI
  demo unchanged.
- [x] Demonstrate medieval Japan and Ancient Rome, including a profile with no
  predefined people.
- [x] Keep preview selections read-only with respect to `used_finds.csv`.

## 0.3 — semantic deduplication and editorial quality

- [x] Audit document, content, fragment, and finding identity without changing
  the current position-based `chunk_id` format.
- [x] Freeze a synthetic Japan/Rome benchmark covering false repeats,
  paraphrases, OCR corrections, reindexing, scholarship, and new angles.
- [x] Define a small evidence-based card-quality rubric and a four-class
  semantic decision model for Python/Codex review.
- [x] Replace proximity-only candidate collapsing with a conservative,
  explainable comparison, as a separate reviewed change.
- [x] Preserve uncertain matches for Codex instead of silently excluding every
  `duplicate_risk`, without changing active automations.
- [x] Teach the public editorial prompt to classify supplied comparisons as a
  confirmed repeat, probable repeat needing review, new angle, or new finding.
- [ ] Define migration and backward compatibility for existing
  `used_finds.csv` histories before adopting any persistent finding identifier.
- [ ] Add an explicit missing-document cleanup command with a mandatory
  preview. Ordinary indexing and `--rebuild` must continue to preserve unseen
  documents.
- [ ] Calibrate retrieval and editorial decisions on reviewed open-material
  examples; do not treat variable model prose as a byte-for-byte artifact.

## 0.3.1 — Codex-controlled research continuation

- [x] Make profile-driven `research-findings` the primary retrieval tool for
  Codex while retaining legacy `daily-five` unchanged.
- [x] Let Codex request disjoint later batches with `--continue-from` after
  source or semantic review rejects earlier candidates.
- [x] Keep final selection with Codex and source evidence with each Python
  candidate; treat Python `final` as a shortlist rather than a verdict.
- [x] Route a missing local profile to the existing conversational onboarding
  flow, without built-in people or historical topics.
- [x] Preserve the 0.3 semantic-review classes and the existing explicit,
  recovery-safe publication-journal boundary.

## 0.4 — automatic acquisition of new materials

- [ ] Prepare a separately reviewed, opt-in plan for discovering and downloading
  new permitted public materials, with source provenance, reuse of previously
  processed documents, failure recovery, and strict separation from the private
  local corpus. Implementation has not started.

Production migration remains separate from public development. Any switch must
first be tested against copies of the corpus and index, comparing document
membership and search availability before and after the change.
