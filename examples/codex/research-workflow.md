# Codex request: run my saved research profile

Use this repository as a local research tool. Python retrieves, ranks, checks
technical duplicates, and supplies source context. You are the researcher and
editor: inspect the evidence, decide semantic novelty, continue searching when
needed, and choose the final findings.

1. Use this workflow for retrieval and publication. Use only
   `examples/codex/daily-news-prompt.md` to write cards and
   `examples/codex/reader-review.ru.md` for an independent reading. Do not
   replace this profile-driven workflow with legacy `daily-five`.
2. If `research_profile.json` does not exist, follow
   `examples/codex/research-onboarding.md`: interview me briefly, confirm the
   interpretation, create the ignored local profile, and run its preview.
   If the profile exists, use its area, mode, interests, filters, preferences
   for kinds of findings, and a concise style preference from
   `finding_preferences.notes`. Apply that preference together with the short
   author brief; it must not contain another writing guide or replace source
   verification.
3. Resolve the intended existing index from my request or the project. If none
   is clear, or several are plausible, ask me for the path instead of guessing.
   Do not rebuild the index, alter the corpus, change the profile's interests,
   or modify `used_finds.csv` while retrieving candidates.
4. Run `taira_search.py research-findings --preview` once for the batch, saving
   the lossless result under `work/research/`. The command also saves a smaller
   `*.editorial.json` beside it. Do not use `--json` to print the payload in the
   terminal. Read the compact packet once and treat `final` as a Python
   shortlist, not an editorial verdict. It contains the theses, history
   matches, comparison grounds, and references needed for first-pass review;
   the full JSON remains the canonical evidence store. Inspect every
   `semantic_review` entry in this compact view.
5. For uncertain relations classify the supported claims as
   `confirmed_repeat`, `probable_repeat_review`, `new_angle`, or `new_finding`.
   Do not publish confirmed repeats. Keep unresolved probable repeats visible
   for human review. Shared people, topics, sources, dates, wording, or a
   positional `chunk_id` are comparison clues, not proof by themselves.
6. If fewer than the profile's maximum number of strong findings survive,
   request another batch with `--continue-from PREVIOUS_FULL_RESULT.json` and a
   new output path. Use one compact overview for that batch and do not reread a
   result file unless a concrete unresolved comparison requires it. If the JSON says no more
   candidates are available at the current depth, one bounded rerun may raise
   `--top-per-interest` or `--pool-size`; keep the same profile and filters.
   Stop when enough strong findings exist or a pass yields no new candidate
   IDs. Never invent a finding to meet a quota.
7. After the compact review, choose provisional finalists. Then make one
   consolidated request for their full source context and all doubtful
   relations, for example:

   `python taira_search.py research-context work/research/batch-1.json --chunk-id ID1 --chunk-id ID2 --include-required-review --output work/research/batch-1.review.json`

   Read that review packet once. It reuses the saved full result and includes
   linked comparison candidates; it does not repeat retrieval. Treat
   historical, literary, scholarly, and other permitted material according to
   the profile. Use the read-only `search` and `context` commands only when the
   saved evidence lacks necessary corroboration or scholarship, and reuse their
   result instead of issuing the same search again. Verify a researcher's
   actual conclusion and distinguish it from historical-source evidence.
8. After source and novelty checks, independently select reader-worthy stories
   and write them under the short author brief. When an independent reader is
   available, give them only the finished cards and the short reader brief.
   Check their concrete questions against the dossier and revise when a question
   reveals a real gap. Do not require a formal `pass`, hashes, multiple rounds,
   or a literary-process report. Reader cards end with a compact source; IDs,
   paths, novelty decisions, and evidence remain in structured working data.
9. Use the documented commands directly. Do not call `--help`, inspect tests or
   source code, or split one saved packet into repeated tool reads merely to
   rediscover standard syntax. Minimize tool calls without reducing candidate
   count, source criticism, factual checks, scholarly attribution, or semantic
   repeat review.
10. Retrieval and preview must not change the journal. Only if my request
    explicitly includes publication, save the exact finalized cards to a local
    manifest under `work/` and use the existing `record-publication` command.
    After exit code 0, run `render-publication` with that same manifest and
    return its complete stdout as the primary chat response. Do not replace it
    with titles, annotations, counts, or a technical status; a short status may
    follow the complete edition. If registration fails, keep the manifest,
    report the single actionable error, and do not render or publish the cards.
    The commands prove preparation and journal registration, not display to the
    user. If registration succeeded but delivery is unconfirmed, check the
    chat/run history and recover by running `render-publication` on the same
    manifest without another search, rewrite, or registration. Never edit the
    CSV directly.

Errors reading the index, profile, source context, or journal are failures to
report. Do not turn them into an empty result. Do not claim the corpus is
exhausted merely because current profile terms or limits produced no finding.



## Scope and person review

See `docs/retrieval-discovery.md`. The whole candidate_pool (final + alternates)
is unreviewed; retrieval_excerpt is raw evidence, not a story. Resolve scope_review
as accepted, rejected or uncertain with a reason and exact quotations before
novelty and editorial selection. Reject out-of-area or uncertain passages.
For focused_people, identify a selected person and verify a substantive connection
to the action, not just their name. Preserve the profile's mode and preferred_kinds.
New manifests carry root search_mode and focus_people (names), and each card has
scope_review: status=accepted, reason, evidence (chunk_id/quote objects), plus
focus_person in person mode. Pending/uncertain cannot be published. Legacy
manifests remain unchanged. coverage.discovery explains source omissions;
continuation advances through document positions instead of repeating FTS tops.
