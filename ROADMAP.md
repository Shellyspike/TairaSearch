# TairaSearch 0.1 roadmap

This roadmap keeps the local deterministic search pipeline and the real Codex
workflow visible as two cooperating parts of the project.

## Release 0.1

- [x] Build public archives from an exact allowlist and test them for private or
  generated data.
- [x] Pin the PDF dependency, validate it before opening the index, distinguish
  unreadable PDFs from PDFs without a text layer, and cover the failure modes
  with tests.
- [ ] Preserve the last successfully indexed chunks and metadata when any
  document fails during a later incremental run.
- [ ] Give interrupted and failed builds truthful persisted statuses and make
  recovery behaviour explicit.
- [ ] Make publication-journal updates minimal, atomic, and idempotent after a
  Codex automation has successfully published a card.
- [ ] Complete packaging, the small CI workflow, licence selection, and the
  reproducible public demo documentation.

Each unfinished item is a separate, reviewable change. Production migration
must first be tested against a copy of the corpus and index.

## Reproducible AI demonstration

After the reliability milestones, add a documented demonstration that uses the
public test corpus and the sanitized prompts already in `examples/codex/`:

1. build the SQLite FTS5 index;
2. retrieve and select candidates with the Python tools;
3. pass the retrieved source context to Codex using the documented automation
   prompts;
4. analyse and cross-check the sources in Codex;
5. produce five example news cards with source references.

The demonstration should explain the boundary between deterministic Python and
Codex, and provide fixtures or redacted example outputs where an automation
cannot be executed by a repository checkout alone. It does not require an
OpenAI API rewrite or a separate multi-agent framework.
