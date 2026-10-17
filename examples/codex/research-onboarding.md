# Codex: install and configure my personal news

Help me install and configure TairaSearch through a short, natural conversation.
Perform available technical actions yourself. Do not ask me to
edit JSON, run commands, or understand Python, SQLite, FTS, or chunks when you
can do the work.

## 1. Install and verify

If the project has not been downloaded, obtain it only from
`https://github.com/Shellyspike/TairaSearch` in a new separate folder. Never
overwrite an existing installation or library. Check for Python 3.11, create
`.venv`, verify inside it that `sys.prefix != sys.base_prefix`, and install
`requirements.txt` only with that environment's Python. Also verify
`python -m pip --version`. If either check fails, do not install anything into
the system Python. On Windows, retry once in a new shorter writable path,
without overwriting or deleting the failed copy; report the limitation if that
also fails.

Run `run_demo.py` as a synthetic smoke test. Do not present it as proof of
access to a real library or website. If network, filesystem, Python, web-search,
or scheduling access is unavailable, identify the exact limitation and ask
only for the smallest necessary action. Never simulate success.

## 2. Interview and profile

First ask about the research area. In plain language ask about interesting fields; important people, events, or
works, if any; desired kinds of stories; result language; detail; and style.
Ask one question or a small group at a time, skip what is already known, accept
“everything,” and do not require a list of people.

Summarize your understanding and let me correct it. After confirmation, create
the local `research_profile.json` using `docs/research-onboarding.md` and
`examples/profiles/`. I should not edit it: never store a preference that should change selection only there. Translate retrieval preferences
into effective `interests[].terms`, `weight`, material types, or filters.
`notes` do not affect retrieval; put purely editorial preferences in
`finding_preferences.notes`, including requests for vivid, expanded cards. Do not invent name variants, sources, or corpus
coverage.

## 3. Offer personal editions first

After confirming the profile, ask whether I would eventually like recurring
personal editions. If I agree, collect cadence, local time, and time zone,
repeat them, and retain them as pending settings. Without explicit consent
create nothing. Even with consent, do not create or run the task yet: a ready
library, index, and accepted preview are required first.

## 4. Choose the materials

Only after confirming my interests ask about materials. Do not assume any known path. Offer three choices:

1. “I have a folder of documents.”
2. “I have a ready TairaSearch index.”
3. “I have nothing yet—help me find research sources.”

For a folder, ask for its path and first run only
`build_index.py <folder> --scan-only`. Report supported files and errors. Then
ask separately before creating a new index under `work/`. Never apply
`--rebuild` to an existing database or delete missing files.

Connect a ready index read-only and verify it with a safe search. Do not
rebuild, migrate, or repair it without a request. Return to material selection
after an error.

If there are no materials, offer discovery first. If web search or download tools are unavailable, honestly offer a folder or ready index. Only after consent follow
`examples/codex/source-acquisition-workflow.md`. Show candidate sources and
rights status, then run the read-only `check`. Download only after I select exact items and only selected items
that qualify under the policy into `work/library-staging/`. Promotion to the
main corpus and `promote --index` need new, separate approval. If discovery or
download tools are unavailable, honestly offer a folder or ready index.

## 5. Separately offer library acquisition

After connecting a library, offer an independent recurring task using
`source-acquisition-workflow.md`. Without explicit consent create nothing. If
I agree, ask for cadence, time zone, maximum files, per-file size, total size,
and whether qualifying material may be downloaded automatically only into
staging. Inspect existing tasks and do not create a duplicate acquisition task.
It never promotes material or updates the index without my explicit agreement.

## 6. Preview and finish setup

When the library and index are ready, run `taira_search.py research-findings`
with the confirmed profile, output under `work/`, and `--preview`. Never run
`record-publication` or change `used_finds.csv`. Read the candidates and
`examples/codex/daily-news-prompt.md`; use only its editorial, style, and
accuracy rules, not its manifest or publication instructions. Show a small
preview with exact `relative_path` and `chunk_id` references.

Ask whether subjects and presentation feel right. Apply retrieval feedback to
effective terms, weights, and filters, and style feedback to
`finding_preferences.notes`. If the first batch fails review, request a
disjoint next batch with `--continue-from`; do not distort the profile.

Only after I accept the preview, repeat the pending personal-edition settings
and ask for final confirmation. Before activation, run `python taira_search.py
check-publication-access` in the actual scheduled-task environment. Require
read-only SQLite access and disposable create-plus-atomic-rename access beside
`used_finds.csv`, without changing the journal or lock. Confirm the path is in
that environment's effective writable roots; `config.toml` alone and an
interactive-chat check are not sufficient. Then create an automation that follows
`examples/codex/research-workflow.md`. Keep it separate from library
acquisition and do not alter other tasks. If automatic creation is unavailable,
offer `codex://automations` and provide one short ready-to-paste task. If I
decline, leave manual use available and do not keep prompting.

If the check fails, do not claim success or activate the task. Explain how to
fix effective writable roots and retest after a Codex restart, or offer a
separate writable project and rebind the existing automation after checking
that no duplicate exists. Treat `windows unelevated restricted-token sandbox
cannot enforce split writable root sets directly` as an environment failure.
Never disable the sandbox, remove the lock file, or bypass synchronization. If
the scheduled environment cannot yet be tested, say that this check remains
required before activation.

If a profile topic has no match, say only that the checked index did not
support it. Do not claim that the entire corpus is exhausted.
