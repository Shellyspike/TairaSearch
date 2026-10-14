# Universal research onboarding through Codex

[Русская версия](research-onboarding.ru.md)

TairaSearch 0.3.1 uses a local research profile on top of the existing FTS5
index. It does not change the SQLite schema, `chunk_id`, legacy `daily-five`,
or `used_finds.csv`.

## Start without editing configuration

1. Download the project and prepare `.venv` as described in
   [README.md](../README.md).
2. Open the folder in the Codex desktop app.
3. Paste the complete
   [`examples/codex/research-onboarding.md`](../examples/codex/research-onboarding.md)
   request.
4. Answer a few plain-language questions about your interests, then choose a
   material source: a document folder, a ready index, or help finding open
   sources.
5. After the library is ready, review the preview findings and describe any
   preference change naturally.

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
- preferred kinds of findings, diversity preferences, and editorial style;
- a result count from one to twenty, with five as the default.

Only fields used by retrieval change the results. Codex must translate a
free-form preference into confirmed `interests[].terms`, an interest `weight`,
material types, or source filters as appropriate. `finding_preferences.notes`
does not affect ranking or filtering, so it cannot be the only place for a
preference that should alter retrieval. It can store purely editorial choices,
such as vivid, expanded cards; the supplied Codex workflow reads and applies
those choices when writing the result.

The profile does not rewrite index annotations. New names and topics become
direct FTS queries over stored text, so a preview does not require reindexing.
Adding new metadata annotations for other CLI commands would be a separate
production migration and is outside this feature.

## Choose a material source

After the interests are confirmed, Codex offers three choices.

### 1. Document folder

Codex asks for the path and first runs a non-mutating scan:

```powershell
.venv\Scripts\python build_index.py "CORPUS_PATH" --scan-only
```

`--scan-only` reports supported files without reading their contents or
creating SQLite. Only after separate confirmation does the existing indexer
create a new database under `work/`. It never uses `--rebuild` on an existing
user database. Temporarily missing documents are not automatically removed.

### 2. Ready index

Codex asks for its path and opens it read-only. It does not rebuild the corpus
or automatically repair or migrate an incompatible file. Access failures stay
visible, after which the user can select another index or a document folder.

### 3. No materials yet

When web search, a browser, or catalogue tools are available, Codex finds a
small set of suitable open sources for the confirmed profile. Before any
download it shows each owner or repository, URL, format, stated reuse terms,
and expected relevance. The user explicitly selects and authorizes concrete
sources. Files are saved only to a local folder under `work/`; Codex then runs
`--scan-only` and asks separately before indexing.

If the required tools are unavailable, Codex says that it cannot search or
download in the current session and asks the user to return with a folder or a
ready index. Onboarding does not start continuous acquisition; automatic
library growth remains a 0.4 feature.

## Preview selection

A representative command is:

```powershell
.venv\Scripts\python taira_search.py research-findings --db work/research/index.sqlite3 --profile research_profile.json --used-finds used_finds.csv --output work/research/candidates.json --preview
```

`--preview` never appends to the publication journal. In fact,
`research-findings` only reads `used_finds.csv`; publication remains a separate
explicit operation. Its JSON includes neighbouring context and a coverage
report for preferences that produced no indexed hit. Its `final` field is a
Python shortlist, not a final editorial verdict; Codex also inspects
`alternates` and `semantic_review` evidence.

Codex applies feedback by updating the profile and rerunning the preview. A
request such as “less military material” changes interests and weights, not
Python code or only the explanatory `notes` field.

## Continue after editorial rejection

If Codex rejects the first batch after checking the sources or semantic
novelty, it requests a disjoint next batch instead of stopping:

```powershell
.venv\Scripts\python taira_search.py research-findings --db work/research/index.sqlite3 --profile research_profile.json --used-finds used_finds.csv --output work/research/candidates-2.json --preview --continue-from work/research/candidates.json
```

The previous JSON records exposed `chunk_id` values and only confirmed exact
technical collapses. `--continue-from` excludes those while leaving
pre-editorial rejects and context-only chunks available: they may become useful
at another retrieval depth. It can be repeated for further batches. If the
current retrieval depth is exhausted, Codex may make one bounded run with a
larger `--top-per-interest` or `--pool-size`, without changing the profile. An
empty batch is not an index error, and an index or data-reading error must not
be presented as an empty result.

## Later manual runs

The saved profile can be reused with the same `research-findings` command.
Omit `--preview` only when the selection is intended for the normal editorial
workflow. Candidate retrieval still only reads `used_finds.csv`; it does not
publish or append to the journal. Codex follows the ready-made
[`examples/codex/research-workflow.md`](../examples/codex/research-workflow.md):
it controls successive `research-findings` calls, checks source support and
the 0.3 semantic classes, and makes the final selection. Only an explicit
publication request leads to a recovery manifest under `work/` and the
existing `record-publication` command described in
[ai-workflow.md](ai-workflow.md). One to the configured maximum number of
strong results is valid; an empty selection is also valid.

## Optional recurring findings

After the user explicitly confirms the profile and approves the preview, Codex
offers a choice between manual runs and a recurring schedule. No automation is
created without separate consent. If the user opts in, Codex asks for cadence,
local time, and time zone, repeats them for confirmation, and creates a task
that uses the saved `research_profile.json` and
[`examples/codex/research-workflow.md`](../examples/codex/research-workflow.md).
It does not alter unrelated schedules.

If the current session cannot create the task automatically, open
`codex://automations` (Scheduled) and create it with the same workflow and
profile path. Codex should provide a short ready-to-paste task so the user does
not need to rewrite the research prompt. Declining a schedule is a complete and
supported outcome; the saved profile remains available for manual runs.

## Two reproducible scenarios

```powershell
.venv\Scripts\python run_research_demo.py
```

The `japan` scenario uses the existing synthetic corpus and names Taira,
Yoshitsune, and Zeami as interests without excluding other people. Its coverage
report honestly identifies names that were not found. The `rome` scenario uses
a separate synthetic Roman corpus and no predefined person at all. Generated
files stay under `work/research-demo/`.
