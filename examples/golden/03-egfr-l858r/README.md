# Golden regression fixture 03 — EGFR p.Leu858Arg

This case verifies faithful retrieval and replay of upstream source
information on the supplied variant, including distinctions between
somatic context and germline classification.

`cassette.json` contains frozen upstream HTTP responses and
`expected.json` the corresponding tool output. No new clinical tier,
drug-response conclusion, or disease mechanism is claimed by this MCP.

The current `clinical_tier` is `NOT_ASSESSED`. Missing germline
classification is not negative evidence about somatic biology or
treatment response. These are different evidence questions.

Run `uv run pytest tests/golden/test_golden_examples.py` to reproduce
the input/output contract offline.
