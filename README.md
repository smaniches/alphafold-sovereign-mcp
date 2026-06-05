# AlphaFold Sovereign MCP

A Model Context Protocol server that wraps AlphaFold DB and 8 other
public biomedical data sources behind a set of MCP tool calls, and
persists each result to a local SQLite knowledge graph for later
querying.

This is an unfunded, independent open-source project. It is not a
service, not certified for any regulated use, and its outputs are
research aids that should be reviewed by qualified humans before any
clinical or regulatory use.

[![CI](https://github.com/smaniches/alphafold-sovereign-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/smaniches/alphafold-sovereign-mcp/actions/workflows/ci.yml)
[![Docs](https://github.com/smaniches/alphafold-sovereign-mcp/actions/workflows/docs.yml/badge.svg)](https://smaniches.github.io/alphafold-sovereign-mcp/)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/smaniches/alphafold-sovereign-mcp/badge)](https://api.securityscorecards.dev/projects/github.com/smaniches/alphafold-sovereign-mcp)
[![Release](https://img.shields.io/github/v/release/smaniches/alphafold-sovereign-mcp?sort=semver)](https://github.com/smaniches/alphafold-sovereign-mcp/releases)
[![PyPI](https://img.shields.io/pypi/v/alphafold-sovereign-mcp?label=PyPI)](https://pypi.org/project/alphafold-sovereign-mcp/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![MCP Spec 2025-06-18](https://img.shields.io/badge/MCP-2025--06--18-purple)](https://modelcontextprotocol.io)
[![Tests](https://img.shields.io/badge/tests-689%20passing-success)](https://github.com/smaniches/alphafold-sovereign-mcp/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)](https://github.com/smaniches/alphafold-sovereign-mcp/actions/workflows/ci.yml)
[![ORCID](https://img.shields.io/badge/ORCID-0009--0005--6480--1987-A6CE39?logo=orcid&logoColor=white)](https://orcid.org/0009-0005-6480-1987)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.20134773-3C5A99?logo=zenodo&logoColor=white)](https://doi.org/10.5281/zenodo.20134773)

**Status:** `v1.1.9` (Beta). Engineering-validated (689 tests, 100%
line and branch coverage). Not yet scientifically validated by
independent domain experts; not yet deployed in production. See
[`STATUS.md`](STATUS.md) and [`LIMITATIONS.md`](LIMITATIONS.md).

---

## What this is

A Python MCP server that:

- Wraps AlphaFold DB, MONDO, HPO, Open Targets, ClinVar, gnomAD,
  DisGeNET, ChEMBL, and Ensembl behind MCP tool calls. Each call
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
  Vietoris-Rips filtrations of Cα coordinates, and an
  L2-distance comparator between those fingerprint vectors. The full
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
- "Structural distance" between proteins is an L2 distance on
  length-normalised TDA fingerprint vectors. It measures *topological*
  similarity of the Cα point cloud. It is not a sequence similarity,
  RMSD, optimal-transport Wasserstein distance, or
  functional-equivalence measure.
- The AlphaFold structures consumed here are *predicted* models with
  per-residue pLDDT confidence, not experimental structures. Low-pLDDT
  regions are unreliable; some proteins (BRCA1 among them) are largely
  low-confidence, and structural inference over those regions should
  be treated with caution.

For a complete, itemised list of known limitations (with module
references, impact, and planned resolution), see [`LIMITATIONS.md`](LIMITATIONS.md).
For the high-level posture — what is engineering-validated vs. what is
not yet scientifically validated — see [`STATUS.md`](STATUS.md).

---

## Install

### From PyPI (recommended)

```bash
pip install alphafold-sovereign-mcp
```

Or run it without installing using `uvx`:

```bash
uvx alphafold-sovereign-mcp
```

Every release on PyPI is built by the `release.yml` workflow under
OIDC Trusted Publishing, attached to a signed GitHub Release with
SLSA L3 build provenance and Sigstore (`cosign`) signatures, and
mirrored to a Zenodo DOI. Verify the supply chain with
`scripts/replicate.sh`.

### From source

```bash
git clone https://github.com/smaniches/alphafold-sovereign-mcp
cd alphafold-sovereign-mcp
uv pip install -e .
# With persistent-homology TDA (requires gudhi):
# uv pip install -e ".[tda]"
```

### Verify the install

```bash
alphafold-sovereign --version       # → 1.1.9
alphafold-sovereign --self-test     # → PASS on the offline BRCA1 fixture
```

`--self-test` boots the server in offline mode and exercises the
deterministic logic of `generate_variant_clinical_report` against a
built-in `BRCA1:c.5266dupC` fixture. No network calls; returns exit
code 0 on PASS, non-zero on FAIL.

### Configure Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "alphafold-sovereign": {
      "command": "alphafold-sovereign-mcp",
      "args": []
    }
  }
}
```

Restart Claude Desktop and the tools become available in conversations.
See the [`examples/`](examples/) directory for three end-to-end
illustrations of what a session looks like.

### Offline mode

```bash
ALPHAFOLD_OFFLINE=1 alphafold-sovereign-mcp
```

Refuses all outbound HTTP. Serves only from the local SQLite cache.

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
| `compare_proteins_topologically` | Pairwise L2 fingerprint-distance matrix for 2–10 proteins |
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

For three documented end-to-end illustrations of a Claude Desktop
session against this server — variant triage on BRCA1 c.5266dupC,
target characterisation on EGFR, and a drug-discovery walk-through
on Imatinib → BCR-ABL → CML — see the [`examples/`](examples/)
directory. Each example includes the user prompt, the tool calls
the model issues, the server's response shape, and the model's
paraphrased reply.

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
structure, computes the TDA fingerprint, and returns the L2 fingerprint
distance from the human structure along with sequence identity.

---

## Data sources

| Source | What we use | License |
|---|---|---|
| AlphaFold DB v6 (EBI/DeepMind) | Structures, pLDDT, PAE, AlphaMissense | CC BY 4.0 |
| MONDO (OLS4) | Disease ontology, ICD cross-refs | CC BY 4.0 |
| HPO (JAX) | Phenotype terms, gene-disease links | hpo.jax.org |
| Open Targets | Disease–target evidence | Apache 2.0 |
| ClinVar (NCBI) | Variant pathogenicity | Public domain |
| gnomAD v4 | Population allele frequencies | ODbL |
| DisGeNET | Gene–disease association scores | CC BY-NC-SA 4.0 |
| ChEMBL v34 (EMBL-EBI) | Drug bioactivity, MoA, ADMET | CC BY-SA 3.0 |
| Ensembl (EMBL-EBI) | VEP, orthologs, gene lookup | Apache 2.0 |

UniProt accessions are used throughout as protein **identifiers** — they
key AlphaFold structures and Open Targets cross-references — but the
UniProt API itself is not queried as a data source. Domain (InterPro),
Gene Ontology, experimental-structure (RCSB PDB), and tissue-expression
(Human Protein Atlas) lookups are **not** integrated in this release.

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

- 689 unit tests with respx-mocked upstreams; the full suite runs
  hermetically in under a minute on a laptop. Test count includes
  parametrised expansions as reported by `pytest --collect-only`.
- Coverage on the shipped surface (`src/alphafold_sovereign/clients`,
  `domain`, `storage`, `server`, `tools`): **100% line + branch**,
  every shipped module at 100%.
- Lint: `ruff` (full ruleset). Type checking: `mypy --strict` on the
  domain, clients, and storage subtrees.
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
Coverage gate: CI enforces 100% line and branch coverage on the shipped surface (`nox -s cov`).
Full guide: [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Related MCP servers by the same author

- [`uniprot-mcp`](https://github.com/smaniches/uniprot-mcp) — Model Context Protocol server for UniProt Swiss-Prot and TrEMBL (`pip install uniprot-mcp-server`).
- [`semantic-scholar-mcp`](https://github.com/smaniches/semantic-scholar-mcp) — Semantic Scholar MCP server, 200M+ academic papers (`pip install s2-mcp-server`).

---

## Citation

Machine-readable metadata: [`CITATION.cff`](CITATION.cff) (GitHub
renders a "Cite this repository" button in the sidebar that consumes
this file).

```bibtex
@software{maniches_alphafold_sovereign_mcp,
  author    = {Maniches, Santiago},
  title     = {AlphaFold Sovereign MCP},
  year      = {2026},
  version   = {1.1.9},
  url       = {https://github.com/smaniches/alphafold-sovereign-mcp},
  license   = {Apache-2.0},
  orcid     = {0009-0005-6480-1987},
  doi       = {10.5281/zenodo.20134773}
}
```

When citing results derived from this software, please also cite the
upstream data sources (AlphaFold DB, Open Targets, ChEMBL, Ensembl,
ClinVar, gnomAD, MONDO, HPO, DisGeNET) according to their own citation
requirements.

## License

Copyright 2024–2026 Santiago Maniches.

Licensed under the Apache License, Version 2.0. See [`LICENSE`](LICENSE).

Patent reservation: see [`PATENTS.md`](PATENTS.md).
Trademark policy: see [`TRADEMARKS.md`](TRADEMARKS.md).
