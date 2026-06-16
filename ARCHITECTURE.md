# Architecture

This document describes the system design of AlphaFold Sovereign MCP as
**shipped in the current release**. Where a capability is planned but not yet
implemented, it is listed under [Roadmap](#roadmap-not-yet-shipped) rather
than described as if it exists. For the threat model, see
[`docs/threat-model.md`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/docs/threat-model.md).

## Design principles

1. **Sovereign and offline-capable.** The package installs and runs without
   network access. With `ALPHAFOLD_OFFLINE=1`, the base HTTP client refuses
   all egress before a socket is opened (raising `AirGapError`). The
   knowledge-graph query and export tools answer from the local SQLite store;
   the upstream-querying tools do not read the knowledge graph, so they fail
   closed in offline mode -- any upstream call raises `AirGapError`. The
   deterministic `--self-test` makes no network calls.
2. **Provenance by capability.** Every tool result *can* be persisted to a
   local SQLite store through the knowledge-graph API. The
   `tool_invocations` and `provenance` tables are designed to hold the tool
   name, parameters, input and output SHA-256 hashes, the upstream
   data-source versions, and a UTC timestamp; the writer
   (`KnowledgeGraph.log_tool_invocation`) exists but is not yet hooked into
   the tool-dispatch path, so in normal operation these tables stay empty
   unless a caller persists explicitly. Cryptographic signing of these
   records is a roadmap item; it is not yet implemented.
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
│   │                    breaker, and the offline allowlist (raises AirGapError);
│   │                    a _sha256 helper is available to callers, not auto-applied
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
                             per-row SHA-256 fingerprint columns (not keys)
```

The package also contains six reserved namespace packages — `compliance/`,
`compute/`, `observability/`, `prompts/`, `resources/`, and `security/`. Each
is currently an empty `__init__.py`: they reserve import paths for the roadmap
items below and contain no shipped code.

---

## Data flow

### 3-D variant triage (a multi-source tool)

This is the data flow as currently implemented. Some upstreams named in the
tool's design are not yet wired (see the Wave-3 notes inline and in the
[Roadmap](#roadmap-not-yet-shipped)).

```
Claude (MCP client): triage_variant_3d(hgvs="BRCA1:c.181T>G")
  │
  ▼
tools/disease.py::triage_variant_3d
  │
  ├─ _parse_hgvs_gene        extract gene symbol from the HGVS string
  │                          (local parse; no Ensembl/UniProt resolution yet)
  ├─ clients/clinvar.py      ClinVar interpretation + review status
  ├─ clients/gnomad.py       gnomAD gene-constraint scores; AlphaMissense
  │                          score is read from this payload when present
  ├─ disease context         placeholder note today; full Open Targets /
  │                          MONDO traversal is a Wave-3 item
  ├─ structure context       a text note pointing at analyze_structural_confidence(); the
  │                          AlphaFold pLDDT/PAE join is a Wave-3 item
  │
  └─ result                  assembled as a plain dict with a provenance
                             footer and returned as JSON (no automatic
                             knowledge-graph persist)
```

Every upstream call passes through `clients/_base.py`, which applies a
per-host rate limit (aiolimiter), retry with exponential back-off and jitter
(tenacity), and a per-host circuit breaker. With `ALPHAFOLD_OFFLINE=1`, egress
is refused at this layer before a socket is opened (`AirGapError`); the client
layer does not transparently fall back to the knowledge graph, so a tool that
needs fresh upstream data fails closed in offline mode.

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
- **Provenance tables (2):** `tool_invocations` (a tool call with its
  parameters, input and output hashes, and timing) and `provenance` (the
  data-source version snapshot per invocation). The writer for
  `tool_invocations`, `KnowledgeGraph.log_tool_invocation`, is implemented but
  is not yet called from the tool-dispatch path, so the table is populated
  only when a caller invokes it explicitly.

Result blobs are stored as JSON in the `tool_invocations` table; each row also
carries SHA-256 fingerprint columns (params/result hashes) recorded for integrity
inspection, not used as keys -- so there is no content-addressing and identical
results are not deduplicated. Data already written to the store can be queried and
exported offline through the knowledge-graph tools. A columnar analytical layer
(DuckDB) for aggregation and export is planned but not yet wired: there is no
DuckDB runtime dependency and the code does not import it. See the
[Roadmap](#roadmap-not-yet-shipped).

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
- **Provenance trail (capability).** The SQLite `tool_invocations` table can
  hold each tool call with input and output SHA-256 hashes and UTC timestamps,
  written insert-only via `KnowledgeGraph.log_tool_invocation`. This writer is
  not yet hooked into tool dispatch, so the trail is populated only when a
  caller logs explicitly; automatic per-invocation logging is a roadmap item.
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
- **Automatic provenance logging.** `KnowledgeGraph.log_tool_invocation`
  exists but is not yet invoked by the tool-dispatch path; wiring it in so
  every MCP tool call lands in `tool_invocations` is a roadmap item. Until
  then the audit trail is a capability, not an always-on behaviour.
- **A DuckDB analytical layer.** A columnar path over the SQLite store for
  fast aggregation and export is planned. It is not wired today: there is no
  DuckDB dependency and the code does not import it.
- **Cryptographic signing of provenance records** (for example, ed25519
  signatures and an external transparency log). Records are currently stored
  unsigned in SQLite.
- **A FIPS 140-3 build** that switches `cryptography` to the OpenSSL FIPS
  provider.

The reserved namespace packages (`compliance/`, `compute/`, `observability/`,
`prompts/`, `resources/`, `security/`) hold the import paths for this work.
