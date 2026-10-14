# Codex request: configure my research

Help me configure TairaSearch through a short, natural conversation. Do not
ask me to edit JSON or ask technical questions about SQLite, FTS, chunks, or
the index schema.

1. First ask for an existing index or corpus folder. Never rebuild an existing
   index without my permission. If only a corpus exists, run
   `build_index.py <folder> --scan-only`, explain the simple summary, and ask
   before creating a new index under `work/`.
2. Briefly ask about the research area; important people, events, or works if
   any; preferred kinds of findings; and result language. Ask one question or
   a small group at a time, skip what is already clear, accept “everything,”
   and allow an empty people list.
3. Summarize your understanding and let me correct it. Do not invent name
   variants, sources, or corpus coverage.
4. After confirmation, create a local `research_profile.json` using the format
   documented in `docs/research-onboarding.md` and the committed examples in
   `examples/profiles/`. I should not edit it manually. Translate every free-form
   preference that should affect retrieval into actual `interests[].terms`,
   interest `weight`, material types, or source filters. `notes` are explanatory
   only and do not affect search; never store an actionable preference only in
   `notes`. Use only terms or name variants I confirmed.
5. Run `taira_search.py research-findings` with that profile, an output under
   `work/`, and `--preview`. Never run `record-publication` or change
   `used_finds.csv`.
6. Read the candidates and `examples/codex/daily-news-prompt.md`. Use only the
   latter's editorial, style, and accuracy rules—not its manifest or
   publication instructions. Show a small preview with exact `relative_path`
   and `chunk_id` references, keeping source report, literary narrative,
   scholarship, and cautious inference distinct.
7. Ask whether the findings feel right. Apply feedback by changing only
   the profile's effective terms, weights, and filters and rerunning the
   preview, not by changing search code. Updating `notes` alone is not an
   implementation of feedback. If the profile is right but individual
   candidates fail source or semantic review, keep the profile and request a
   disjoint next batch with `--continue-from` instead.
8. When I accept the preview, explain briefly how the saved profile can be
   reused with `examples/codex/research-workflow.md` for later manual runs. Do
   not create or change an automation.

If a preference or name has no hit, say that the checked index did not support
it. Do not claim that the entire original corpus is exhausted.
