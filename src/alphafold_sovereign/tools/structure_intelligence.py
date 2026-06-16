# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Structure-intelligence MCP tools.

These tools take raw AlphaFold structures (PDB text and PAE arrays from
AlphaFold DB) and derive a small set of summaries from them:

* pLDDT / PAE confidence-and-domain maps,
* a 64-dimensional topological-data-analysis (TDA) fingerprint
  (Betti numbers β₀, β₁, β₂ from a Vietoris-Rips filtration of Cα
  coordinates, computed with `gudhi` when the optional `[tda]` extra
  is installed; a coarse fallback without persistent homology
  otherwise — see ``_compute_lightweight_tda``),
* a pairwise distance matrix between TDA fingerprints (the
  implementation is an L2 distance on length-normalised fingerprint
  vectors — it is **not** an optimal-transport Wasserstein distance;
  see ``_fingerprint_distance``),
* a geometric pocket-detection heuristic, and
* an intrinsic-disorder-region map.

All tools are read-only. Tools that require outbound HTTP fail closed when
``ALPHAFOLD_OFFLINE=1`` (they raise ``AirGapError``); there is no local
structure cache.

Tool inventory:
  1. analyze_structural_confidence       — pLDDT + PAE domain map
  2. compute_topology_fingerprint        — TDA Betti numbers (β₀, β₁, β₂)
  3. compare_proteins_topologically      — Pairwise fingerprint-distance matrix
  4. find_evolutionary_structural_shifts — Cross-species TDA fingerprint compare
  5. score_binding_pocket_geometry       — Heuristic pocket detection + score
  6. detect_intrinsically_disordered     — IDR region map
