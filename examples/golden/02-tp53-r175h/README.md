# Golden regression fixture 02 — TP53 p.Arg175His

This case tests repeatability of source-specific variant observations
and exact ClinVar record attribution. The MCP does not independently
classify the variant.

`cassette.json` records upstream API responses; `expected.json`
records their processed output. A ClinVar classification, if present,
is a source-reported assertion; AlphaMissense, SIFT, and PolyPhen scores
remain computational predictions rather than validated criteria.

The current `clinical_tier` output is `NOT_ASSESSED`. No local
PP3/PP5 clinical conclusion or mechanistic claim is inferred from this
regression fixture. It tests the code path, not clinical validity.

Run `uv run pytest tests/golden/test_golden_examples.py` to reproduce.
