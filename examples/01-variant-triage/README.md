# Variant-source evidence example (historical capture retired)

Current tool: `generate_variant_clinical_report`.
Input example: `BRCA1:c.181T>G`.

The current MCP aggregates source-attributed ClinVar, Ensembl VEP,
population-frequency and computational-prediction observations.
Its clinical tier is `NOT_ASSESSED`: no independent pathogenicity
classification or ACMG criterion is assigned.

The 2026-06-08 transcript used the former clinical-tier interface and
has been withdrawn from this active example. Do not infer clinical
interpretations from this page. The current return contract and source
error handling are exercised in `tests/test_tool_precision_medicine.py`
and in the offline golden regression fixtures.
