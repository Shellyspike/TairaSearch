# TairaSearch public AI demo request

Use only the editorial and evidence rules from
`examples/codex/daily-news-prompt.md` as the baseline and use
`work/demo/ai-input.json` as the only source evidence. This demo request
overrides the baseline's publication, manifest, and journal instructions.

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

Do not browse the web, edit tracked repository files, publish anything, or
update a publication journal. When the calling request asks for a saved result,
you may write only `work/demo/ai-cards.md`. Return only the five cards and a
short final note saying that a human must review model output before any real
publication.
