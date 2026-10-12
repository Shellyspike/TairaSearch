# Codex request: cards from an existing AI handoff

`work/demo/ai-input.json` has already been generated in this project. Do not
run `run_demo.py`, any other Python command, or dependency installation.

Read that JSON and use only the evidence it contains. Also read
`examples/codex/daily-news-prompt.md`, but use only its editorial rules and its
requirements for accuracy, style, and separation of source layers. Its
operational instructions about a manifest, publication, and journal updates do
not apply to this demo and must not be followed. Verify that the JSON has
exactly five candidates, then create `work/demo/ai-cards.en.md` with five
English cards in input order.

Every card must have a `[DEMO]` title, explicitly say that it is fictional test
material rather than a historical claim, and separate the event account from
scholarship and cautious inference. Include the event source and related
scholarship `relative_path` and `chunk_id`. Do not invent facts, browse the
web, modify any other files, SQLite databases, or automations, publish the
cards, or create or update any manifest or journal. Finally verify the card
count and every fragment reference.