"""

from __future__ import annotations

import asyncio
import datetime
import math
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import structlog
from pydantic import BaseModel, ConfigDict, Field

from alphafold_sovereign import __version__
from alphafold_sovereign.clients.alphafold import AlphaFoldClient
from alphafold_sovereign.clients.ensembl import EnsemblClient
from alphafold_sovereign.server.app import mcp

if TYPE_CHECKING:
    from alphafold_sovereign.clients._base import BaseAsyncClient

logger = structlog.get_logger(__name__)


def _provenance(**meta: str) -> str:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = ", ".join(f"{k}={v}" for k, v in meta.items() if v)
    return f"\n\n---\n*AlphaFold Sovereign MCP v{__version__} · {ts} · {parts}*"


# ── Input models ──────────────────────────────────────────────────────────────


class UniProtInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    uniprot_id: str = Field(
        ...,
        description="UniProt accession, e.g. 'P38398' (BRCA1).",
        pattern=r"^[A-Z][0-9][A-Z0-9]{3}[0-9](?:[A-Z][0-9][A-Z0-9]{3}[0-9])?$",
    )


class MultiProteinInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    uniprot_ids: list[str] = Field(
        ...,
        description="List of UniProt accessions (2–10) for pairwise comparison.",
        min_length=2,
        max_length=10,
    )


class EvolutionaryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    gene_symbol: str = Field(
        ...,
        description="HGNC gene symbol for cross-species structural divergence analysis.",
    )
    target_species: list[str] = Field(
        default_factory=lambda: [
            "mus_musculus",
            "rattus_norvegicus",
            "sus_scrofa",
            "bos_taurus",
            "gallus_gallus",
            "danio_rerio",
        ],
        description="Ensembl species names to include in the analysis.",
        max_length=12,
    )


class BindingPocketInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    uniprot_id: str = Field(
        ...,
        description="UniProt accession for binding-pocket geometry analysis.",
        pattern=r"^[A-Z][0-9][A-Z0-9]{3}[0-9](?:[A-Z][0-9][A-Z0-9]{3}[0-9])?$",
    )
    min_pocket_residues: int = Field(
        default=4,
        ge=3,
        le=20,
        description="Minimum number of residues to define a pocket.",
    )


# ── AF structure fetcher (uses existing fetcher infrastructure) ───────────────


_CLIENTS: dict[str, BaseAsyncClient] = {}


def _alphafold() -> AlphaFoldClient:
    """Return the process-wide AlphaFold DB client (lazily constructed)."""
    if "alphafold" not in _CLIENTS:
        _CLIENTS["alphafold"] = AlphaFoldClient()
    return cast("AlphaFoldClient", _CLIENTS["alphafold"])


async def _fetch_af_structure(uniprot_id: str) -> dict[str, Any] | None:
    """Fetch AlphaFold structure coordinates for a UniProt accession.

    Routes through AlphaFoldClient, so the request shares the client's
    rate limiter, retry policy, circuit breaker, air-gap enforcement,
    and the advertised-file-URL host guard. Returns None when the
    accession has no AlphaFold model.
    """
    try:
        pdb_bytes = await _alphafold().get_pdb_bytes(uniprot_id)
    except Exception as exc:
        logger.warning("af.fetch.failed", uniprot_id=uniprot_id, exc=str(exc))
        return None
    if not pdb_bytes:
        return None
    return {
        "pdb_text": pdb_bytes.decode("utf-8", errors="replace"),
        "uniprot_id": uniprot_id,
    }


async def _fetch_af_plddt(uniprot_id: str) -> dict[str, Any] | None:
    """Fetch the pLDDT summary and PAE matrix for a UniProt accession.

    Routes through AlphaFoldClient. Reads the global pLDDT confidence
    from the prediction metadata (the ``globalMetricValue`` field; the
    older ``meanPlddt`` field is absent from the current AlphaFold DB
    schema) and the PAE matrix from the advertised PAE document.

    Returns None when the accession has no AlphaFold model, so callers
    can distinguish "no structure" from a structure with missing
    fields.
    """
    client = _alphafold()
    try:
        meta = await client.get_prediction(uniprot_id)
    except Exception as exc:
        logger.warning("af.summary.failed", uniprot_id=uniprot_id, exc=str(exc))
        return None
    if not isinstance(meta, dict) or not meta.get("entryId"):
        return None

    result: dict[str, Any] = {
        "uniprot_id": uniprot_id,
        "mean_plddt": meta.get("globalMetricValue"),
        "model_url": meta.get("pdbUrl", ""),
        "sequence_length": len(meta.get("uniprotSequence") or ""),
    }

    try:
        pae_doc = await client.get_pae(uniprot_id)
    except Exception as exc:
        logger.warning("af.pae.failed", uniprot_id=uniprot_id, exc=str(exc))
        return result

    pae_matrix = np.array(pae_doc.get("predicted_aligned_error", []))
    if pae_matrix.size > 0:
        result["pae_matrix_shape"] = list(pae_matrix.shape)
        result["pae_mean"] = float(np.mean(pae_matrix))
        result["pae_max"] = float(np.max(pae_matrix))
        # Inter-domain: regions where PAE is high (>15 Å) between segments
        result["high_pae_pairs"] = _find_high_pae_pairs(pae_matrix, threshold=15.0)
        result["domain_boundaries"] = _detect_domain_boundaries(pae_matrix)

    return result


def _no_structure_response(uniprot_id: str) -> dict[str, Any]:
    """Return a uniform, human-readable response when AF DB has no model.

    AlphaFold DB does not contain a model for every UniProt accession.
    When a structure or prediction fetch returns nothing, every
    structure tool returns this same shape, so an LLM or a human
    receives one clear, consistent explanation rather than a terse or
    silent failure.

    Args:
        uniprot_id: The accession that was requested.

    Returns:
        A dict carrying ``structure_available`` set to False, a plain
        ``error`` line, and an explanatory ``note``.
    """
    return {
        "uniprot_id": uniprot_id,
        "structure_available": False,
        "error": (
            "No AlphaFold model: AlphaFold DB returned no structure "
            "prediction for this UniProt accession."
        ),
        "note": (
            "AlphaFold DB covers most of UniProtKB but not every "
            "accession. Some fragments, non-reference isoforms, and "
            "very recently added entries have no deposited model. This "
            "is an expected data-coverage gap, not a server fault. "
            "Confirm the accession at https://alphafold.ebi.ac.uk/."
        ),
    }


def _find_high_pae_pairs(pae: np.ndarray, threshold: float = 15.0) -> list[dict[str, Any]]:
    """Find residue pairs with high inter-residue positional error."""
    # Sample to avoid O(n²) memory — take top 20 worst pairs
    rows, cols = np.where(pae > threshold)
    pairs_arr = [
        (float(pae[r, c]), int(r) + 1, int(c) + 1)
        for r, c in zip(rows, cols)
        if abs(int(r) - int(c)) > 10
    ]
    pairs_arr.sort(reverse=True, key=lambda x: x[0])
    return [{"residue_a": p[1], "residue_b": p[2], "pae": round(p[0], 2)} for p in pairs_arr[:20]]


def _detect_domain_boundaries(pae: np.ndarray, window: int = 10) -> list[int]:
    """Detect domain boundaries as positions where PAE rises sharply.

    Uses a sliding-window mean of the PAE block diagonal to find positions
    where the local structural certainty drops — indicating a flexible linker
    or domain boundary.
    """
    n = pae.shape[0]
    boundaries: list[int] = []
    if n < 2 * window:
        return boundaries
    scores = []
    for i in range(window, n - window):
        local = float(np.mean(pae[i - window : i + window, i - window : i + window]))
        global_mean = float(np.mean(pae))
        scores.append((i, local - global_mean))
    # Peak detection: residues where local PAE >> global mean
    threshold = float(np.std([s for _, s in scores])) * 1.5
    prev_over = False
    for pos, score in scores:
        if score > threshold and not prev_over:
            boundaries.append(pos)
            prev_over = True
        elif score <= threshold:
            prev_over = False
    return boundaries[:10]  # Max 10 boundary candidates


# ── TDA fingerprint computation ───────────────────────────────────────────────


def _compute_tda_fingerprint(
    ca_coords: np.ndarray,
    max_dimension: int = 2,
) -> dict[str, Any]:
    """Compute a topological fingerprint from Cα coordinates.

    Builds a Vietoris-Rips complex over the Cα point cloud with a
    Euclidean metric and reads off the persistent-homology Betti
    numbers (β₀, β₁, β₂) using `gudhi`. If `gudhi` is not installed,
    falls back to a coarse heuristic (see ``_fallback_tda_fingerprint``)
    that does not compute persistent homology.

    Args:
        ca_coords: (N, 3) array of Cα coordinates.
        max_dimension: Maximum homology dimension (default 2: β₀, β₁, β₂).

    Returns:
        Dict with Betti numbers, a (truncated) persistence summary, and
        a 64-dimensional fingerprint vector. The fingerprint vector is
        a fixed-length feature used for downstream pairwise comparison;
        it is not a published embedding from a peer-reviewed method.
    """
    try:
        import gudhi
    except ImportError:
        return _fallback_tda_fingerprint(ca_coords)

    # Subsample for efficiency (max 500 residues → dense enough for topology)
    if len(ca_coords) > 500:
        idx = np.linspace(0, len(ca_coords) - 1, 500, dtype=int)
        ca_coords = ca_coords[idx]

    # Build Rips complex
    max_edge_length = 15.0  # Ångström — captures secondary structure contacts
    rips = gudhi.RipsComplex(points=ca_coords.tolist(), max_edge_length=max_edge_length)
    simplex_tree = rips.create_simplex_tree(max_dimension=max_dimension)
    simplex_tree.compute_persistence()

    # Extract persistence diagrams per dimension
    betti_numbers: list[int] = []
    landscapes: list[dict[str, Any]] = []
    fingerprint: list[float] = []

    for dim in range(max_dimension + 1):
        intervals = [
            (b, d) for (k, (b, d)) in simplex_tree.persistence() if k == dim and d < float("inf")
        ]
        betti = len(intervals)
        betti_numbers.append(betti)

        if intervals:
            lifetimes = [d - b for b, d in intervals]
            fingerprint.extend(
                [
                    float(np.mean(lifetimes)),
                    float(np.std(lifetimes)),
                    float(np.max(lifetimes)),
                    float(np.min(lifetimes)),
                    float(np.median(lifetimes)),
                    float(np.percentile(lifetimes, 75)),
                    float(np.percentile(lifetimes, 25)),
                    float(sum(lifetimes)),
                ]
            )
            landscapes.append(
                {
                    "dimension": dim,
                    "n_intervals": len(intervals),
                    "mean_lifetime": round(float(np.mean(lifetimes)), 3),
                    "max_lifetime": round(float(np.max(lifetimes)), 3),
                    "total_persistence": round(float(sum(lifetimes)), 3),
                    "representative_intervals": [
                        {"birth": round(b, 3), "death": round(d, 3)}
                        for b, d in sorted(intervals, key=lambda x: x[1] - x[0], reverse=True)[:5]
                    ],
                }
            )
        else:
            fingerprint.extend([0.0] * 8)
            landscapes.append({"dimension": dim, "n_intervals": 0})

    # Pad to fixed 64-dim vector
    fingerprint = (fingerprint + [0.0] * 64)[:64]

    return {
        "betti_numbers": betti_numbers,
        "persistence_landscapes": landscapes,
        "fingerprint_vector": [round(f, 6) for f in fingerprint],
        "fingerprint_dimension": 64,
        "n_residues_used": len(ca_coords),
        "max_filtration_length_angstrom": max_edge_length,
        "methodology": "Vietoris-Rips persistent homology via gudhi.",
    }


def _fallback_tda_fingerprint(ca_coords: np.ndarray) -> dict[str, Any]:
    """Coarse fallback fingerprint when gudhi is not installed.

    Computes a few distance-matrix statistics (mean, std, min, max,
    histogram bins) as a proxy for topological features. This is **not**
    persistent homology and the returned ``betti_numbers`` field beyond
    β₀ is set to zero. Install gudhi (``pip install
    alphafold-sovereign-mcp[tda]``) for the real persistent-homology
    computation.
    """
    if len(ca_coords) < 2:
        return {"betti_numbers": [], "fingerprint_vector": [0.0] * 64, "gudhi_available": False}

    dists = np.sqrt(np.sum((ca_coords[:, None, :] - ca_coords[None, :, :]) ** 2, axis=-1))
    np.fill_diagonal(dists, np.inf)

    # Approximate β0: connected components (residues within 4 Å of another)
    contacts = (dists < 4.0).sum(axis=1)
    b0 = int((contacts == 0).sum())  # isolated residues ≈ components

    # Approximate β1: residues forming cycles (high local connectivity)
    mean_contacts = float(np.mean(contacts[contacts < np.inf]))

    fingerprint: list[float] = [
        float(np.mean(dists[dists < np.inf])),
        float(np.std(dists[dists < np.inf])),
        float(np.min(dists[dists < np.inf])),
        float(np.max(dists[dists < 30.0]) if np.any(dists < 30.0) else 0.0),
        mean_contacts,
        float(np.percentile(dists[dists < np.inf], 10)),
        float(np.percentile(dists[dists < np.inf], 90)),
        float(b0),
    ]
    fingerprint = (fingerprint + [0.0] * 64)[:64]

    return {
        "betti_numbers": [b0, 0, 0],
        "fingerprint_vector": [round(f, 6) for f in fingerprint],
        "fingerprint_dimension": 64,
        "n_residues_used": len(ca_coords),
        "gudhi_available": False,
        "note": "Install gudhi for full persistent-homology computation: pip install alphafold-sovereign-mcp[tda]",
    }


def _fingerprint_distance(fp_a: list[float], fp_b: list[float]) -> float:
    """L2 distance between length-normalised TDA fingerprint vectors.

    This is *not* the optimal-transport (Wasserstein) distance between
    persistence diagrams.  It is a cheap, deterministic surrogate over
    the fixed-length fingerprint vector that the project uses for
    pairwise ranking only.  When `gudhi` is available, a true
    persistence-diagram Wasserstein distance can be plugged in here in
    a future revision.
    """
    a = np.array(fp_a, dtype=float)
    b = np.array(fp_b, dtype=float)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a > 0:
        a = a / norm_a
    if norm_b > 0:
        b = b / norm_b
    return float(np.sqrt(np.sum((a - b) ** 2)))


def _parse_ca_coords_from_pdb(pdb_text: str) -> np.ndarray:
    """Extract Cα coordinates from PDB ATOM records."""
    coords: list[list[float]] = []
    for line in pdb_text.splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            try:
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
                coords.append([x, y, z])
            except ValueError:
                continue
    return np.array(coords, dtype=float) if coords else np.empty((0, 3), dtype=float)


# ── Tool 1: Structural confidence ────────────────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Analyze Structural Confidence (pLDDT + PAE)",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def analyze_structural_confidence(
    params: UniProtInput,
) -> dict[str, Any]:
    """Analyze AlphaFold structural confidence using pLDDT and PAE matrices.

    Returns a multi-layered structural reliability assessment:
    - **pLDDT** (per-residue): mean confidence, low-confidence segments (disordered/novel)
    - **PAE** (predicted aligned error): inter-domain uncertainty, domain boundaries
    - **Druggability pre-screen**: high-pLDDT + low-PAE regions → ordered pockets

    pLDDT interpretation:
      > 90: Very high confidence — likely correct at backbone + sidechain level
      70–90: High confidence — backbone correct, some sidechain uncertainty
      50–70: Low confidence — may be IDP or novel fold
      < 50: Very low — disordered or no structure deposited

    Args:
        params.uniprot_id: UniProt accession.
    """
    uid = params.uniprot_id
    result = await _fetch_af_plddt(uid)

    if not result:
        return _no_structure_response(uid)

    plddt = result.get("mean_plddt")
    confidence_tier = _plddt_tier(plddt)
    domain_boundaries = result.get("domain_boundaries", [])

    return {
        "uniprot_id": uid,
        "mean_plddt": round(plddt, 2) if plddt else None,
        "confidence_tier": confidence_tier,
        "confidence_tier_explanation": _plddt_tier_explanation(confidence_tier),
        "sequence_length": result.get("sequence_length"),
        "pae_summary": {
            "mean_pae_angstrom": round(result.get("pae_mean", 0.0), 2),
            "max_pae_angstrom": round(result.get("pae_max", 0.0), 2),
            "high_uncertainty_pairs": result.get("high_pae_pairs", [])[:5],
        },
        "domain_boundaries": {
            "candidate_positions": domain_boundaries,
            "n_putative_domains": max(1, len(domain_boundaries)),
            "note": (
                "Boundary positions are zero-indexed residue numbers where PAE rises sharply. "
                "Validate with InterPro or UniProt feature annotations."
            ),
        },
        "druggability_pre_screen": {
            "ordered_fraction": _estimate_ordered_fraction(plddt),
            "structural_suitability": (
                "SUITABLE for structure-based drug design"
                if (plddt or 0) >= 70
                else "CAUTION: low confidence may indicate IDP or novel fold"
            ),
        },
        "model_url": result.get("model_url", ""),
        "provenance": _provenance(alphafold_db="v6", plddt_version="v6"),
    }


# ── Tool 2: TDA Fingerprint ───────────────────────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Compute Topological Fingerprint (TDA)",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def compute_topology_fingerprint(
    params: UniProtInput,
) -> dict[str, Any]:
    """Compute a topological fingerprint for a protein structure.

    Uses persistent homology (Vietoris-Rips filtration) over the Cα
    coordinate cloud to derive a 64-dimensional fingerprint vector and
    Betti numbers β₀, β₁, β₂. Requires `gudhi` (install with
    ``pip install alphafold-sovereign-mcp[tda]``); without `gudhi`, a
    coarse fallback runs that does **not** compute persistent homology
    (see ``_fallback_tda_fingerprint``).

    What the Betti numbers count, intuitively:

    - **β₀** — connected components of the Vietoris-Rips complex at the
      chosen filtration scale. Distinguishes single-domain from
      multi-domain or fragmented chains.
    - **β₁** — 1-dimensional holes / loops. Picks up ring-like
      topology (e.g. β-barrels, large macrocycles).
    - **β₂** — 2-dimensional voids. Picks up enclosed cavities.

    Topological features are invariant to rigid-body rotation and
    translation. They are *not* a substitute for sequence alignment,
    RMSD, or functional homology assessment; they are a coarse,
    geometry-only summary.

    Args:
        params.uniprot_id: UniProt accession.
    """
    uid = params.uniprot_id
    log = logger.bind(uniprot_id=uid, tool="compute_topology_fingerprint")
    log.info("start")

    structure = await _fetch_af_structure(uid)
    if not structure:
        return _no_structure_response(uid)

    ca_coords = _parse_ca_coords_from_pdb(structure["pdb_text"])
    if ca_coords.shape[0] == 0:
        return {"uniprot_id": uid, "error": "No Cα atoms found in PDB file."}

    tda = _compute_tda_fingerprint(ca_coords)

    log.info("complete", n_residues=ca_coords.shape[0])
    return {
        "uniprot_id": uid,
        "n_residues": int(ca_coords.shape[0]),
        "topological_fingerprint": tda,
        "interpretation": _interpret_tda(tda),
        "usage": (
            "Use this fingerprint vector with compare_proteins_topologically to measure "
            "structural similarity between any two proteins, regardless of sequence identity. "
            "Store in your knowledge graph for rapid cross-protein screening."
        ),
        "provenance": _provenance(alphafold_db="v6", methodology="VR-persistent-homology"),
    }


# ── Tool 3: Pairwise topological comparison ───────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Compare Proteins Topologically (TDA Fingerprint Distance)",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def compare_proteins_topologically(
    params: MultiProteinInput,
) -> dict[str, Any]:
    """Compare multiple proteins using a TDA-fingerprint distance.

    Computes a pairwise distance matrix between the TDA fingerprints of
    the provided proteins.  Distance metric: L2 distance between
    length-normalised 64-dimensional fingerprint vectors (see
    ``_fingerprint_distance``).  Distance = 0 means identical
    fingerprints; larger values mean more divergent fingerprints.  This
    is **not** a Wasserstein distance between persistence diagrams.

    Applications:
    Possible uses (all of which require independent validation
    before any downstream use):

    - Drug-repurposing triage: proteins with low fingerprint distance
      may share gross topology.
    - Off-target screening: family members with near-zero distance.
    - Cross-species comparison of the same gene's structure.

    None of these are direct functional or sequence-similarity
    measures.

    Args:
        params.uniprot_ids: 2–10 UniProt accessions.
    """
    ids = params.uniprot_ids
    log = logger.bind(n_proteins=len(ids), tool="compare_proteins_topologically")
    log.info("start")

    # Parallel structure fetching
    structures = await asyncio.gather(
        *[_fetch_af_structure(uid) for uid in ids],
        return_exceptions=True,
    )

    # Compute fingerprints
    fingerprints: dict[str, list[float]] = {}
    errors: dict[str, str] = {}
    protein_meta: dict[str, dict[str, Any]] = {}

    for uid, struct in zip(ids, structures):
        if isinstance(struct, BaseException) or struct is None:
            errors[uid] = "No AlphaFold model for this accession."
            continue
        ca = _parse_ca_coords_from_pdb(struct["pdb_text"])
        if ca.shape[0] == 0:
            errors[uid] = "No Cα atoms."
            continue
        tda = _compute_tda_fingerprint(ca)
        fingerprints[uid] = tda["fingerprint_vector"]
        protein_meta[uid] = {
            "n_residues": int(ca.shape[0]),
            "betti_numbers": tda.get("betti_numbers", []),
        }

    # Build distance matrix
    valid_ids = list(fingerprints.keys())
    n = len(valid_ids)
    matrix: list[list[float]] = []
    for i in range(n):
        row: list[float] = []
        for j in range(n):
            if i == j:
                row.append(0.0)
            else:
                d = _fingerprint_distance(fingerprints[valid_ids[i]], fingerprints[valid_ids[j]])
                row.append(round(d, 6))
        matrix.append(row)

    # Find most similar pair
    most_similar = _find_most_similar_pair(valid_ids, matrix)

    log.info("complete", n_valid=n)
    return {
        "proteins_analyzed": valid_ids,
        "proteins_failed": errors,
        "distance_matrix": {
            "proteins": valid_ids,
            "matrix": matrix,
            "metric": "L2 distance over length-normalised TDA fingerprint vectors (not Wasserstein on persistence diagrams)",
        },
        "most_topologically_similar": most_similar,
        "protein_metadata": protein_meta,
        "interpretation": (
            "Distance < 0.1: very similar fingerprints. "
            "Distance 0.1-0.4: moderately divergent. "
            "Distance > 0.4: clearly divergent. "
            "These bands are heuristic and are not calibrated to any "
            "fold-classification scheme such as SCOP/CATH."
        ),
        "provenance": _provenance(alphafold_db="v6", methodology="VR-persistent-homology"),
    }


# ── Tool 4: Evolutionary structural shifts ───────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Find Evolutionary Structural Shifts",
        "readOnlyHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
async def find_evolutionary_structural_shifts(
    params: EvolutionaryInput,
) -> dict[str, Any]:
    """Quantify cross-species structural and sequence divergence for a gene.

    For each ortholog, attempts to fetch the AlphaFold structure and compute
    a TDA fingerprint distance against the human structure. When an ortholog
    structure is available in AlphaFold DB, the ``divergence_method`` is
    ``tda_fingerprint`` and the distance is the L2 distance between
    length-normalised fingerprint vectors. When the ortholog has no
    AlphaFold model, the method falls back to ``sequence_identity``
    (``1 - identity/100``).

    AlphaFold DB coverage of non-human proteomes is partial: model organisms
    (mouse, rat, zebrafish) are well-covered; others may not be. The
    ``divergence_method`` field on each result tells you which method was
    used.

    Args:
        params.gene_symbol: Human gene symbol.
        params.target_species: List of species to compare.
    """
    sym = params.gene_symbol.upper()
    log = logger.bind(gene=sym, tool="find_evolutionary_structural_shifts")
    log.info("start")

    ensembl = EnsemblClient()
    orthologs = await ensembl.orthologs(sym, target_species=params.target_species, limit=20)

    if not orthologs:
        return {
            "gene_symbol": sym,
            "error": "No orthologs found via Ensembl for the specified species.",
        }

    # Fetch human structure and compute TDA fingerprint
    human_gene = await ensembl.gene_lookup(sym)
    human_uniprot = (human_gene.get("uniprot_ids") or [""])[0]

    human_struct = await _fetch_af_structure(human_uniprot) if human_uniprot else None
    human_ca: np.ndarray | None = None
    if human_struct:
        human_ca = _parse_ca_coords_from_pdb(human_struct["pdb_text"])
        if human_ca.shape[0] == 0:
            human_ca = None

    human_fingerprint: list[float] | None = None
    if human_ca is not None:
        human_tda = _compute_tda_fingerprint(human_ca)
        human_fingerprint = human_tda["fingerprint_vector"]

    # For each ortholog, try to fetch its AlphaFold structure and compute
    # TDA fingerprint distance; fall back to sequence identity.
    drift_results: list[dict[str, Any]] = []
    for orth in orthologs[:8]:
        species = orth.get("species", "")
        orth_gene_id = orth.get("gene_id", "")
        identity = orth.get("identity", 0.0)
        dn_ds = orth.get("dn_ds")

        divergence_estimate: float | None = None
        divergence_method = "sequence_identity"
        tda_distance: float | None = None

        if orth_gene_id and human_fingerprint:
            orth_uniprot = await _resolve_ortholog_uniprot(ensembl, orth_gene_id)
            if orth_uniprot:
                orth_struct = await _fetch_af_structure(orth_uniprot)
                if orth_struct:
                    orth_ca = _parse_ca_coords_from_pdb(orth_struct["pdb_text"])
                    if orth_ca.shape[0] > 0:
                        orth_tda = _compute_tda_fingerprint(orth_ca)
                        tda_distance = round(
                            _fingerprint_distance(
                                human_fingerprint, orth_tda["fingerprint_vector"]
                            ),
                            6,
                        )
                        divergence_estimate = tda_distance
                        divergence_method = "tda_fingerprint"

        if divergence_estimate is None and orth_gene_id:
            divergence_estimate = round(1.0 - (identity / 100.0), 4)

        drift_results.append(
            {
                "species": species,
                "ensembl_gene_id": orth_gene_id,
                "gene_name": orth.get("gene_name", ""),
                "orthology_type": orth.get("type", ""),
                "sequence_identity_pct": round(identity, 2),
                "dn_ds_ratio": round(dn_ds, 4) if dn_ds is not None else None,
                "divergence_estimate": divergence_estimate,
                "divergence_method": divergence_method,
                "tda_fingerprint_distance": tda_distance,
                "drift_interpretation": _drift_interpretation(divergence_estimate, dn_ds),
                "cross_reactivity_risk": _cross_reactivity_risk(identity, dn_ds),
            }
        )

    drift_results.sort(key=lambda r: r.get("divergence_estimate") or 1.0)

    tda_count = sum(1 for r in drift_results if r["divergence_method"] == "tda_fingerprint")
    seq_count = sum(1 for r in drift_results if r["divergence_method"] == "sequence_identity")

    return {
        "gene_symbol": sym,
        "human_uniprot_id": human_uniprot,
        "species_compared": len(drift_results),
        "tda_comparisons": tda_count,
        "sequence_identity_fallbacks": seq_count,
        "evolutionary_profile": drift_results,
        "most_conserved_species": drift_results[0]["species"] if drift_results else None,
        "most_diverged_species": drift_results[-1]["species"] if drift_results else None,
        "methodology_note": (
            "When an ortholog has an AlphaFold structure, divergence_estimate is "
            "the L2 distance between length-normalised TDA fingerprint vectors "
            "(divergence_method='tda_fingerprint'). When no AlphaFold model "
            "exists for the ortholog, divergence_estimate falls back to "
            "1 - sequence_identity (divergence_method='sequence_identity'). "
            f"{tda_count} of {len(drift_results)} comparisons used TDA."
        ),
        "provenance": _provenance(ensembl="current", alphafold_db="v6"),
    }


# ── Tool 5: Binding pocket geometry ──────────────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Score Binding Pocket Geometry",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def score_binding_pocket_geometry(
    params: BindingPocketInput,
) -> dict[str, Any]:
    """Identify and score putative binding pockets from AlphaFold geometry.

    Detects pockets with a geometry-only heuristic. Residues in the
    inner 60 percent of the structure by distance from the centroid are
    treated as buried, then grown greedily into clusters within an 8
    Angstrom radius. A cluster is kept as a putative pocket when it has
    at least ``min_pocket_residues`` members and a mean pLDDT of at
    least 50.

    Each pocket reports a radius of gyration (compactness of the pocket
    residues), a burial value (distance of the pocket centroid from the
    structure centroid), a mean pLDDT, and a druggability index. The
    druggability index runs 0 to 100 and is the sum of four equally
    weighted 0 to 25 sub-scores: residue count, radius of gyration, mean
    pLDDT, and burial.

    This is a fast, dependency-free pre-screen, not a substitute for a
    validated pocket detector such as fpocket or P2Rank. It needs no ML
    model, is fully reproducible from AlphaFold coordinates, and runs in
    air-gapped deployments.

    Args:
        params.uniprot_id: UniProt accession.
        params.min_pocket_residues: Minimum pocket size (residues).
    """
    uid = params.uniprot_id
    log = logger.bind(uniprot_id=uid, tool="score_binding_pocket_geometry")
    log.info("start")

    structure = await _fetch_af_structure(uid)
    if not structure:
        return _no_structure_response(uid)

    pdb_text = structure["pdb_text"]
    ca_coords, residue_info = _parse_pdb_full(pdb_text)

    if ca_coords.shape[0] < 10:
        return {
            "uniprot_id": uid,
            "error": "Protein too short for pocket analysis (< 10 residues).",
        }

    pockets = _geometric_pocket_detection(
        ca_coords, residue_info, min_residues=params.min_pocket_residues
    )

    # Score by druggability potential
    for pocket in pockets:
        pocket["druggability_index"] = _pocket_druggability_index(pocket)
        pocket["druggability_label"] = _pocket_druggability_label(pocket["druggability_index"])

    pockets.sort(key=lambda p: p["druggability_index"], reverse=True)

    log.info("complete", n_pockets=len(pockets))
    return {
        "uniprot_id": uid,
        "n_residues": int(ca_coords.shape[0]),
        "putative_pockets": pockets[:10],
        "n_pockets_found": len(pockets),
        "methodology": (
            "Geometric clustering of buried Cα atoms (the inner 60 percent "
            "of residues by distance from the structure centroid), grown "
            "greedily within an 8 Angstrom radius. Clusters with fewer "
            "than min_pocket_residues members or a mean pLDDT below 50 "
            "are discarded. Druggability index is the sum of four equally "
            "weighted 0 to 25 sub-scores: residue count, radius of "
            "gyration, mean pLDDT, and burial."
        ),
        "note": (
            "For production use, validate with fpocket, P2Rank, or DoGSiteScorer. "
            "This tool provides rapid pocket pre-screening without external software dependencies."
        ),
        "provenance": _provenance(alphafold_db="v6", method="geometric-clustering"),
    }


# ── Tool 6: Intrinsic disorder map ───────────────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Detect Intrinsically Disordered Regions",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def detect_intrinsically_disordered(
    params: UniProtInput,
) -> dict[str, Any]:
    """Map intrinsically disordered regions (IDRs) using pLDDT as proxy.

    IDRs with pLDDT < 50 are predicted to be disordered in isolation by AlphaFold.
    This pLDDT-as-disorder-proxy approach is consistent with Ruff & Pappu (2021)
    and scales to the full human proteome from precomputed AlphaFold confidence.

    IDR functional categories returned:
    - **Linkers**: short (< 20 aa) disordered regions between domains
    - **Tails**: N/C terminal IDRs
    - **Long IDRs**: candidate intrinsically disordered protein (IDP) segments

    Clinical relevance:
    - IDRs are enriched for disease-causing mutations
    - IDRs host post-translational modification sites (phosphorylation, ubiquitination)
    - Long IDRs are emerging drug targets (targeted covalent inhibitors, phase separation modulators)

    Reference:
      Ruff KM & Pappu RV. J Mol Biol. 2021;433(20):167208.

    Args:
        params.uniprot_id: UniProt accession.
    """
    uid = params.uniprot_id
    result = await _fetch_af_plddt(uid)

    if not result:
        return _no_structure_response(uid)

    # We can reconstruct per-residue pLDDT from PDB B-factor column
    structure = await _fetch_af_structure(uid)
    if not structure:
        return _no_structure_response(uid)

    per_residue_plddt = _extract_plddt_from_pdb(structure["pdb_text"])
    idr_segments = _detect_idr_segments(per_residue_plddt)

    total_residues = len(per_residue_plddt)
    disordered_residues = sum(1 for p in per_residue_plddt if p < 50)
    idr_fraction = disordered_residues / total_residues if total_residues > 0 else 0.0

    return {
        "uniprot_id": uid,
        "sequence_length": total_residues,
        "idr_fraction": round(idr_fraction, 4),
        "disordered_residue_count": disordered_residues,
        "is_idr_protein": idr_fraction > 0.3,
        "idr_segments": idr_segments,
        "idr_classification": _classify_idr_protein(idr_fraction, idr_segments),
        "clinical_implications": _idr_clinical_implications(idr_fraction, idr_segments),
        "drug_target_potential": (
            "EMERGING: long IDRs are targets for targeted covalent inhibitors and "
            "phase-separation modulators — consult recent IDR drug discovery literature."
            if idr_fraction > 0.3
            else "CONVENTIONAL: ordered structure is suitable for classical SBDD approaches."
        ),
        "reference": "Ruff KM & Pappu RV (2021) J Mol Biol 433:167208. doi:10.1016/j.jmb.2021.167208",
        "provenance": _provenance(alphafold_db="v6", plddt_cutoff="50"),
    }


# ── Pocket geometry helpers ───────────────────────────────────────────────────


def _parse_pdb_full(
    pdb_text: str,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Parse Cα coordinates + residue metadata including B-factor (pLDDT)."""
    coords: list[list[float]] = []
    residues: list[dict[str, Any]] = []
    for line in pdb_text.splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            try:
                coords.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
                residues.append(
                    {
                        "chain": line[21].strip(),
                        "resnum": int(line[22:26].strip()),
                        "resname": line[17:20].strip(),
                        "plddt": float(line[60:66].strip()),  # B-factor stores pLDDT in AF
                    }
                )
            except (ValueError, IndexError):
                continue
    return np.array(coords, dtype=float), residues


