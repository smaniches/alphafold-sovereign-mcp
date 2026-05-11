# Architecture

This document describes the system design of AlphaFold Sovereign MCP.
For the rationale behind key decisions, see `docs/adr/`. For the
threat model, see `docs/THREAT_MODEL.md`.

## Design Principles

1. **Sovereign first.** Every feature must be installable and operable
   without network access. Online APIs enhance; they never gate.
2. **Auditable by default.** Every tool invocation produces a signed,
   content-addressed audit record. Nothing is optional except the
   exporter.
3. **Single licence.** The codebase is Apache 2.0 — one licence,
   no dual-licence funnel, no feature gated behind a paid edition.
4. **Protocol-native.** We implement the full MCP 2025-06-18 surface:
   tools, resources, prompts, sampling, roots, progress, cancellation,
   and resource subscriptions. We do not paper over the spec.
5. **Disease-integrated.** Structural biology without disease context
   is incomplete. Every protein query optionally traverses MONDO, HPO,
   Open Targets, ClinVar, gnomAD, and DisGeNET to answer "why does
   this structure matter clinically?"

---

## Module Map

```
src/alphafold_sovereign/
│
├── server/               MCP transport layer
│   ├── __init__.py
│   ├── stdio.py          stdio (Claude Desktop / CLI)
│   ├── http.py           Streamable HTTP (MCP spec 2025-06-18)
│   ├── auth.py           OAuth 2.1 + PKCE + capability tokens
│   ├── session.py        Mcp-Session-Id, resumability, Last-Event-ID
│   └── registry.py       Tool / resource / prompt registration
│
├── tools/                MCP tool implementations (thin orchestration)
│   ├── structure.py      Structure retrieval, search, batch, cache
│   ├── features.py       pLDDT profiles, PAE, contact maps
│   ├── topology.py       Persistent homology, Wasserstein / bottleneck
│   ├── enrichment.py     UniProt, GO annotations, domain families
│   ├── analysis.py       Disorder, domain detection, IC, semantics
│   ├── disease.py    ★   MONDO, HPO, Open Targets, common-disease targets
│   ├── variants.py       AlphaMissense, ClinVar, gnomAD, HGVS triage
│   ├── biothreat.py      Sequence-of-concern, cross-species homology
│   └── federation.py     Peer discovery, delegation, mesh routing
│
├── resources/            MCP Resources (URI-addressable canonical data)
│   ├── protein.py        protein://{uniprot_id}
│   ├── structure.py      structure://{uniprot_id}/{layer}
│   ├── disease.py        disease://{mondo_id}
│   └── ontology.py       go://{go_id}, hpo://{hpo_id}, mondo://{mondo_id}
│
├── prompts/              MCP Prompts (curated multi-turn workflows)
│   ├── clinical.py       triage_missense_variant, summarize_for_clinician
│   ├── discovery.py      characterize_drug_target, find_binding_pocket
│   ├── comparative.py    compare_orthologs, assess_disorder_landscape
│   └── biosec.py         screen_sequence_of_concern, assess_dual_use_risk
│
├── clients/              Async HTTP clients (one per upstream)
│   ├── _base.py          httpx + tenacity + aiolimiter + circuit breaker
│   ├── alphafold.py      AlphaFold DB v4 (PDB, CIF, PAE, confidence)
│   ├── uniprot.py        UniProt REST + SPARQL
│   ├── pdb.py            RCSB PDB REST + GraphQL; PDBe
│   ├── interpro.py       InterPro / Pfam domain annotations
│   ├── mondo.py      ★   MONDO via OLS4 + Monarch API
│   ├── hpo.py        ★   HPO via HPO API + OLS4
│   ├── opentargets.py ★  Open Targets Platform GraphQL
│   ├── clinvar.py    ★   ClinVar via NCBI E-utilities
│   ├── gnomad.py     ★   gnomAD GraphQL
│   ├── disgenet.py   ★   DisGeNET REST
│   ├── ensembl.py        Ensembl REST (gene / variant)
│   ├── chembl.py         ChEMBL REST
│   ├── openfda.py        openFDA REST
│   ├── clinicaltrials.py ClinicalTrials.gov v2
│   └── pubmed.py         NCBI PubMed E-utilities
│
├── domain/               Pure-Python types; no I/O
│   ├── structure.py      AlphaFoldStructure, Atom, Residue, Metadata
│   ├── sequence.py       AminoAcidSequence, HGVS, VariantPosition
│   ├── disease.py    ★   DiseaseRecord, PhenotypeAssociation,
│   │                      TargetEvidenceScore, VariantReport
│   ├── ontology.py       GOTerm, MONDOTerm, HPOTerm, OntologyEdge
│   └── provenance.py     ToolCallRecord, ContentHash, AuditEntry
│
├── storage/              Persistence and indexing
│   ├── cache.py          LRU + on-disk + optional Redis
│   ├── index.py          Dynamic UniProt-ID index (O(1))
│   ├── object_store.py   S3 / MinIO / local FS adapter
│   └── content_addressed.py  SHA-256 keyed immutable store
│
├── compute/              CPU / GPU computation
│   ├── ripser_adapter.py Persistent homology via ripser.py
│   ├── pae.py            PAE extraction, domain detection
│   ├── disorder.py       Intrinsic disorder predictor
│   ├── semantics.py      GO IC, Resnik/Lin/Jiang similarity
│   ├── foldseek_adapter.py Structure-similarity search
│   └── batched.py        Bounded-concurrency asyncio.gather
│
├── observability/        Cross-cutting concerns
│   ├── logging.py        structlog JSON, request_id correlation
│   ├── tracing.py        OpenTelemetry OTLP spans
│   ├── metrics.py        Prometheus + OTel metrics
│   └── audit.py          Signed audit log (ed25519 + optional Rekor)
│
└── security/             Security controls
    ├── signing.py        ed25519 reasoning-trace signatures
    ├── policy.py         OPA / Rego policy hooks
    ├── secrets.py        env + Vault + AWS KMS providers
    ├── allowlist.py      Outbound domain allowlist (air-gap mode)
    └── screening.py      Sequence-of-concern + dual-use guardrails
```

