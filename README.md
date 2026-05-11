# AlphaFold Sovereign MCP

A Model Context Protocol server that wraps AlphaFold DB and 13 other
public biomedical data sources behind a set of MCP tool calls, and
persists each result to a local SQLite knowledge graph for later
querying.

This is an unfunded, independent open-source project. It is not a
service, not certified for any regulated use, and its outputs are
research aids that should be reviewed by qualified humans before any
clinical or regulatory use.

[![CI](https://github.com/smaniches/alphafold-sovereign-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/smaniches/alphafold-sovereign-mcp/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![MCP Spec 2025-06-18](https://img.shields.io/badge/MCP-2025--06--18-purple)](https://modelcontextprotocol.io)

---

## What this is

A Python MCP server that:

- Wraps AlphaFold DB, UniProt, MONDO, HPO, Open Targets, ClinVar,
  gnomAD, DisGeNET, ChEMBL, Ensembl, InterPro, RCSB PDB, Gene
  Ontology, and Human Protein Atlas behind MCP tool calls. Each call
  is a thin orchestration over those upstreams; the server does not
  add scientific judgement.
- Composes upstreams into multi-source workflows: variant
  cross-reference reports, disease–target landscape summaries,
  heuristic target-druggability scoring, drug-repurposing candidate
  ranking, and cross-species structural-distance computation.
- Persists every tool result to a local SQLite knowledge graph
  (`storage/knowledge_graph.py`) so a research session accumulates a
  queryable, exportable database.
- Includes a topological-data-analysis (TDA) module that computes
  persistent-homology fingerprints (Betti numbers β₀, β₁, β₂) over
  Vietoris-Rips filtrations of Cα coordinates, and a
  Wasserstein-distance comparator between fingerprints. The full
  persistent-homology features require the optional `[tda]` extra
  (`gudhi`).

It targets `mcp-spec 2025-06-18` and runs on Python 3.10–3.13.

## What this is **not**

- It is **not** a hosted service or a SaaS.
- It is **not** certified for any regulated use (HIPAA, GxP, 21 CFR
  Part 11, FedRAMP, FIPS, SOC 2). The code structures audit logging
  in a way that could later support such a certification, but no
  such audit has been performed.
- It does **not** train, fine-tune, or publish AlphaFold models — it
  consumes AlphaFold DB's public REST API.
- The "ACMG/AMP criteria" that `generate_variant_clinical_report`
  produces are a **draft surface** of the upstream evidence the
  server can fetch automatically. They are not a substitute for
  clinical-laboratory variant review.
- The "druggability tier" that `assess_target_druggability` returns is
  a **heuristic** built from drug-precedent counts, Open Targets
  tractability labels, pLDDT, and gnomAD constraint. It is not a
  validated prediction.
- "Structural distance" between proteins via TDA Wasserstein distance
  measures *topological* similarity of the Cα point cloud. It is not
  a sequence similarity, RMSD, or functional-equivalence measure.

For a complete, itemised list of known limitations (with module
references, impact, and planned resolution), see [`LIMITATIONS.md`](LIMITATIONS.md).
For the high-level posture — what is engineering-validated vs. what is
not yet scientifically validated — see [`STATUS.md`](STATUS.md).

---

## Install

```bash
# Via uvx (no install required)
uvx alphafold-sovereign-mcp

# Via pip
pip install alphafold-sovereign-mcp

# With persistent-homology TDA (requires gudhi)
pip install "alphafold-sovereign-mcp[tda]"
```

**Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "alphafold-sovereign": {
      "command": "uvx",
      "args": ["alphafold-sovereign-mcp"]
    }
  }
}
```

**Offline mode** — set `ALPHAFOLD_OFFLINE=1` to refuse all outbound
HTTP and serve only from the local SQLite cache.

---

## Tool inventory

The server exposes 29 MCP tools across four modules. Each tool's
input schema is a Pydantic model; results are JSON.

### Disease & ontology (`tools/disease.py`)

| Tool | What it does |
|---|---|
| `lookup_disease` | MONDO record + hierarchy + ICD cross-references |
| `search_diseases` | Full-text MONDO ontology search |
| `lookup_phenotype` | HPO term + associated diseases |
| `get_gene_phenotype_profile` | HPO phenotypes + gnomAD constraint for a gene |
| `get_disease_targets` | Top drug targets for a MONDO disease (Open Targets) |
| `get_target_diseases` | Top diseases for a UniProt target (Open Targets) |
| `get_common_disease_targets` | Parallel profiling across curated MONDO diseases |
| `triage_variant_3d` | HGVS → ClinVar + gnomAD + MONDO disease context |
| `phenotype_to_structures` | HPO → diseases → OT targets → UniProt IDs |
| `get_orphan_disease_atlas` | Orphanet → MONDO → HPO + OT targets |
| `compare_disease_target_overlap` | Jaccard similarity of target sets for two diseases |
| `resolve_icd10_to_mondo` | ICD-10 code → MONDO disease record |

### Precision medicine (`tools/precision_medicine.py`)

| Tool | What it does |
|---|---|
| `generate_variant_clinical_report` | HGVS → multi-source report + draft ACMG/AMP criteria |
| `assess_target_druggability` | UniProt → HOT/WARM/COLD/NOT_DRUGGABLE tier |
| `synthesize_protein_dossier` | UniProt → multi-source briefing |
| `map_disease_drug_landscape` | MONDO → approved drugs + pipeline + ChEMBL phase counts |
| `classify_variant_acmg` | HGVS → ACMG/AMP criteria checklist (PVS1, PM2, PP3, BS1, BP4) |
| `find_drug_repurposing_candidates` | MONDO → candidates ranked by OT evidence × ChEMBL phase |

The ACMG/AMP criteria produced are a **draft**: they reflect the
upstream evidence the server can fetch automatically, and they
are not a substitute for clinical-laboratory review.

### Structure intelligence (`tools/structure_intelligence.py`)

| Tool | What it does |
|---|---|
| `analyze_structural_confidence` | pLDDT distribution + PAE-derived domain map |
| `compute_topology_fingerprint` | 64-dim TDA fingerprint (Betti numbers β₀ β₁ β₂) |
| `compare_proteins_topologically` | Pairwise Wasserstein distance matrix for 2–10 proteins |
| `find_evolutionary_structural_shifts` | Cross-species structural divergence (TDA + Ensembl orthologs) |
| `score_binding_pocket_geometry` | Geometric pocket detection + heuristic druggability index |
| `detect_intrinsically_disordered` | IDR map (linkers, tails, long IDRs) |

### Knowledge graph (`tools/knowledge_graph_tools.py`)

| Tool | What it does |
|---|---|
| `query_variant_database` | Search locally stored variant triage results |
| `query_protein_database` | Search locally stored protein assessments |
| `get_knowledge_graph_stats` | Database size, entity counts, last activity |
| `export_research_dataset` | Export tables to JSON for pandas/ML pipelines |
| `find_drug_gene_network` | Traverse the accumulated drug–gene–disease graph |

---

## Example usage

### Clinical variant report

```
generate_variant_clinical_report(hgvs="BRCA1:c.181T>G")
```

The server resolves the HGVS, fetches ClinVar, gnomAD, AlphaMissense
(via AlphaFold DB), Open Targets disease evidence, ChEMBL drug data,
and Ensembl VEP consequence annotations, and returns a single JSON
record with the cross-referenced fields plus the ACMG/AMP criteria
that the available evidence supports.

### Drug repurposing

```
find_drug_repurposing_candidates(disease_mondo_id="MONDO:0007739")
```

Returns drugs whose Open Targets evidence connects them to the
disease, ranked by a composite of OT evidence score × the maximum
ChEMBL clinical phase reached against the target.

### Cross-species structural divergence

```
find_evolutionary_structural_shifts(
    gene_symbol="ACE2",
    target_species=["mus_musculus", "rhinolophus_ferrumequinum"]
)
```

For each species: fetches the ortholog (Ensembl), the AlphaFold
structure, computes the TDA fingerprint, and returns the Wasserstein
distance from the human structure along with sequence identity.

---

## Data sources

| Source | What we use | License |
|---|---|---|
| AlphaFold DB v4 (EBI/DeepMind) | Structures, pLDDT, PAE, AlphaMissense | CC BY 4.0 |
| UniProt | Protein function, domains, GO | CC BY 4.0 |
| MONDO (OLS4) | Disease ontology, ICD cross-refs | CC BY 4.0 |
| HPO (JAX) | Phenotype terms, gene-disease links | hpo.jax.org |
| Open Targets | Disease–target evidence | Apache 2.0 |
| ClinVar (NCBI) | Variant pathogenicity | Public domain |
| gnomAD v4 | Population allele frequencies | ODbL |
| DisGeNET | Gene–disease association scores | CC BY-NC-SA 4.0 |
| ChEMBL v34 (EMBL-EBI) | Drug bioactivity, MoA, ADMET | CC BY-SA 3.0 |
| Ensembl (EMBL-EBI) | VEP, orthologs, gene lookup | Apache 2.0 |
| InterPro | Domain + family annotations | CC0 |
| RCSB PDB | Experimental structures | CC0 |
| Gene Ontology | Biological process, molecular function | CC BY 4.0 |
| Human Protein Atlas | Tissue expression | CC BY-SA 3.0 |

See [`NOTICE`](NOTICE) for full attributions.

---

## Architecture

```
clients/_base.py
  ├── Air-gap enforcement (refuses sockets when ALPHAFOLD_OFFLINE=1)
  ├── Token-bucket rate limiting (aiolimiter)
  ├── Exponential backoff with jitter (tenacity)
  ├── Circuit breaker (CLOSED / OPEN / HALF_OPEN)
  └── Content-addressed SHA-256 dedup of upstream responses

