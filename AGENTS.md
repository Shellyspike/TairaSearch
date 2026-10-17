# TairaSearch agent guide

TairaSearch creates a personal news feed from books, historical sources, and
scholarship. It is not a breaking-news crawler. Keep that product promise clear
when helping a user install or configure the project.

## First-run request

Treat a request such as “Install TairaSearch and help me configure my news” as
permission to prepare a separate local project copy and begin onboarding. It is
not permission to download research material, create scheduled tasks, promote
files into a corpus, update an index, or publish findings.

If the project has not been downloaded yet:

1. Obtain the canonical repository from
   `https://github.com/Shellyspike/TairaSearch` in a new, clearly named folder.
   Never overwrite an existing checkout or user library. Use Git when it is
   available; otherwise use GitHub's source archive. On Windows, prefer a short
   writable project path near the top of a user-approved drive; deeply nested
   paths can leave `venv` without a working `pip`.
2. Inspect the operating system and available tools. TairaSearch supports
   Python 3.11.
3. Create `.venv`. Before installing anything, verify with the environment's
   Python that `sys.prefix != sys.base_prefix`, then run
   `python -m pip --version` with that same interpreter. If either check fails,
   do not install packages into the system Python. On Windows, retry once by
   preparing a new copy in a shorter writable path; do not overwrite or delete
   the failed copy. If the short-path retry also fails, explain the problem and
   offer the manual recovery steps from `docs/development.md`.
4. Install `requirements.txt` using that verified environment's Python.
5. Run `run_demo.py` as a synthetic smoke test. Clearly label it as a demo; it
   does not prove access to a user's files or to real websites.

Do these steps yourself when the environment permits. Do not make a
nontechnical user copy shell commands merely because commands exist in the
documentation. If network, filesystem, Python, browser, or scheduling access is
unavailable, say exactly what is blocked and ask only for the smallest action
needed. Never simulate a successful installation, source search, download, or
automation.

## Conversational onboarding

Reply in the user's language. Read the matching onboarding files completely:

- `examples/codex/research-onboarding.ru.md` and
  `docs/research-onboarding.ru.md` for Russian;
- `examples/codex/research-onboarding.md` and
  `docs/research-onboarding.md` for English.

Follow this order:

1. Interview the user about interests, useful kinds of stories, language,
   length, and style. Confirm your understanding, then create the ignored local
   `research_profile.json`; never ask the user to edit JSON.
2. Offer a recurring personal-news edition. If the user is interested, collect
   cadence, local time, and time zone as pending settings. Do not create or run
   the task until a library and index are ready and the user accepts a preview.
3. Ask whether materials come from a document folder, a ready TairaSearch
   index, or agent-assisted source discovery. Follow the consent boundaries in
   the onboarding workflow.
4. Once a library is connected, separately offer recurring source acquisition
   with `examples/codex/source-acquisition-workflow.md`. It is independent from
   personal editions. Check existing tasks before offering a new one.
5. Run a preview through `examples/codex/research-workflow.md`, ask for
   feedback, and update the profile only with the user's confirmation.
6. Only after the preview is accepted may you create the previously approved
   personal-edition task. Before activation, run
   `python taira_search.py check-publication-access` in the exact scheduled-task
   environment. This must prove Python execution, read-only SQLite access, and
   creation plus atomic rename of disposable files beside `used_finds.csv`;
   the real journal and `.used_finds.csv.lock` must remain unchanged. Treat the
   effective writable roots reported/enforced by that environment as
   authoritative: a path merely listed in `config.toml` is not sufficient.
   Repeat the schedule before creation.

If the scheduled environment cannot pass the check, do not claim setup is
complete and do not activate the task. Explain how to grant the project folder
as an effective writable root and retest after restarting Codex if needed. A
safe alternative is a separate writable Codex project followed by rebinding
the existing automation; inspect existing tasks first and never create a
duplicate. If Windows reports `windows unelevated restricted-token sandbox
cannot enforce split writable root sets directly`, report that environment
error and use the restart/separate-project path. Never recommend disabling the
sandbox, deleting the lock file, or bypassing publication synchronization. If
the scheduled environment is not yet available, mark this check as pending and
require it before activation rather than substituting an interactive-chat test.

No automation is created without explicit consent. Source acquisition may
download only under an agreed policy and only into `work/library-staging/`.
Moving staged material into the main corpus and running indexing require a
separate approval. An existing installation's corpus, SQLite files, profile,
publication journal, and automations must be preserved unless the user
explicitly asks to change a specific item.

## Existing installations and development tasks

Do not restart onboarding for ordinary code, test, or documentation work. Do
not replace a confirmed profile merely because an example profile exists. For
manual commands, architecture, tests, and release checks, use
`docs/development.md` (or `docs/development.ru.md`).
