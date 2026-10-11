# TairaSearch

TairaSearch is a local research pipeline for indexing a multilingual historical
corpus, searching it with SQLite FTS5/BM25, selecting candidate findings, and
giving a Codex automation verified context for short historical news cards.

The project intentionally combines two layers:

- deterministic Python code for extraction, chunking, indexing, search,
  context retrieval, duplicate checks, and candidate selection;
- Codex automations for discovering possible new sources, reviewing retrieved
  context, comparing scholarship, and writing the final cards.

The public repository contains only source code and a small synthetic sample.
It does not contain the author's personal library, production SQLite database,
search exports, publication journal, or active automation configuration.

## Current release status

This working copy is the preparation branch for version 0.1. It is not yet a
published release. The first completed safety milestone is an exact release
allowlist with tests that reject private/generated data and absolute local
paths. PDF dependency preflight and error diagnostics are also covered by the
test suite. See [ROADMAP.md](ROADMAP.md) for the remaining isolated stages.

## Quick local run

Python 3.11 is the initial supported version for release 0.1.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python build_index.py sample_corpus --db work/demo.sqlite3 --drive-csv work/demo.csv --drive-jsonl work/demo.jsonl --log work/demo.log --rebuild
.venv\Scripts\python taira_search.py search --db work/demo.sqlite3 --query "維盛" --json
```

On POSIX systems, replace `.venv\Scripts\python` with `.venv/bin/python`.

`requirements.txt` pins the tested `pypdf` version. When the corpus contains at
least one PDF, the builder checks this dependency before it opens the SQLite
index or creates logs and exports. A missing dependency therefore fails with an
installation hint without changing an existing index. Valid PDFs without an
extractable text layer receive the `pdf_no_text` status; unreadable containers
are reported as `PDF_READ_ERROR`. OCR is not included in release 0.1.

Incremental updates keep the last successfully indexed chunks and FTS rows when
parsing or database writes fail. A PDF with one or more unreadable pages is
treated as incomplete and cannot replace a complete indexed version. Files not
seen during a scan are retained because a local or mounted corpus directory may
be temporarily unavailable. `--rebuild` forces reprocessing of visible files;
it does not prune missing files.

The index command reports one of these build statuses:

- `succeeded`: every supported document was handled; exit code 0;
- `completed_with_errors`: individual documents failed but safe results and any
  previous good versions were retained; exit code 1;
- `failed`: a critical error prevented a completed build; exit code 1.

User interruption retains exit code 130, and `--scan-only` retains exit code 0.
The final report lists successful, skipped, and problematic files, short error
reasons, and how many previous versions were preserved. Local indexing does not
require or evaluate licence metadata.

## Public release safety

`release_manifest.toml` lists every file allowed into the public archive.
Files not listed there are ignored, even if they are present in the project
directory.

Validate the source set without creating an archive:

```powershell
python make_release.py --check-only
```

Build a deterministic ZIP:

```powershell
python make_release.py
```

The builder rejects database files, generated exports, publication journals,
private-data directories, symlinks, path traversal, oversized files, and
absolute local paths in public text files.

## AI workflow

The AI-assisted part is a first-class part of TairaSearch, while the searchable
index remains local and deterministic. See [docs/ai-workflow.md](docs/ai-workflow.md)
and the sanitized prompt templates under `examples/codex/`.

The templates are documentation only. Installing or running this repository
does not create, modify, start, or stop any Codex automation.

## Private corpora

Users may index their own local documents by passing an explicit corpus path.
The program does not require licence metadata for local indexing. Responsibility
for acquiring, sharing, or publishing source documents remains with the user.

Never add a personal corpus, generated index, extracted text, search export, or
publication journal to `release_manifest.toml`.

## Tests

The release-safety tests use only the Python standard library:

```powershell
python -m unittest tests.test_release_safety -v
```

The complete integration suite additionally exercises PDF parsing and requires
the dependencies from `requirements.txt`.

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
```

## Licence

A code licence will be selected before the first public release. The synthetic
sample corpus will receive an explicit data notice separately.

