# First-run personal news setup

[Русская версия](research-onboarding.ru.md)

A regular user does not need to install TairaSearch manually or edit
configuration. They can ask an agent:

> **Install TairaSearch from https://github.com/Shellyspike/TairaSearch and help me configure my news.**

After the downloaded project is opened, Codex reads the root `AGENTS.md` and
follows the flow below. Another agent must be able to use local files and a
shell and follow repository guidance. If a capability is unavailable, it must
stop honestly at that boundary.

## Complete user journey

### 1. Safe installation

The agent downloads the canonical repository into a separate folder, checks
Python 3.11, creates `.venv`, installs dependencies only into the verified
environment, and runs the synthetic `run_demo.py`. It does not overwrite an
existing checkout or fall back to system Python after an environment failure.
The demo verifies the distributed project, not access to real books, websites,
or scheduling.

Manual commands and Windows `.venv` recovery are in
[development.md](development.md); the agent performs them when it has shell
access.

### 2. Interview and `research_profile.json`

In plain language the agent asks about subjects, desired kinds of stories,
language, detail, and style. Named people and events are optional: a profile
may describe a whole field. The agent summarizes its understanding and accepts
corrections before creating the local, Git-ignored `research_profile.json`.

Retrieval is actually controlled by `interests[].terms`, `weight`, material
types, and filters. Pure editorial preferences belong in
`finding_preferences.notes`; a retrieval preference must not exist only in
`notes`. `examples/profiles/` documents the format, but the user does not edit
it manually.

### 3. Offer personal editions

Immediately after profile confirmation, the agent offers recurring personal
news. If the user opts in, it asks for cadence, local time, and time zone and
retains them as pending settings. The task is not created or run yet: a ready
library, index, and accepted preview come first. Declining leaves a complete
manual workflow.

### 4. Prepare the research library

The agent offers three plain choices.

#### A document folder exists

After receiving the path, the agent first runs only `build_index.py <path>
--scan-only`. Scanning creates no SQLite file and reports supported files and
errors. A new index under `work/` is created only after separate consent. The
agent never uses `--rebuild` on an existing database or automatically removes
temporarily unavailable documents.

#### A ready index exists

The agent connects it read-only and verifies it with a safe search. It does
not rebuild the corpus or repair or migrate an incompatible file without a
request. An error remains visible and returns the user to material selection.

#### No materials exist yet

After consent, the agent follows
[`source-acquisition-workflow.md`](../examples/codex/source-acquisition-workflow.md):
it discovers and shows options, checks metadata and duplicates, and downloads
only selected policy-eligible material into `work/library-staging/`. Copies
with unclear rights may remain in the report but are not downloaded
automatically. Promotion to the main corpus and `promote --index` require new,
separate approval.

If web discovery or download is unavailable, the agent does not simulate
results; it offers a document folder or ready index.

### 5. Independent library acquisition

After materials are connected, the agent separately offers a second
automation for finding and downloading new sources. If accepted, it asks for
schedule, time zone, file-count and size limits, and whether automatic download
only into staging is allowed. It checks existing tasks and creates no
duplicate. This task never promotes files or updates the index without a new
user decision.

### 6. Preview and activation

With a ready index, the agent runs `research-findings --preview`, reviews the
candidates using
[`research-workflow.md`](../examples/codex/research-workflow.md), and shows a
small edition with `relative_path` and `chunk_id`. Preview does not change
`used_finds.csv` or register cards as published.

If the first batch fails review, the agent continues with a disjoint batch via
`--continue-from`. It does not present an empty result as an error or mask a
read failure as no findings. User feedback changes the profile and a repeated
preview, not the search engine.

After the user accepts the edition, the agent repeats the previously selected
personal-news schedule and asks for final confirmation. Only then is the task
created using `research-workflow.md`. If programmatic creation is unavailable,
the agent provides one short ready-to-paste task and offers
`codex://automations`. Personal editions and library acquisition always remain
independent automations.

## Consent boundaries

- the profile is written after the user confirms the interpreted interests;
- no schedule is created without separate consent;
- discovering a source is not permission to download it;
- eligible downloads go only to staging;
- corpus promotion and indexing require new approval;
- installation must preserve any existing corpus, SQLite, journal, and tasks.

The exact executable guidance is in
[`examples/codex/research-onboarding.md`](../examples/codex/research-onboarding.md).
Technical architecture and manual commands are in
[development.md](development.md).
