# Ready-to-use Codex app request (English)

Run the public TairaSearch AI demonstration in this local repository.

1. Use the repository's verified Python 3.11 environment to run `run_demo.py`.
   Confirm that it creates `work/demo/ai-input.json` with exactly five
   candidates. If Python or a dependency fails, report the real error instead
   of treating it as an empty result.
2. Read `examples/codex/daily-news-prompt.md` and the generated
   `work/demo/ai-input.json`. Use the daily prompt only for its editorial and
   evidence rules: this request overrides all publication, manifest, and
   journal instructions.
3. Treat `ai-input.json` as the only evidence. Do not browse the web or use
   another corpus. Every input text is synthetic.
4. Write exactly five English Markdown cards, in candidate order, to
   `work/demo/ai-cards.en.md`. Begin every title with `[DEMO]` and state in
   every card that it is fictional test material, not a historical claim.
5. Make each card a compact, engaging story. Lead with the most vivid supported
   detail and explain its human, historical, or cultural interest. Never talk
   about search quality in the story. Vary the shape and length naturally.
6. Clearly distinguish what the event source says, what the synthetic research
   note interprets, and any cautious inference you make. A literary source is
   a literary scene, not proof that an event happened. Invent no dialogue,
   emotion, motive, person, cause, date, place, or circumstance.
7. End each card with a compact source block containing the event
   `relative_path`, `chunk_id`, classification, and the related scholarship
   path and chunk when present. Do not imply that historical-looking folder
   names identify real quotations.
8. Do not edit tracked files, publish anything, or update `used_finds.csv`.
   Verify the five demo labels and every path/chunk reference, then report the
   result. Human review is still required.
