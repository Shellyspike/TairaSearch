# TairaSearch 0.1 roadmap

This roadmap keeps the local deterministic search pipeline and the real Codex
workflow visible as two cooperating parts of the project.

## Release 0.1

- [x] Build public archives from an exact allowlist and test them for private or
  generated data.
- [x] Pin the PDF dependency, validate it before opening the index, distinguish
  unreadable PDFs from PDFs without a text layer, and cover the failure modes
  with tests.
- [x] Preserve the last successfully indexed chunks and metadata when any
  document fails during a later incremental run.
- [x] Give successful, partially successful, interrupted, and failed builds
  truthful statuses and make recovery behaviour explicit.
- [x] Save the exact finalized cards locally and make publication-journal
  updates minimal, atomic, and idempotent before a Codex automation publishes
  them.
- [x] Complete allowlisted ZIP packaging, the small CI workflow, MIT licensing,
  and the reproducible public demo documentation.

Production migration remains separate from the public release and must first
be tested against a copy of the corpus and index.

## Post-0.1

- [ ] Add an optional missing-document cleanup command with a mandatory
  preview. Ordinary indexing and `--rebuild` intentionally never prune unseen
  files.

## Reproducible AI demonstration

After the reliability milestones, add a documented demonstration that uses the
public test corpus and the sanitized prompts already in `examples/codex/`:

1. build the SQLite FTS5 index;
2. retrieve and select candidates with the Python tools;
3. pass the retrieved source context to Codex using the documented automation
   prompts;
4. analyse and cross-check the sources in Codex;
5. produce five example news cards with source references.

Steps 1 and 2 now have an offline, one-command fixture in `run_demo.py`, backed
by multilingual golden results. Steps 3–5 are documented in `docs/ai-demo.md`
and include a stable Codex handoff, a one-request Codex app workflow, an
optional read-only CLI command, and a saved five-card example. The live prose
remains variable and human-reviewed; no API or multi-agent framework was added.

The demonstration should explain the boundary between deterministic Python and
Codex, and provide fixtures or redacted example outputs where an automation
cannot be executed by a repository checkout alone. It does not require an
OpenAI API rewrite or a separate multi-agent framework.

## Public-release environment check

Before the public release, verify standard Windows `venv` creation and command
execution outside the current Codex sandbox. On the current development host
the sandbox resolves the environment's `python.exe` to the base interpreter
even with a valid `pyvenv.cfg`; a short ASCII path produces the same result.
The documentation therefore uses a fail-fast prefix check and does not present
this as a general Windows or non-ASCII-path defect.
