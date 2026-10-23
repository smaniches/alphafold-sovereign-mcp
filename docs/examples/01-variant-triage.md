# Variant evidence retrieval

The `generate_variant_clinical_report` tool aggregates source-attributed
Ensembl VEP, ClinVar, population-frequency, prediction, and gene-context
records for research use. It does **not** independently classify a variant.

For example, call the tool with `hgvs="BRCA1:c.181T>G"` in an MCP client.
Inspect the source-specific fields, retrieval statuses, and identifiers.
The tool's `clinical_tier` is `NOT_ASSESSED`; computational signals in
`acmg_criteria_draft` are not established ACMG/AMP clinical criteria.

Source observations and predictions have different evidence types.
ClinVar assertions are attributable to ClinVar submitters and review
status. VEP and AlphaMissense are computational predictions, not
experimental confirmation.

An earlier June 2026 illustrative transcript used a different, now-retired
clinical-tier contract; it is not reproduced as current output. For
replayable current regression examples see [Golden examples](golden.md).
