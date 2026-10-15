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

A manifest has `version: 1` and a `sources` array. Every source needs `title`,
`author`, `url`, `format`, and `access`. Formats are `pdf`, `html`, `txt`, `md`,
`xml`, `tei`, and `epub`. Access must be `open`, `public-domain`, or
`authorized`. This is Codex's evidence-based statement from the official source
page, not an automated legal opinion by Python.

## Three safe steps

1. `check` downloads nothing and reads the journal and optional SQLite index in
   read-only mode.
2. `stage` requires `--approve-downloads` or a previously approved policy and
   enforces count and byte limits. A final staging directory appears only after
   complete download, extraction, and metadata creation.
3. `promote` requires `--approve` and exact `--source-id` values. `--index`
   invokes the existing `build_index.py` incrementally. A failed index run
   leaves staging and the journal available for recovery.

PDF checks sample the beginning, middle, and end; a partial read is not marked
ready. HTML keeps unchanged source bytes and extracted visible text. EPUB and
XML/TEI extraction does not rewrite the content. SHA-256 verifies originals.

## Duplicates and boundaries

Exact URL, DOI, title and title variants, and filenames are checked against the
local journal and SQLite. This does not scan Google Drive and cannot decide
whether two genuinely different editions are semantically identical; Codex or
the user reviews ambiguity. The downloader does not bypass site controls,
accept URL credentials, or fetch a source Codex has classified as unauthorised.

Download consent and indexing consent are separate. Scheduled library
acquisition and scheduled research cards are two independent automations. One
never authorises creating or changing the other.

## Testing a real open site

CI uses a local HTTP server and synthetic files. It proves the format pipeline,
not the availability of external repositories. A manual network check may use
an official Project Gutenberg public-domain download: put its direct URL and
stated terms in a separate manifest, run `check`, and only then consent to
`stage`. Network availability and current site policy remain external; a
network error is not a zero-result search.
