# Examples

Three end-to-end illustrations of a Claude Desktop session against
`alphafold-sovereign-mcp`.

| Example | What it shows |
|---|---|
| [Variant triage on BRCA1 c.5266dupC](01-variant-triage.md) | Ensembl VEP + ClinVar + gnomAD + AlphaMissense + AlphaFold for a well-characterised pathogenic frameshift. |
| [Target characterisation on EGFR](02-target-characterization.md) | Open Targets, ChEMBL, gnomAD constraint, AlphaFold pLDDT for a HOT-tier drug target. |
| [Drug discovery: Imatinib → BCR-ABL → CML](03-drug-discovery.md) | Multi-turn flow tying a drug to its target to the disease to the structural gatekeeper (T315I). |

## Status

These examples are **illustrative**. The transcripts and prose
responses are consistent with what the server emits when its upstream
clients return data we have unit tests for — but the specific numbers
have not been verified against a live API call for these exact
queries. End-to-end live-API validation is on the
[v1.2.0 roadmap](../status.md).

## Reproducing locally

See [Installation](../installation.md), configure Claude Desktop,
restart, then paste the user prompt from any example into a new
conversation.
