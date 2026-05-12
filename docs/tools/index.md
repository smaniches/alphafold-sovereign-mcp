# Tool reference

`alphafold-sovereign-mcp` exposes 25 MCP tools organised into four
modules.

## At a glance

| Module | Tools | What it does |
|---|---|---|
| [Disease](disease.md) | `query_disease_ontology`, `explore_disease_target_landscape`, … | Ontology lookups (MONDO, HPO), disease-target evidence from Open Targets. |
| [Precision medicine](precision-medicine.md) | `generate_variant_clinical_report`, `classify_variant_acmg`, `assess_target_druggability`, … | Variant triage (Ensembl VEP + ClinVar + gnomAD + AlphaMissense + AlphaFold), druggability heuristic. |
| [Structure intelligence](structure-intelligence.md) | `fetch_alphafold_structure`, `compute_structure_fingerprint`, `compare_structures`, … | AlphaFold model retrieval, pLDDT, PAE matrices, persistent-homology fingerprints. |
| [Knowledge graph](knowledge-graph.md) | `query_variant_database`, `find_drug_gene_network`, `export_research_dataset`, … | Traversal and export of the accumulated SQLite knowledge graph. |

## Tool annotations

Every tool decorates `@mcp.tool()` with MCP-spec annotations:

- `readOnlyHint=True` — none of the tools mutate state outside the
  local cache.
- `idempotentHint=True` — re-running with the same args gives the
  same result (modulo upstream data drift).
- `openWorldHint=True` — most tools call live upstream APIs.

## Provenance

Every tool result includes a `sources_cited` array listing the
upstream APIs that contributed to the response. The local cache
records every tool invocation in the SQLite knowledge graph for
later query via the knowledge-graph tools.

## ⚠ Limitations

The scientific outputs of the precision-medicine tools (the ACMG
draft and the druggability tier) are **not validated** by independent
domain experts. See [Limitations L1 + L2](../limitations.md) for
details and [Status — Roadmap to v1.2.0](../status.md) for the
validation plan.
