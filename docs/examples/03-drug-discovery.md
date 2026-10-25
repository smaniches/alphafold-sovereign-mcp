# Disease, drug, and structure source integration

This workflow illustrates retrieval across public databases, not a new
therapeutic or mechanistic conclusion by Topologica.

An MCP client can request:

1. `map_disease_drug_landscape(disease_mondo_id="MONDO:0011996")` for
   Open Targets and ChEMBL source-reported disease-drug records.
2. `assess_target_druggability(uniprot_id="P00519")` for the original
   target-side evidence and an explicitly heuristic local summary.
3. `analyze_structural_confidence(uniprot_id="P00519")` for
   AlphaFold DB predicted-coordinate and model-confidence information.

Gene products, drug indications, structural models, and disease records are
**different evidence objects**. A drug's reported indication does not show
that the isolated AlphaFold structure represents a fusion protein, mutation,
binding state, or treatment response.

Use source identifiers and provenance for any downstream scientific work.
The earlier June 2026 numerical transcript is historical, not a maintained
assertion about current source data or clinical actionability.
