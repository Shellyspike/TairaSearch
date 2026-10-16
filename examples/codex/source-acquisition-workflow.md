# Codex request: discover and stage new sources

Grow the local TairaSearch research library from the confirmed
`research_profile.json`. This workflow is independent from historical-card
generation: do not run `research-workflow` and do not change `used_finds.csv`.

1. Read `research_profile.json`, `docs/source-acquisition.md`, and the local
   `source_acquisition_policy.json` if present. Follow `interests[].terms`,
   weights, material types, and source filters. Add no built-in people, periods,
   languages, or topics.
2. Without a local policy, ask before every download. Agree on per-run file
   count, per-file and total sizes, and whether automatic downloads are allowed.
   A refusal permits a report of candidates only; it permits neither downloads
   nor a schedule.
3. Choose a few narrow directions from the profile and rotate them between
   runs. Discovery may search official repositories and also unofficial
   libraries, mirrors, community archives, and sites of uncertain reputation.
   Do not discard or hide a useful bibliographic lead solely because of the
   site's category. Record tried directions under `work/source-acquisition/`
   so future runs do not repeat one query forever.
4. Separate discovery from download permission. Record unclear,
   apparently unauthorised, paywalled, or uncertain-provenance leads in the
   report as “found but not downloaded”; do not put them in the download
   manifest or automatic staging. Search title, author, DOI, identifiers, and
   title variants for an accessible lawful alternative. If a site is blocked
   geographically or fails technically, look for legitimate repository,
   author, publisher, preprint, library, or archive copies. Never bypass
   authentication, paywalls, robots controls, regional restrictions, or rate
   limits. Do not present a catalogue record, abstract, or preview as a
   complete text.
5. Put only candidates with evidence-backed `open`, `public-domain`, or
   `authorized` access in a JSON download manifest following
   `examples/acquisition/candidates.example.json`. Include title, author or
   organisation, direct URL, format, access status, and the matching profile
   interest. Include DOI, title variants, language, repository, and reuse terms
   when known; never invent missing metadata.
6. Before downloading, run the read-only duplicate check:

   ```powershell
   python source_acquisition.py check --manifest work/source-acquisition/candidates.json --profile research_profile.json --journal work/source-acquisition/downloads.json --db taira_index.sqlite3 --report work/source-acquisition/check-report.json
   ```

   Use URL, DOI, title and variants, filename, journal, and the existing index.
   Do not scan all of Google Drive. Do not automatically download a `duplicate`;
   explain ambiguous matches to the user.
7. In manual mode, show the exact eligible sources, links, formats, access
   terms, and limits. Only after explicit consent run `stage` with
   `--approve-downloads`. In scheduled mode only a previously approved local
   policy with `automatic_downloads: true` may replace that flag:

   ```powershell
   python source_acquisition.py stage --manifest work/source-acquisition/candidates.json --profile research_profile.json --journal work/source-acquisition/downloads.json --db taira_index.sqlite3 --staging work/library-staging --policy source_acquisition_policy.json --report work/source-acquisition/stage-report.json
   ```

8. Read the report and each metadata file. Python preserves original bytes,
   extracts text, and technically checks PDF, HTML, TXT, Markdown, XML/TEI, and
   EPUB. You judge completeness, bibliography, relevance, and the legitimacy of
   the selected source. Do not correct OCR, historical wording, or spelling in
   either the original or extracted text. Show every result with its `source_id`,
   title, author, URL, format, size, staging paths for the original and extracted
   text, extracted character count, and, for PDF, the sampled beginning, middle,
   and end pages. List duplicates, errors, and partial-run failures separately
   with reasons; successfully staged items remain available for review.
9. Nothing leaves staging automatically. Show all `ready_for_review` items,
   then ask a separate question: “Add approved SOURCE_ID values to corpus
   PATH_TO_CORPUS and update index PATH_TO_INDEX?” On refusal or without an
   answer, do not run `promote`, `build_index.py`, or indexing; leave the files
   in staging. Only separate explicit consent for the named IDs, corpus, and
   index permits promotion and incremental indexing through the existing
   indexer:

   ```powershell
   python source_acquisition.py promote --source-id SOURCE_ID --staging work/library-staging --corpus PATH_TO_CORPUS --journal work/source-acquisition/downloads.json --db PATH_TO_INDEX --approve --index --report work/source-acquisition/promote-report.json
   ```

   Repeat the paths and IDs first. Afterwards, show the promotion and indexing
   status from the report. If indexing fails, explain that files were promoted
   but staging and the journal remain for diagnosis; do not claim that the
   index was updated. Never use `--rebuild`, delete missing documents, or
   replace an existing index.
10. Report every run in separate groups: downloadable or staged sources;
    valuable leads found but not downloaded because rights or provenance are
    unclear; geographically or technically inaccessible leads and alternatives
    searched; duplicates, unusable items, and errors; and items awaiting
    approval and indexing. Include titles, authors, URLs, staging paths, and
    text quality where applicable. If no suitable source exists, say so. Never
    disguise a search, network, index, or parsing error as zero results.
11. Create a schedule only after explicit agreement on cadence, local time,
    time zone, limits, and `automatic_downloads`. Check existing automations
    first and do not create a duplicate acquisition task for the same project. The
    acquisition task uses this workflow; the research-card task uses
    `research-workflow.md`. They are independent. A pre-approved policy permits
    a scheduled task to discover sources and run only `check` and `stage` into
    staging. A scheduled run must not call `promote`, `build_index.py`, or
    `--index`, and must not copy files into the corpus. It reports pending
    materials; promotion and indexing always require separate explicit consent
    from the user in an interactive conversation.

If web search, downloads, or scheduling are unavailable in the current Codex,
state the limitation and provide manual commands. Never pretend that a source
was found or downloaded.
