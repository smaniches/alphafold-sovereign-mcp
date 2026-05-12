# Threat Model

> First-cut STRIDE-style threat model for v1.1.0-rc1. This document
> is the baseline for the security review work in v1.2.0. Findings
> from the v1.2.0 audit (see [`AUDIT.md`](audit.md)) will be appended
> here as new threat IDs or amendments to existing ones.

## Scope

This threat model covers the MCP server (`alphafold-sovereign-mcp`)
as deployed by an end user on their own machine, communicating over
stdio with an MCP client (typically Claude Desktop) and calling
public biomedical APIs over the internet (or refusing to, in
offline mode).

**Out of scope:**

- The MCP client itself (Claude Desktop, etc.).
- The upstream APIs' own security posture.
- Network-layer attacks beyond what the host OS provides (TLS is
  handled by `httpx`).
- Streamable HTTP / OAuth (planned for v1.3 — see
  [STATUS.md "Roadmap"](status.md)).

## Trust boundaries

```
┌─────────────────────────────────────────────────────────────┐
│  User's machine                                             │
│                                                             │
│  ┌──────────────┐    stdio JSON-RPC    ┌─────────────────┐ │
│  │ MCP client   │ ◄──────────────────► │ alphafold-      │ │
│  │ (Claude      │                      │ sovereign-mcp   │ │
│  │ Desktop)     │                      │                 │ │
│  └──────────────┘                      └──┬──────────────┘ │
│                                            │                │
│                                            ▼                │
│                         ┌────────────────────────────────┐ │
│                         │  Local SQLite knowledge graph  │ │
│                         │  ~/.alphafold-sovereign-mcp/   │ │
│                         └────────────────────────────────┘ │
└──────────────────────────────│──────────────────────────────┘
                               │ HTTPS (off by default in offline mode)
                               ▼
                ┌──────────────────────────────┐
                │  14 upstream biomedical APIs │
                │  (Ensembl, ClinVar, gnomAD,  │
                │   AlphaFold DB, …)           │
                └──────────────────────────────┘
```

Three trust boundaries:

1. **Client → Server**: stdio is on the same host but the MCP client
   process is a different program. The server trusts only the JSON-RPC
   protocol surface, not the client's intent — but it accepts every
   `tools/call` the client sends.
2. **Server → Local SQLite**: same-host. The DB file is at a path
   controlled by `platformdirs`; permissions follow the OS user.
3. **Server → Upstream APIs**: outbound HTTPS. The server can be
   pinned via `ALPHAFOLD_ALLOW_HOSTS` or disabled entirely via
   `ALPHAFOLD_OFFLINE=1`.

## STRIDE table

