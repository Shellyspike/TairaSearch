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

Profile-driven research for Codex:

```powershell
.venv\Scripts\python taira_search.py research-findings --db work/index.sqlite3 --profile research_profile.json --used-finds used_finds.csv --output work/research/candidates.json --preview
```

`daily-five` remains for compatibility. The current workflow uses
`research-findings` and, when needed, `--continue-from`.

Python indexes, ranks, retrieves context, and performs reproducible checks.
Codex investigates sources, reviews semantic novelty, and writes cards.
Publication and the `used_finds.csv` update are separate operations through a
JSON manifest and `record-publication`; preview does not change the journal.

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
