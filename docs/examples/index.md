# Source-retrieval examples

Use these examples to inspect source attribution, prediction types, and
partial-failure handling, not to obtain independent medical conclusions.

| Example | Data path |
|---|---|
| [Variant evidence retrieval](01-variant-triage.md) | Ensembl VEP, ClinVar, population and computational source fields |
| [Target evidence retrieval](02-target-characterization.md) | ChEMBL, Open Targets, gnomAD, AlphaFold DB predicted-structure confidence |
| [Drug/target evidence retrieval](03-drug-discovery.md) | Disease-drug and target-source lookup, with predicted structure confidence |

The original 2026-06-08 illustrative transcripts were captured under an
earlier API/output contract. They are not maintained as current tool outputs.
Use an installed current package to reproduce live results. Source records,
confidence estimates, and model predictions retain their upstream meaning.

For deterministic offline coverage, see [Golden fixtures](golden.md).
For client configuration, see [Installation](../installation.md).
