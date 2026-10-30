# Proposal: make the daily cards more engaging

**Status: superseded historical proposal.** It is not an active workflow or
current writing instruction. Use [editorial-system.md](editorial-system.md),
[the daily template](../examples/codex/daily-news-prompt.md) and the matching
saved-profile research workflow instead. In particular, the old recommendations
below to use `daily-five`, explain why every story matters and show technical
metadata in reader cards are obsolete. The example below is retained as history,
not as the current literary reference. This file does not update an active task.

## Proposed editorial change

Keep the current deterministic `daily-five` retrieval and recovery-safe journal
workflow. Replace only the editorial emphasis in the active prompt:

1. read the target chunk and neighbours, not only the candidate summary;
2. search indexed scholarship when it can support interpretation;
3. lead with the strongest supported human detail, object, action,
   contradiction, or source problem;
4. explain historical/cultural interest, never how the search engine worked;
5. label primary report, literary narrative, scholarship, and model inference;
6. allow the evidence to determine length and structure;
7. put path, chunk ID, classification, and scholarship in a compact final block;
8. retain the current zero-candidate and publication-manifest rules unchanged.

The public wording in `examples/codex/daily-news-prompt.md` is the proposed
template. It does not alter retrieval, publication order, or error handling.

## Style comparison on a real open text

This is an editorial illustration, not a TairaSearch production finding. It
uses a publicly accessible 1943 Japanese school text containing the literary
episode “The Last Moments of Atsumori.” The page says that, after the young
warrior is killed, a flute is found at his waist and the onlookers weep. This
is evidence for a **literary portrayal**, not independent proof of the event.
Source: [Japanese Wikisource, *Shotōka Kokugo 6 / Genji and Heike*](https://ja.wikisource.org/wiki/%E5%88%9D%E7%AD%89%E7%A7%91%E5%9C%8B%E8%AA%9E_%E5%85%AD/%E6%BA%90%E6%B0%8F%E3%81%A8%E5%B9%B3%E5%AE%B6#%E6%95%A6%E7%9B%9B%EF%BC%88%E3%81%82%E3%81%A4%E3%82%82%E3%82%8A%EF%BC%89%E3%81%AE%E6%9C%80%E6%9C%9F).

### Dry style

> Atsumori had a flute. This is interesting because it shows a cultural aspect
> of Taira life. The source is literary and requires verification.

The statements are cautious, but the object and the source's narrative logic
never become a story.

### Proposed style

> **The flute found after the battle**
>
> The literary account waits until Atsumori has been killed before revealing
> the object at his waist: a flute in a brocade bag. That discovery makes the
> music reportedly heard from the fortress at dawn newly significant. The
> onlookers' tears belong to the narrative, but the contrast is the point of
> the scene—a cultivated young courtier is recognized only after battle has
> reduced him to an enemy body.
>
> This source can show how Atsumori was remembered and taught; by itself it
> cannot establish each detail as historical fact.
>
> **Source:** literary retelling, “敦盛の最期,” Japanese Wikisource; production
> `relative_path` and `chunk_id` would be inserted only from an actual retrieved
> candidate.

The new version adds no dialogue, motive, or unsupported background. It makes
the source limitation part of the story instead of surrounding the story with
technical disclaimers.

## Safe review against the real local corpus

Before changing the active automation:

1. run the existing selector against a **copy** of the index and journal;
2. choose one or two fresh candidates without calling `record-publication`;
3. generate old-style and proposed-style drafts side by side;
4. check every factual phrase against target context and any scholarship;
5. review tone, attribution, length, and repeat risk with the owner;
6. only after explicit approval, update the active prompt separately.

The real-corpus comparison is intentionally not committed here: the public
repository must not contain private excerpts or derivative data. No active
automation setting should change as part of release 0.1.1.

