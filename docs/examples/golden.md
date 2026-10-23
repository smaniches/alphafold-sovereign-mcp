# Golden integration fixtures

Three source-response replay cases exercise `generate_variant_clinical_report`
without network access during CI.

| Case | Tool input | Clinical tier assigned by this MCP |
|---|---|---|
| BRCA1 | `BRCA1:c.5266dupC` | `NOT_ASSESSED` |
| TP53 | `TP53:p.Arg175His` | `NOT_ASSESSED` |
| EGFR | `EGFR:p.Leu858Arg` | `NOT_ASSESSED` |

The upstream responses are preserved as `cassette.json`; `expected.json`
contains the tested tool output. The offline golden test checks deterministic
reproduction of those recorded responses, source attribution, missingness
states, and computed fields. It does **not** independently validate biological
mechanisms, therapeutic efficacy, or ACMG pathogenicity classifications.

The corresponding [fixture directory](https://github.com/smaniches/alphafold-sovereign-mcp/tree/main/examples/golden)
documents the mechanical reproduction contract. To intentionally regenerate
a capture after reviewing upstream changes, run
`uv run python scripts/record_golden_examples.py`; inspect the resulting
scientific-field diffs before accepting them.
