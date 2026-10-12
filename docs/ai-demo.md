# Reproducible AI demonstration

This walkthrough reproduces the public TairaSearch pipeline from the synthetic
sample corpus through five Codex-written cards. The primary workflow uses one
Codex app chat in the local repository: Codex runs the deterministic Python
stage, reads its handoff, writes the cards, and verifies the result. It does not
start a second model process.

The demonstration does not need the author's private library, production
database, publication history, active automations, chat history, or an OpenAI
API integration in the Python project.

> **Demonstration data only:** every event and excerpt in `sample_corpus` is
> fictional test material. Historical-looking directory names exercise source
> classification and do not mean that a sentence occurs in the named work.

## Files used

- `sample_corpus/`: public synthetic Russian, Japanese, and English documents;
- `run_demo.py`: deterministic index, search, selection, and AI-input builder;
- `examples/codex/daily-news-prompt.md`: sanitized editorial baseline;
- `examples/demo/codex-request.md`: demo-only evidence and output constraints;
- `work/demo/ai-input.json`: generated five-candidate handoff for Codex;
- `examples/demo/ai-input.json`: committed copy of the expected handoff;
- `examples/demo/ai-output.md`: committed result produced in a Codex app chat.

## 1. Install the Python dependency

Release 0.1 targets Python 3.11. Run commands from the repository root.

On Windows PowerShell:

```powershell
python --version
python -m venv .venv
.venv\Scripts\python -c "import sys; assert sys.prefix != sys.base_prefix, 'Broken virtual environment: stop before installing dependencies'; print(sys.version); print(sys.prefix)"
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -c "import pypdf; print(pypdf.__version__)"
```

The first command must report Python 3.11. The assertion must succeed, and the
printed `sys.prefix` must point to this checkout's `.venv`. Do not continue to
`pip install` if the assertion fails, because `pip` may then target the base
interpreter. A version-specific Windows `py` launcher command is an equivalent
alternative only when `py --list-paths` actually lists Python 3.11.

On macOS or Linux:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Only `pypdf` is installed. The Python stage makes no network request after the
dependency has been installed.

Known development-host limitation: inside the current Codex Windows sandbox,
the virtual-environment launcher can fall back to the base interpreter even
when `pyvenv.cfg` is valid. Testing with a short ASCII path did not fix it, so
this is not attributed to a non-ASCII profile path and is not presented as a
general Windows problem. If the assertion fails in Codex, run `run_demo.py` in
a normal PowerShell session using a working Python 3.11 environment, then use
the Codex app to read the generated `work/demo/ai-input.json`. The Python and
AI stages do not have to run in separate model sessions.

