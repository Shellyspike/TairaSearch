# AI-assisted workflow

TairaSearch is a hybrid project. Its retrieval core is deterministic, while
Codex handles research and editorial work that benefits from language-model
reasoning.

## Daily historical news

1. Python queries the local SQLite FTS5 index and ranks matches with BM25.
2. `daily-five` applies source, topic, person, quality, duplicate, and diversity
   rules, retrieves neighbouring chunks, and returns up to five candidates.
3. If it returns one to five candidates, a Codex automation reads those
   candidates and their context. Zero candidates is a successful empty result:
   no cards or publication manifest are created and the journal is unchanged.
4. Codex distinguishes primary, literary, and scholarly sources, checks the
   available evidence, and writes concise cards with citations.
5. Codex saves the exact finalized cards to a local publication manifest and
   asks Python to record those selected findings before returning the cards in
   chat. Later runs can then avoid repeats.

The Python retrieval command does not publish a message or silently update the
publication journal. Publication and editorial synthesis belong to the Codex
workflow. The separate `record-publication` command is the explicit boundary
between finalized editorial output and the local journal.

An empty result means that no new finding passed the current filters; it does
not establish that the corpus contains no other material. Search, index,
configuration, and data-reading errors remain failures with a non-zero exit
code and must not be converted into an empty news batch.

## Publication journal and recovery

Before publication, save the complete finalized batch under the ignored
`work/` directory, for example `work/publications/2026-10-12.json`. The JSON
must contain a `publication_id` and a non-empty `cards` array. Every card must
contain `id` or `chunk_id`, `type` (`event` or `interpretation`), `persons`,
`topics`, `short_description`, `source`, and the exact final text in
`card_markdown`.

Then run:

```powershell
python taira_search.py record-publication work/publications/2026-10-12.json
```

The command validates the complete manifest and atomically replaces
`used_finds.csv` only after the new CSV has been written successfully. Existing
rows and the CSV schema are retained, and rerunning the same manifest does not
create duplicates. Publish the cards only after exit code 0. If journal writing
fails, or if chat delivery fails after the journal update, the unchanged local
JSON contains the exact cards needed for a retry. Publication manifests are
runtime data and must never be added to the public release allowlist.

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

The complete public walkthrough is in [ai-demo.md](ai-demo.md). Its primary
route is one Codex app chat that runs Python, reads the generated handoff, and
writes the demonstration cards. An ephemeral, read-only `codex exec` command
is documented only as an optional alternative. Both routes use a committed
input and example output and do not depend on an active automation or previous
conversation.

