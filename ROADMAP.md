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

## Compatibility research after onboarding

- [ ] Design content versioning without changing the current position-based
  `chunk_id` format prematurely.
- [ ] Evaluate semantic deduplication that can distinguish an OCR correction of
  the same episode from a genuinely new finding.
- [ ] Define migration and backward compatibility for existing
  `used_finds.csv` histories before adopting any new identifier.
- [ ] Add an explicit missing-document cleanup command with a mandatory
  preview. Ordinary indexing and `--rebuild` must continue to preserve unseen
  documents.
- [ ] Add retrieval/editorial quality fixtures and repeatable human review
  criteria; do not treat variable model prose as a byte-for-byte artifact.

Production migration remains separate from public development. Any switch must
first be tested against copies of the corpus and index, comparing document
membership and search availability before and after the change.
