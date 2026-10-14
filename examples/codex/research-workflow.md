# Codex request: run my saved research profile

Use this repository as a local research tool. Python retrieves, ranks, checks
technical duplicates, and supplies source context. You are the researcher and
editor: inspect the evidence, decide semantic novelty, continue searching when
needed, and choose the final findings.

1. Read `docs/ai-workflow.md` and `examples/codex/daily-news-prompt.md`. From
   the latter use the editorial style, source criticism, factuality, semantic
   review classes, and publication-safety rules. Do not replace this
   profile-driven workflow with legacy `daily-five`.
2. If `research_profile.json` does not exist, follow
   `examples/codex/research-onboarding.md`: interview me briefly, confirm the
   interpretation, create the ignored local profile, and run its preview.
   If the profile exists, read `finding_preferences.notes` and apply its saved
   preferences for detail, tone, and presentation. Those notes do not alter
   Python ranking and never replace source verification.
3. Resolve the intended existing index from my request or the project. If none
   is clear, or several are plausible, ask me for the path instead of guessing.
   Do not rebuild the index, alter the corpus, change the profile's interests,
   or modify `used_finds.csv` while retrieving candidates.
4. Run `taira_search.py research-findings --preview`, saving the first result
   under `work/research/`. Treat `final` as a Python shortlist, not an editorial
   verdict. Inspect `final`, `alternates`, every `semantic_review`, and the
   supplied neighbouring context.
5. For uncertain relations classify the supported claims as
   `confirmed_repeat`, `probable_repeat_review`, `new_angle`, or `new_finding`.
   Do not publish confirmed repeats. Keep unresolved probable repeats visible
   for human review. Shared people, topics, sources, dates, wording, or a
   positional `chunk_id` are comparison clues, not proof by themselves.
6. If fewer than the profile's maximum number of strong findings survive,
   request another batch with `--continue-from PREVIOUS_RESULT.json` and a new
   output path. Inspect that batch in the same way. If the JSON says no more
   candidates are available at the current depth, one bounded rerun may raise
   `--top-per-interest` or `--pool-size`; keep the same profile and filters.
   Stop when enough strong findings exist or a pass yields no new candidate
   IDs. Never invent a finding to meet a quota.
7. Treat historical, literary, scholarly, and other permitted material types
   according to the profile. Use the read-only `search` and `context` commands
   when a candidate needs more indexed source context, corroboration, or a
   separate scholarship search. Python returns those passages; you decide what
   they support. Verify a researcher's actual conclusion before using
   scholarship, and distinguish it from evidence in historical sources.
8. Write only the findings that survive your source and semantic review, with
   exact `relative_path`, `chunk_id`, source role, and cautious attribution.
   Follow the saved style: for vivid, expanded cards, open with a strong
   supported detail or conflict, give enough context, and explain why the
   finding matters without dramatizing beyond the source. Explain briefly when
   fewer results were justified.
9. Retrieval and preview must not change the journal. Only if my request
   explicitly includes publication, save the exact finalized cards to a local
   manifest under `work/` and use the existing `record-publication` command.
   Publish only after that command succeeds. Never edit the CSV directly.

Errors reading the index, profile, source context, or journal are failures to
report. Do not turn them into an empty result. Do not claim the corpus is
exhausted merely because current profile terms or limits produced no finding.