★ = new in this wave

---

## Data Flow

### Online Structure Request (typical)

```
Claude (MCP client)
  │  tool_call: get_structure(uniprot_id="P12345")
  ▼
server/stdio.py  ─── request_id, session_id generated
  │
  ▼
tools/structure.py  ─── validate Pydantic input
  │
  ├──(1) storage/index.py  ─── O(1) hash-set lookup
  │        │ hit → storage/cache.py → return CIF bytes
  │        │ miss ↓
  │        └──(2) clients/alphafold.py
  │                   httpx GET alphafold.ebi.ac.uk/files/AF-P12345-F1-model_v4.pdb
  │                   retry(tenacity) → rate-limit(aiolimiter) → circuit-breaker
  │                   response bytes → SHA-256 verify → storage/cache.py store
  │
  ├──(3) compute/ripser_adapter.py  ─── Cα coords → VR filtration → barcodes
  │
  ├──(4) observability/audit.py  ─── sign & append AuditEntry
  │
  └──(5) format response → provenance footer appended
              (server version · timestamp · request_id · content_hash)
  ▼
Claude: structured Markdown + JSON with provenance
```

### Variant Triage (new disease layer)

```
Claude: triage_variant_3d(hgvs="BRCA1:c.181T>G")
  │
  ▼
tools/disease.py::triage_variant_3d
  │
  ├─ clients/ensembl.py    HGVS → UniProt accession, residue position
  ├─ clients/alphafold.py  3-D structure → residue neighborhood
  ├─ clients/alphafold.py  AlphaMissense score for that variant
  ├─ clients/clinvar.py    ClinVar interpretation + review status
  ├─ clients/gnomad.py     Population allele frequency + constraint
  ├─ clients/opentargets.py  Disease-target evidence scores
  ├─ clients/mondo.py      Disease names, synonyms, ICD-10/11 cross-refs
  │
  └─ domain/disease.py::VariantReport  ─── assembled structured report
       provenance footer: all upstream call IDs + timestamps + hashes
```

