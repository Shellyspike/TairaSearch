# Growing a TairaSearch research library (0.4)

Version 0.4 keeps responsibilities explicit. Codex discovers and evaluates
sources. `source_acquisition.py` reproducibly validates a manifest, enforces
download limits, preserves originals and extracted text, keeps a journal, and
promotes only specifically approved items. It needs neither an OpenAI API key
nor a separate LLM service.

## Quick start in Codex

Open the project folder in the Codex app and send one request:

> Read `examples/codex/source-acquisition-workflow.md` and help me safely grow
> my research library from `research_profile.json`.

If the profile is missing, first use
`examples/codex/research-onboarding.md`. Codex must not download anything until
you explicitly consent or create a local automatic-mode policy.

## Local files

- `research_profile.json`: interests and retrieval preferences;
- `source_acquisition_policy.json`: automatic-mode permissions and limits;
- `work/source-acquisition/candidates.json`: discovered candidate manifest;
- `work/source-acquisition/downloads.json`: atomically updated download journal;
- `work/library-staging/`: originals, extracted text, and metadata;
- `work/source-acquisition/*-report.json`: command reports.

Git ignores all of these working files. The public example policy at
`examples/acquisition/policy.example.json` disables automatic downloads.

## Manifest and formats

A download manifest has `version: 1` and a `sources` array. Every source needs
`title`, `author`, `url`, `format`, and `access`. Formats are `pdf`, `html`,
`txt`, `md`, `xml`, `tei`, and `epub`. Access must be `open`,
`public-domain`, or `authorized`. This is Codex's evidence-based statement from
the source page or another reliable rights statement, not an automated legal
opinion by Python. A discovery lead with unclear rights does not enter this
manifest; it remains in the research report until suitable evidence or a
lawfully accessible alternative is found.

## Three safe steps

1. `check` downloads nothing and reads the journal and optional SQLite index in
   read-only mode.
2. `stage` requires `--approve-downloads` or a previously approved policy and
   enforces count and byte limits. A final staging directory appears only after
   complete download, extraction, and metadata creation.
3. `promote` requires `--approve` and exact `--source-id` values. `--index`
   invokes the existing `build_index.py` incrementally. A failed index run
   leaves staging and the journal available for recovery.

After `stage`, Codex shows each document's title, author, URL, staging paths,
and quality measurements. It then separately asks which `source_id` values to
move into the named corpus and whether to update the named index. Refusal or no
answer leaves everything in staging. A successful automatic download is never
consent for `promote --index`.

PDF checks sample the beginning, middle, and end; a partial read is not marked
ready. HTML keeps unchanged source bytes and extracted visible text. EPUB and
XML/TEI extraction does not rewrite the content. SHA-256 verifies originals.

## Discovery and download are separate decisions

Research discovery may use official repositories as well as unofficial
libraries, mirrors, community archives, and sites of uncertain reputation. A
site category alone is not a reason to hide a potentially valuable
bibliographic lead. Record the title, author, stable identifiers, landing-page
URL, why it matters, the site's character, and the known access or rights
evidence.

Discovery does not authorise downloading. Sources with unclear rights,
apparently unauthorised copies, login or paywall requirements, or uncertain
provenance are reported as **found but not downloaded** and are excluded from
automatic staging. Search by title, author, DOI, catalogue identifier, and
title variants for an accessible lawful copy in repositories, author or
publisher pages, preprint servers, national libraries, or other archives. A
geographic or technical failure should trigger this alternative search, not
proxying around the restriction or bypassing controls. If rights evidence is
later established, the source can be reconsidered under the normal manifest
and consent rules.

## Duplicates and safety boundaries

DOI, canonical URL, matching title plus author, and a downloaded content hash
can confirm a duplicate. A basename such as `download.pdf` is only a potential
match reported for review and never blocks an otherwise distinct source.
Different sources with the same basename remain isolated by source ID in
staging. The total byte budget counts bytes received by successful, rejected,
and failed transfers; no later download starts after that budget is exhausted.
An optional manifest `encoding` field can resolve ambiguous plain text; HTML
and XML declarations are honoured automatically.

These identifiers are checked against the local journal and SQLite. This does
not scan Google Drive and cannot decide
whether two genuinely different editions are semantically identical; Codex or
the user reviews ambiguity. The downloader still does not bypass
authentication, paywalls, robots controls, rate limits, regional blocks, or
other site controls; it does not accept URL credentials or fetch report-only
leads whose download rights remain unclear. It also rejects localhost,
loopback, private, link-local, reserved, and service addresses, including HTTP
redirects to them. The private-network allowance is an internal hook solely
for the isolated test HTTP server; neither the CLI nor a policy file can enable
it.

Download consent and indexing consent are separate. Scheduled library
acquisition and scheduled research cards are two independent automations. One
never authorises creating or changing the other. A pre-approved automatic
policy lets a scheduled run discover and download into staging only; moving
files into the corpus and updating SQLite always remain interactive actions
requiring separate explicit consent.

## Testing a real open site

CI uses a local HTTP server and synthetic files. It proves the format pipeline,
not the availability of external repositories. A manual network check may use
an official Project Gutenberg public-domain download: put its direct URL and
stated terms in a separate manifest, run `check`, and only then consent to
`stage`. Network availability and current site policy remain external; a
network error is not a zero-result search.