A Codex worktree is a separate checkout and may not contain ignored local
dependencies such as `.venv`. Create and verify an environment for that
checkout, or run the demo from the already prepared local checkout. Official
[local-environment documentation](https://learn.chatgpt.com/docs/environments/local-environment)
describes per-worktree setup scripts; release 0.1 does not require adding one.

## 2. Primary workflow: one Codex app request

Open this repository as a local project in the Codex app and start a chat whose
working directory is the repository root. The official
[projects documentation](https://learn.chatgpt.com/docs/projects?surface=app)
explains that a local project gives Codex access to the attached folder and its
working tree.

Send this single request:

```text
Выполни публичную AI-демонстрацию TairaSearch в текущей рабочей копии.

1. Запусти run_demo.py интерпретатором из .venv и убедись, что он успешно создал work/demo/ai-input.json ровно с пятью кандидатами.
2. Прочитай examples/codex/daily-news-prompt.md, examples/demo/codex-request.md и сгенерированный work/demo/ai-input.json. Из daily-news-prompt.md используй только редакционные правила и требования к доказательствам: для этой демонстрации codex-request.md отменяет инструкции о публикации, манифесте и журнале.
3. Используй ai-input.json как единственный источник сведений. Не ищи информацию в интернете и не обращайся к другим корпусам.
4. Создай ровно пять русскоязычных Markdown-карточек в порядке входных кандидатов. Каждый заголовок должен начинаться с [ДЕМО], а каждая карточка должна быть явно названа вымышленным тестовым материалом, содержать разделы «Что случилось», «Почему это интересно», «Фрагмент» и «Источник» и ссылаться на relative_path и chunk_id.
5. Сохрани результат только в work/demo/ai-cards.md. Не изменяй отслеживаемые файлы репозитория, не публикуй карточки и не обновляй журнал находок.
6. Проверь число карточек, маркировку [ДЕМО], все пять relative_path и chunk_id и сообщи результат проверки.
```

Codex performs both roles in the same chat: it invokes Python for retrieval and
then uses the generated, path-safe handoff as model context. No nested
`codex exec`, OpenAI SDK code, API key in the repository, personal automation,
or previous chat is required. The human still reviews the final file.

The checked-in `examples/demo/ai-output.md` was produced with this division of
work in the current Codex app session. It is a reviewable example, not a
byte-for-byte golden model response.

## 3. What the Python command produces

`run_demo.py` rebuilds only `work/demo/index.sqlite3` from `sample_corpus`, runs
a multilingual SQLite FTS5/BM25 search, and applies the existing deterministic
candidate rules. It creates:

- `work/demo/search.jsonl`: example search result;
- `work/demo/candidates.json`: complete deterministic candidate result;
- `work/demo/ai-input.json`: stable, path-safe five-candidate handoff for Codex;
- local CSV/JSONL diagnostics and an empty demo-only publication-history file.

The generated AI input omits absolute paths, timestamps, private data,
credentials, and automation identifiers. It must match the committed
`examples/demo/ai-input.json` fixture.

To run only this deterministic stage manually:

```powershell
.venv\Scripts\python run_demo.py
```

On macOS or Linux, use `.venv/bin/python run_demo.py`.

## 4. Inspect and verify the result

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

Model wording is not byte-for-byte deterministic. Compare structure and
evidence use with `examples/demo/ai-output.md`, not exact prose. The committed
example lets readers inspect the complete demonstration without access to
Codex.

Run the automated checks with:

```powershell
.venv\Scripts\python -m unittest tests.test_demo_workflow -v
python make_release.py --check-only
```

## 5. Optional alternative: Codex CLI

Users who prefer a separate non-interactive process can install and sign in to
the Codex CLI, then run:

```powershell
codex exec --ephemeral --sandbox read-only --output-last-message work/demo/ai-cards.md "Read examples/codex/daily-news-prompt.md and examples/demo/codex-request.md. Use only the editorial and evidence rules from the daily-news prompt; the demo request overrides its publication, manifest, and journal instructions. Use work/demo/ai-input.json as the only source evidence. Return exactly five Markdown cards. Do not edit tracked files."
```

On Windows, `codex.cmd` can be used instead of `codex` when PowerShell blocks
the `codex.ps1` wrapper. This CLI route is optional and requires the terminal's
network route to reach Codex. It is not needed when the current Codex app chat
already has the repository open. See the official
[non-interactive mode documentation](https://learn.chatgpt.com/docs/non-interactive-mode)
for the CLI flags.

## What Python and AI each do

| Stage | Performed by | Result |
| --- | --- | --- |
| PDF/text/JSON reading and chunking | Python | Normalized local chunks |
| SQLite FTS5 search and BM25 ranking | Python | Ranked matches |
| Person/topic checks, neighbour loading, deduplication, diversity | Python | Exactly five grounded candidates |
| Removal of volatile/private handoff fields | Python | `ai-input.json` |
| Concise Russian prose and explanation of interest | Codex | Five Markdown cards |
| Preservation of uncertainty and demo labels | Codex, checked by a human | Reviewable draft |
| Command launch and final approval | Human | Controlled local workflow |

Python does not generate the final prose. Codex does not change retrieval
rules, publish cards, or update a journal. A human remains responsible for
reviewing model output before real publication.
