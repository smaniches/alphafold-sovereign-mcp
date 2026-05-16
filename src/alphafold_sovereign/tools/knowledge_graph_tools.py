# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""MCP tools for querying the local AlphaFold Sovereign Knowledge Graph.

These tools expose the accumulated research intelligence stored in the local
relational database — turning every past query into a reusable asset.

This is one of the most powerful aspects of AlphaFold Sovereign:
the platform LEARNS from usage.  Every variant triage, druggability assessment,
and protein dossier enriches the local graph, enabling:

  - Instant recall of previously analysed entities (no API call required)
  - Cross-session pattern discovery ("which HIGH-tier variants share a WARM target?")
  - Batch analytics export to pandas for downstream ML
  - Audit-complete provenance for regulatory submissions

Tool inventory:
  1. query_variant_database  — search accumulated variant triage results
  2. query_protein_database  — search accumulated protein assessments
  3. get_knowledge_graph_stats — database health and coverage summary
  4. export_research_dataset  — export to JSON for pandas/ML pipelines
  5. find_drug_gene_network   — traverse the accumulated drug-gene-disease graph
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
    limit: int = Field(default=50, ge=1, le=500)


class ProteinQueryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    druggability_tier: Literal["HOT", "WARM", "COLD", "NOT_DRUGGABLE"] | None = Field(
        None, description="Druggability tier filter."
    )
    min_plddt: float | None = Field(
        None, ge=0.0, le=100.0, description="Minimum mean pLDDT confidence score."
    )
    limit: int = Field(default=50, ge=1, le=500)


class ExportInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    tables: list[str] = Field(
        default_factory=list,
        description=(
            "Tables to export. Leave empty for all entity tables. "
            "Options: proteins, variants, diseases, drugs, protein_disease, protein_drug."
        ),
    )
    limit_per_table: int = Field(default=5000, ge=1, le=50000)


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
    """Search the local knowledge graph for previously analysed variants.

    Returns variants matching the filter criteria from your accumulated
    research sessions.  No API calls are made — all data is served from
    the local SQLite knowledge graph.

    This is how AlphaFold Sovereign enables longitudinal research:
    every variant triaged by ``generate_variant_clinical_report`` is
    automatically stored and becomes instantly searchable here.

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
            "Results served from local knowledge graph. "
            "Run generate_variant_clinical_report to populate this database."
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
    """Search the local knowledge graph for previously assessed proteins.

    Returns proteins matching the filter criteria from accumulated
    research.  Serves from local SQLite — no API calls.

    Args:
        params.druggability_tier: HOT/WARM/COLD/NOT_DRUGGABLE filter.
        params.min_plddt: Minimum AF2 confidence score.
        params.limit: Maximum results.
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
            "Results served from local knowledge graph. "
            "Run synthesize_protein_dossier or analyze_structural_confidence "
            "to populate this database."
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
    understanding the breadth of your accumulated research.
    """
    async with get_knowledge_graph() as kg:
        stats = await kg.get_statistics()

    stats["description"] = (
        "AlphaFold Sovereign local knowledge graph — "
        "persistent relational store for all research intelligence. "
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
    """Export accumulated research data for downstream analysis.

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

    Given any seed (UniProt ID, gene symbol, or MONDO disease ID),
    expands up to ``max_hops`` through the drug-gene-disease graph
    stored in the local knowledge graph.

    This reveals hidden connections between entities accumulated across
    multiple research sessions — a form of network medicine powered by
    your own research history.

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
            "Run more research tools to enrich the graph."
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
            # UniProt-like protein node
            proteins = await kg.query_proteins(limit=1)
            p = next((r for r in proteins if r.get("uniprot_id") == entity_id), None)
            if p:
                nodes[entity_id] = {"type": "protein", **p}
        else:
            # Gene symbol — find linked proteins and variants
            # _fetchall is a sync method on the KG; do not await.
            proteins = kg._fetchall(
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
