# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""MCP tools for querying the local AlphaFold Sovereign Knowledge Graph.

These tools read and traverse the local SQLite knowledge graph — a genuine
ACID store (WAL journalling, versioned migrations, schema v3) with foreign-key
integrity across proteins, variants, diseases, drugs and their relationships.

The graph ships with a curated boot seed (loaded automatically when the store
is empty; disable with ``AFSMCP_DISABLE_KG_SEED=1``) so these tools return
representative results out of the box. It is extended by writing through the
knowledge-graph storage API; the analysis tools do not write to it on their own
(no automatic per-invocation persistence). On top of that store the tools provide:

  - Recall of stored entities with no upstream API call required
  - Cross-entity pattern queries ("which HIGH-tier variants share a WARM target?")
  - Batch export to JSON for pandas/ML pipelines
  - Optional provenance/audit tables (opt-in; empty by default)

Tool inventory:
  1. query_variant_database  — search stored variant triage results
  2. query_protein_database  — search stored protein assessments
  3. get_knowledge_graph_stats — database health and coverage summary
  4. export_research_dataset  — export to JSON for pandas/ML pipelines
  5. find_drug_gene_network   — traverse the stored drug-gene-disease graph
"""

from __future__ import annotations

import datetime
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

from alphafold_sovereign import __version__
from alphafold_sovereign.server.app import mcp
from alphafold_sovereign.storage.knowledge_graph import get_knowledge_graph

logger = structlog.get_logger(__name__)


def _provenance(**meta: str) -> str:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = ", ".join(f"{k}={v}" for k, v in meta.items() if v)
    return f"\n\n---\n*AlphaFold Sovereign MCP v{__version__} · {ts} · local-kg · {parts}*"


# ── Input models ──────────────────────────────────────────────────────────────


class VariantQueryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    gene: str | None = Field(None, description="Filter by gene symbol (e.g. 'BRCA1').")
    tier: Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"] | None = Field(
        None, description="Clinical tier filter."
    )
    clinvar_class: str | None = Field(
        None, description="ClinVar classification (e.g. 'Pathogenic')."
    )
    min_am_score: float | None = Field(
        None, ge=0.0, le=1.0, description="Minimum AlphaMissense score (0.564 = likely pathogenic)."
    )
    max_gnomad_af: float | None = Field(
        None, ge=0.0, le=1.0, description="Maximum gnomAD allele frequency (0.001 = rare)."
    )
    limit: int = Field(default=50, ge=1, le=500, description="Maximum rows to return (1–500).")


class ProteinQueryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    druggability_tier: Literal["HOT", "WARM", "COLD", "NOT_DRUGGABLE"] | None = Field(
        None,
        description="Keep only stored proteins with this druggability tier; omit for any tier.",
    )
    min_plddt: float | None = Field(
        None,
        ge=0.0,
        le=100.0,
        description="Minimum stored mean AlphaFold pLDDT (0–100; ≥70 = high confidence).",
    )
    limit: int = Field(default=50, ge=1, le=500, description="Maximum rows to return (1–500).")


class ExportInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    tables: list[str] = Field(
        default_factory=list,
        description=(
            "Tables to export. Leave empty for all entity tables. "
            "Options: proteins, variants, diseases, drugs, protein_disease, protein_drug."
        ),
    )
    limit_per_table: int = Field(
        default=5000, ge=1, le=50000, description="Maximum rows to export per table (1–50000)."
    )


class DrugNetworkInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    seed: str = Field(
        ...,
        description=(
            "Seed entity: UniProt ID (e.g. 'P38398'), gene symbol (e.g. 'BRCA1'), "
            "or MONDO ID (e.g. 'MONDO:0007254')."
        ),
    )
    max_hops: int = Field(default=2, ge=1, le=3, description="Graph traversal depth.")


# ── Tools ─────────────────────────────────────────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Query Variant Research Database",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def query_variant_database(
    params: VariantQueryInput,
) -> dict[str, Any]:
    """Search the local knowledge graph for stored variants.

    Returns variants matching the filter criteria. No upstream API calls are
    made — all data is served from the local SQLite knowledge graph, which is
    populated by the curated boot seed and by any explicit writes through the
    knowledge-graph storage API (the analysis tools do not write to it on their
    own).

    Args:
        params.gene: Gene symbol filter.
        params.tier: Clinical tier (HIGH/MEDIUM/LOW/UNKNOWN).
        params.clinvar_class: ClinVar classification string.
        params.min_am_score: Minimum AlphaMissense score.
        params.max_gnomad_af: Maximum gnomAD allele frequency.
        params.limit: Maximum results.
    """
    async with get_knowledge_graph() as kg:
        rows = await kg.query_variants(
            gene=params.gene,
            tier=params.tier,
            clinvar_class=params.clinvar_class,
            min_am_score=params.min_am_score,
            max_gnomad_af=params.max_gnomad_af,
            limit=params.limit,
        )

    return {
        "query": {
            "gene": params.gene,
            "tier": params.tier,
            "clinvar_class": params.clinvar_class,
            "min_am_score": params.min_am_score,
            "max_gnomad_af": params.max_gnomad_af,
        },
        "result_count": len(rows),
        "variants": rows,
        "note": (
            "Results served from the local knowledge graph. The store is populated "
            "by the curated boot seed (disable with AFSMCP_DISABLE_KG_SEED=1) and by "
            "explicit writes through the knowledge-graph storage API."
        ),
        "provenance": _provenance(source="local-kg"),
    }


@mcp.tool(
    annotations={
        "title": "Query Protein Research Database",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def query_protein_database(
    params: ProteinQueryInput,
) -> dict[str, Any]:
    """Recall proteins already stored in the local knowledge graph.

    This is a local-recall query, not a live lookup: it returns only proteins that
    have previously been written to the local SQLite store (the curated boot seed,
    plus anything added through the knowledge-graph storage API). No upstream API is
    called. To assess a protein that may not be stored yet, use
    ``assess_target_druggability`` (druggability tier) or
    ``analyze_structural_confidence`` (pLDDT), which query live sources.

    Filters are combined with AND; omit a filter to leave that dimension
    unconstrained. Returns a JSON record with the applied ``query``, a
    ``result_count``, and the matching ``proteins`` rows. The list is empty when
    nothing stored matches — common when only the boot seed is loaded, so a broad
    filter returning few rows usually means the store is small, not that no such
    protein exists.

    Args:
        params.druggability_tier: Keep only proteins whose stored tier equals this
            (HOT, WARM, COLD, or NOT_DRUGGABLE); omit for any tier.
        params.min_plddt: Keep only proteins whose stored mean AlphaFold pLDDT
            (0–100; ≥70 is high confidence) is at least this value.
        params.limit: Maximum rows to return (1–500).
    """
    async with get_knowledge_graph() as kg:
        rows = await kg.query_proteins(
            druggability_tier=params.druggability_tier,
            min_plddt=params.min_plddt,
            limit=params.limit,
        )

    return {
        "query": {
            "druggability_tier": params.druggability_tier,
            "min_plddt": params.min_plddt,
        },
        "result_count": len(rows),
        "proteins": rows,
        "note": (
            "Results served from the local knowledge graph. The store is populated "
            "by the curated boot seed (disable with AFSMCP_DISABLE_KG_SEED=1) and by "
            "explicit writes through the knowledge-graph storage API."
        ),
        "provenance": _provenance(source="local-kg"),
    }


@mcp.tool(
    annotations={
        "title": "Get Knowledge Graph Statistics",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def get_knowledge_graph_stats() -> dict[str, Any]:
    """Return statistics about the local knowledge graph.

    Shows entity counts, database size, and last activity — useful for
    understanding the current contents and coverage of the local store.
    """
    async with get_knowledge_graph() as kg:
        stats = await kg.get_statistics()

    stats["description"] = (
        "AlphaFold Sovereign local knowledge graph — "
        "persistent ACID SQLite store (curated seed plus explicitly stored entities). "
        f"Database: {stats['database_path']}"
    )
    stats["provenance"] = _provenance(source="local-kg")
    return stats


@mcp.tool(
    annotations={
        "title": "Export Research Dataset",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def export_research_dataset(
    params: ExportInput,
) -> dict[str, Any]:
    """Export the stored knowledge-graph data for downstream analysis.

    Returns all stored entities as JSON-serialisable dicts, suitable for:
    - Loading into pandas DataFrames for ML feature engineering
    - Importing into R or Julia for statistical analysis
    - Feeding into downstream bioinformatics pipelines

    Example (Python)::

        import pandas as pd
        result = await export_research_dataset(ExportInput(tables=["variants"]))
        df = pd.DataFrame(result["data"]["variants"])
        high_tier = df[df["clinical_tier"] == "HIGH"]

    Args:
        params.tables: Tables to export (empty = all entity tables).
        params.limit_per_table: Maximum rows per table.
    """
    async with get_knowledge_graph() as kg:
        data = await kg.export_to_dict(
            tables=params.tables or None,
            limit=params.limit_per_table,
        )

    total_rows = sum(len(v) for v in data.values())
    return {
        "tables_exported": list(data.keys()),
        "total_rows": total_rows,
        "data": data,
        "usage": {
            "pandas": "pd.DataFrame(result['data']['variants'])",
            "polars": "pl.DataFrame(result['data']['variants'])",
        },
        "provenance": _provenance(source="local-kg"),
    }


@mcp.tool(
    annotations={
        "title": "Find Drug-Gene-Disease Network",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def find_drug_gene_network(
    params: DrugNetworkInput,
) -> dict[str, Any]:
    """Traverse the local knowledge graph from a seed entity.

    Given a seed (UniProt ID, gene symbol, or MONDO disease ID), expands its
    immediate neighbourhood in the stored drug-gene-disease graph: a gene
    symbol resolves to its encoded proteins and reported variants, a UniProt
    accession resolves to its stored protein record, and a MONDO disease
    resolves to drugs with an indication for it. The store is populated by the
    curated boot seed and by explicit writes through the storage API.

    Args:
        params.seed: Starting entity identifier.
        params.max_hops: Graph traversal depth (1–3).
    """
    seed = params.seed.strip()

    async with get_knowledge_graph() as kg:
        network = await _traverse_network(kg, seed, params.max_hops)

    return {
        "seed": seed,
        "max_hops": params.max_hops,
        "network": network,
        "note": (
            "Network contains only entities stored in the local knowledge graph. "
            "The store is populated by the curated boot seed (disable with "
            "AFSMCP_DISABLE_KG_SEED=1) and by explicit writes through the "
            "knowledge-graph storage API."
        ),
        "provenance": _provenance(source="local-kg"),
    }


async def _traverse_network(
    kg: Any,
    seed: str,
    max_hops: int,
) -> dict[str, Any]:
    """Build a subgraph centred on the seed entity."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    visited: set[str] = set()

    async def expand(entity_id: str, hop: int) -> None:
        if hop > max_hops or entity_id in visited:
            return
        visited.add(entity_id)

        # Determine entity type
        if entity_id.startswith("MONDO:"):
            # Disease node
            rows = await kg.query_drug_landscape(mondo_id=entity_id, min_phase=1, limit=10)
            nodes[entity_id] = {"type": "disease", "id": entity_id}
            for row in rows:
                drug_id = row.get("chembl_id", "")
                if drug_id:
                    nodes[drug_id] = {
                        "type": "drug",
                        "id": drug_id,
                        "name": row.get("pref_name", ""),
                        "max_phase": row.get("max_phase"),
                    }
                    edges.append({"from": drug_id, "to": entity_id, "rel": "indication"})

        elif entity_id.startswith(("P", "Q", "A")):
            # UniProt-like protein node. Filter by accession: a bare
            # query_proteins(limit=1) returns the single highest-pLDDT row and
            # matches the seed only by coincidence, so any other protein seed
            # would be silently dropped.
            proteins = await kg.fetch(
                "SELECT * FROM proteins WHERE uniprot_id = ? LIMIT 1",
                [entity_id],
            )
            if proteins:
                nodes[entity_id] = {"type": "protein", **proteins[0]}
        else:
            # Gene symbol — find linked proteins and variants.
            proteins = await kg.fetch(
                "SELECT uniprot_id, gene_symbol, druggability_tier, mean_plddt "
                "FROM proteins WHERE gene_symbol = ? LIMIT 5",
                [entity_id.upper()],
            )
            for p in proteins:
                pid = p["uniprot_id"]
                nodes[pid] = {"type": "protein", **p}
                edges.append({"from": entity_id, "to": pid, "rel": "encodes"})
                if hop < max_hops:
                    await expand(pid, hop + 1)

            variants = await kg.query_variants(gene=entity_id.upper(), limit=5)
            for v in variants:
                vid = v.get("hgvs", "")
                if vid:
                    nodes[vid] = {"type": "variant", **v}
                    edges.append({"from": entity_id, "to": vid, "rel": "has_variant"})

    await expand(seed, hop=0)

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
