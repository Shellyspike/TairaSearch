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
   runs. Search open scholarly repositories, libraries, university archives,
   and other relevant lawful sources. Record tried directions under
   `work/source-acquisition/` so future runs do not repeat one query forever.
4. Never bypass authentication, paywalls, robots controls, or rate limits.
   Never download from pirate or clearly unauthorised libraries. A useful lead
   there may be reported separately as “not downloaded”, but must not enter the
   download manifest. Do not present a catalogue record, abstract, or preview
   as a complete text.
5. Put strong candidates in a JSON manifest following
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
   either the original or extracted text.
9. Nothing leaves staging automatically. Show all `ready_for_review` items.
   After separate approval of exact IDs, promotion and incremental indexing may
   call the existing indexer:

   ```powershell
   python source_acquisition.py promote --source-id SOURCE_ID --staging work/library-staging --corpus PATH_TO_CORPUS --journal work/source-acquisition/downloads.json --db PATH_TO_INDEX --approve --index --report work/source-acquisition/promote-report.json
   ```

   Repeat the paths and IDs first. Never use `--rebuild`, delete missing
   documents, or replace an existing index.
10. Report every run: found and downloaded titles, authors, and URLs; staging
    paths and text quality; duplicate, unusable, and inaccessible counts; and
    items awaiting approval and indexing. If no suitable source exists, say so.
    Never disguise a search, network, index, or parsing error as zero results.
11. Create a schedule only after explicit agreement on cadence, local time,
    time zone, limits, and `automatic_downloads`. Check existing automations
    first and do not create a duplicate acquisition task for the same project. The
    acquisition task uses this workflow; the research-card task uses
    `research-workflow.md`. They are independent.

If web search, downloads, or scheduling are unavailable in the current Codex,
state the limitation and provide manual commands. Never pretend that a source
was found or downloaded.
