# Universal research onboarding through Codex

[Русская версия](research-onboarding.ru.md)

TairaSearch 0.2 adds a local research profile on top of the existing FTS5
index. It does not change the SQLite schema, `chunk_id`, legacy `daily-five`,
or `used_finds.csv`.

## Start without editing configuration

1. Download the project and prepare `.venv` as described in
   [README.md](../README.md).
2. Open the folder in the Codex desktop app.
3. Paste the complete
   [`examples/codex/research-onboarding.md`](../examples/codex/research-onboarding.md)
   request.
4. Provide an existing index or corpus folder and answer a few plain-language
   questions about your interests.
5. Review the preview findings and describe any preference change naturally.

The user never edits configuration. After confirming its interpretation,
Codex saves an ignored local `research_profile.json`.
The two committed examples in [`examples/profiles/`](../examples/profiles/)
show the exact schema; they are test fixtures, not profiles the user must edit.

## Profile contents

The profile is a small auditable JSON containing:

- research area and result language;
- named interests with confirmed search terms;
- optional focus people and name variants;
- material types;
- preferred kinds of findings and diversity preferences;
- a result count from one to twenty, with five as the default.

Only fields used by retrieval change the results. Codex must translate a
free-form preference into confirmed `interests[].terms`, an interest `weight`,
material types, or source filters as appropriate. `finding_preferences.notes`
is explanatory metadata and does not affect ranking or filtering; saving a
request only in `notes` does not apply it.

The profile does not rewrite index annotations. New names and topics become
direct FTS queries over stored text, so a preview does not require reindexing.
Adding new metadata annotations for other CLI commands would be a separate
production migration and is outside this feature.

## Safe first index

An existing index is opened read-only. If the user has only a corpus folder,
Codex first runs a non-mutating scan:

```powershell
.venv\Scripts\python build_index.py "CORPUS_PATH" --scan-only
```

Only after confirmation does Codex create a new index under `work/`. It never
uses `--rebuild` on an existing user database. Temporarily missing documents
are not automatically removed.

## Preview selection

A representative command is:

```powershell
.venv\Scripts\python taira_search.py research-findings --db work/research/index.sqlite3 --profile research_profile.json --used-finds used_finds.csv --output work/research/candidates.json --preview
```

`--preview` never appends to the publication journal. In fact,
`research-findings` only reads `used_finds.csv`; publication remains a separate
explicit operation. Its JSON includes neighbouring context and a coverage
report for preferences that produced no indexed hit.

Codex applies feedback by updating the profile and rerunning the preview. A
request such as “less military material” changes interests and weights, not
Python code or only the explanatory `notes` field.

## Later manual runs

The saved profile can be reused with the same `research-findings` command.
Omit `--preview` only when the selection is intended for the normal editorial
workflow. Candidate retrieval still only reads `used_finds.csv`; it does not
publish or append to the journal. Codex may then apply the full editorial
workflow from `examples/codex/daily-news-prompt.md`, save the finalized cards
to a recovery manifest under `work/`, and call `record-publication` exactly as
described in [ai-workflow.md](ai-workflow.md). One to the configured maximum
number of strong results is valid; an empty selection is also valid. Search,
index, and data-reading failures remain errors.

This is a manual workflow. Version 0.2 does not create a schedule or alter any
existing Codex automation.

## Two reproducible scenarios

```powershell
.venv\Scripts\python run_research_demo.py
```

The `japan` scenario uses the existing synthetic corpus and names Taira,
Yoshitsune, and Zeami as interests without excluding other people. Its coverage
report honestly identifies names that were not found. The `rome` scenario uses
a separate synthetic Roman corpus and no predefined person at all. Generated
files stay under `work/research-demo/`.
