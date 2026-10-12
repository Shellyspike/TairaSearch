# Example: daily-news automation

This is a sanitized prompt template, not an active automation configuration.

> Run the deterministic daily candidate command against the configured local
> index. Read the selected chunks and their neighbouring context. Separately
> search scholarship when it adds a useful interpretation. Produce up to five
> concise historical cards from the returned candidates; never invent extra
> cards to reach five. State whether evidence is primary, literary, or
> scholarly, preserve precise source references, and avoid unsupported claims.
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

