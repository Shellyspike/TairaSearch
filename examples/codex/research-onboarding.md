# Codex request: configure my research

Help me configure TairaSearch through a short, natural conversation. Do not
ask me to edit JSON or ask technical questions about SQLite, FTS, chunks, or
the index schema.

1. First ask about the research area; important people, events, or works if
   any; preferred kinds of findings; result language; and the desired detail
   and presentation style. Ask one question or a small group at a time, skip
   what is already clear, accept “everything,” and allow an empty people list.
2. Summarize your understanding and let me correct it. Do not invent name
   variants, sources, or corpus coverage.
3. After confirmation, create a local `research_profile.json` using the format
   documented in `docs/research-onboarding.md` and the committed examples in
   `examples/profiles/`. I should not edit it manually. Translate every free-form
   preference that should affect retrieval into actual `interests[].terms`,
   interest `weight`, material types, or source filters. `notes` do not affect
   retrieval, so never store a preference that should change selection only
   there. Purely editorial preferences—such as vivid, expanded cards that
   explain why a finding matters—belong in `finding_preferences.notes` and must
   be applied when writing cards. Use only terms or name variants I confirmed.
4. Only after confirming my interests, ask where the research materials should
   come from. Do not assume that a local path, profile index, or personal
   library is already known. Offer three plain-language choices:
   1) “I have a folder of documents”;
   2) “I have a ready TairaSearch index”;
   3) “I have nothing yet—help me find open sources.”
5. For a document folder, ask for its path and run only
   `build_index.py <folder> --scan-only`. Explain supported-file counts and
   errors; scanning must not create a database. Separately ask permission to
   create a new index under `work/`, and run the existing indexer only after
   consent. Never use `--rebuild` on an existing database or delete missing
   documents.
6. For a ready index, ask for its path and connect read-only without rebuilding
   the corpus or index. Check availability with a safe read command. If the
   format is incompatible or the file is unavailable, report the error and
   return to the material choice without attempting an automatic repair.
7. If there are no materials, use available web search, browser, or connected
   catalogues to find a small set of suitable open sources for the confirmed
   profile. Use `examples/codex/source-discovery-prompt.md` only as a checklist,
   not as an automation. For every option state the owner or repository, URL,
   format, stated reuse terms, and expected relevance. Download nothing until
   I explicitly select and authorize the sources. After consent, download only
   the selected material to a local folder under `work/`, run `--scan-only`,
   show the result, and ask again before indexing. If search or download tools
   are unavailable, explain the limitation honestly and ask me for a document
   folder or ready index. Do not turn this one-time setup step into automatic
   library acquisition; that belongs to version 0.4.
8. Once the library and index are ready, run `taira_search.py research-findings`
   with the confirmed profile, an output under
   `work/`, and `--preview`. Never run `record-publication` or change
   `used_finds.csv`.
9. Read the candidates and `examples/codex/daily-news-prompt.md`. Use only the
   latter's editorial, style, and accuracy rules—not its manifest or
   publication instructions. Show a small preview with exact `relative_path`
   and `chunk_id` references, keeping source report, literary narrative,
   scholarship, and cautious inference distinct.
10. Ask whether the findings and presentation feel right. Apply retrieval
   feedback by changing effective terms, weights, and filters and rerunning the
   preview, not by changing search code. Save style-only feedback in
   `finding_preferences.notes` and apply it when rewriting the cards. If the
   profile is right but individual candidates fail source or semantic review,
   keep the profile and request a disjoint next batch with `--continue-from`.
11. After I explicitly confirm the profile and accept the preview, explain how
   to reuse it with `examples/codex/research-workflow.md` for manual runs. Then
   separately ask whether I want recurring automatic findings. Do not create
   or change any schedule without my explicit agreement.
12. If I agree, ask for cadence, local time, and time zone, then repeat the
   settings before creation. Create a Codex automation that uses the saved
   `research_profile.json` and follows `examples/codex/research-workflow.md`;
   do not alter other automations. If automatic creation is unavailable, open
   or offer `codex://automations` (Scheduled) and provide a ready-to-paste task
   with the same paths, profile, and workflow. If I decline, leave manual runs
   available and do not keep prompting.

If a preference or name has no hit, say that the checked index did not support
it. Do not claim that the entire original corpus is exhausted.
