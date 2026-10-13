# Example: daily-news automation

This is a sanitized prompt template, not an active automation configuration.

> Run the deterministic daily candidate command against the configured local
> index. Read the selected chunk and its neighbouring context; do not rely only
> on the short candidate summary. Search indexed scholarship separately when it
> can support an interpretation. Produce up to five source-grounded historical
> cards from the returned candidates and never invent cards to reach five.
>
> Write for a curious reader, not for a search-system developer. Open with the
> most interesting supported action, fate, object, contradiction, or cultural
> detail. Explain who the people are and why the episode matters only when the
> supplied evidence supports that context. Prefer human-scale history—daily
> life, illness, relationships, art, belief, fear, material objects—over a dry
> catalogue summary. Vary structure and length according to the evidence; do
> not pad a thin finding.
>
> Keep evidence layers explicit: a primary or contemporary source reports; a
> literary source narrates; scholarship interprets; the model may make only a
> clearly labelled cautious inference. Never convert a literary image or a
> researcher's proposal into an established fact, and never invent dialogue,
> emotion, motive, participants, dates, places, causes, or circumstances.
> Preserve exact attribution. Put `relative_path`, `chunk_id`, source class,
> and any scholarship reference in one compact source block at the end rather
> than interrupting the story with technical metadata.
>
> Before choosing cards, inspect `semantic_review` for every candidate. Compare
> the supported claim in the candidate with every supplied history match and
> candidate match: actor, action or scholarly thesis, object, time and place
> when stated, outcome, source role, and the material detail or interpretation
> that would actually be new. Shared people, topics, dates, or source names are
> reasons to compare; none is a duplicate verdict by itself. OCR changes,
> reindexing, paraphrase, and translation require this claim-level comparison.
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

If `daily-five` returns zero candidates, report only that no new finding passed
the current filters. Do not claim that the corpus is exhausted, create cards or
a publication manifest, or update the publication journal. A non-zero command
exit is an error to report, not an empty news batch.

Before returning the cards in chat:

1. Save exactly the selected cards to
   `work/publications/<publication-id>.json`. Include a unique
   `publication_id` and a `cards` array. Each card must contain its stable
   `id`/`chunk_id`, `type` (`event` or `interpretation`), `persons`, `topics`,
   `short_description`, `source`, and its complete final Markdown in
   `card_markdown`.
2. Run `python taira_search.py record-publication
   work/publications/<publication-id>.json`.
3. Return the saved card text only if that command exits with code 0. If it
   fails, do not publish the cards; report the error and keep the JSON for a
   retry.

Do not edit `used_finds.csv` directly. Rerunning the command with the same JSON
is safe. The JSON is also the recovery copy if the journal update succeeds but
the chat response is not delivered.

