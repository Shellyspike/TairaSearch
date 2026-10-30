# Personal newspaper: writing and independent editorial review

This is the agent workflow for new personal historical editions. It is not a
Python feature or a new publication schema. Read source evidence and resolve
scope and semantic novelty through the saved-profile research workflow first.
Then independently select reader-worthy stories: novelty alone does not earn a
place. Prefer concrete actions, unusual circumstances, relationships and outcomes;
do not fill five slots with weak material or impose genre quotas.

Research, story selection and prose review are distinct decisions. A story can
be accurate and new yet still be a poor or confusing newspaper card. The author
remains responsible for the final text after a second agent's pass.

## Reference examples and private material

If a user supplies approved local examples, include them in the first-stage
review packet and use them for quality comparison. Their paths belong in local
run configuration or ignored working artifacts, not this public repository.
Do not include private corpus excerpts, trial editions, review logs, profiles or
publication journals in a PR. If an edition requires particular examples but they
are unavailable, report that missing input rather than pretending to read them.
The writing rules below are the public baseline; they do not require the sample
stories to be republished. Compare how an example prepares roles, causes, a turn
and an ending, rather than copying its sentence length or paragraph pattern.

## Reader text

Write as an intelligent, engaging storyteller who knows the historical material:
natural Russian, without pomp, moralizing or bureaucratic language. Tell the story
rather than describing the research process. These are writing rules, not changes
to retrieval, research admission or editorial selection.

- Usually follow events in chronological order, letting the situation unfold.
  An opening at the climax is allowed when it improves that particular story;
  do not routinely reveal the ending and then rewind to the background.
- Use concrete verbs and natural phrasing. Prefer «распорядился отдать рис» to
  «оформить выдачу зерна» when the evidence supports that action. Avoid officialese,
  artificial turns of phrase and cumbersome constructions. Preserve circumstances
  that matter to the plot; do not simplify away an important distinction.
- If the source story is funny or absurd, preserve its comic timing and details.
  Let the situation carry the humour, without explaining the joke, adding modern
  narrator jokes or turning the anecdote into an administrative report. Humour
  remains optional; it cannot rescue a weak story.
- End where the story ends. No obligatory moral, evaluation, generalization or
  explanation of the story's meaning. Add a closing clarification only if needed
  to prevent a factual misunderstanding; do not manufacture an outcome.
- Treat 150–250 words as a guide, not a quota. Keep a complete 80–120-word story
  short. Allow a reasonable increase for a complex plot; length must serve the
  evidence and story, never padding or an arbitrary target.
- Choose the composition separately for each card. Vary openings, pacing,
  paragraphing and length where the stories call for it, without forcing variety.
  Never apply a fixed headline → ending → background → explanatory conclusion
  template to every card.
- Use an accurate, specific headline. Avoid clickbait, journalistic stock phrases,
  artificial sensationalism and deliberate dramatization. Do not manufacture
  suspense by hiding qualifications necessary to understand the source.
- Liveliness comes from supported actions, details and sentence rhythm. Never
  invent dialogue, thoughts, motives, feelings, circumstances, causation or an
  ending. A paraphrase is not a direct quotation. Tell legends and literary
  anecdotes as such, without requiring proof that their events really happened.

Use concise evidence-sensitive attribution in the story: “the diary records”,
“in the tale”, “according to the chronicle”. Keep version boundaries explicit.
Never invent dialogue, motives, emotions, circumstances, causal links or endings.
Usually a short label such as "in the tale" or "according to the legend" and
a compact source suffice. Do not burden cards with repeated historicity
disclaimers; explain further only to avoid misleading the reader.
Before final selection, compare every claim in the final prose to the dossier.
Then read the cards together as a prose edit: remove officialese and repeated
composition, check that any comic effect belongs to the source, and cut padded
sentences or an appended moral. Repeat the claim check for any rewritten facts;
style editing never relaxes attribution, uncertainty or duplicate review.

### Reader comprehension before sentence editing

