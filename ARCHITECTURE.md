# Architecture

This document describes the system design of AlphaFold Sovereign MCP as
**shipped in the current release**. Where a capability is planned but not yet
implemented, it is listed under [Roadmap](#roadmap-not-yet-shipped) rather
than described as if it exists. For the threat model, see
[`docs/threat-model.md`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/docs/threat-model.md).

## Design principles

1. **Sovereign and offline-capable.** The package installs and runs without
   network access. With `ALPHAFOLD_OFFLINE=1`, the base HTTP client refuses
   all egress before a socket is opened and the server answers from the local
   SQLite knowledge graph. The deterministic `--self-test` makes no network
   calls.
2. **Provenance by default.** Every tool result can be persisted to a local,
   content-addressed SQLite store. The `tool_invocations` and `provenance`
   tables record the tool name, parameters, input and output SHA-256 hashes,
   the upstream data-source versions, and a UTC timestamp. Cryptographic
   signing of these records is a roadmap item; it is not yet implemented.
3. **Single licence.** The codebase is Apache 2.0 — one licence, with no
   dual-licence funnel and no feature gated behind a paid edition.
4. **Protocol-native, tools first.** The server implements the MCP *tools*
   surface over the stdio transport: 29 tools registered on a single FastMCP
   application. MCP resources, MCP prompts, and the Streamable HTTP transport
   are on the roadmap and are not part of the shipped surface.
5. **Disease-integrated.** Structural data is joined with disease context.
   The variant- and target-level tools traverse MONDO, HPO, Open Targets,
   ClinVar, gnomAD, and DisGeNET to answer why a given structure matters
   clinically.

---

## Module map (shipped)

```
src/alphafold_sovereign/
│
├── __init__.py          Package metadata (__version__, author, licence)
├── __main__.py          CLI entry point: --version, --self-test, stdio server
│
├── server/              MCP transport layer
│   ├── app.py           The single FastMCP application instance
│   └── stdio.py         stdio transport; imports the tool modules and runs it
│
├── tools/               MCP tool implementations (29 tools; thin orchestration)
│   ├── precision_medicine.py     variant clinical report, ACMG draft,
│   │                             druggability tier, protein dossier,
│   │                             disease–drug map, drug repurposing  (6)
│   ├── structure_intelligence.py pLDDT confidence, topology fingerprint,
│   │                             topological comparison, evolutionary
│   │                             shifts, pocket geometry, disorder      (6)
│   ├── disease.py                MONDO/HPO lookups, target–disease evidence,
│   │                             3-D variant triage, ICD-10 resolution  (12)
│   └── knowledge_graph_tools.py  query and export the local graph        (5)
│
├── clients/             Async HTTP clients — one per upstream (9 + base)
│   ├── _base.py         BaseAsyncClient: httpx HTTP/2, tenacity retry with
│   │                    jitter, aiolimiter per-host rate limiting, a circuit
│   │                    breaker, the offline allowlist, SHA-256 verification
│   ├── alphafold.py     AlphaFold DB (prediction metadata, PDB, PAE, AlphaMissense)
│   ├── opentargets.py   Open Targets Platform GraphQL
│   ├── chembl.py        ChEMBL REST
│   ├── ensembl.py       Ensembl REST (VEP, gene and variant lookup, orthologs)
│   ├── clinvar.py       ClinVar via NCBI E-utilities
│   ├── gnomad.py        gnomAD GraphQL
│   ├── mondo.py         MONDO via OLS4 and the Monarch API
│   ├── hpo.py           HPO via the HPO API and OLS4
│   └── disgenet.py      DisGeNET REST
│
├── domain/              Pure-Python types; no I/O, no network, no MCP SDK
│   └── disease.py       PathogenicityClass, EvidenceType, OntologyTerm,
│                        DiseaseRecord, PhenotypeAssociation,
│                        TargetEvidenceScore, PopulationFrequency, VariantReport
│
└── storage/             Persistence and provenance
    └── knowledge_graph.py   SQLite knowledge graph (WAL mode); six entity,
                             four relationship, and two provenance tables;
                             SHA-256-keyed JSON blobs; optional DuckDB layer
```

The package also contains six reserved namespace packages — `compliance/`,
`compute/`, `observability/`, `prompts/`, `resources/`, and `security/`. Each
is currently an empty `__init__.py`: they reserve import paths for the roadmap
items below and contain no shipped code.

---

## Data flow

### 3-D variant triage (representative multi-source tool)

```
Claude (MCP client): triage_variant_3d(hgvs="BRCA1:c.181T>G")
  │
  ▼
tools/disease.py::triage_variant_3d
  │
  ├─ clients/ensembl.py      HGVS -> UniProt accession, residue position
  ├─ clients/alphafold.py    structure context + AlphaMissense score
  ├─ clients/clinvar.py      ClinVar interpretation + review status
  ├─ clients/gnomad.py       population allele frequency + constraint
  ├─ clients/opentargets.py  disease–target evidence scores
  ├─ clients/mondo.py        disease names, synonyms, ICD-10 cross-refs
  │
  ├─ domain/disease.py::VariantReport   assembled, validated result
  └─ storage/knowledge_graph.py         optional persist: result + provenance
```

Every upstream call passes through `clients/_base.py`, which applies a
per-host rate limit (aiolimiter), retry with exponential back-off and jitter
(tenacity), and a per-host circuit breaker. With `ALPHAFOLD_OFFLINE=1`, egress
is refused at this layer and the request is served from the knowledge graph if
the data is already present.

---

## Persistence: the knowledge graph

The only persistence layer is a local SQLite database
(`storage/knowledge_graph.py`), opened in WAL mode. Its location defaults to
the platform user-data directory and can be overridden with `ALPHAFOLD_KG_PATH`.
The schema comprises:

- **Entity tables (6):** `proteins`, `variants`, `diseases`, `drugs`,
  `phenotypes`, `genes`.
- **Relationship tables (4):** `protein_disease`, `protein_drug`,
  `variant_disease`, `gene_phenotype`.
- **Provenance tables (2):** `tool_invocations` (each tool call with its
  parameters, input and output hashes, and timing) and `provenance` (the
  data-source version snapshot per invocation).

Result blobs are stored as SHA-256-keyed JSON, so identical inputs deduplicate
and an analysis can be replayed offline. If DuckDB is installed it is used as
an optional columnar layer for aggregation and export; it is not required and
is not a runtime dependency.

---

## Disease-ontology integration

The disease-layer tools query six upstreams directly:

| Source | What is used | API |
|---|---|---|
| MONDO | Unified disease IDs and cross-references (ICD-10, OMIM, Orphanet, DOID) | OLS4 REST + Monarch |
| HPO | Phenotype terms and gene–phenotype links | HPO API + OLS4 |
| Open Targets | Disease–target evidence and association scores | GraphQL |
| ClinVar | Variant clinical significance and review status | NCBI E-utilities |
| gnomAD | Population allele frequencies and constraint | GraphQL |
| DisGeNET | Gene–disease association scores | REST |

ICD-10 codes (`resolve_icd10_to_mondo`) and Orphanet rare-disease identifiers
(`get_orphan_disease_atlas`) are resolved through MONDO's cross-references,
not by querying separate ICD or Orphanet services. The
`get_common_disease_targets` tool profiles protein targets across the major
ICD-10 disease chapters, anchored to MONDO disease roots.

---

## Security and sovereignty

Shipped controls:

- **Egress control.** With `ALPHAFOLD_OFFLINE=1`, all outbound requests are
  refused in `clients/_base.py` before a socket is opened.
  `ALPHAFOLD_ALLOW_HOSTS` provides a comma-separated allowlist for
  partial-air-gap deployments.
- **Provenance trail.** Tool invocations are recorded in the SQLite
  `tool_invocations` table with input and output SHA-256 hashes and UTC
  timestamps. These records are insert-only in normal operation.
- **Parameterised SQL.** All knowledge-graph queries use bound parameters;
  table names are drawn from a fixed internal allowlist, never from user input.

For the full STRIDE analysis, see [`docs/threat-model.md`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/docs/threat-model.md).

---

## Roadmap (not yet shipped)

These capabilities are intentionally absent from the current release and are
listed so the shipped boundary is unambiguous:

- **Streamable HTTP transport with OAuth 2.1 / PKCE.** Only the stdio
  transport ships today; stdio clients (such as Claude Desktop) own their own
  process capabilities and use no separate auth.
- **MCP resources and prompts.** Only the tools surface is implemented.
- **Cryptographic signing of provenance records** (for example, ed25519
  signatures and an external transparency log). Records are currently stored
  unsigned in SQLite.
- **A FIPS 140-3 build** that switches `cryptography` to the OpenSSL FIPS
  provider.

The reserved namespace packages (`compliance/`, `compute/`, `observability/`,
`prompts/`, `resources/`, `security/`) hold the import paths for this work.