def _geometric_pocket_detection(
    ca_coords: np.ndarray,
    residue_info: list[dict[str, Any]],
    min_residues: int = 4,
) -> list[dict[str, Any]]:
    """Detect concave surface regions as putative binding pockets."""
    n = len(ca_coords)
    if n < min_residues:
        return []

    # Centroid of whole structure
    centroid = ca_coords.mean(axis=0)

    # Distance of each residue from centroid
    dist_from_centroid = np.linalg.norm(ca_coords - centroid, axis=1)
    surface_threshold = np.percentile(dist_from_centroid, 60)

    # Identify surface residues (farther than median from centroid)
    surface_mask = dist_from_centroid >= surface_threshold
    buried_mask = ~surface_mask

    # Cluster buried residues into pockets using simple distance clustering
    buried_coords = ca_coords[buried_mask]
    buried_indices = np.where(buried_mask)[0]

    if len(buried_coords) < min_residues:
        return []

    # Greedy clustering: grow pockets from each buried residue
    assigned = [False] * len(buried_coords)
    pockets: list[dict[str, Any]] = []

    for seed_idx in range(len(buried_coords)):
        if assigned[seed_idx]:
            continue
        # Find neighbours within 8 Å
        dists = np.linalg.norm(buried_coords - buried_coords[seed_idx], axis=1)
        neighbour_mask = (dists < 8.0) & ~np.array(assigned)
        if neighbour_mask.sum() < min_residues:
            continue

        member_indices = np.where(neighbour_mask)[0]
        for m in member_indices:
            assigned[m] = True

        pocket_ca = buried_coords[member_indices]
        global_indices = buried_indices[member_indices]
        pocket_residues = [residue_info[i] for i in global_indices if i < len(residue_info)]
        pocket_plddts = [r["plddt"] for r in pocket_residues]
        mean_plddt = float(np.mean(pocket_plddts)) if pocket_plddts else 0.0

        # Only include high-confidence pockets
        if mean_plddt < 50:
            continue

        # Geometric pocket properties
        pocket_centroid = pocket_ca.mean(axis=0)
        rog = float(np.sqrt(np.mean(np.sum((pocket_ca - pocket_centroid) ** 2, axis=1))))
        burial = float(np.linalg.norm(pocket_centroid - centroid))

        pockets.append(
            {
                "pocket_id": len(pockets) + 1,
                "n_residues": len(member_indices),
                "residue_numbers": sorted({r["resnum"] for r in pocket_residues}),
                "residue_names": sorted({r["resname"] for r in pocket_residues}),
                "mean_plddt": round(mean_plddt, 2),
                "radius_of_gyration_angstrom": round(rog, 2),
                "burial_from_centroid": round(burial, 2),
                "estimated_volume_angstrom3": round((4 / 3) * math.pi * rog**3, 1),
            }
        )

    return pockets


