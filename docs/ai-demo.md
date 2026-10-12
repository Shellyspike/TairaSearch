# Reproducible AI demonstration (English)

[Русская версия](ai-demo.ru.md)

This walkthrough produces five source-linked English cards from the public
synthetic corpus. It needs no private files, active automation, prior chat,
OpenAI API integration, or internet access during the Python stage.

Every event, quotation, and research note under `sample_corpus/` is fictional
test material. Historical-looking folder names test classification only.

## Prerequisites

- Git;
- Python 3.11;
- the Codex desktop app for the AI stage.

From the repository root on Windows:

```powershell
python -m venv .venv
.venv\Scripts\python -c "import sys; assert sys.prefix != sys.base_prefix, 'Broken virtual environment'; print(sys.version); print(sys.prefix)"
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -c "import pypdf; print(pypdf.__version__)"
```

On macOS/Linux:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Do not install after a failed prefix assertion. On the current development
host, the Codex Windows sandbox can launch the base interpreter for a valid
`.venv`; this is not known to be a general Windows or Unicode-path defect. Run
the setup in a normal terminal if that local check fails. A Codex worktree is a
separate checkout and needs its own verified environment. See the official
[local environment guide](https://learn.chatgpt.com/docs/environments/local-environment).

## Primary path: one Codex app request

Open the repository folder as a local project in the Codex app. Start a chat in
that folder and paste the complete contents of
`examples/demo/codex-request.md`.

That single request tells Codex to:

1. run `run_demo.py` with the prepared environment;
2. verify that `work/demo/ai-input.json` has five candidates;
3. read the editorial rules and candidate evidence;
4. write five English `[DEMO]` cards to `work/demo/ai-cards.en.md`;
5. verify every event and scholarship path/chunk reference.

Do not run `run_demo.py` manually first in this path. Codex runs Python and then
uses the generated handoff in the same chat—there is no nested model process.
The official [projects guide](https://learn.chatgpt.com/docs/projects?surface=app)
describes local project access.

## Python-only path

To inspect deterministic retrieval without AI:

```powershell
.venv\Scripts\python run_demo.py
```

On macOS/Linux use `.venv/bin/python run_demo.py`.

The command creates only ignored files under `work/demo/`:

- `index.sqlite3`: index of the public sample corpus;
- `search.jsonl`: one multilingual search example;
- `candidates.json`: the deterministic five-candidate result;
- `ai-input.json`: path-safe event context plus related synthetic scholarship;
- local diagnostics and an empty demo-only journal.

It does not call a model, browse, or generate prose. Its `ai-input.json` must
match `examples/demo/ai-input.json` exactly.

## Verify the AI result

A valid `work/demo/ai-cards.en.md` has:

- exactly five `[DEMO]` titles in input order;
- an explicit fictional-test-material warning in every card;
- an engaging, evidence-grounded story rather than comments about search;
- clear separation of event source, literary framing, scholarship, and model
  inference;
- every event `relative_path` and `chunk_id`;
- each related scholarship path/chunk when present;
- no invented fact and no claim that a folder name proves a real quotation;
- no publication or journal update.

Compare it with `examples/demo/ai-output.en.md`. The saved result is a reviewed
example from a Codex session, not a byte-for-byte golden model response. Model
wording can vary.

Run deterministic checks with:

```powershell
.venv\Scripts\python -m unittest tests.test_demo_workflow -v
.venv\Scripts\python make_release.py --check-only
```

## Optional Codex CLI route

The desktop app is the primary path. Users who deliberately want a separate
non-interactive process may first run the Python-only command, then use:

```powershell
codex exec --ephemeral --sandbox workspace-write "Read examples/demo/codex-request.md. run_demo.py has already been run, so use work/demo/ai-input.json and write only work/demo/ai-cards.en.md. Do not modify tracked files or any journal."
```

This optional route requires Codex CLI sign-in and network access. It is not
needed when the app already has the project open.

## Responsibility boundary

| Work | Python | Codex | Human |
| --- | ---: | ---: | ---: |
| Extract, index, rank, verify, deduplicate | yes | no | reviews |
| Link one synthetic research note per candidate | yes | no | reviews |
| Choose a narrative angle and write cards | no | yes | reviews |
| Publish or use real historical claims | no | no | decides |

Python does not call a model. Codex does not change retrieval rules or publish
the demo. Human review remains mandatory.
