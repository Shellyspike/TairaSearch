# Reproducible AI demonstration

This walkthrough reproduces the public TairaSearch pipeline from the synthetic
sample corpus through five Codex-written cards. It does not need the author's
private library, production database, publication history, active automations,
or an OpenAI API integration in the Python project.

> **Demonstration data only:** every event and excerpt in `sample_corpus` is
> fictional test material. Historical-looking directory names exercise source
> classification and do not mean that a sentence occurs in the named work.

## Files used

- `sample_corpus/`: public synthetic Russian, Japanese, and English documents;
- `run_demo.py`: deterministic index, search, selection, and AI-input builder;
- `examples/codex/daily-news-prompt.md`: the existing sanitized editorial prompt;
- `examples/demo/codex-request.md`: demo-only constraints and output format;
- `work/demo/ai-input.json`: generated handoff containing the five candidates;
- `examples/demo/ai-input.json`: committed copy of the expected handoff;
- `examples/demo/ai-output.md`: committed example of a valid Codex result.

Run every command below from the repository root.

## 1. Install the Python dependency

Release 0.1 targets Python 3.11. On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

On macOS or Linux:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Only `pypdf` is installed. The Python stage makes no network request after the
dependency has been installed.

## 2. Build the index and five candidates

Windows PowerShell:

```powershell
.venv\Scripts\python run_demo.py
```

macOS or Linux:

```bash
.venv/bin/python run_demo.py
```

The command rebuilds only `work/demo/index.sqlite3` from `sample_corpus`, runs
one multilingual SQLite FTS5/BM25 search, and applies the existing deterministic
candidate rules. It creates:

- `work/demo/search.jsonl`: example search result;
- `work/demo/candidates.json`: complete deterministic candidate result;
- `work/demo/ai-input.json`: stable, path-safe five-candidate handoff for Codex;
- local CSV/JSONL diagnostics and an empty demo-only publication-history file.

The generated AI input deliberately omits absolute paths, timestamps, private
data, credentials, and automation identifiers. It must match the committed
`examples/demo/ai-input.json` fixture.

## 3. Install and sign in to Codex

Install the Codex CLI with npm and confirm that it is available:

```powershell
npm install -g @openai/codex@latest
codex --version
```

Run `codex` once from the repository and choose **Sign in with ChatGPT** (or
another sign-in method offered by the CLI):

```powershell
codex
```

This follows the official [Codex CLI quickstart](https://developers.openai.com/codex/cli).
The repository does not read or store the resulting credentials. No API key is
required by TairaSearch, and this demonstration does not add OpenAI SDK code.

## 4. Ask Codex to create the cards

The command below starts a new non-interactive, ephemeral Codex run. The model
can read the checkout but cannot edit it; the CLI itself writes only the final
message to `work/demo/ai-cards.md`.

```powershell
codex exec --ephemeral --sandbox read-only --output-last-message work/demo/ai-cards.md "Read examples/codex/daily-news-prompt.md and examples/demo/codex-request.md. Use work/demo/ai-input.json as the only source evidence. Return exactly five Markdown cards. Do not edit files."
```

The same command works in Bash. `codex exec` is the supported non-interactive
mode, and `--output-last-message` saves the final answer; see the official
[non-interactive mode documentation](https://developers.openai.com/codex/non-interactive-mode).

No existing chat, automation, schedule, or saved thread is used. For an
interactive run, start `codex` in the repository and paste the quoted
instruction from the command above. Keep the three referenced files unchanged.

## 5. Inspect and verify the result

Open `work/demo/ai-cards.md`. A valid result has all of these properties:

- exactly five cards, in the order of `ai-input.json`;
- every title starts with `[ДЕМО]`;
- every card says that the event is fictional test material, not a historical
  claim;
- every card cites its `relative_path` and stable `chunk_id`;
- quotations and concrete details are supported by `source_excerpt` or the
  supplied context;
- missing dates or places remain missing;
- folder names are not presented as proof that the text belongs to a real
  historical work;
- no publication or `used_finds.csv` update is claimed.

Model wording is not byte-for-byte deterministic. Compare the structure and
evidence use with `examples/demo/ai-output.md`, not exact prose. The committed
example lets readers inspect the complete demonstration without installing or
accessing Codex.

Run the local automated checks with:

```powershell
.venv\Scripts\python -m unittest tests.test_demo_workflow -v
python make_release.py --check-only
```

## What Python and AI each do

| Stage | Performed by | Result |
| --- | --- | --- |
| PDF/text/JSON reading and chunking | Python | Normalized local chunks |
| SQLite FTS5 search and BM25 ranking | Python | Ranked matches |
| Person/topic checks, neighbour loading, deduplication, diversity | Python | Exactly five grounded candidates |
| Removal of volatile/private handoff fields | Python | `ai-input.json` |
| Concise Russian prose and explanation of interest | Codex | Five Markdown cards |
| Preservation of uncertainty and demo labels | Codex, checked by a human | Reviewable draft |
| Authentication, command launch, and final approval | Human | Controlled local workflow |

Python does not generate the final prose. Codex does not rebuild the index,
change retrieval rules, publish cards, or update a journal. A human remains
responsible for reviewing any model output before real publication.
