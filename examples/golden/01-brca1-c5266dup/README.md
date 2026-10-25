# Golden regression fixture 01 — BRCA1 c.5266dupC

This case tests the **exact-record matching and response provenance**
of the variant report pipeline for the supplied HGVS input.

The `cassette.json` file contains recorded upstream API responses.
`expected.json` is the reproducible output of those responses.
Its `clinvar` field preserves the source-reported classification and
review metadata; these belong to ClinVar, not to a Topologica clinical
determination. The MCP's own `clinical_tier` is `NOT_ASSESSED`.

The test asserts that source identity, failure states, computational
observations, and output structure do not drift accidentally. It does
**not** independently establish a molecular mechanism, ACMG PVS1,
therapeutic actionability, or treatment outcome.

Run `uv run pytest tests/golden/test_golden_examples.py` to replay this
fixture without network access. Review changes to upstream records
and model annotations separately before replacing the recording.
