# Codex request: configure my research

Help me configure TairaSearch through a short, natural conversation. Do not
ask me to edit JSON or ask technical questions about SQLite, FTS, chunks, or
the index schema.

1. First ask for an existing index or corpus folder. Never rebuild an existing
   index without my permission. If only a corpus exists, run
   `build_index.py <folder> --scan-only`, explain the simple summary, and ask
   before creating a new index under `work/`.
2. Briefly ask about the research area; important people, events, or works if
   any; preferred kinds of findings; result language; and the desired detail
   and presentation style. Ask one question or a small group at a time, skip
   what is already clear, accept “everything,” and allow an empty people list.
3. Summarize your understanding and let me correct it. Do not invent name
   variants, sources, or corpus coverage.
4. After confirmation, create a local `research_profile.json` using the format
   documented in `docs/research-onboarding.md` and the committed examples in
   `examples/profiles/`. I should not edit it manually. Translate every free-form
   preference that should affect retrieval into actual `interests[].terms`,
   interest `weight`, material types, or source filters. `notes` do not affect
   retrieval, so never store a preference that should change selection only
   there. Purely editorial preferences—such as vivid, expanded cards that
   explain why a finding matters—belong in `finding_preferences.notes` and must
   be applied when writing cards. Use only terms or name variants I confirmed.
5. Run `taira_search.py research-findings` with that profile, an output under
   `work/`, and `--preview`. Never run `record-publication` or change
   `used_finds.csv`.
6. Read the candidates and `examples/codex/daily-news-prompt.md`. Use only the
   latter's editorial, style, and accuracy rules—not its manifest or
   publication instructions. Show a small preview with exact `relative_path`
   and `chunk_id` references, keeping source report, literary narrative,
   scholarship, and cautious inference distinct.
7. Ask whether the findings and presentation feel right. Apply retrieval
   feedback by changing effective terms, weights, and filters and rerunning the
   preview, not by changing search code. Save style-only feedback in
   `finding_preferences.notes` and apply it when rewriting the cards. If the
   profile is right but individual candidates fail source or semantic review,
   keep the profile and request a disjoint next batch with `--continue-from`.
8. After I explicitly confirm the profile and accept the preview, explain how
   to reuse it with `examples/codex/research-workflow.md` for manual runs. Then
   separately ask whether I want recurring automatic findings. Do not create
   or change any schedule without my explicit agreement.
9. If I agree, ask for cadence, local time, and time zone, then repeat the
   settings before creation. Create a Codex automation that uses the saved
   `research_profile.json` and follows `examples/codex/research-workflow.md`;
   do not alter other automations. If automatic creation is unavailable, open
   or offer `codex://automations` (Scheduled) and provide a ready-to-paste task
   with the same paths, profile, and workflow. If I decline, leave manual runs
   available and do not keep prompting.

If a preference or name has no hit, say that the checked index did not support
it. Do not claim that the entire original corpus is exhausted.
