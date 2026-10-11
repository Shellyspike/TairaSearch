# TairaSearch public AI demo request

Use `examples/codex/daily-news-prompt.md` as the editorial baseline and
`work/demo/ai-input.json` as the only source evidence.

This is a public demonstration, not a publication run. Every input event and
source excerpt is synthetic. The historical-looking folder names exist only to
exercise classification rules.

Produce exactly five Russian-language Markdown cards, one for each candidate,
in input order. For every card:

1. begin the title with `[ДЕМО]`;
2. state explicitly that the event is fictional test material and not a
   historical claim;
3. include `Что случилось`, `Почему это интересно`, `Фрагмент` and `Источник`;
4. preserve the source excerpt without inventing missing details;
5. cite `relative_path`, `chunk_id`, source classification, date and place when
   they are present;
6. do not imply that the synthetic text really comes from the historical work
   named by its folder.

Do not browse the web, edit repository files, publish anything, or update a
publication journal. Return only the five cards and a short final note saying
that a human must review model output before any real publication.
