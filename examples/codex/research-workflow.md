# Codex request: run my saved research profile

Use this repository as a local research tool. Python retrieves, ranks, checks
technical duplicates, and supplies source context. You are the researcher and
editor: inspect the evidence, decide semantic novelty, continue searching when
needed, and choose the final findings.

1. Use this workflow for retrieval and publication. Use only
   `examples/codex/daily-news-prompt.md` to write cards and
   `examples/codex/reader-review.ru.md` for an independent reading.
2. If `research_profile.json` does not exist, follow
   `examples/codex/research-onboarding.md`: interview me briefly, confirm the
   interpretation, create the ignored local profile, and run its preview.
   If the profile exists, use its area, mode, interests, filters, preferences
   for kinds of findings, and settings from `finding_preferences.notes`. The
   profile controls interests, kinds of material, result language, detail, and
   style; the short author brief supplies only common clarity and accuracy
   requirements and cannot override the profile. Profile settings do not
   replace source verification.
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
   `semantic_review` entry in this compact view. By default the command resumes
   `source_exploration` from the latest registered checkpoint under
   `work/publications/`; do not select yesterday's file manually. Thematic FTS
   still searches the whole permitted library every day.
5. For uncertain relations classify the supported claims as
   `confirmed_repeat`, `probable_repeat_review`, `new_angle`, or `new_finding`.
   Do not publish confirmed repeats. Keep unresolved probable repeats visible
   for human review. Shared people, topics, sources, dates, wording, or a
   positional `chunk_id` are comparison clues, not proof by themselves.
6. If fewer than the profile's maximum number of materials remain that match
   the profile, contain enough information for a coherent account, and do not
   repeat a publication,
   request another batch with `--continue-from PREVIOUS_FULL_RESULT.json` and a
   new output path. Use one compact overview for that batch and do not reread a
   result file unless a concrete unresolved comparison requires it. If the JSON says no more
   candidates are available at the current depth, one bounded rerun may raise
   `--top-per-interest` or `--pool-size`; keep the same profile and filters.
   Stop when the profile maximum is reached or a pass yields no new candidate
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
8. After source and novelty checks, select materials that match the profile,
   contain information for a coherent account, and do not repeat a publication,
   then write them under the short author brief. When an independent reader is
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
    manifest under `work/publications/`, copy the unchanged root
    `exploration_checkpoint` from the last full result when present, and use the
    existing `record-publication` command.
    After exit code 0, run `render-publication` with that same manifest and
    return its complete stdout as the primary chat response. Do not replace it
    with titles, annotations, counts, or a technical status; a short status may
    follow the complete edition. If registration fails, keep the manifest,
    report the single actionable error, and do not render or publish the cards.
    The commands prove preparation and journal registration, not display to the
    user. If registration succeeded but delivery is unconfirmed, check the
    chat/run history and recover by running `render-publication` on the same
    manifest without another search, rewrite, or registration.
    `record-publication` seals the checkpoint in that manifest only after the
    cards reach the journal. A failed or merely prepared manifest cannot advance
    the next edition. Never edit the seal or CSV directly.

Errors reading the index, profile, source context, or journal are failures to
report. Do not turn them into an empty result. Do not claim the corpus is
exhausted merely because current profile terms or limits produced no finding.



## Scope and person review

See `docs/retrieval-discovery.md`. The whole candidate_pool (final + alternates)
is unreviewed; retrieval_excerpt is raw evidence, not a story. Resolve scope_review
as accepted, rejected or uncertain with a reason and exact quotations before
novelty and editorial selection. Reject material outside the profile's area or
relations unsupported by the cited context. `scope_review` tests area and person
fit, not the historical truth of the evidence. Treat legends, rumours, and
disputed testimony according to the profile and identify their status when
needed. For focused_people, identify a selected person and verify a substantive connection
to the action, not just their name. Preserve the profile's mode and preferred_kinds.
New manifests carry root search_mode and focus_people (names), and each card has
scope_review: status=accepted, reason, evidence (chunk_id/quote objects), plus
focus_person in person mode. Pending/uncertain cannot be published. Legacy
manifests remain unchanged. coverage.discovery explains source omissions;
continuation advances through document positions instead of repeating FTS tops.


## Review accumulated leads before stopping

Stopping new retrieval does not end review of already retrieved material.
Before calling two batches devoid of new candidates, inspect the full context of
unreviewed leads from every batch. Uncertain authenticity, legends, and
scholarly hypotheses are not exclusions by themselves: apply the profile and
attribute them accurately. Distinguish a fragment exposed to the agent, a
fragment substantively evaluated, and a story registered as published. `seen`
and presence of a `chunk_id` in retrieval output prove exposure only, not
substantive review or publication.

Retrieval limits bound new requests, not review of accumulated leads. If the
request or automation names a local JSON file of deferred reviews, read it
before new retrieval. It is not a CLI queue: the program does not consume or
update it. For each record taken up, obtain context and save the concrete review
outcome in the run dossier. Before finishing, atomically retain in that same
local JSON every record not yet substantively reviewed, preserving its
`chunk_id` and path; repeated exposure is not a reason to remove it. A story is
published only after successful `record-publication`. Never rewrite registered
checkpoints or describe this manual local list as an automatic queue.