def _pocket_druggability_index(pocket: dict[str, Any]) -> float:
    """Score 0–100 for druggability based on pocket geometry."""
    n_res: int = pocket.get("n_residues", 0)
    rog: float = pocket.get("radius_of_gyration_angstrom", 0.0)
    plddt: float = pocket.get("mean_plddt", 0.0)
    burial: float = pocket.get("burial_from_centroid", 0.0)

    # Ideal pocket: 4–12 residues, rog 3–8 Å, plddt > 80, well-buried
    n_score = min(1.0, n_res / 12.0) * 25
    rog_score = max(0.0, 1.0 - abs(rog - 5.0) / 5.0) * 25
    plddt_score = (plddt / 100.0) * 25
    burial_score = min(1.0, burial / 20.0) * 25

    return round(n_score + rog_score + plddt_score + burial_score, 1)


def _pocket_druggability_label(pdi: float) -> str:
    if pdi >= 75:
        return "EXCELLENT"
    if pdi >= 55:
        return "GOOD"
    if pdi >= 35:
        return "MODERATE"
    return "POOR"


def _extract_plddt_from_pdb(pdb_text: str) -> list[float]:
    """Extract per-residue pLDDT from PDB B-factor column (AF convention)."""
    plddts: list[float] = []
    seen: set[tuple[str, int]] = set()
    for line in pdb_text.splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            try:
                chain = line[21].strip()
                resnum = int(line[22:26].strip())
                key = (chain, resnum)
                if key not in seen:
                    seen.add(key)
                    plddts.append(float(line[60:66].strip()))
            except (ValueError, IndexError):
                continue
    return plddts


