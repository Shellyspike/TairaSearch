# TairaSearch

**[Русская инструкция](README.ru.md)** · [Detailed AI demo](docs/ai-demo.md) ·
[Copy-ready English Codex request](examples/demo/codex-request.md)

TairaSearch is a small local AI-assisted project for finding human-scale
episodes in a multilingual historical corpus. Deterministic Python code reads
documents, builds a SQLite FTS5/BM25 index, verifies context, removes repeats,
and selects candidates. Codex reads that evidence and writes source-aware
cards for a human to review.

The public repository is self-contained. It contains synthetic Russian,
Japanese, and English fixtures (including PDFs), not the author's personal
library, production database, publication journal, active automation, or chat
history.

## Universal research onboarding (0.2)

A new user can configure retrieval by conversation instead of editing JSON:

1. prepare the environment using the instructions below;
2. open the project in Codex;
3. paste the
   [ready-made onboarding request](examples/codex/research-onboarding.md);
4. provide an existing index or corpus folder;
5. answer a few questions, review a preview, and refine preferences in plain
   language.

Codex saves an ignored local `research_profile.json`. The new
`research-findings` command reuses the existing FTS5 search, neighbouring
context, and repeat checks. A preview never updates `used_finds.csv`. See
[docs/research-onboarding.md](docs/research-onboarding.md) for details and two
synthetic scenarios.

Legacy `daily-five`, existing indexes, and the five-card demonstration below
retain their existing contracts.

## Quick start: get five AI cards

You need Python 3.11 and access to the Codex desktop app. Git is optional and
only needed by developers who prefer to clone the repository. Python does not
call a model or require an OpenAI API key. Codex access is required only for
the AI-written cards.

### 1. Download without Git and install

On the repository page, choose **Code → Download ZIP**, extract the archive,
and open PowerShell in the extracted folder (normally `TairaSearch-main`). Then
run:

```powershell
python -m venv .venv
.venv\Scripts\python -c "import sys; assert sys.prefix != sys.base_prefix, 'Broken virtual environment'; print(sys.version); print(sys.prefix)"
.venv\Scripts\python -m pip install -r requirements.txt
```

Developers may use Git instead:

```powershell
git clone https://github.com/Shellyspike/TairaSearch.git
cd TairaSearch
```

After cloning, run the same `.venv` creation and verification commands above.

The version check should report Python 3.11 and a prefix ending in `.venv`.
Stop if the assertion fails: installing after that may target the base Python.
On macOS/Linux, use `python3.11 -m venv .venv` and
`.venv/bin/python -m pip install -r requirements.txt`.

### 2. Open once, ask once

Open the cloned `TairaSearch` folder as a local project in the Codex desktop
app, start a chat in that folder, and paste the complete request from
[examples/demo/codex-request.md](examples/demo/codex-request.md).

Codex will run `run_demo.py`, read the resulting `work/demo/ai-input.json`,
write exactly five English `[DEMO]` cards to `work/demo/ai-cards.en.md`, and
check their source links. You do **not** run `run_demo.py` first on this primary
path. The official
[Codex projects guide](https://learn.chatgpt.com/docs/projects?surface=app)
explains how a local project gives a chat access to a folder.

For Russian instructions, prompt, and output, use
[README.ru.md](README.ru.md).

### 3. Fallback when Python does not run inside Codex

From a normal PowerShell window opened in the project folder, run:

```powershell
.venv\Scripts\python run_demo.py
```

This must create `work/demo/ai-input.json`. Return to the Codex project chat
and paste the short request from
[examples/demo/codex-request-existing-input.md](examples/demo/codex-request-existing-input.md).
It explicitly tells Codex not to run Python again: Codex reads the prepared
JSON and writes the cards. Never run `pip` against the system Python after a
failed `.venv` verification.

## Python-only demo

If you want to inspect retrieval without Codex, run:

```powershell
.venv\Scripts\python run_demo.py
```

On macOS/Linux:

```bash
.venv/bin/python run_demo.py
```

This offline command builds `work/demo/index.sqlite3`, runs a multilingual
search, selects five candidates, finds one synthetic scholarship note for each,
and writes `work/demo/ai-input.json`. It makes no network or model call. The
checked-in [Russian](examples/demo/ai-output.md) and
[English](examples/demo/ai-output.en.md) results show what the AI stage can
produce without pretending that tests generated the prose.

## What Python and Codex do

| Stage | Owner |
| --- | --- |
| Text/PDF/JSON extraction, chunking, stable position IDs | Python |
| SQLite FTS5 search, BM25 ranking, adjacent context | Python |
| Candidate checks, deduplication, diversity, scholarship lookup | Python |
| Narrative angle, careful synthesis, readable cards | Codex |
| Evidence and publication review | Human |

Literary narrative, research interpretation, and model inference must stay
visibly separate. An interesting card is never permission to invent facts.

## Main commands

Build an index:

```powershell
.venv\Scripts\python build_index.py sample_corpus --db work/index.sqlite3 --drive-csv work/drive.csv --drive-jsonl work/drive.jsonl --log work/index.log --rebuild
```

Search it:

```powershell
.venv\Scripts\python taira_search.py search --db work/index.sqlite3 --query "維盛" --json
```

Select zero to five daily candidates:

```powershell
.venv\Scripts\python taira_search.py daily-five --db work/index.sqlite3 --used-finds work/demo-used.csv --output work/candidates.json --json
```

Zero candidates and one-to-four candidates are successful outcomes. A non-zero
exit means a real index/search/data error. Only the synthetic `run_demo.py`
fixture requires exactly five.

Record already-finalized cards atomically:

```powershell
.venv\Scripts\python taira_search.py record-publication work/publications/example.json --used-finds used_finds.csv
```

The CSV update is atomic, idempotent, and protected by a Windows/Linux
interprocess lock around the whole read/check/write cycle. The saved JSON is
the recovery copy if chat delivery or journal writing fails.

## Reliability and privacy boundaries

- Read-only search uses SQLite `mode=ro`, sees committed WAL updates, and
  rejects writes. Legacy indexes can still take the existing migration path.
- Re-indexing prepares a document first and replaces its chunks in one
  transaction. A parse/write failure keeps the last valid version.
- Missing files are not pruned automatically. Cleanup remains an explicit
  future feature.
- The local corpus may be indexed without licence metadata. Distribution
  checks apply to the public release, not to private local search.
- `make_release.py` copies only the exact `release_manifest.toml` allowlist and
  rejects databases, journals, secrets, local paths, and generated files.

The current development host has a Codex Windows sandbox quirk where
`.venv\Scripts\python` can resolve to the base interpreter. The fail-fast
prefix check above detects it. This is not known to be a general Windows or
Unicode-path problem. A Codex worktree is a separate checkout and needs its own
verified environment; see the official
[local environment guide](https://learn.chatgpt.com/docs/environments/local-environment).

## Tests and public build

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python run_demo.py
.venv\Scripts\python make_release.py --check-only
```

GitHub Actions runs these checks on Windows and Linux with Python 3.11. The
project is MIT-licensed; the synthetic sample corpus is distributed under the
same licence. See [ROADMAP.md](ROADMAP.md) and
[docs/ai-workflow.md](docs/ai-workflow.md) for design limits and future work.

