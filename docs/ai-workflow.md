# AI-assisted workflow

TairaSearch is a hybrid project. Its retrieval core is deterministic, while
Codex handles research and editorial work that benefits from language-model
reasoning.

## Profile-driven Codex research

In 0.3.1, `research-findings` is the primary retrieval tool for Codex. Python
performs FTS5/BM25 retrieval from the terms and weights in
`research_profile.json`, verifies local evidence, adds neighbouring context,
and applies the 0.3 technical and semantic-review preparation. It does not
make the final editorial choice. Codex checks the cited evidence, resolves the
four semantic classes, researches further when needed, and selects only the
supported findings.

If `research_profile.json` is missing, the ready-made prompt in
`examples/codex/research-onboarding.md` starts a short conversation about the
user's subject, interests, result language, material types, and optional
people. Codex translates the confirmed preferences into effective search
terms and weights and saves the ignored local profile. Nothing in the command
contains built-in historical characters or topics.

Codex first runs `research-findings --preview`. If source or semantic review
rejects that batch, it requests another with `--continue-from` and a new output
path. The next run excludes candidate `chunk_id` values already exposed in the
earlier JSON; it does not silently discard verified candidates that were not
shown. For source checks, neighbouring context, and indexed scholarship, Codex
may direct the existing read-only `search` and `context` commands; Python
returns passages and Codex decides what they support. Codex may make one
bounded increase to retrieval depth, then stops when it has enough strong
findings or a pass yields no new IDs. The copy-ready instructions are in
`examples/codex/research-workflow.md`.

Each run now writes two artifacts: a lossless full JSON and a compact
`*.editorial.json`. `semantic_review` links compared candidates by ID and
supported thesis rather than embedding another copy of their full neighbouring
context. Codex reads one compact overview per batch, then calls
`research-context` once with provisional finalist IDs and
`--include-required-review`. That consolidated packet restores the canonical
full context for finalists, doubtful candidates, and linked comparisons without
rerunning retrieval. If a linked comparison falls outside `final` and
`alternates`, the lossless result stores its evidence once under
`comparison_contexts`; the compact packet still carries only the reference.
The reference workflow therefore needs three file/tool
interactions per accepted batch (retrieval, one compact read, one consolidated
full-context request/read boundary) instead of printing the full payload and
performing repeated candidate-by-candidate reads. It does not cap the number of
reviewed candidates or weaken source and semantic checks.

Measure Python time and the byte sizes of both artifacts separately. A smaller
packet and fewer prescribed calls do not by themselves prove lower end-to-end
Codex time; only an isolated agent run can establish that claim.

The regression fixture (`sample_corpus`, 20-candidate batch, 20 Windows runs)
measured the following on the implementation branch versus its `main` base:

| Measure | `main` | optimized |
| --- | ---: | ---: |
| median Python process time | 235.3 ms | 237.4 ms |
| lossless full JSON | 47,813 bytes | 48,117 bytes |
| first-pass editorial packet | not available | 27,866 bytes |

The first-pass payload is 41.7% smaller than the baseline full JSON. The full
artifact remains lossless and gains artifact references, so this small fixture
does not promise that it will shrink; repeated full comparison contexts are no
longer embedded. Python time is effectively unchanged at this scale. In the
50-candidate reference interaction budget, first-pass inspection plus full
context is bounded to one compact read and one consolidated context packet,
rather than as many as 50 candidate-level full-context reads (up to 48 fewer
reads). This is a workflow bound, not a measured Codex latency result.

Preview and retrieval are read-only for `used_finds.csv`. Only an explicit
publication request crosses the existing manifest and `record-publication`
boundary. Building a new index remains a separate, explicit step: onboarding
first scans a proposed corpus and asks before creating an index. Legacy
`daily-five`, existing profiles and indexes, the publication journal, and the
AI news demo retain their contracts.

## Daily historical news

Use the saved-profile `research-findings --preview` route and matching
`examples/codex/research-workflow.md` or `.ru.md`, not legacy `daily-five`.
After research and novelty review, independently choose stories, write for a
reader unfamiliar with the setting, and follow [editorial-system.md](editorial-system.md).
A separate reviewer first reads cards without dossiers, then checks full evidence
for additions and essential omissions. Resolve remarks within three rounds and
withhold unapproved cards. This extends the agent workflow, not the CLI validator.
The author remains responsible for quality after pass.

