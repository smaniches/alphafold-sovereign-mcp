# Disease, drug, and structure source integration

This workflow illustrates retrieval across public databases, not a new
therapeutic or mechanistic conclusion by Topologica.

An MCP client can request:

1. `map_disease_drug_landscape` with a source-checked MONDO identifier to
   retrieve Open Targets and ChEMBL disease-drug records.
2. `assess_target_druggability` with a source-checked UniProt accession to
   retrieve target evidence and an explicitly heuristic local summary.
3. `analyze_structural_confidence` with the same source-checked accession
   to inspect AlphaFold DB predicted coordinates and confidence information.

Gene products, drug indications, structural models, and disease records are
**different evidence objects**. A drug's reported indication does not show
that the isolated AlphaFold structure represents a fusion protein, mutation,
binding state, or treatment response.

Use source identifiers and provenance for any downstream scientific work.
The earlier June 2026 numerical transcript is historical, not a maintained
assertion about current source data or clinical actionability.
