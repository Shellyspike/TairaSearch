# TairaSearch development and manual setup

[Русская версия](development.ru.md)

This document contains technical commands. A regular user can ask an agent to
install and configure the project as described in the [README](../README.md).

## Requirements and installation

- Windows, Linux, or macOS;
- Python 3.11;
- Git is needed only for development. A source archive is available from
  GitHub → Code → Download ZIP.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -c "import sys; assert sys.prefix != sys.base_prefix"
.venv\Scripts\python -m pip --version
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run_demo.py
```

Linux and macOS:

```bash
python3.11 -m venv .venv
.venv/bin/python -c 'import sys; assert sys.prefix != sys.base_prefix'
.venv/bin/python -m pip --version
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_demo.py
```

Do not fall back to installing packages into the system Python when the
`sys.prefix` or `pip --version` check fails. The standard `.venv` has been
incomplete in some deeply nested Windows Codex paths. The agent should retry
once in a new, shorter writable path without deleting the failed copy. If that
still fails, create the environment in ordinary PowerShell and reopen the
folder in Codex.

## Main commands

Scan a folder without creating an index:

```powershell
.venv\Scripts\python build_index.py "CORPUS_PATH" --scan-only
```

Build a new index and search it:

```powershell
.venv\Scripts\python build_index.py "CORPUS_PATH" --db work/index.sqlite3
.venv\Scripts\python taira_search.py search "search terms" --db work/index.sqlite3
```

An existing SQLite is bound to its recorded `corpus_root`. Reusing it with a
different folder is rejected before the database is changed; use a separate
SQLite instead. Text decoding uses BOMs, UTF-8, and conservative legacy-script
checks. For an ambiguous TXT, Markdown, or JSON corpus, pass an explicit
encoding such as `--text-encoding cp1251`; this reparses all supported text
files.

Profile-driven research for Codex:

```powershell
.venv\Scripts\python taira_search.py research-findings --db work/index.sqlite3 --profile research_profile.json --used-finds used_finds.csv --output work/research/candidates.json --preview
```

The command keeps the lossless `candidates.json` and also writes
`candidates.editorial.json`, a compact first-pass packet. After selecting IDs,
collect all full contexts in one operation instead of printing or repeatedly
reading the large result. Linked candidates outside the visible batch are kept
once in the full JSON and are included automatically:

```powershell
.venv\Scripts\python taira_search.py research-context work/research/candidates.json --chunk-id ID1 --chunk-id ID2 --include-required-review --output work/research/review.json
```

`daily-five` remains for compatibility. The current workflow uses
`research-findings` and, when needed, `--continue-from`.

Python indexes, ranks, retrieves context, and performs reproducible checks.
Codex investigates sources, reviews semantic novelty, and writes cards.
Publication and the `used_finds.csv` update are separate operations through a
JSON manifest and `record-publication`; preview does not change the journal.

To test the user-visible handoff, register a manifest against an isolated
journal and then render it:

```powershell
.venv\Scripts\python taira_search.py record-publication work/publications/test.json --used-finds work/test-used.csv
.venv\Scripts\python taira_search.py render-publication work/publications/test.json --used-finds work/test-used.csv
.venv\Scripts\python taira_search.py publication-status work/publications/test.json --used-finds work/test-used.csv --json
```

The render command is read-only and emits every complete `card_markdown` only
when all card IDs are registered. Status deliberately leaves delivery
unconfirmed: only the Codex task/chat surface can show the response, and the
CLI has no display acknowledgement. Recovery therefore reuses and renders the
same manifest without registering it again.

## Scheduled-publication access check

Before enabling an edition automation, run this from the automation's actual
environment, not only from an interactive shell:

```powershell
.venv\Scripts\python taira_search.py check-publication-access --db work/index.sqlite3 --used-finds used_finds.csv
```

It opens SQLite read-only, reads the journal when present, and proves that two
disposable files can be created and atomically renamed in the journal folder.
If `.used_finds.csv.lock` exists, the check opens it read-write without writing,
truncating, or deleting it; if it is absent, the check does not create it. The
real journal and lock contents remain unchanged. Success proves the effective
process permissions; a path merely
listed in `config.toml` does not. If the scheduler cannot run the check yet,
record the check as pending and do not activate publication.

On failure, add the project directory to the scheduled environment's effective
writable roots and retest after restarting Codex. A separate writable project
plus safe rebinding of the existing automation is another option; inspect
tasks first so no duplicate is created. The Windows error `windows unelevated
restricted-token sandbox cannot enforce split writable root sets directly` is
an environment error. Do not disable the sandbox, delete the lock file, or
bypass synchronization.

## Verification

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python run_demo.py
.venv\Scripts\python run_research_demo.py
.venv\Scripts\python run_dedup_audit.py --check
.venv\Scripts\python make_release.py --check-only
```

GitHub Actions runs the supported suite on Python 3.11 for Windows and Linux.
The public archive is built only from `release_manifest.toml`; personal books,
production SQLite, `used_finds.csv`, local profiles, and secrets are excluded.

See also the [AI demo](ai-demo.md), [onboarding](research-onboarding.md), and
[library acquisition](source-acquisition.md).



## Search modes and source exploration

See [retrieval-discovery.md](retrieval-discovery.md). Profiles explicitly save
`search_mode`: `open` or `focused_people`. The agent can switch modes without
reindexing; legacy profiles are not rewritten automatically. `preferred_kinds`
supplies soft discovery probes, and coverage.discovery explains coverage and
source omissions. Optional `research-findings --preview --discovery-path
<relative-prefix>` audits a source with continuation while preserving all
material-type and source filters. A source audit is not a publication quota.
