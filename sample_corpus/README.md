# Sample corpus

This directory contains short synthetic fixtures for indexing, Unicode paths,
multilingual search, exact and near duplicates, ambiguous romanized names,
chunk-boundary context, JSON, Markdown, and PDF tests. They are not copies of
the author's personal corpus and must not be treated as historical evidence.

The two PDF files are test fixtures: one contains synthetic extractable text and
one represents a PDF without an extractable text layer.

The Russian, Japanese, and English event texts deliberately include the same
Japanese person/topic anchors used by the deterministic candidate selector.
Folders named after historical works only exercise source classification; they
do not claim that the synthetic sentences occur in those works. Expected search
and five-candidate results are recorded in
`examples/demo/expected_results.json`.

Five event fixtures contain enough material for a small human-scale story. Each
has a separate synthetic note under `Статьи/`, allowing the demo to distinguish
an event or literary scene from a research interpretation. The notes are not
real scholarship and cannot confirm the fictional episodes.

These synthetic fixtures are distributed under the repository's MIT License.

