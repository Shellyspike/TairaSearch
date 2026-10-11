# AI-assisted workflow

TairaSearch is a hybrid project. Its retrieval core is deterministic, while
Codex handles research and editorial work that benefits from language-model
reasoning.

## Daily historical news

1. Python queries the local SQLite FTS5 index and ranks matches with BM25.
2. `daily-five` applies source, topic, person, quality, duplicate, and diversity
   rules and retrieves neighbouring chunks.
3. A Codex automation reads those candidates and their context.
4. Codex distinguishes primary, literary, and scholarly sources, checks the
   available evidence, and writes concise cards with citations.
5. After publication, the selected findings are recorded so later runs can
   avoid repeats.

The Python command does not publish a message and does not silently update the
publication journal. Publication and editorial synthesis belong to the Codex
workflow.

## Discovery of new materials

A separate Codex automation can search public catalogues and repositories,
compare candidate sources with the existing index, inspect downloaded files,
and prepare a staging report. Staged files are not promoted into the main
corpus or indexed automatically.

## Public example versus active automation

The files in `examples/codex/` are sanitized templates that demonstrate the AI
role without exposing personal paths, thread identifiers, downloaded research
materials, or active schedules. They are not executable automation settings.

The active automation remains a user-owned local configuration and is not part
of the GitHub release.

## Index-build contract for automation

The current sanitized Codex prompts do not rebuild the index, so the new build
exit codes do not change their present behaviour. If a future automation adds
an indexing step, it must check the process exit code before retrieval:

- exit code 0 means `succeeded` and the pipeline may continue;
- exit code 1 means either `completed_with_errors` or `failed`; stop the
  automatic pipeline and inspect the final report and log;
- exit code 130 means the user interrupted the build; do not continue.

For a completed build, the exact status is also stored as `build_status` in the
SQLite `meta` table. A critical failure may happen before SQLite can be opened,
so automation must treat the process exit code as authoritative. It must not
publish cards merely because an older index remains searchable after a failed
or partially successful refresh.

## Reproducibility boundary

The sample corpus can reproduce parsing, indexing, search, context retrieval,
and candidate selection. Final prose can vary between model runs, so AI output
is demonstrated through documented inputs and expected editorial constraints,
not treated as a byte-for-byte deterministic build artifact.