def _detect_idr_segments(
    per_residue_plddt: list[float],
    cutoff: float = 50.0,
    min_length: int = 5,
) -> list[dict[str, Any]]:
    """Find contiguous runs of residues with pLDDT < cutoff."""
    segments: list[dict[str, Any]] = []
    n = len(per_residue_plddt)
    in_idr = False
    start = 0

    for i, p in enumerate(per_residue_plddt):
        if p < cutoff and not in_idr:
            in_idr = True
            start = i
        elif p >= cutoff and in_idr:
            length = i - start
            if length >= min_length:
                mean_p = float(sum(per_residue_plddt[start:i]) / length)
                segments.append(_classify_idr_segment(start + 1, i, length, mean_p, n))
            in_idr = False

    if in_idr:
        length = n - start
        if length >= min_length:
            mean_p = float(sum(per_residue_plddt[start:]) / length)
            segments.append(_classify_idr_segment(start + 1, n, length, mean_p, n))

    return segments


def _classify_idr_segment(
    start: int, end: int, length: int, mean_plddt: float, total: int
) -> dict[str, Any]:
    if start == 1:
        kind = "N-terminal tail"
    elif end == total:
        kind = "C-terminal tail"
    elif length < 20:
        kind = "Linker"
    else:
        kind = "Long IDR"
    return {
        "start": start,
        "end": end,
        "length": length,
        "mean_plddt": round(mean_plddt, 2),
        "segment_type": kind,
    }