The retrieval interaction counts above concern Python evidence handoff only;
they exclude writing, the independent agent and revision rounds. Do not treat
them as an end-to-end limit or a reason to skip literary/source checks.

Legacy `daily-five` returns up to five candidates and remains supported for
manual/demo compatibility. Old demo outputs illustrate that fixed handoff;
they are not the daily editorial standard.
An explicitly requested unregistered preview does not write the publication
journal. New publication still requires explicit authorization and the existing
record-then-render workflow described below.

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

After exit code 0, render the user-facing edition from that same immutable
manifest:

```powershell
python taira_search.py render-publication work/publications/2026-10-12.json
```

`render-publication` refuses to emit cards unless all manifest IDs are already
present in `used_finds.csv`. Its stdout contains the complete saved
`card_markdown` values and no registration summary. The agent must return that
output as the primary chat result; titles, short descriptions, counts, and
technical status are not substitutes for the edition.

The command validates the complete manifest and takes a Windows/Linux
interprocess lock around the full read, duplicate-check, and write cycle. It
atomically replaces `used_finds.csv` only after the new CSV has been written
successfully. Existing rows and the CSV schema are retained, and rerunning the
same manifest does not create duplicates. Publish the cards only after exit
code 0. That exit confirms journal registration, not delivery to chat. If
journal writing fails, keep the unchanged manifest, report the actionable
error once, do not render the cards, and avoid repeated diagnostics inside the
daily run. If chat delivery fails after the journal update, check run/chat
history and run `render-publication` against the same manifest; do not search
again, rewrite the cards, or create a new registration. Idempotent retry of the
same manifest still skips already registered IDs, but it is unnecessary for
recovery. The unchanged local JSON contains the exact cards needed for
recovery.

Publication state is deliberately split into three parts:

1. **Prepared** — a valid manifest durably stores every complete card.
2. **Registered** — every manifest card ID is present in the journal.
3. **Delivered** — the complete rendered edition is visible in the user-facing
   task or chat result.

`publication-status` can verify the first two states and reports delivery as
`unconfirmed`. The local process receives no acknowledgement that Codex
displayed a response, so it must not write a synthetic delivered flag or
promise exactly-once delivery. When history is ambiguous, recovery requires a
human decision because replaying the manifest can display the edition twice.

A scheduled personal edition must use a result surface capable of returning
the full Markdown. A status-only heartbeat or notification envelope is not
compatible: detect that before registration and move the workflow to a normal
standalone scheduled-task result. The OpenAI documentation describes the
[Scheduled view](https://developers.openai.com/training/walkthroughs/scheduled-tasks)
as the place to review completed run history, but it does not expose a
delivery receipt that the local TairaSearch CLI can record.
Publication manifests and lock files are runtime data and must never be added
to the public release allowlist.

Before activating a scheduled publisher, run `check-publication-access` in the
scheduled task's effective environment. It verifies read-only SQLite access and
disposable create-plus-atomic-rename access beside the journal without touching
the journal or lock. An interactive test or `config.toml` entry is not a
substitute for effective writable roots in the scheduled process. Recovery and
the Windows split-writable-root error are documented in `development.md` and
the onboarding guide.

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

The complete English and Russian walkthroughs are in [ai-demo.md](ai-demo.md)
and [ai-demo.ru.md](ai-demo.ru.md). Their primary route is one Codex app chat
that runs Python, reads the generated handoff, and writes the demonstration
cards. A separate `codex exec` process is documented only as an optional
alternative. Both routes use committed inputs and example outputs and do not
depend on an active automation or previous conversation.




## Scope and person review

See `docs/retrieval-discovery.md`. The whole candidate_pool (final + alternates)
is unreviewed; retrieval_excerpt is raw evidence, not a story. Resolve scope_review
as accepted, rejected or uncertain with a reason and exact quotations before
novelty and editorial selection. Reject out-of-area or uncertain passages.
For focused_people, identify a selected person and verify a substantive connection
to the action, not just their name. Preserve the profile's mode and preferred_kinds.
New manifests carry root search_mode and focus_people (names), and each card has
scope_review: status=accepted, reason, evidence (chunk_id/quote objects), plus
focus_person in person mode. Pending/uncertain cannot be published. Legacy
manifests remain unchanged. coverage.discovery explains source omissions;
continuation advances through document positions instead of repeating FTS tops.
