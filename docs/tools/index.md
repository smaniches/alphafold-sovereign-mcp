# Tool reference

`alphafold-sovereign-mcp` exposes 29 MCP tools organised into four
modules.

## At a glance

| Module | Tools | What it does |
|---|---|---|
| [Disease](disease.md) | `lookup_disease`, `search_diseases`, `get_disease_targets`, … | Ontology lookups (MONDO, HPO), disease-target evidence from Open Targets. |
| [Precision medicine](precision-medicine.md) | `generate_variant_clinical_report`, `classify_variant_acmg`, `assess_target_druggability`, … | Variant triage (Ensembl VEP + ClinVar + gnomAD + AlphaMissense + AlphaFold), druggability heuristic. |
| [Structure intelligence](structure-intelligence.md) | `analyze_structural_confidence`, `compute_topology_fingerprint`, `compare_proteins_topologically`, … | AlphaFold model retrieval, pLDDT and PAE summaries, exploratory Cα summary vectors (persistent homology with the optional `[tda]` extra), geometric core-residue clusters. |
| [Knowledge graph](knowledge-graph.md) | `query_variant_database`, `find_drug_gene_network`, `export_research_dataset`, … | Traversal and export of the local SQLite knowledge graph. |

## Tool annotations

Every tool decorates `@mcp.tool()` with MCP-spec annotations:

- `readOnlyHint=True` — none of the tools mutate state outside the
  local cache.
- `idempotentHint=True` — re-running with the same args gives the
  same result (modulo upstream data drift). Two tools carry `False`:
  `find_evolutionary_structural_shifts` and `synthesize_protein_dossier`.
- `openWorldHint=True` on every tool that queries an upstream service.
  Only the five knowledge-graph tools, which read the local SQLite store,
  carry `openWorldHint=False`.

## Provenance

Every tool result carries a provenance footer listing the server
version, a UTC timestamp, and the upstream data sources that
contributed to the response (the disease-layer tools additionally
return a `sources_queried` field). The SQLite knowledge graph can
record tool invocations via `KnowledgeGraph.log_tool_invocation`, but
this writer is not yet hooked into tool dispatch, so the audit trail is
populated only when a caller logs explicitly.

## Limitations

The scientific outputs of the precision-medicine tools (the ACMG
draft and the druggability tier) are **not validated** by independent
domain experts. See [Limitations L1 + L2](../limitations.md) for
details and [Status — Roadmap (validation, post-1.2.0)](../status.md) for the
validation plan.

The structure-intelligence heuristics are not validated either:
`analyze_structural_confidence` does not identify domains,
`score_binding_pocket_geometry` does not detect binding pockets or
assess druggability, and the Cα summary vector is not a validated
similarity measure. See [Limitations L10 to L12](../limitations.md).

## Output changes after 1.5.12

The corrections made after release 1.5.12 removed no tool, parameter or
output key, and changed no parameter's type, default or constraint. They
changed which values some existing fields can hold, so a client written
against 1.5.12 should review the fields below.

| Tool | Field | In 1.5.12 | Afterwards |
|---|---|---|---|
| `triage_variant_3d` | `status` | `success` for every HGVS expression it could parse, also when every lookup had failed | `success`, `partial` when some attempted lookups failed, `error` when all of them failed |
| `get_common_disease_targets` | `status` | `success` for every recognised category, also when every lookup had failed | `success`, `partial` when some lookups failed, `error` when all of them failed |
| `get_common_disease_targets` | `diseases_profiled` | number of diseases looked up | number of lookups that succeeded |
| `analyze_structural_confidence` | `domain_boundaries.candidate_positions`, `domain_boundaries.n_putative_domains` | up to ten positions and a domain count; `[]` and `null` without a PAE matrix | always `[]` and `null` |
| `score_binding_pocket_geometry` | `druggability_label` of each `putative_pockets` entry | `EXCELLENT`, `GOOD`, `MODERATE` or `POOR` | always `NOT_ASSESSED` |
| `analyze_structural_confidence`, `compute_topology_fingerprint`, `score_binding_pocket_geometry`, `detect_intrinsically_disordered`, `get_protein_structure` | `error` and `note` when `structure_available` is `false` | one text, whatever the cause | unchanged when AlphaFold DB has no model; they name the cause when the request failed |
| `get_protein_structure` | `coordinates_pdb`, returned with `include_coordinates` | PDB text read through a second prediction lookup; `""` when none was retrieved, whatever the cause | the file that the reported record advertises (`file_urls.pdb`), with no second lookup; `""` when none was retrieved, and `coordinates_status` and `coordinates_error` say why |

Both `status` fields already answered `error` to input the tool could not
interpret; `partial` is a new value. Explanatory texts (`interpretation`,
`methodology`, `note`) were reworded where they stated what the corrections
retracted, and provenance footers name the AlphaFold DB version of the
record that was read where 1.5.12 always wrote `v6`.

Deprecated, and still returned so that existing clients keep working:

- `score_binding_pocket_geometry`: `putative_pockets` and `n_pockets_found`,
  with the entry keys `pocket_id`, `druggability_index` and
  `druggability_components`. They repeat `core_residue_clusters`,
  `n_core_residue_clusters`, `cluster_id`, `geometry_score` and
  `geometry_score_components` with the same numbers. The result's
  `deprecated_aliases` maps each old key to its current name.
- `analyze_structural_confidence`: the `domain_boundaries` block. The
  positions it used to list are reported as `local_high_pae.positions`
  and are not domain boundaries.

New fields stand beside the existing ones, among them `retrieval_status`,
`coordinates_status`, `coordinates_error`, `lookup_summary`,
`diseases_requested`, `diseases_failed`, `local_high_pae`,
`core_residue_clusters`, `fingerprint_layout` and `cadd_phred_note`. ClinVar
conditions, which 1.5.12 returned empty for current ClinVar records, and the
`hgvsp` of the variant report, which it always returned empty, are filled
when the source reports them. The `openWorldHint` annotation changed from
false to true on
`compute_topology_fingerprint`, `compare_proteins_topologically`,
`score_binding_pocket_geometry`, `detect_intrinsically_disordered` and
`get_common_disease_targets`.