def _classify_idr_protein(
    idr_fraction: float,
    segments: list[dict[str, Any]],
) -> str:
    long_idrs = [s for s in segments if s["segment_type"] == "Long IDR"]
    if idr_fraction > 0.7:
        return "Fully disordered (IDP) — likely functions via disorder-to-order transitions."
    if idr_fraction > 0.3 or long_idrs:
        return "Partially disordered (IDPR) — ordered domains connected by IDRs."
    return "Predominantly ordered — classical structural biology approaches apply."


def _idr_clinical_implications(idr_fraction: float, segments: list[dict[str, Any]]) -> list[str]:
    implications: list[str] = []
    if idr_fraction > 0.3:
        implications.append(
            "High IDR fraction: enriched for post-translational modification sites "
            "(phosphorylation, acetylation, ubiquitination)."
        )
    tails = [s for s in segments if "tail" in s["segment_type"].lower()]
    if tails:
        implications.append(
            "Terminal IDRs identified: candidate nuclear localisation signals, "
            "degradation signals, or binding motifs."
        )
    long_idrs = [s for s in segments if s["segment_type"] == "Long IDR"]
    if long_idrs:
        implications.append(
            f"{len(long_idrs)} long IDR(s) detected: candidate liquid-liquid phase "
            "separation (LLPS) driver. Relevant for neurodegenerative disease mechanisms."
        )
    if not implications:
        implications.append("No significant IDRs: protein is predominantly ordered.")
    return implications