storage/knowledge_graph.py
  ├── SQLite WAL mode (embedded, ACID)
  ├── 6 entity tables: proteins, variants, diseases, drugs, genes, phenotypes
  ├── 4 relationship tables: protein_disease, protein_drug, variant_disease, gene_phenotype
  ├── tool_invocations audit table (SHA-256 of input + output, timestamps)
  └── Analytical views: variant_summary, drug_landscape

domain/disease.py
  └── Pure Python frozen dataclasses (PathogenicityClass, VariantReport, ...)
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full module map.

---

## Testing & quality

- 610 unit tests with respx-mocked upstreams; the full suite runs
  hermetically in under 15 seconds on a laptop.
- Coverage on the shipped surface (`src/alphafold_sovereign/clients`,
  `domain`, `storage`, `server`, `tools`): **99% line + branch**, with
  19 of 20 modules at 100%.
- Lint: `ruff` (full ruleset, no per-file ignores on the production
  tree). Type checking: `mypy --strict` on the domain, clients, and
  storage subtrees.
- Security: `bandit` plus CodeQL `security-extended`.
- Supply chain: SBOM generation in CI; reproducible-build script at
  `scripts/replicate.sh`.

The full CI matrix (Python 3.10, 3.11, 3.12, 3.13 × Ubuntu, macOS)
runs on every push. Test counts and coverage percentages above are
the numbers a `git clone && uv run pytest` produces on the current
HEAD; if you find a divergence, please open an issue.

---

## Contributing

DCO sign-off required (`git commit -s`). No copyright assignment.
Coverage gate: ≥95% line / ≥90% branch for new modules.
Full guide: [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Citation

```bibtex
@software{maniches2024alphafold_sovereign,
  author    = {Maniches, Santiago},
  title     = {AlphaFold Sovereign MCP},
  year      = {2024},
  url       = {https://github.com/smaniches/alphafold-sovereign-mcp},
  license   = {Apache-2.0},
  orcid     = {0009-0005-6480-1987}
}
```

## License

Copyright 2024–2026 Santiago Maniches.

Licensed under the Apache License, Version 2.0. See [`LICENSE`](LICENSE).

Patent reservation: see [`PATENTS.md`](PATENTS.md).
Trademark policy: see [`TRADEMARKS.md`](TRADEMARKS.md).