| ID | Threat | Category | Surface | Mitigation | Code receipt |
|---|---|---|---|---|---|
| T01 | A malicious local user impersonates Claude Desktop and invokes tools that exfiltrate cached data. | **Spoofing** | stdio | stdio runs on the same OS user; no cross-user authentication. The cache file is OS-permission-protected. The server has no concept of "user identity" because everything is local. | `server/stdio.py`, `storage/knowledge_graph.py` |
| T02 | A compromised upstream API returns adversarial JSON to corrupt the knowledge graph. | **Tampering** | client → upstream | All responses are deserialised through Pydantic models (`domain/`) with strict types. Unknown/malformed fields are dropped, not stored. Schema drift surfaces as a `ValidationError`, not silent corruption. | `domain/*.py`, every `clients/*` returns typed models |
| T03 | A malformed `tools/call` argument causes a SQL injection in the knowledge graph. | **Tampering** | client → server → DB | All SQL is parameterised. `_ALLOWED_TABLES` allow-list guards `export_to_dict(tables=...)`. CWE-89 closed; CodeQL `security-extended` runs on every push. | `storage/knowledge_graph.py` (`_fetchall`, `_executemany`); CI workflow `.github/workflows/ci.yml` |
| T04 | A user disputes that a tool was invoked or returned a certain result. | **Repudiation** | server | Every tool invocation is recorded in the SQLite knowledge graph with timestamp and arguments. The cache file is the audit trail; signing it (Sigstore Rekor or local ed25519) is on the v1.3 roadmap. | `storage/knowledge_graph.py` `record_*` methods |
| T05 | The MCP client (or a malicious tool argument) extracts sensitive cached data. | **Information disclosure** | client → server | The knowledge graph holds only public biomedical metadata — no PHI, no credentials. The server does not read environment variables to obtain secrets (upstream APIs we use are unauthenticated). If a future API requires a token, it will be loaded from a config file the user explicitly creates. | All `clients/*.py` — no `os.environ.get("*_API_KEY")` calls in v1.1.0-rc1 |
| T06 | Logs leak sensitive query content (e.g., a patient identifier inadvertently passed as a `gene_symbol` argument). | **Information disclosure** | server → stdout/stderr | `structlog` JSON logs include argument values. Recommended deployment: redirect stderr to a file the user owns. The server itself does not log to remote endpoints. | `server/stdio.py` uses `structlog.get_logger`; no remote handlers |
| T07 | An upstream API rate-limits or 5xx-storms the server, blocking legitimate requests. | **Denial of service** | server → upstream | `aiolimiter` token-bucket per host; `tenacity` exponential backoff with jitter; circuit breaker (`CircuitBreaker` in `clients/_base.py`) opens after `failure_threshold` consecutive failures and refuses requests for `cooldown_seconds`. | `clients/_base.py` (`UpstreamConfig`, `CircuitBreaker`, `RetryConfig`) |
| T08 | A buggy or malicious upstream returns a 100 MB JSON payload, OOMing the server. | **Denial of service** | server → upstream | `httpx` requests use a default response timeout and the client modules read responses into bounded Pydantic models. No streaming-into-memory of unbounded payloads. We do not yet enforce a max-response-bytes; this is tracked. | `clients/_base.py`; **gap: max-bytes ceiling — track for v1.2.0** |
| T09 | A user calls `export_research_dataset` with an arbitrary table name, getting access to internal tables. | **Elevation of privilege** | client → server → DB | `_ALLOWED_TABLES` allow-list explicitly enumerates exportable tables. Any other table name returns a `ValueError`. Unit test exists. | `storage/knowledge_graph.py:_ALLOWED_TABLES`; `tests/test_knowledge_graph.py` |
| T10 | A path-traversal argument tricks the server into writing the SQLite DB outside its allowed directory. | **Elevation of privilege** | client → server | The DB path is computed via `platformdirs.user_data_dir(...)` and is not configurable from the MCP API surface. No tool exposes a `path=` argument. | `storage/knowledge_graph.py` (constructor uses `platformdirs`) |
| T11 | A user runs the server in offline mode but the cache contains stale or attacker-tainted data from an earlier online session. | **Tampering / Information disclosure** | server → cache | This is a known limitation: in offline mode, the cache is the source of truth. Users responsible for the integrity of their own cache file. The v1.3 air-gap bundle work will introduce a signed bundle format. | `server/stdio.py` (`ALPHAFOLD_OFFLINE` flag); **gap: signed bundle — v1.3** |
| T12 | A malicious PR introduces a dependency with a backdoor. | **Supply chain** | repo | Apache 2.0 + Dependabot + Bandit + Safety + pip-audit + CodeQL on every PR. SBOM (CycloneDX) emitted in CI. SLSA L3 build provenance + cosign signing on the release artefacts (Phase E of the polish sprint). | `.github/workflows/ci.yml`, `release.yml`; OpenSSF Scorecard badge in README |

## Risk register summary

| Risk level | Count | IDs |
|---|---|---|
| High | 0 | — |
| Medium (with named mitigation) | 4 | T03, T07, T09, T12 |
| Medium (with gap) | 2 | T08, T11 |
| Low | 6 | T01, T02, T04, T05, T06, T10 |

## Identified gaps (tracked for v1.2.0+)

- **T08**: enforce a configurable max-response-bytes in `clients/_base.py`.
- **T11**: signed offline-bundle format so a tampered cache is detectable.
- **T04**: append-only signed audit log (Sigstore Rekor option).

## How to add or amend a threat

When a new threat is identified (e.g., by a security audit or a
researcher report):

1. Open a GitHub issue with the `threat-model` label.
2. Add a new `T<NN>` row to the STRIDE table in a PR; or amend an
   existing row with new mitigations or new gaps.
3. If the threat is exploitable today, follow the disclosure
   process in [SECURITY.md](security.md).

---

Last updated: 2026-05-11.
