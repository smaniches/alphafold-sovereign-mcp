# Source-retrieval examples

These examples describe the current database-access MCP's source and
calculation boundaries. They do not provide clinical case narratives.

| Example | Tools and evidence |
|---|---|
| [Variant source retrieval](01-variant-triage/) | Ensembl VEP, ClinVar, population sources, computational predictions |
| [Target evidence retrieval](02-target-characterization/) | ChEMBL, Open Targets, gnomAD, AlphaFold DB prediction confidence |
| [Disease/drug source retrieval](03-drug-discovery/) | Disease, drug, target, and predicted structure records |

The original June 2026 illustrative transcripts were withdrawn from the
active repository because their old tool outputs and interpretations are
not the current contract. Re-query live upstreams for current evidence;
the source's classification or prediction is not a new Topologica
scientific observation.

For reproducible offline regression tests, see [golden fixtures](golden/).
These retain hashed recorded upstream responses and test what the code
returns, not clinical correctness.

## Run

Follow the root [installation instructions](../README.md#installation).
Run the current MCP server through your client, then inspect each tool's
source identifiers and failure status rather than treating an illustrative
example as a fixed biological conclusion.