---

## Disease Ontology Integration

### Sources

| Source | What we use | API |
|---|---|---|
| MONDO | Unified disease IDs, cross-refs (ICD-10, OMIM, Orphanet, DOID) | OLS4 REST + Monarch |
| HPO | Phenotype terms, HPO-disease links, phenotype profiles | HPO REST + OLS4 |
| Open Targets | Disease-target evidence, association scores, evidence types | GraphQL |
| ClinVar | Variant pathogenicity, clinical significance, review status | NCBI E-utils |
| gnomAD | Population allele frequencies, constraint scores, pext | GraphQL |
| DisGeNET | Gene-disease association scores, literature evidence | REST |
| ICD-10/11 | Clinical coding (billing, EHR integration) | NLM API |
| Orphanet | Rare-disease-specific data, prevalence | OLS4 |
| MeSH | Literature indexing, disease hierarchy | NCBI E-utils |
| OMIM | Mendelian disease genetics (API key required) | REST |

### Common-Disease Coverage

The `get_common_disease_targets` tool profiles protein targets across
all major ICD-10 disease chapters, with curated prevalence tiers:

| ICD chapter | Representative conditions | MONDO root |
|---|---|---|
| I — Circulatory | MI, stroke, HF, AFib, hypertension | MONDO:0004995 |
| II — Neoplasms | Top-10 cancers by incidence | MONDO:0045024 |
| III — Blood | Leukaemia, lymphoma, anaemia | MONDO:0005570 |
| IV — Endocrine | T1DM, T2DM, thyroid disease | MONDO:0005002 |
| V — Mental | Depression, schizophrenia, bipolar | MONDO:0005084 |
| VI — Neurological | AD, PD, ALS, MS, epilepsy | MONDO:0005071 |
| X — Respiratory | COPD, asthma, IPF, TB | MONDO:0005087 |
| XI — Digestive | IBD, NASH, CRC | MONDO:0004335 |
| XIII — Musculoskeletal | RA, OA, SLE | MONDO:0007147 |
| I (infectious) | HIV, COVID-19, malaria, TB | MONDO:0005550 |

---

## Caching Architecture

```
Request
  │
  ├─ L1: Python LRU dict (in-process, TTL 10 min)
  ├─ L2: On-disk SHA-256 content store (persistent, no TTL)
  ├─ L3: Redis (optional, for multi-instance deployments)
  └─ L4: Air-gap bundle (signed snapshot for offline mode)
```

Cache keys are always the SHA-256 of `(upstream_url, canonical_params)`.
This means any two calls with identical parameters return the same
bytes, always — enabling deterministic audit replay.

---

## Security Architecture

See `docs/THREAT_MODEL.md` for the full STRIDE analysis.

Key controls:

- **Outbound allowlist** — in air-gap mode (`ALPHAFOLD_OFFLINE=1`),
  all egress is blocked at the `clients/_base.py` layer before a
  socket is opened.
- **Sequence-of-concern screening** — `security/screening.py` runs
  before any deep enrichment of a submitted protein sequence.
- **Audit log** — every tool invocation is recorded in the
  `tool_invocations` table with SHA-256 hashes of inputs and outputs
  and a UTC timestamp. The log is append-only at the SQLite layer;
  cryptographic signing of audit records is a tracked work item
  (not yet implemented in the shipped codebase).

Items on the roadmap but **not** yet implemented in the shipped
codebase, listed here so the boundary is clear:

- OAuth 2.1 + PKCE on the HTTP transport (the stdio transport, which
  is what `claude-desktop` uses, has no separate auth — the client
  process owns its capabilities).
- A FIPS 140-3 build that switches `cryptography` to the OpenSSL FIPS
  provider.