# ── pLDDT helpers ─────────────────────────────────────────────────────────────


def _plddt_tier(plddt: float | None) -> str:
    if plddt is None:
        return "UNKNOWN"
    if plddt >= 90:
        return "VERY_HIGH"
    if plddt >= 70:
        return "HIGH"
    if plddt >= 50:
        return "LOW"
    return "VERY_LOW"


def _plddt_tier_explanation(tier: str) -> str:
    return {
        "VERY_HIGH": "pLDDT ≥ 90: backbone and sidechain positions likely correct. Suitable for SBDD.",
        "HIGH": "pLDDT 70–90: backbone correct, some sidechain uncertainty. Suitable for pocket analysis.",
        "LOW": "pLDDT 50–70: may represent IDP region or novel fold. Verify with experimental structure.",
        "VERY_LOW": "pLDDT < 50: disordered in isolation or no structural data. Not suitable for SBDD.",
        "UNKNOWN": "AlphaFold confidence data not available.",
    }.get(tier, "Unknown.")


def _estimate_ordered_fraction(plddt: float | None) -> float | None:
    if plddt is None:
        return None
    return round(min(1.0, max(0.0, (plddt - 50.0) / 50.0)), 3)


# ── Ortholog resolution ──────────────────────────────────────────────────────


async def _resolve_ortholog_uniprot(ensembl: EnsemblClient, ensembl_gene_id: str) -> str:
    """Resolve an Ensembl gene ID to a UniProt accession via the Ensembl xref endpoint."""
    try:
        # The Ensembl /xrefs endpoint returns a JSON *array*; ``_get`` is
        # annotated ``dict[str, Any]`` for the common object case, so widen
        # locally to keep the list branch reachable.
        data: Any = await ensembl._get(
            f"/xrefs/id/{ensembl_gene_id}",
            params={"external_db": "Uniprot/SWISSPROT"},
        )
        if isinstance(data, list):
            for xref in data:
                pid = xref.get("primary_id", "")
                if pid:
                    return str(pid)
    except Exception:
        pass
    return ""


