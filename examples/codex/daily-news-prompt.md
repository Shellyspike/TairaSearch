# Example: daily-news automation

This is a sanitized prompt template, not an active automation configuration.

> Use the saved-profile `research-findings --preview` workflow against the
> configured local index. Follow the matching `research-workflow.md` or `.ru.md`.
> Read the selected chunk and its neighbouring context; do not rely only
> on the short candidate summary. Search indexed scholarship separately when it
> can support an interpretation. Produce up to five source-grounded historical
> cards from the returned candidates and never invent cards to reach five.
>
> Write for a curious reader, not for a search-system developer.
> Before writing, read `docs/editorial-system.md` and
> `examples/codex/reader-review.ru.md`. They define the current writing and
> independent-review procedure. Make every story intelligible to a newcomer:
> introduce roles and name/title identities, preserve necessary context and causal
> links, and use natural Russian. Usually follow chronology, preserve source humour,
> vary composition and length, and end with the plot rather than a mandatory moral.
> Treat 150–250 words as guidance. Do not invent dialogue, thoughts, motives,
> circumstances or outcomes. Keep necessary attribution to the source's evidence
> layer; legends and literary anecdotes remain stories attributed as such.
> Reader cards end with a compact author/work/page citation. Keep technical IDs,
> paths, novelty classes, dossier quotations and review details in separate
> structured working artifacts, not in the reader text.
>
> A separate `spawn_agent` reviewer must first save a reading of only finished
> cards, rules and available approved examples, without research dossiers. Only
> then send the dossiers and full evidence. The second stage checks source support
> and essential omissions: causes, circumstances, whole dialogue units and the
> details needed for the outcome. Require concrete reasons and a source-detail map.
> Fix remarks and return revisions to that agent, maximum three rounds total.
> Exclude unapproved cards; do not register or publish drafts when the reviewer is
> unavailable. A pass alone is insufficient: the author still judges the final
> narrative. Save exact reviewed texts, remarks and final hashes under ignored
> `work/research/`. These checks are instructions, not a programmatic CLI gate.
>
> Before choosing cards, inspect `semantic_review` for every candidate. Compare
> the supported claim in the candidate with every supplied history match and
> candidate match: actor, action or scholarly thesis, object, time and place
> when stated, outcome, source role, and the material detail or interpretation
> that would actually be new. Shared people, topics, dates, or source names are
> reasons to compare; none is a duplicate verdict by itself. OCR changes,
> reindexing, paraphrase, and translation require this claim-level comparison.
> A matching `chunk_id` is only a positional clue: if the supported claim has
> changed, do not treat it as a confirmed repeat. Likewise, near-identical
> wording can reverse meaning through a changed number, date, negation, action,
> or outcome; compare those facts explicitly.
>
> Classify every reviewed relation as exactly one of:
>
> - `confirmed_repeat`: the same event or scholarly conclusion with no supported
>   substantive addition;
> - `probable_repeat_review`: the core claim may be the same, but the supplied
>   evidence is insufficient for a confident decision;
> - `new_angle`: a known story gains a supported material detail, different
>   outcome, or independent scholarly interpretation;
> - `new_finding`: the supported action, object, outcome, or context is distinct.
>
> State the classification and a short evidence-based reason.
> Do not make a card from `confirmed_repeat`. Keep `probable_repeat_review` visible for human review
> instead of silently deleting or publishing it. `new_angle` and `new_finding`
> remain eligible for cards. A new publication date or source is not a new angle
> unless its evidence adds something substantive; scholarship must be compared
> by its actual conclusion, not merely by article title or source type.
>
> Do not modify retrieval rules or rebuild the index during the editorial run.

If `research-findings --preview` returns zero candidates, report only that no new
finding passed the current filters. Do not claim that the corpus is exhausted, create cards or
a publication manifest, or update the publication journal. A non-zero command
exit is an error to report, not an empty news batch.

This workflow requires a scheduled-task result that can contain the complete
edition. A status-only heartbeat or notification envelope is not a compatible
delivery surface. Detect that limitation before journal registration; do not
register a new edition when the current run cannot return its full text.

For an explicitly requested unregistered preview, finish the same editorial
review and show accepted cards without registration; label it as a preview.
Do not report reviewer failure as absence of findings. Previously registered
editions are recovered unchanged, without applying new writing rules retroactively.

Before returning a newly authorized publication in chat, complete the independent
review above and check publication access in the exact publishing environment.
Then use the existing CLI contract (no new flags or manifest version):

1. Save exactly the selected cards to
   `work/publications/<publication-id>.json`. Include a unique
   `publication_id` and a `cards` array. Each card must contain its stable
   `id`/`chunk_id`, `type` (`event` or `interpretation`), `persons`, `topics`,
   `short_description`, `source`, and its complete final Markdown in
   `card_markdown`.
2. Run `python taira_search.py record-publication
   work/publications/<publication-id>.json`.
3. Only if that command exits with code 0, run `python taira_search.py
   render-publication work/publications/<publication-id>.json`. Return the
   complete stdout of `render-publication` as the primary chat response. Do not
   summarize it, substitute titles or annotations, or return only a technical
   report. A short technical note may appear only after all card Markdown.
4. If registration fails, do not run `render-publication` and do not publish
   the cards. Report one clear cause and recovery action, keep the JSON, and do
   not spend the daily run on repeated retries or lengthy permission
   diagnostics.

Do not edit `used_finds.csv` directly. Rerunning the registration command with
the same JSON is safe, but recovery does not need to rerun it. The JSON is the
recovery copy if the journal update succeeds but the chat response is not
delivered: inspect chat/run history, then run `render-publication` against the
same manifest and return its exact output without a new search, rewrite, or
registration. `publication-status` distinguishes a prepared manifest from a
fully registered one and always reports chat delivery as unconfirmed because
the local CLI receives no display acknowledgement from Codex.

The three states are intentionally separate:

- `prepared`: the validated manifest contains every complete `card_markdown`;
- `registered`: every card ID from that manifest is present in the journal;
- `delivered`: the complete edition is visibly present in the task/chat result.

TairaSearch persists the first two states. It cannot persistently prove the
third from the local CLI. When run history is ambiguous, ask before replaying
the edition because recovery may show the same cards twice. Do not promise
exactly-once chat delivery.