Every card must work for a reader unfamiliar with the people and setting.
Follow `examples/codex/reader-review.ru.md` in full. Before drafting, map the
necessary roles, relationships, situation, actions, supported causal links and
outcome to evidence. Include each indispensable link in the reader text; a
fact present only in the dossier cannot explain the story to the reader.
Introduce roles when needed and make name/title identities explicit or omit
the spare title. Do not turn presumed offences against a new ruler into proven
crimes. Retrieve missing context; never invent a motive or a causal bridge.
Give only context needed for the action and stakes, without a history lecture,
a mandatory conflict or fixed length. Edit the whole narrative before sentences.
The rules against explaining humour or appending morals do not prohibit the
context required to understand the joke or situation.

### Required prose pass before registration

Read the writing rules here and any user-approved local prose examples supplied
for this edition before writing. Examples are a quality reference, not a pool of
findings or a fixed template. Do not claim to have read unavailable examples. A factual dossier and a fluent story are different
artifacts: do not copy the dossier's numbered claims into successive sentences and call that prose.

Draft from the verified sequence of events, then edit narrative comprehension,
composition and the actual sentences in a separate pass before registration.
For each card, identify the source-supported
turn that holds it together (a joke, an escalation, a request, a reversal, or a
quiet incident); let the syntax and paragraph breaks serve that particular story.
Do not append an explanation of that turn for the reader.

Check the words, not just compliance with the rules. Replace nominal abstractions
with actions and speakable Russian. Remove book-report scaffolding such as
«рассказано о», «поэт завершает историю решением», «причина своей просьбы»,
«жалоба об отсутствии сыновей» where it adds no necessary attribution or meaning.
These are examples of editing problems, not an automated banned-word list.
Integrate attribution once where needed, without continually returning the reader
from the scene to the description of its source.

If the humour or dramatic turn lives in a source quotation, retain the essential
wording and its placement. A faithfully checked translation may be presented as
speech, with its translation status clear; do not invent dialogue or a rhymed
translation. Where wording is uncertain, keep indirect speech and preserve the
logical reversal. Factual accuracy does not require turning every source speech
into a report about what was said.

Compare the draft against the writing rules and available approved examples
for naturalness, not merely length
or chronology. A card that still reads like a synopsis of a source must be revised
before registration. In the working editorial notes, record a concrete before/
after phrase or structural change for each card, plus the evidence check for any
changed claim. If no change is needed, identify a specific passage that already
works and why. A repeated assurance such as «после литературной правки проверено»
is not evidence of this pass. Keep these notes out of reader text; this does not
change the publication schema or the research/novelty/selection criteria.

End each card with a compact `reader_source`: author/work, pages, and literary
status where relevant. Keep long paths, IDs, novelty classes, deduplication
explanations and agent notes out of `card_markdown`. Keep all of them in the
structured dossier. A newspaper excerpt is not a substitute for full evidence.

### Independent literary review before registration

For daily editions, a second agent must review the finished reader text after
self-editing and before registration. This is a separate agent invocation, not
another role played by the author in the same response. Use collaboration
spawn_agent with fork_turns="none" and a self-contained review task. The workflow
requires this editorial delegation within the runtime permission policies.
The reviewer must not have authored
the draft. Reuse this reviewer for revision rounds. Do not require a remote MCP;
if separate-agent tools are unavailable or the review fails, save the draft and
report that independent review could not be completed. Do not register or publish
an unreviewed draft, and do not report this as absence of suitable findings.

Use the two-stage process in `examples/codex/reader-review.ru.md`. First give
only the complete reader cards, rules and available user-approved examples;
do not give
dossiers or their paths yet. The separate agent saves a cold-reading report:
what happens, who is who, which textual passages establish essential links,
and exactly where a novice must guess. No source lookup or final pass at this
stage. Only after that report exists, send the verified dossiers and relevant
full evidence to the same reviewer. Answers found in the dossier do not repair
gaps in the card. Do not prime either stage with the author's self-assessment.
Review narrative understanding and composition before polishing sentences.

