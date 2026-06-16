# Examples

Three end-to-end illustrations of a Claude Desktop session against
`alphafold-sovereign-mcp`.

| Example | What it shows |
|---|---|
| [Variant triage on BRCA1 c.181T>G](01-variant-triage.md) | Ensembl VEP + ClinVar + gnomAD + AlphaMissense + AlphaFold for a well-characterised pathogenic missense variant. |
| [Target characterisation on EGFR](02-target-characterization.md) | Open Targets, ChEMBL, gnomAD constraint, AlphaFold pLDDT for a HOT-tier drug target. |
| [Drug discovery: Imatinib → BCR-ABL → CML](03-drug-discovery.md) | Multi-turn flow tying a drug to its target to the disease to the structural gatekeeper (T315I). |

## Status

These transcripts were **captured live** against the upstream APIs on 2026-06-08; the per-example pages record the exact run and the full payload is in each example's `transcript.jsonl`. Turning these into CI-diffed golden tests is tracked on the [validation roadmap](../status.md).

## Reproducing locally

See [Installation](../installation.md), configure Claude Desktop,
restart, then paste the user prompt from any example into a new
conversation.
