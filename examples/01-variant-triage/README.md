# Variant-source evidence example (historical capture retired)

Current tool: `generate_variant_clinical_report`.
Input form: a source-specific HGVS expression supplied by the caller.

The current MCP searches ClinVar, Ensembl VEP, population-frequency and
computational-prediction sources. This gene-relative input can identify
unverified ClinVar candidates; their classifications cannot be attributed
to a specific allele without versioned-reference matching and further
validation. The clinical tier is `NOT_ASSESSED`: no independent
pathogenicity classification or ACMG criterion is assigned.

The 2026-06-08 transcript used the former clinical-tier interface and
has been withdrawn from this active example. Do not infer clinical
interpretations from this page. The current return contract and source
error handling are exercised in `tests/test_tool_precision_medicine.py`
and in `tests/test_synthetic_variant_pipeline.py`, which uses fabricated data.
