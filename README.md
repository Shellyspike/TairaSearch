# TairaSearch

**[Русская версия](README.ru.md)** · [How setup works](docs/research-onboarding.md) ·
[View the AI demo](docs/ai-demo.md)

## Tired of the news? Make your own!

Had enough of politics, scandals, and an endless stream of alarming headlines?
What if every day brought news about something you genuinely care about?

Medieval Japan, Ancient Rome, art history, forgotten civilizations—or any
other subject you choose.

TairaSearch turns books, historical sources, and scholarship into your
personal news feed. An AI agent finds surprising stories, unusual details, and
interesting discoveries, checks the supporting sources, and tries not to
repeat itself.

**You choose what you want to read about. The agent does the rest.**

These are the news stories we deserve.

> TairaSearch is not a breaking-news search engine. It prepares personal
> editions from your research library and from new sources you have approved.

### What could appear in your edition

- why a banquet stopped for a rain-soaked messenger;
- how a box of letters became less valuable than the fire around it;
- why illness at court may be more visible in an empty seat than in a list of
  symptoms.

These are headlines from the [fictional demonstration edition](examples/demo/ai-output.en.md),
not real historical claims. Your feed depends on your interests and library.

## Start with one request

Open Codex—or another AI agent that can work with local files and run shell
commands—and send:

> **Install TairaSearch from https://github.com/Shellyspike/TairaSearch and help me configure my news.**

There is nothing else to copy. After downloading the repository, the agent
reads the root `AGENTS.md`, prepares an isolated Python environment, verifies
the synthetic demo pipeline, and starts a conversational setup. You do not
need to edit JSON or understand SQLite.

If an agent cannot download the project, the no-Git fallback is GitHub →
**Code → Download ZIP**. Open the extracted folder in the agent and send the
same request; manual developer setup remains optional.

If the agent cannot access the network, local files, Python, or scheduled
tasks, it must explain the exact limitation and offer a clear next step. It
must not pretend that installation or source discovery succeeded.

## What happens during setup

1. **Safe installation.** The agent downloads the project into a separate
   folder, checks Python, creates `.venv`, installs dependencies only inside
   it, and verifies the pipeline against the synthetic demo.
2. **A short interview.** You describe the subjects and stories you enjoy,
   result language, level of detail, and writing style. The agent summarizes
   its understanding and creates a local `research_profile.json` only after
   you confirm it.
3. **Personal editions.** The agent offers a recurring edition and asks for
   schedule and time zone. It creates nothing without consent, and execution
   starts only after the library and index are ready.
4. **Research materials.** The agent offers three choices: a folder of books
   and articles, an existing TairaSearch index, or help discovering open
   research sources. Scanning, downloading, and indexing have separate,
   explicit approval boundaries.
5. **Library acquisition.** Once materials are connected, the agent separately
   offers a second automation for discovering and downloading new sources. It
   does not replace the personal edition and is not duplicated if it already
   exists.
6. **A preview edition.** The agent shows initial cards with exact file and
   fragment references. You can ask for more context, fewer military stories,
   a different style, or new subjects; the profile is refined without
   rewriting the search engine.

## Two independent automations

| Task | What it may do automatically | What still needs separate consent |
| --- | --- | --- |
| Personal news | Retrieve candidates, check context and repeats, and prepare an edition from the profile | It does not invent cards to reach a quota or modify the library |
| Library acquisition | Discover suitable sources and optionally save approved material to staging | It does not promote files into the main corpus or update the index |

Both tasks are opt-in. Cadence, local time, time zone, and limits are repeated
before creation. New documents first enter `work/library-staging/`; promotion
and indexing require separate approval.

## What TairaSearch can do

- search multilingual TXT, Markdown, JSON, and PDF documents, while the
  acquisition workflow can also validate HTML, XML/TEI, and EPUB;
- retrieve neighbouring context instead of quoting one isolated line;
- combine fast, reproducible Python retrieval with AI editorial review;
- distinguish a confirmed repeat, a probable repeat, a new angle, and a new
  finding;
- request disjoint later batches when the first candidates fail review;
- update the publication journal atomically and idempotently;
- run without the OpenAI API or a separate LLM service.

## Important limitations

- Edition quality depends on the coverage and quality of the research library.
- AI reviews meaning and writes prose, but historical claims still deserve
  critical human review.
- Unclear or apparently unauthorised copies may be reported but are not
  downloaded automatically. Access controls are never bypassed.
- A private corpus may be indexed locally without licence metadata, but it is
  not part of the public release.
- The public repository contains only synthetic Russian, Japanese, and English
  material. It contains no personal library, production database, publication
  journal, secrets, automation, or chat history.
- Installation through an arbitrary AI agent depends on its filesystem, shell,
  network, and scheduling permissions. If a capability is unavailable, the
  agent must stop at that boundary and explain it.

## Try it without a personal library

Ask the agent:

> **Show me the reproducible TairaSearch demo in this repository and explain what Python did and what the AI did.**

The demo builds a separate index from fictional material and creates five
`[DEMO]` cards. It does not use the internet, personal files, or the OpenAI API.
See [docs/ai-demo.md](docs/ai-demo.md).

Python does not call or impersonate a model: it produces candidates and source
context, while the agent performs the editorial analysis. For a manual setup,
the environment guard is `assert sys.prefix != sys.base_prefix`; the complete
commands remain in the developer guide.

## Developer and manual setup

Architecture, manual installation, indexing commands, tests, and public-build
instructions live in [docs/development.md](docs/development.md). The complete
first-run conversation is documented in
[docs/research-onboarding.md](docs/research-onboarding.md), and safe library
acquisition in [docs/source-acquisition.md](docs/source-acquisition.md).

The project is distributed under the [MIT License](LICENSE).