Before a final verdict, audit meaning retention in both directions under
`examples/codex/reader-review.ru.md`: check not only whether claims are supported,
but whether essential source details survive the retelling. Save a concise
source-detail-to-card map, including justified omissions. Check motives, decisive
circumstances, whole question/answer units, qualifications and details needed for
the outcome. A labelled speech excerpt cannot omit a regret or contrast that
changes the answer. Difficult context must be researched or carefully expressed,
not removed merely to make the prose easier. Require a separate meaning_retention
section in working review notes; unresolved essential losses require revise even
when the remaining prose is accurate and clear. The lead author checks this map
after revision. This does not change manifest fields or publication commands.

For every card require pass or revise, specific quoted passages and reasons
for comprehension/composition, literary quality, and source fidelity separately.
Assess connected narrative, natural syntax, sentence rhythm, meaningful details,
comic timing where relevant, and an ending that belongs to the plot. Flag a bare
plot skeleton, monotonous short sentences, ambiguous wording, forced colloquial
words, repeated composition, unnecessary explanations and unsupported additions.
Shortness and absence of officialese alone are not quality. Do not impose genre,
length or humour quotas. Legends need faithful attribution, not proof of miracles.
A pass must explain through specific passages why the story works; a generic
approval is insufficient. Review the cards together as well as individually.
Suggestions must stay within evidence; missing evidence is returned to the author,
never filled by invention. The reviewer must not modify publications or journals.

Save the exact submitted text and reviewer response under
work/research/<run-id>/literary-review/ with reviewer identity, round number,
per-card verdicts and SHA-256 of each reviewed card_markdown. The author resolves
remarks, checks revised facts against evidence, then returns revised texts to
the same reviewer. Both stages together count as one round. After a pass the
lead author must independently reread the final card for a novice and resolve
any remaining gaps; a pass alone never establishes quality. The lead may reject
a pass but cannot override a revise. Further text changes require review within
the same three-round limit; otherwise exclude the card. Allow at most three
review rounds total for the edition, including replacement stories. Register only cards
with an explicit pass for their exact final text; exclude unresolved cards rather
than silently overriding the reviewer. If none pass, do not create a manifest;
report that literary review was not passed. This differs from no suitable finds.
Before record-publication, compare the final card hashes to the accepted review.
Any later prose change invalidates its pass and requires review again within the
same round limit. Save the final gate check beside the review. These are working
artifacts, not new manifest fields. This is an agent-enforced prerequisite, not
a claim that the CLI mechanically validates literary quality. Recovery of an
already registered edition still renders its unchanged manifest without review.

## Publication boundary and runtime limitations

The independent-review pass is a prerequisite in these instructions. Before any
new registration, the author must exclude unresolved/unapproved cards, verify
that every remaining exact card text has a pass, and preserve the final review
and hashes under ignored `work/research/`. If the reviewer is unavailable or a
required check is incomplete, retain the draft and report the blocker; do not
register or publish it. A review failure is not absence of search findings.

Use only publication arguments supported by the installed CLI. These instructions
do not introduce `--require-editorial`, a new manifest version or a machine-enforced
literary gate. The existing manifest validation does not launch `spawn_agent`,
verify reviewer identity, count rounds, validate review hashes or assess meaning
retention. A valid manifest can still pass the CLI without this review if the
agent ignores these instructions. Tests cannot establish literary quality.

Keep the existing publication-access check, locking, atomic writes, idempotence,
record-then-render order and full stdout delivery. Keep technical IDs, paths,
research evidence and review reasoning in structured working artifacts; reader
cards end with only a compact author/work/page citation. Do not manually edit the
publication journal. An explicitly requested unregistered preview may be shown
without registration; never claim it was published. Already registered editions
are recovered by rendering the same unchanged manifest, without rewriting,
re-review or new registration. CLI success does not prove display or reading.

The daily entry point is `examples/codex/daily-news-prompt.md`, with the matching
`research-workflow.md` or `.ru.md`. They preserve retrieval/profile/source filters;
this writing procedure does not change them. See `docs/ai-workflow.md` for the
existing publication contract and the distinction between public templates and
the separately configured active automation.