# ── TDA interpretation ────────────────────────────────────────────────────────


def _interpret_tda(tda: dict[str, Any]) -> str:
    betti = tda.get("betti_numbers", [0, 0, 0])
    b0 = betti[0] if len(betti) > 0 else 0
    b1 = betti[1] if len(betti) > 1 else 0
    b2 = betti[2] if len(betti) > 2 else 0
    parts = []
    if b0 > 1:
        parts.append(f"β₀={b0} disconnected components (multi-domain or extended chain)")
    else:
        parts.append("β₀=1 single connected component (compact globular)")
    if b1 > 3:
        parts.append(f"β₁={b1} loops (ring-like topology such as β-barrels or large macrocycles)")
    elif b1 > 0:
        parts.append(f"β₁={b1} loop(s) detected")
    if b2 > 0:
        parts.append(f"β₂={b2} enclosed cavity/cavities (potential binding voids)")
    return "; ".join(parts) + "." if parts else "Topology computed."


# ── Evolutionary drift helpers ────────────────────────────────────────────────


def _drift_interpretation(drift: float | None, dn_ds: float | None) -> str:
    if drift is None:
        return "Structural drift not quantifiable (AF DB coverage unavailable for this species)."
    if drift < 0.1:
        return "Highly conserved structural topology — supports cross-species structural comparison (validate binding site separately)."
    if drift < 0.3:
        return "Moderate structural drift — drug binding site may differ; validate binding pose."
    return "High structural drift — independent validation required before using as disease model."


def _cross_reactivity_risk(identity: float, dn_ds: float | None) -> str:
    if identity >= 90:
        return "HIGH — near-identical sequence; antibody cross-reactivity likely."
    if identity >= 70:
        return "MODERATE — shared structural epitopes likely; antibody cross-reactivity possible."
    if identity >= 50:
        return "LOW — limited shared epitopes; selective immune targeting possible."
    return "MINIMAL — distant homolog; cross-reactivity unlikely."


def _find_most_similar_pair(ids: list[str], matrix: list[list[float]]) -> dict[str, Any] | None:
    if len(ids) < 2:
        return None
    best: tuple[float, str, str] = (float("inf"), "", "")
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            d = matrix[i][j]
            if d < best[0]:
                best = (d, ids[i], ids[j])
    return {
        "protein_a": best[1],
        "protein_b": best[2],
        "distance": best[0],
        "similarity_pct": round((1.0 - best[0]) * 100, 1),
    }
