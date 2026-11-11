# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Structure-intelligence MCP tools.

These tools take raw AlphaFold structures (PDB text and PAE arrays from
AlphaFold DB) and derive a small set of summaries from them:

* pLDDT and PAE confidence summaries, including the positions where
  near-diagonal PAE is locally elevated. Those positions are not domain
  boundaries, and no domain count is derived from them,
* a 64-slot exploratory Cα feature vector that holds at most 16 summary
  statistics. Optional GUDHI computes H₀/H₁ at the final 15-Å
  Vietoris-Rips filtration step and contributes eight bar-lifetime
  statistics for each; H₂ is not computed and the other 48 slots are
  zero. Models longer than 500 residues are reduced to 500 evenly
  spaced Cα atoms first. Without GUDHI, the fallback fills eight slots
  with distance and contact statistics, one of them the 4-Å
  contact-graph component count, and computes no persistent homology,
* a pairwise distance matrix between TDA fingerprints (the
  implementation is an L2 distance on length-normalised fingerprint
  vectors — it is **not** an optimal-transport Wasserstein distance;
  see ``_fingerprint_distance``),
* geometric clusters of core residues with an uncalibrated geometry
  score. This is not a validated binding-pocket detector, and no
  druggability class is assigned, and
* an intrinsic-disorder-region map.

All tools are read-only. Tools that require outbound HTTP fail closed when
``ALPHAFOLD_OFFLINE=1``: the client raises ``AirGapError`` and the tool
reports the AlphaFold DB request as failed, not as a missing model. There
is no local structure cache.

Tool inventory:
  1. analyze_structural_confidence       — pLDDT + PAE confidence summary
  2. compute_topology_fingerprint        — Exploratory Cα features; H₀/H₁ if GUDHI
  3. compare_proteins_topologically      — Pairwise fingerprint-distance matrix
  4. find_evolutionary_structural_shifts — Cross-species TDA fingerprint compare
  5. score_binding_pocket_geometry       — Core-residue clusters + geometry score
  6. detect_intrinsically_disordered     — IDR region map
  7. get_protein_structure               — Retrieve AF model metadata, URLs, coordinates
"""

from __future__ import annotations

import asyncio
import datetime
import math
from typing import TYPE_CHECKING, Any, Literal, cast

import numpy as np
import structlog
from pydantic import BaseModel, ConfigDict, Field

from alphafold_sovereign import __version__
from alphafold_sovereign.clients._base import UpstreamError
from alphafold_sovereign.clients._isoform import UniProtVerificationError
from alphafold_sovereign.clients.alphafold import (
    AlphaFoldClient,
    AlphaFoldPredictionSchemaError,
    _afdb_version_label,
    _prediction_model_id,
    _prediction_sequence,
    _prediction_version,
)
from alphafold_sovereign.clients.ensembl import EnsemblClient
from alphafold_sovereign.domain.druggability import validated_plddt
from alphafold_sovereign.domain.uniprot import UNIPROT_ISOFORM_PATTERN
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
        description="UniProt accession (6/10 characters), optionally with isoform suffix (e.g. P04637-2).",
        pattern=UNIPROT_ISOFORM_PATTERN,
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
        description=(
            "UniProt accession of the protein whose AlphaFold DB model is clustered, "
            "e.g. 'P24941' (CDK2). Six or ten characters; an isoform suffix such as "
            "'P04637-2' selects that isoform's model when AlphaFold DB provides one."
        ),
        pattern=UNIPROT_ISOFORM_PATTERN,
    )
    min_pocket_residues: int = Field(
        default=4,
        ge=3,
        le=20,
        description=(
            "Minimum cluster size: a core residue seeds a cluster only when at least this "
            "many unassigned core Cα atoms, itself included, lie within 8 Å of it. Higher "
            "values suppress small clusters. The name is historical; clusters are not "
            "validated pockets."
        ),
    )


class StructureRetrievalInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    uniprot_id: str = Field(
        ...,
        description="UniProt accession whose AlphaFold model to retrieve, e.g. 'P38398' (BRCA1).",
        pattern=UNIPROT_ISOFORM_PATTERN,
    )
    include_coordinates: bool = Field(
        default=False,
        description=(
            "If true, embed the full PDB coordinate text in the response (large — "
            "hundreds of KB for big proteins). Default false returns the metadata "
            "and download URLs only, from which the coordinate files can be fetched."
        ),
    )


# ── AF structure fetcher (uses existing fetcher infrastructure) ───────────────


_CLIENTS: dict[str, BaseAsyncClient] = {}


def _alphafold() -> AlphaFoldClient:
    """Return the process-wide AlphaFold DB client (lazily constructed)."""
    if "alphafold" not in _CLIENTS:
        _CLIENTS["alphafold"] = AlphaFoldClient()
    return cast("AlphaFoldClient", _CLIENTS["alphafold"])


class _RequestFailed:
    """An AlphaFold DB request that did not complete.

    Distinct from ``None``, which means AlphaFold DB answered and returned no
    model. An instance is falsy, so code that only needs a model treats the
    two alike, while a response can still say which one happened: a blocked
    or failed request is not evidence that no prediction exists.
    """

    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def __bool__(self) -> Literal[False]:
        return False


_HTTP_NOT_FOUND = 404


def _unretrieved(exc: Exception) -> _RequestFailed | None:
    """Classify an error raised by an AlphaFold DB call.

    HTTP 404 is how AlphaFold DB answers for an accession it serves no model
    for, so it maps to ``None``. Anything else (offline mode, an open circuit
    breaker, a timeout, a server error, an unreadable body) is a request that
    failed, and says nothing about whether a model exists.
    """
    if isinstance(exc, UpstreamError) and exc.status == _HTTP_NOT_FOUND:
        return None
    return _RequestFailed(f"{type(exc).__name__}: {exc}")


async def _fetch_af_structure(uniprot_id: str) -> dict[str, Any] | _RequestFailed | None:
    """Fetch AlphaFold structure coordinates for a UniProt accession.

    Routes through AlphaFoldClient, so the request shares the client's
    rate limiter, retry policy, circuit breaker, air-gap enforcement,
    and the advertised-file-URL host guard. Returns None when AlphaFold DB
    answers without a model for the accession, and a falsy
    ``_RequestFailed`` when the request did not complete.
    ``model_version`` is the version the prediction record reports for the
    file (None if it reports none).
    """
    try:
        record, pdb_bytes = await _alphafold().get_pdb_model(uniprot_id)
    except (UniProtVerificationError, AlphaFoldPredictionSchemaError):
        raise
    except Exception as exc:
        logger.warning("af.fetch.failed", uniprot_id=uniprot_id, exc=str(exc))
        return _unretrieved(exc)
    if not pdb_bytes:
        return None
    return {
        "pdb_text": pdb_bytes.decode("utf-8", errors="replace"),
        "uniprot_id": uniprot_id,
        "model_version": _prediction_version(record),
    }


async def _fetch_af_plddt(uniprot_id: str) -> dict[str, Any] | _RequestFailed | None:
    """Fetch the pLDDT summary and PAE matrix for a UniProt accession.

    Routes through AlphaFoldClient. Reads the global pLDDT confidence
    from the prediction metadata (the ``globalMetricValue`` field; the
    older ``meanPlddt`` field is absent from the current AlphaFold DB
    schema) and the PAE matrix from the advertised PAE document.

    Returns None when AlphaFold DB answers without a model for the
    accession, so callers can distinguish "no structure" from a structure
    with missing fields, and a falsy ``_RequestFailed`` when the request
    did not complete.
    """
    client = _alphafold()
    try:
        meta = await client.get_prediction(uniprot_id)
    except (UniProtVerificationError, AlphaFoldPredictionSchemaError):
        raise
    except Exception as exc:
        logger.warning("af.summary.failed", uniprot_id=uniprot_id, exc=str(exc))
        return _unretrieved(exc)
    if not isinstance(meta, dict) or not _prediction_model_id(meta):
        return None

    mean_plddt, plddt_status = validated_plddt(meta.get("globalMetricValue"))
    result: dict[str, Any] = {
        "uniprot_id": uniprot_id,
        "model_entity_id": _prediction_model_id(meta),
        "model_version": _prediction_version(meta),
        "mean_plddt": mean_plddt,
        "plddt_status": plddt_status,
        "model_url": meta.get("pdbUrl", ""),
        "sequence_length": len(_prediction_sequence(meta)),
        "model_uniprot_accession": meta.get("uniprotAccession"),
        "verified_displayed_isoform": meta.get("_sovereign_verified_isoform"),
        "sequence_start": meta.get("sequenceStart", meta.get("uniprotStart")),
        "sequence_end": meta.get("sequenceEnd", meta.get("uniprotEnd")),
    }

    try:
        pae_doc = await client.get_pae(uniprot_id)
    except Exception as exc:
        logger.warning("af.pae.failed", uniprot_id=uniprot_id, exc=str(exc))
        result["pae_status"] = "unavailable"
        return result

    try:
        pae_matrix = np.asarray(pae_doc.get("predicted_aligned_error", []), dtype=float)
    except (TypeError, ValueError):
        result["pae_status"] = "invalid_numeric_data"
        return result
    if pae_matrix.size == 0:
        result["pae_status"] = "missing"
        return result
    if pae_matrix.ndim != 2 or pae_matrix.shape[0] != pae_matrix.shape[1]:
        result["pae_status"] = "invalid_shape"
        return result
    if not bool(np.isfinite(pae_matrix).all()) or bool((pae_matrix < 0).any()):
        result["pae_status"] = "invalid_values"
        return result
    sequence_length = result["sequence_length"]
    if sequence_length and pae_matrix.shape[0] != sequence_length:
        result["pae_status"] = "sequence_length_mismatch"
        return result

    result["pae_status"] = "available"
    result["pae_matrix_shape"] = list(pae_matrix.shape)
    result["pae_mean"] = float(np.mean(pae_matrix))
    result["pae_max"] = float(np.max(pae_matrix))
    # The PAE is directional and indexed in the selected model's local sequence.
    result["high_pae_pairs"] = _find_high_pae_pairs(pae_matrix, threshold=15.0)
    result["local_high_pae_positions"] = _local_high_pae_onsets(pae_matrix)
    result["local_high_pae_scanned"] = max(0, pae_matrix.shape[0] - 2 * _LOCAL_PAE_WINDOW)
    return result


def _no_structure_response(uniprot_id: str, fetched: object = None) -> dict[str, Any]:
    """Return a uniform, human-readable response when no model was retrieved.

    AlphaFold DB does not contain a model for every UniProt accession.
    When a structure or prediction fetch returns nothing, every
    structure tool returns this same shape, so an LLM or a human
    receives one clear, consistent explanation rather than a terse or
    silent failure.

    The two reasons are kept apart in ``retrieval_status``.
    ``no_prediction_returned``: AlphaFold DB answered and returned no model.
    ``request_failed``: the request was blocked or failed, which is not
    evidence that no prediction exists.

    Args:
        uniprot_id: The accession that was requested.
        fetched: What the fetch returned: ``None``, or the ``_RequestFailed``
            that describes why the request did not complete.

    Returns:
        A dict carrying ``structure_available`` set to False,
        ``retrieval_status``, a plain ``error`` line, and an explanatory
        ``note``.
    """
    if isinstance(fetched, _RequestFailed):
        return {
            "uniprot_id": uniprot_id,
            "structure_available": False,
            "retrieval_status": "request_failed",
            "error": (
                "The AlphaFold DB request for this UniProt accession did not "
                f"complete: {fetched.reason}"
            ),
            "note": (
                "A request that was blocked or failed is not evidence that "
                "AlphaFold DB has no prediction for this accession. No model was "
                "examined. Retry when the service is reachable."
            ),
        }
    return {
        "uniprot_id": uniprot_id,
        "structure_available": False,
        "retrieval_status": "no_prediction_returned",
        "error": (
            "No structure prediction returned by the AlphaFold DB REST API "
            "for this UniProt accession."
        ),
        "note": (
            "An empty API response does not prove that no prediction exists. "
            "Human proteins longer than 2700 residues may have overlapping "
            "fragment models available through the AlphaFold FTP archive only; "
            "other identifiers may be absent or recently updated. "
            "Check https://alphafold.ebi.ac.uk/ and its FTP documentation."
        ),
    }


def _missing_model_reason(fetched: object) -> str:
    """Say in one line why no model is available for an accession."""
    if isinstance(fetched, _RequestFailed):
        return (
            f"AlphaFold model retrieval failed ({fetched.reason}); this is not "
            "evidence that no model exists."
        )
    return "No AlphaFold model for this accession."


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


_LOCAL_PAE_WINDOW = 10
"""Half-width, in residues, of the diagonal PAE block scanned for local uncertainty."""

_LOCAL_HIGH_PAE_DEFINITION = (
    "Zero-based model indices (not UniProt positions) where a run of locally elevated "
    "near-diagonal PAE begins: the mean PAE of the 20x20 diagonal block around the index "
    "exceeds the whole-matrix mean by more than 1.5 standard deviations of that statistic. "
    "Approximate to within 10 residues; the first and last 10 indices are not scanned, so "
    "10 means at or before index 10; at most 10 are reported. A flagged run is a stretch "
    "much less certain than the model overall, such as a flexible tail. Not a domain "
    "boundary."
)

_DOMAIN_BOUNDARIES_NOT_ASSESSED = (
    "NOT_ASSESSED: this tool does not identify domain boundaries or count domains. The "
    "positions formerly listed here are reported as local_high_pae.positions. In an "
    "internal audit of 8 multi-domain proteins they marked no border between two "
    "annotated UniProtKB domains (LIMITATIONS.md L10). Use curated domain annotations "
    "such as InterPro for domains."
)


def _local_high_pae_onsets(pae: np.ndarray, window: int = _LOCAL_PAE_WINDOW) -> list[int]:
    """Return where runs of locally elevated near-diagonal PAE begin.

    For every index ``i`` with ``window <= i < n - window`` the statistic is
    the mean PAE of the diagonal block ``[i - window, i + window)`` minus the
    mean of the whole matrix. An index is flagged when that excess is more
    than 1.5 standard deviations of the statistic over all scanned indices,
    and the first index of each flagged run is returned (zero-based model
    indices, at most 10).

    The block sits on the diagonal, so the statistic measures how uncertain
    residues are relative to their sequence neighbours, and the threshold is
    relative to the whole matrix: what gets flagged is a short stretch much
    less certain than the model overall (a flexible tail or linker), and a
    model with a high overall PAE usually yields nothing. Uncertainty
    *between* two confidently predicted regions appears off the diagonal and
    is not measured, so the onsets are not domain boundaries and no domain
    count follows from them. An onset is approximate to within ``window``
    residues. The first and last ``window`` indices are never scanned; an
    onset equal to ``window`` therefore means the run starts at or before
    that index.
    """
    n = pae.shape[0]
    onsets: list[int] = []
    if n < 2 * window:
        return onsets
    global_mean = float(np.mean(pae))
    scores = []
    for i in range(window, n - window):
        local = float(np.mean(pae[i - window : i + window, i - window : i + window]))
        scores.append((i, local - global_mean))
    threshold = float(np.std([s for _, s in scores])) * 1.5
    prev_over = False
    for pos, score in scores:
        if score > threshold and not prev_over:
            onsets.append(pos)
            prev_over = True
        elif score <= threshold:
            prev_over = False
    return onsets[:10]


# ── TDA fingerprint computation ───────────────────────────────────────────────

_TDA_MAX_RESIDUES = 500
"""Cα atoms the Rips complex is built on; longer models are subsampled evenly."""

_TDA_FINGERPRINT_LAYOUT = (
    "64 slots, at most 16 non-zero. Slots 0-7 and 8-15: mean, standard deviation, "
    "maximum, minimum, median, 75th percentile, 25th percentile and sum of the finite "
    "H0 and H1 bar lifetimes. Slots 16-23: zero (H2 is not computed). Slots 24-63: "
    "zero padding."
)

_FALLBACK_FINGERPRINT_LAYOUT = (
    "64 slots, at most 8 non-zero. Slots 0-7: mean, standard deviation and minimum of "
    "the pairwise Cα distances, largest distance below 30 Å, mean number of contacts "
    "within 4 Å, 10th and 90th distance percentiles, and the 4-Å contact-graph "
    "component count. Slots 8-63: zero padding. No persistent homology is computed."
)


def _compute_tda_fingerprint(
    ca_coords: np.ndarray,
    max_dimension: int = 2,
) -> dict[str, Any]:
    """Compute a topological fingerprint from Cα coordinates.

    Builds a Vietoris-Rips 2-skeleton over the Cα point cloud.
    GUDHI provides H0/H1 persistence at a finite 15-Å filtration scale.
    H2 is not established from this truncated complex and is reported as
    unavailable, never as zero. Without GUDHI the distance-statistics
    fallback computes only the exact 4-Å graph component count.

    A model with more than 500 Cα atoms is reduced to 500 evenly spaced
    ones before the complex is built. The Betti numbers and statistics
    then describe that subsample, whose neighbour spacing is wider than
    the chain's, and can differ from the values for all residues;
    ``subsampled`` and ``n_residues_total`` report when this happened.

    Args:
        ca_coords: (N, 3) array of Cα coordinates.
        max_dimension: Maximum homology dimension (default 2: β₀, β₁, β₂).

    Returns:
        Dict with Betti numbers, a (truncated) persistence summary, and
        a 64-slot fingerprint vector. Slots 0-7 and 8-15 hold eight
        statistics of the finite H0 and H1 bar lifetimes (mean, standard
        deviation, maximum, minimum, median, 75th percentile, 25th
        percentile, sum). GUDHI computes no H2 for a 2-skeleton, so slots
        16-23 stay zero, and slots 24-63 are zero padding: the vector
        carries at most 16 statistics. It is a fixed-length feature used
        for downstream pairwise comparison, not a published embedding
        from a peer-reviewed method.
    """
    try:
        import gudhi
    except ImportError:
        return _fallback_tda_fingerprint(ca_coords)

    n_total = len(ca_coords)
    if n_total > _TDA_MAX_RESIDUES:
        idx = np.linspace(0, n_total - 1, _TDA_MAX_RESIDUES, dtype=int)
        ca_coords = ca_coords[idx]

    # Build Rips complex
    max_edge_length = 15.0  # Ångström — captures secondary structure contacts
    rips = gudhi.RipsComplex(points=ca_coords.tolist(), max_edge_length=max_edge_length)
    simplex_tree = rips.create_simplex_tree(max_dimension=max_dimension)
    simplex_tree.compute_persistence()

    # The number of finite persistence bars is NOT a Betti number.
    # At the terminal filtration value, infinite bars represent surviving
    # homology classes. GUDHI excludes the maximum simplex dimension by
    # default; never pretend that missing top-dimensional H2 equals zero.
    diagram = simplex_tree.persistence()
    betti_numbers: list[int | None] = []
    landscapes: list[dict[str, Any]] = []
    fingerprint: list[float] = []

    for dim in range(max_dimension + 1):
        intervals = [(b, d) for (k, (b, d)) in diagram if k == dim and d < float("inf")]
        betti_numbers.append(
            None
            if dim == max_dimension
            else sum(1 for k, (_b, death) in diagram if k == dim and death == float("inf"))
        )

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
        "fingerprint_layout": _TDA_FINGERPRINT_LAYOUT,
        "n_residues_used": len(ca_coords),
        "n_residues_total": n_total,
        "subsampled": n_total > _TDA_MAX_RESIDUES,
        "max_filtration_length_angstrom": max_edge_length,
        "methodology": (
            "Vietoris-Rips 2-skeleton via GUDHI on the Cα atoms (500 evenly spaced ones "
            "when the model has more); H0/H1 at the terminal 15-Å filtration; H2 not computed."
        ),
        "gudhi_available": True,
    }


def _fallback_tda_fingerprint(ca_coords: np.ndarray) -> dict[str, Any]:
    """Coarse fallback fingerprint when gudhi is not installed.

    Computes distance-matrix statistics and the connected-component count
    of the 4-Å contact graph. This is NOT persistent homology: H1 and H2
    are unknown (None), not zero. Install gudhi with the [tda] extra
    for H0/H1 persistence. All residues are used (no subsampling), and
    the 64-slot vector carries eight statistics followed by zeros.
    """
    if len(ca_coords) < 2:
        return {
            "betti_numbers": [len(ca_coords), None, None],
            "fingerprint_vector": [0.0] * 64,
            "fingerprint_dimension": 64,
            "fingerprint_layout": _FALLBACK_FINGERPRINT_LAYOUT,
            "n_residues_used": len(ca_coords),
            "n_residues_total": len(ca_coords),
            "subsampled": False,
            "gudhi_available": False,
        }

    dists = np.sqrt(np.sum((ca_coords[:, None, :] - ca_coords[None, :, :]) ** 2, axis=-1))
    np.fill_diagonal(dists, np.inf)

    # Exact β0 for the 4-Å contact graph, including non-singleton components.
    adjacency = dists < 4.0
    contacts = adjacency.sum(axis=1)
    seen = np.zeros(len(ca_coords), dtype=bool)
    b0 = 0
    for start in range(len(ca_coords)):
        if seen[start]:
            continue
        b0 += 1
        seen[start] = True
        stack = [start]
        while stack:
            for neighbor in np.flatnonzero(adjacency[stack.pop()]):
                if not seen[neighbor]:
                    seen[neighbor] = True
                    stack.append(int(neighbor))

    mean_contacts = float(np.mean(contacts))

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
        "betti_numbers": [b0, None, None],
        "fingerprint_vector": [round(f, 6) for f in fingerprint],
        "fingerprint_dimension": 64,
        "fingerprint_layout": _FALLBACK_FINGERPRINT_LAYOUT,
        "n_residues_used": len(ca_coords),
        "n_residues_total": len(ca_coords),
        "subsampled": False,
        "gudhi_available": False,
        "note": "Install gudhi for full persistent-homology computation: pip install alphafold-sovereign-mcp[tda]",
    }


def _fingerprint_method_label(gudhi_flags: list[bool]) -> str:
    """Name the fingerprint method that ran, one flag per fingerprint computed."""
    if not gudhi_flags:
        return "not-computed"
    return "VR-persistent-homology" if all(gudhi_flags) else "geometric-proxy"


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
    """Analyze AlphaFold structural confidence using pLDDT and PAE.

    Returns a structural reliability summary (not a per-residue profile):
    - **pLDDT**: the model's mean confidence (AlphaFold DB ``globalMetricValue``)
      plus a coarse confidence tier
    - **PAE** (predicted aligned error): mean and maximum; up to five
      residue pairs more than 10 positions apart with PAE above 15 Å
      (one-based model indices); and ``local_high_pae``, the approximate
      zero-based model indices where a run of locally elevated
      near-diagonal PAE begins (a short stretch much less certain than
      the model as a whole, such as a flexible tail or linker)
    - **Domains**: NOT assessed. Near-diagonal PAE does not locate domain
      boundaries; the legacy ``domain_boundaries`` block is kept for
      existing clients with ``n_putative_domains`` null and no candidate
      positions
    - **Druggability pre-screen**: model confidence limitations; actual
      ordered fraction and ligand suitability are NOT assessed

    pLDDT interpretation:
      > 90: Very high confidence — likely correct at backbone + sidechain level
      70–90: High confidence — backbone correct, some sidechain uncertainty
      50–70: Low confidence — may be IDP or novel fold
      < 50: Very low model confidence; does not establish disorder

    Input fields:
        params.uniprot_id: UniProt accession.
    """
    uid = params.uniprot_id
    result = await _fetch_af_plddt(uid)

    if not result:
        return _no_structure_response(uid, result)

    plddt, plddt_status = validated_plddt(result.get("mean_plddt"))
    if plddt_status == "missing" and result.get("plddt_status") == "invalid_response":
        plddt_status = "invalid_response"
    confidence_tier = _plddt_tier(plddt)
    model_version = _afdb_version_label([result.get("model_version")])

    return {
        "uniprot_id": uid,
        "mean_plddt": round(plddt, 2) if plddt is not None else None,
        "confidence_tier": confidence_tier,
        "plddt_status": plddt_status,
        "confidence_tier_explanation": _plddt_tier_explanation(confidence_tier),
        "sequence_length": result.get("sequence_length"),
        "model_entity_id": result.get("model_entity_id"),
        "model_uniprot_accession": result.get("model_uniprot_accession"),
        "verified_displayed_isoform": result.get("verified_displayed_isoform"),
        "sequence_start": result.get("sequence_start"),
        "sequence_end": result.get("sequence_end"),
        "pae_summary": {
            "available": "pae_mean" in result,
            "status": result.get(
                "pae_status", "available" if "pae_mean" in result else "unavailable"
            ),
            "mean_pae_angstrom": (round(result["pae_mean"], 2) if "pae_mean" in result else None),
            "max_pae_angstrom": (round(result["pae_max"], 2) if "pae_max" in result else None),
            "high_uncertainty_pairs": result.get("high_pae_pairs", [])[:5],
        },
        "local_high_pae": {
            "status": "computed" if "pae_mean" in result else "pae_unavailable",
            "positions": result.get("local_high_pae_positions", []),
            "n_indices_scanned": result.get("local_high_pae_scanned", 0),
            "definition": _LOCAL_HIGH_PAE_DEFINITION,
        },
        # Legacy block, kept so existing clients find the keys. It carries the
        # not-assessed state earlier releases already used when PAE was missing.
        "domain_boundaries": {
            "status": "NOT_ASSESSED",
            "candidate_positions": [],
            "n_putative_domains": None,
            "note": _DOMAIN_BOUNDARIES_NOT_ASSESSED,
        },
        "druggability_pre_screen": {
            "ordered_fraction": None,
            "ordered_fraction_note": (
                "NOT_ASSESSED: mean pLDDT cannot determine the fraction "
                "of residues that are intrinsically ordered."
            ),
            "structural_suitability": (
                "NOT_ASSESSED: mean pLDDT is unavailable; model confidence cannot be categorized."
                if plddt is None
                else (
                    "HIGHER MODEL CONFIDENCE: validate pockets and ligand binding independently"
                    if plddt >= 70
                    else "CAUTION: low confidence may indicate disorder or an uncertain prediction"
                )
            ),
        },
        "model_url": result.get("model_url", ""),
        "provenance": _provenance(alphafold_db=model_version, plddt_version=model_version),
    }


# ── Tool 2: TDA Fingerprint ───────────────────────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Compute Topological Fingerprint (TDA)",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def compute_topology_fingerprint(
    params: UniProtInput,
) -> dict[str, Any]:
    """Compute an exploratory, rotation-invariant Cα summary vector for an AlphaFold model.

    Fetches the AlphaFold model for ``uniprot_id`` and derives an
    exploratory 64-slot feature vector from its Cα coordinates. With GUDHI
    installed, H0 and H1 are computed on the 15-Å Vietoris-Rips 2-skeleton
    and the vector holds 16 summary statistics of their finite bar
    lifetimes (eight each); the other 48 slots are zero. H2 is NOT
    computed. Models longer than 500 residues are reduced to 500 evenly
    spaced Cα atoms first, so their Betti numbers and statistics describe
    that subsample (``subsampled`` is then true). Without GUDHI the vector
    holds eight distance and contact statistics, one of them a 4-Å
    contact-graph component count, and no persistent homology is computed.
    Betti numbers describe this chosen filtration, not protein domains,
    β-barrels, drug cavities, molecular function, or an experimental structure.

    Returns the fingerprint vector and its slot layout, the Betti numbers, the
    residue counts, and which method ran. Full persistent homology needs the
    optional ``[tda]`` extra (``gudhi``); without it a coarse fallback runs that
    does NOT compute persistent homology, and the result flags this. Returns a
    no-structure result when AlphaFold DB has no model for the accession. This is
    a coarse, geometry-only summary — not a substitute for sequence alignment,
    RMSD, or functional-homology assessment.

    Input fields:
        params.uniprot_id: UniProt accession of the protein to fingerprint,
            e.g. 'P38398' (BRCA1).
    """
    uid = params.uniprot_id
    log = logger.bind(uniprot_id=uid, tool="compute_topology_fingerprint")
    log.info("start")

    structure = await _fetch_af_structure(uid)
    if not structure:
        return _no_structure_response(uid, structure)

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
            "Exploratory feature-vector comparison only; not validated structural homology, "
            "functional identity, binding-site equivalence, or a diagnostic endpoint."
        ),
        "provenance": _provenance(
            alphafold_db=_afdb_version_label([structure.get("model_version")]),
            methodology=tda.get("methodology", "geometric-proxy"),
        ),
    }


# ── Tool 3: Pairwise topological comparison ───────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Compare Proteins Topologically (TDA Fingerprint Distance)",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def compare_proteins_topologically(
    params: MultiProteinInput,
) -> dict[str, Any]:
    """Compare multiple proteins using a TDA-fingerprint distance.

    Computes a pairwise distance matrix between the TDA fingerprints of
    the provided proteins.  Distance metric: L2 distance between
    length-normalised 64-slot fingerprint vectors (see
    ``_fingerprint_distance``).  Distance = 0 means identical
    fingerprints; larger values mean more divergent fingerprints.  This
    is **not** a Wasserstein distance between persistence diagrams.

    The vectors hold at most 16 statistics (see
    ``compute_topology_fingerprint``), and a model longer than 500
    residues is compared on 500 evenly spaced Cα atoms. In an internal
    audit of 23 AlphaFold models, nearly all of each normalised vector lay
    in its two total-persistence components, so the distance mostly tracks
    one ratio: total H1 over total H0 persistence. It has no validated
    threshold for fold similarity and is not a functional,
    sequence-similarity or binding-site measure (LIMITATIONS.md L12).

    Input fields:
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
    model_versions: list[int | None] = []
    gudhi_flags: list[bool] = []

    for uid, fetched in zip(ids, structures):
        # gather() hands back what the fetch re-raised (isoform verification
        # or schema errors). That too is a failed retrieval, not a missing model.
        struct = (
            _RequestFailed(f"{type(fetched).__name__}: {fetched}")
            if isinstance(fetched, BaseException)
            else fetched
        )
        if not struct:
            errors[uid] = _missing_model_reason(struct)
            continue
        ca = _parse_ca_coords_from_pdb(struct["pdb_text"])
        if ca.shape[0] == 0:
            errors[uid] = "No Cα atoms."
            continue
        tda = _compute_tda_fingerprint(ca)
        fingerprints[uid] = tda["fingerprint_vector"]
        model_versions.append(struct.get("model_version"))
        gudhi_flags.append(tda.get("gudhi_available") is True)
        protein_meta[uid] = {
            "n_residues": int(ca.shape[0]),
            "n_residues_used": tda.get("n_residues_used"),
            "subsampled": tda.get("subsampled"),
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
            "Uncalibrated geometric/topological feature-vector distances. "
            "No validated threshold for fold similarity, protein function, "
            "drug repurposing, or off-target effects; verify the calculation method."
        ),
        "provenance": _provenance(
            alphafold_db=_afdb_version_label(model_versions),
            methodology=_fingerprint_method_label(gudhi_flags),
        ),
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
    """Report ortholog sequence identity and exploratory structural distances.

    Distances between Cα-derived feature vectors are not calibrated
    evolutionary, functional, binding, or antibody cross-reactivity measures.
    The GUDHI and geometric-proxy methods are distinguished in each result.
    There is deliberately no cross-method conservation ranking.
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

    human_gene = await ensembl.gene_lookup(sym)
    human_uniprot = (human_gene.get("uniprot_ids") or [""])[0]
    human_struct = await _fetch_af_structure(human_uniprot) if human_uniprot else None
    human_ca: np.ndarray | None = None
    model_versions: list[int | None] = []
    if human_struct:
        model_versions.append(human_struct.get("model_version"))
        human_ca = _parse_ca_coords_from_pdb(human_struct["pdb_text"])
        if human_ca.shape[0] == 0:
            human_ca = None

    human_fingerprint: list[float] | None = None
    human_has_gudhi = False
    if human_ca is not None:
        human_tda = _compute_tda_fingerprint(human_ca)
        human_fingerprint = human_tda["fingerprint_vector"]
        human_has_gudhi = human_tda.get("gudhi_available") is True

    results: list[dict[str, Any]] = []
    for orth in orthologs[:8]:
        species = orth.get("species", "")
        orth_gene_id = orth.get("gene_id", "")
        raw_identity = orth.get("identity")
        identity = float(raw_identity) if raw_identity is not None else None
        dn_ds = orth.get("dn_ds")

        feature_distance: float | None = None
        tda_distance: float | None = None
        proxy_distance: float | None = None
        method = "sequence_identity"

        if orth_gene_id and human_fingerprint:
            orth_uniprot = await _resolve_ortholog_uniprot(ensembl, orth_gene_id)
            if orth_uniprot:
                orth_struct = await _fetch_af_structure(orth_uniprot)
                if orth_struct:
                    model_versions.append(orth_struct.get("model_version"))
                    orth_ca = _parse_ca_coords_from_pdb(orth_struct["pdb_text"])
                    if orth_ca.shape[0] > 0:
                        orth_tda = _compute_tda_fingerprint(orth_ca)
                        feature_distance = round(
                            _fingerprint_distance(
                                human_fingerprint, orth_tda["fingerprint_vector"]
                            ),
                            6,
                        )
                        if human_has_gudhi and orth_tda.get("gudhi_available") is True:
                            tda_distance = feature_distance
                            method = "tda_fingerprint"
                        else:
                            proxy_distance = feature_distance
                            method = "geometric_proxy"

        results.append(
            {
                "species": species,
                "ensembl_gene_id": orth_gene_id,
                "gene_name": orth.get("gene_name", ""),
                "orthology_type": orth.get("type", ""),
                "sequence_identity_pct": round(identity, 2) if identity is not None else None,
                "sequence_dissimilarity": (
                    round(1.0 - identity / 100.0, 4) if identity is not None else None
                ),
                "dn_ds_ratio": round(dn_ds, 4) if dn_ds is not None else None,
                "divergence_estimate": feature_distance,
                "divergence_method": method,
                "tda_fingerprint_distance": tda_distance,
                "geometric_proxy_distance": proxy_distance,
                "drift_interpretation": _drift_interpretation(feature_distance, dn_ds),
                "cross_reactivity_risk": _cross_reactivity_risk(identity, dn_ds),
            }
        )

    # Ensembl ordering is retained: the methods above have incompatible scales.
    tda_count = sum(1 for r in results if r["divergence_method"] == "tda_fingerprint")
    seq_count = sum(1 for r in results if r["divergence_method"] == "sequence_identity")
    proxy_count = sum(1 for r in results if r["divergence_method"] == "geometric_proxy")
    return {
        "gene_symbol": sym,
        "human_uniprot_id": human_uniprot,
        "species_compared": len(results),
        "tda_comparisons": tda_count,
        "sequence_identity_fallbacks": seq_count,
        "geometric_proxy_comparisons": proxy_count,
        "evolutionary_profile": results,
        "most_conserved_species": None,
        "most_diverged_species": None,
        "ranking_status": "not_computed_incomparable_metrics",
        "methodology_note": (
            "Sequence identity and exploratory structural distances are separately "
            "reported. GUDHI and geometric-proxy distances are not interchangeable. "
            "With GUDHI, a model longer than 500 residues is compared on 500 evenly "
            "spaced Cα atoms. "
            "No cross-method conservation ranking, biological functional inference, "
            "or antibody cross-reactivity risk assessment is supported."
        ),
        "provenance": _provenance(
            ensembl="current", alphafold_db=_afdb_version_label(model_versions)
        ),
    }


# ── Tool 5: Core-residue clusters (historical name: binding pocket geometry) ──

_DRUGGABILITY_NOT_ASSESSED = "NOT_ASSESSED"
"""Value of the legacy ``druggability_label``; ``assessment_status`` gives the reason."""

_POCKET_ASSESSMENT_STATUS = (
    "NOT_ASSESSED: binding pockets and druggability are not assessed. The clusters are a "
    "geometric grouping of core residues, not validated binding sites."
)

_POCKET_DEPRECATED_ALIASES = {
    "putative_pockets": "core_residue_clusters",
    "n_pockets_found": "n_core_residue_clusters",
    "pocket_id": "cluster_id",
    "druggability_index": "geometry_score",
    "druggability_components": "geometry_score_components",
}
"""Legacy output keys kept for existing clients, mapped to their accurate names."""


def _legacy_pocket_entry(cluster: dict[str, Any]) -> dict[str, Any]:
    """Return a cluster under the key names that releases up to 1.5.12 used.

    The measurements are the same numbers. The druggability class those
    releases attached to the score is replaced by ``NOT_ASSESSED``.
    """
    entry = {
        ("pocket_id" if key == "cluster_id" else key): value
        for key, value in cluster.items()
        if key not in ("geometry_score", "geometry_score_components")
    }
    entry["druggability_index"] = cluster["geometry_score"]
    entry["druggability_components"] = dict(cluster["geometry_score_components"])
    entry["druggability_label"] = _DRUGGABILITY_NOT_ASSESSED
    return entry


_POCKET_METHODOLOGY = (
    "Greedy geometric clustering of core Cα atoms. Core residues are those closer to the "
    "model centroid than the 60th percentile of centroid distances. In sequence order, "
    "each unassigned core residue seeds a cluster of the unassigned core residues within "
    "8 Å of it; a seed with fewer than min_pocket_residues such residues forms no "
    "cluster, and clusters with a mean pLDDT below 50 are discarded. No cavity, "
    "solvent-accessible surface or ligand is computed. geometry_score is the sum of four "
    "equally weighted 0 to 25 sub-scores: residue count (saturating at 12), radius of "
    "gyration (highest at 5 Å), mean pLDDT, and centroid offset (saturating at 20 Å; a "
    "larger offset means more peripheral geometry, not measured access or ligand "
    "binding). estimated_volume_angstrom3 is the volume of a sphere whose radius is the "
    "cluster's radius of gyration, not a cavity volume."
)

_POCKET_NOTE = (
    "Not a validated binding-pocket detector. In an internal audit of 19 AlphaFold "
    "models the top-ranked cluster was enriched for the PDBe-KB ligand-binding site in "
    "4 of the 18 proteins that had one, and every reported cluster scored 55 or more "
    "(LIMITATIONS.md L11). To locate binding sites, use a dedicated pocket detector such "
    "as fpocket or P2Rank and experimental evidence."
)


@mcp.tool(
    annotations={
        "title": "Cluster Core Residues by Geometry (Unvalidated Pocket Heuristic)",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def score_binding_pocket_geometry(
    params: BindingPocketInput,
) -> dict[str, Any]:
    """Cluster the core residues of an AlphaFold model by geometry.

    Not a validated binding-pocket detector; no druggability class is
    assigned. Cα atoms closer to the model centroid than the 60th
    percentile of centroid distances are grouped greedily: in sequence
    order, each unassigned core residue seeds a cluster of the unassigned
    core residues within 8 Å of it. A cluster is reported when it has at
    least ``min_pocket_residues`` members and a mean pLDDT of at least 50.
    No cavity, solvent-accessible surface or ligand is computed.

    Each of up to 10 clusters reports its residue numbers, mean pLDDT,
    radius of gyration, centroid offset from the model centroid, and
    ``geometry_score``: an uncalibrated 0 to 100 sum of four equally
    weighted sub-scores (residue count, radius of gyration, mean pLDDT,
    centroid offset) that only orders the clusters.
    ``estimated_volume_angstrom3`` is the volume of a sphere with the
    cluster's radius of gyration, not a cavity volume.

    Validation status: in an internal audit of 19 AlphaFold models the
    top-ranked cluster was enriched for the PDBe-KB ligand-binding site in
    4 of the 18 proteins that had one, and every reported cluster scored
    55 or more (LIMITATIONS.md L11). For existing clients the same
    clusters are also returned under the earlier names, as deprecated
    aliases: ``putative_pockets`` and ``n_pockets_found``, with entries
    keyed ``pocket_id``, ``druggability_index`` and
    ``druggability_components``; their ``druggability_label`` is
    ``NOT_ASSESSED``. To locate binding sites, use a dedicated pocket
    detector such as fpocket or P2Rank.

    Input fields:
        params.uniprot_id: UniProt accession of the AlphaFold model to
            cluster, e.g. 'P24941' (CDK2).
        params.min_pocket_residues: Minimum cluster size, 3 to 20
            (default 4).
    """
    uid = params.uniprot_id
    log = logger.bind(uniprot_id=uid, tool="score_binding_pocket_geometry")
    log.info("start")

    structure = await _fetch_af_structure(uid)
    if not structure:
        return _no_structure_response(uid, structure)

    pdb_text = structure["pdb_text"]
    ca_coords, residue_info = _parse_pdb_full(pdb_text)

    if ca_coords.shape[0] < 10:
        return {
            "uniprot_id": uid,
            "error": "Model too short for core-residue clustering (< 10 residues).",
        }

    clusters = _cluster_core_residues(
        ca_coords, residue_info, min_residues=params.min_pocket_residues
    )

    for cluster in clusters:
        cluster["geometry_score"] = _geometry_score(cluster)
        cluster["geometry_score_components"] = _geometry_score_components(cluster)

    clusters.sort(key=lambda c: c["geometry_score"], reverse=True)
    reported = clusters[:10]

    log.info("complete", n_clusters=len(clusters))
    return {
        "uniprot_id": uid,
        "n_residues": int(ca_coords.shape[0]),
        "core_residue_clusters": reported,
        "n_core_residue_clusters": len(clusters),
        "assessment_status": _POCKET_ASSESSMENT_STATUS,
        # Deprecated aliases: the same clusters in the entry shape of 1.5.12.
        "putative_pockets": [_legacy_pocket_entry(cluster) for cluster in reported],
        "n_pockets_found": len(clusters),
        "deprecated_aliases": dict(_POCKET_DEPRECATED_ALIASES),
        "methodology": _POCKET_METHODOLOGY,
        "note": _POCKET_NOTE,
        "provenance": _provenance(
            alphafold_db=_afdb_version_label([structure.get("model_version")]),
            method="geometric-clustering",
        ),
    }


# ── Tool 6: Intrinsic disorder map ───────────────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Detect Intrinsically Disordered Regions",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def detect_intrinsically_disordered(
    params: UniProtInput,
) -> dict[str, Any]:
    """Flag low-confidence modeled regions as intrinsic-disorder candidates.

    Reads per-residue AlphaFold pLDDT from PDB C-alpha records and groups
    contiguous runs below 50. Low pLDDT may reflect intrinsic disorder,
    missing binding partners, alternate conformations, or model uncertainty;
    it is NOT independent evidence that a region is disordered.

    Returns model-local residue indices, observed PDB chain/residue identifiers,
    and positional descriptions of low-pLDDT runs. These labels describe
    model geometry, not validated linkers, tails, disorder or function.
    Legacy idr_fraction and disordered_residue_count remain deprecated numeric
    aliases of low-pLDDT measurements, NOT validated intrinsic-disorder assays.
    Prefer low_plddt_* fields for scientific interpretation.
    PDB numbering is not mapped to full-length UniProt via SIFTS here.

    This implementation is a reproducible screening heuristic, not a validated
    disorder predictor, biomolecular mechanism classifier, or clinical result.
    For background on intrinsic disorder, see Ruff & Pappu (2021),
    J Mol Biol. 433:167208; that paper does not validate these cutoffs or code.

    Input fields:
        params.uniprot_id: UniProt accession.
    """
    uid = params.uniprot_id
    result = await _fetch_af_plddt(uid)

    if not result:
        return _no_structure_response(uid, result)

    # We can reconstruct per-residue pLDDT from PDB B-factor column
    structure = await _fetch_af_structure(uid)
    if not structure:
        return _no_structure_response(uid, structure)

    residue_records = _extract_plddt_residue_records(structure["pdb_text"])
    per_residue_plddt = [record[3] for record in residue_records]
    positions = [(record[0], record[1], record[2]) for record in residue_records]
    idr_segments = _detect_idr_segments(per_residue_plddt, positions=positions)
    for segment in idr_segments:
        first = residue_records[segment["start"] - 1]
        last = residue_records[segment["end"] - 1]
        segment["pdb_chain"] = first[0]
        segment["pdb_residue_start"] = first[1]
        segment["pdb_residue_end"] = last[1]
        segment["pdb_insertion_code_start"] = first[2]
        segment["pdb_insertion_code_end"] = last[2]

    total_residues = len(per_residue_plddt)
    if total_residues == 0:
        return {
            "uniprot_id": uid,
            "sequence_length": 0,
            "error": "No valid C-alpha residue confidence records in the selected model.",
        }
    low_plddt_count = sum(1 for p in per_residue_plddt if p < 50)
    low_plddt_fraction = low_plddt_count / total_residues

    return {
        "uniprot_id": uid,
        "sequence_length": total_residues,
        "model_entity_id": result.get("model_entity_id"),
        "model_uniprot_accession": result.get("model_uniprot_accession"),
        "verified_displayed_isoform": result.get("verified_displayed_isoform"),
        "sequence_start": result.get("sequence_start"),
        "sequence_end": result.get("sequence_end"),
        "coordinate_system": "model_C_alpha_order_1_based",
        "residue_mapping_note": (
            "Segment start/end are ordinal indices of observed C-alpha residues "
            "in the selected model; PDB residue identifiers are reported separately. "
            "Neither index is a verified UniProt or PDB/SIFTS residue mapping. "
            "Terminal and whole-protein labels only describe the modeled segment."
        ),
        # Deprecated numeric aliases of low-pLDDT, not observed disorder.
        "idr_fraction": round(low_plddt_fraction, 4),
        "disordered_residue_count": low_plddt_count,
        "is_idr_protein": None,
        "idr_segments": idr_segments,
        "idr_classification": "NOT_ASSESSED: model confidence is not an IDR assay.",
        "low_plddt_cutoff": 50.0,
        "low_plddt_fraction": round(low_plddt_fraction, 4),
        "low_plddt_residue_count": low_plddt_count,
        "low_plddt_segments": idr_segments,
        "segment_evidence_note": (
            "Segments are modeled C-alpha runs with pLDDT < 50. "
            "Their type is positional only; they are not proven intrinsically "
            "disordered residues, linkers or biomolecular mechanisms."
        ),
        "clinical_implications": None,
        "drug_target_potential": None,
        "reference": "Ruff KM & Pappu RV (2021) J Mol Biol 433:167208. doi:10.1016/j.jmb.2021.167208",
        "provenance": _provenance(
            alphafold_db=_afdb_version_label(
                [result.get("model_version"), structure.get("model_version")]
            ),
            plddt_cutoff="50",
        ),
    }


# ── Tool 7: Retrieve AlphaFold structure ─────────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Retrieve AlphaFold Protein Structure",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_protein_structure(
    params: StructureRetrievalInput,
) -> dict[str, Any]:
    """Retrieve a protein's AlphaFold model: metadata, download URLs, optional coordinates.

    The single entry point for getting the predicted structure itself. Returns the
    AlphaFold DB entry metadata — entry ID, model version and creation date,
    organism, gene, UniProt description, the amino-acid sequence and its length, and
    the model's mean pLDDT — plus stable download URLs for the PDB and mmCIF
    coordinate files, the PAE matrix, and the AlphaMissense substitutions
    CSV. The PAE image URL is only present in legacy API responses. Set ``include_coordinates`` to embed the full PDB coordinate text directly.

    Use the sibling structure tools for *interpretation* rather than retrieval, so
    their scopes don't overlap: ``analyze_structural_confidence`` for a pLDDT/PAE
    confidence read, ``score_binding_pocket_geometry`` for geometric clusters
    of core residues (not validated pockets), ``compute_topology_fingerprint``
    for an exploratory Cα summary vector, and
    ``detect_intrinsically_disordered`` for low-pLDDT intervals. This tool hands you the
    structure and its handles; it does not score or interpret the model.

    Returns ``structure_available: false`` when no model was retrieved, and
    ``retrieval_status`` says why. ``no_prediction_returned``: AlphaFold DB answered
    without a model for the accession, an expected coverage gap. ``request_failed``:
    the request was blocked (offline mode) or failed, which is not evidence that no
    prediction exists.

    Input fields:
        params.uniprot_id: UniProt accession to retrieve, e.g. 'P38398' (BRCA1).
        params.include_coordinates: Embed the full PDB coordinate text (large);
            default false returns metadata and download URLs only.
    """
    uid = params.uniprot_id
    log = logger.bind(uniprot_id=uid, tool="get_protein_structure")
    log.info("start")

    failed: _RequestFailed | None = None
    try:
        meta = await _alphafold().get_prediction(uid)
    except (UniProtVerificationError, AlphaFoldPredictionSchemaError):
        raise
    except Exception as exc:
        log.warning("prediction.failed", exc=str(exc))
        meta = {}
        failed = _unretrieved(exc)

    if not isinstance(meta, dict) or not _prediction_model_id(meta):
        return _no_structure_response(uid, failed)

    sequence = _prediction_sequence(meta)
    global_metric, plddt_status = validated_plddt(meta.get("globalMetricValue"))
    result: dict[str, Any] = {
        "uniprot_id": uid,
        "structure_available": True,
        "entry_id": _prediction_model_id(meta),
        "model_uniprot_accession": meta.get("uniprotAccession"),
        "verified_displayed_isoform": meta.get("_sovereign_verified_isoform"),
        "gene": meta.get("gene", ""),
        "organism": meta.get("organismScientificName", ""),
        "taxonomy_id": meta.get("taxId"),
        "description": meta.get("uniprotDescription", ""),
        "sequence_length": len(sequence),
        "sequence": sequence,
        "mean_plddt": round(global_metric, 2) if global_metric is not None else None,
        "plddt_status": plddt_status,
        "model_version": meta.get("latestVersion"),
        "model_created": meta.get("modelCreatedDate", ""),
        "model_chain_id": meta.get("chainId", ""),
        "sequence_start": meta.get("sequenceStart", meta.get("uniprotStart")),
        "sequence_end": meta.get("sequenceEnd", meta.get("uniprotEnd")),
        "residue_mapping_status": (
            "Model sequence interval from AlphaFold metadata; no experimentally "
            "verified PDB/SIFTS residue mapping performed."
        ),
        "file_urls": {
            "pdb": meta.get("pdbUrl", ""),
            "cif": meta.get("cifUrl", ""),
            "pae_image": meta.get("paeImageUrl", ""),
            "pae_doc": meta.get("paeDocUrl", ""),
            "alphamissense_annotations": meta.get("amAnnotationsUrl", ""),
        },
        "note": (
            "AlphaFold models are predicted, not experimental, and per-residue pLDDT "
            "confidence varies along the chain — see analyze_structural_confidence for a "
            "confidence read. Fetch the coordinate files from file_urls, or pass "
            "include_coordinates=true to embed the PDB text in this response."
        ),
        "provenance": _provenance(
            alphafold_db=_afdb_version_label([_prediction_version(meta)]),
            source="prediction-metadata",
        ),
    }

    if params.include_coordinates:
        structure = await _fetch_af_structure(uid)
        result["coordinates_pdb"] = structure["pdb_text"] if structure else ""

    log.info("complete", entry_id=result["entry_id"])
    return result


# ── Core-residue cluster helpers ──────────────────────────────────────────────


def _parse_pdb_full(
    pdb_text: str,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Parse Cα coordinates + residue metadata including B-factor (pLDDT)."""
    coords: list[list[float]] = []
    residues: list[dict[str, Any]] = []
    for line in pdb_text.splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            try:
                coordinate = [float(line[30:38]), float(line[38:46]), float(line[46:54])]
                residue = {
                    "chain": line[21].strip(),
                    "resnum": int(line[22:26].strip()),
                    "resname": line[17:20].strip(),
                    "plddt": float(line[60:66].strip()),  # B-factor stores pLDDT in AF
                }
            except (ValueError, IndexError):
                continue
            # Only append a complete coordinate/residue pair, never just one.
            coords.append(coordinate)
            residues.append(residue)
    return np.array(coords, dtype=float), residues


def _cluster_core_residues(
    ca_coords: np.ndarray,
    residue_info: list[dict[str, Any]],
    min_residues: int = 4,
) -> list[dict[str, Any]]:
    """Group the core Cα atoms of a model into greedy distance clusters.

    Core residues are those closer to the model centroid than the 60th
    percentile of centroid distances. No surface, concavity or cavity is
    computed: a cluster is a compact group of core residues, not a detected
    pocket.
    """
    n = len(ca_coords)
    if n < min_residues:
        return []

    centroid = ca_coords.mean(axis=0)
    dist_from_centroid = np.linalg.norm(ca_coords - centroid, axis=1)

    # Core: residues nearer the centroid than the 60th percentile of distances.
    core_mask = dist_from_centroid < np.percentile(dist_from_centroid, 60)
    core_coords = ca_coords[core_mask]
    core_indices = np.where(core_mask)[0]

    if len(core_coords) < min_residues:
        return []

    # Greedy clustering in sequence order: each unassigned core residue seeds a
    # cluster of the unassigned core residues within 8 Å of it.
    assigned = [False] * len(core_coords)
    clusters: list[dict[str, Any]] = []

    for seed_idx in range(len(core_coords)):
        if assigned[seed_idx]:
            continue
        dists = np.linalg.norm(core_coords - core_coords[seed_idx], axis=1)
        neighbour_mask = (dists < 8.0) & ~np.array(assigned)
        if neighbour_mask.sum() < min_residues:
            continue

        member_indices = np.where(neighbour_mask)[0]
        for m in member_indices:
            assigned[m] = True

        member_ca = core_coords[member_indices]
        global_indices = core_indices[member_indices]
        member_residues = [residue_info[i] for i in global_indices if i < len(residue_info)]
        member_plddts = [r["plddt"] for r in member_residues]
        mean_plddt = float(np.mean(member_plddts)) if member_plddts else 0.0

        # Discard clusters of low model confidence; their members stay assigned.
        if mean_plddt < 50:
            continue

        cluster_centroid = member_ca.mean(axis=0)
        rog = float(np.sqrt(np.mean(np.sum((member_ca - cluster_centroid) ** 2, axis=1))))
        # Distance of the cluster centroid from the model centroid. Larger means
        # more peripheral geometry; it measures neither solvent access nor burial.
        centroid_offset = float(np.linalg.norm(cluster_centroid - centroid))

        clusters.append(
            {
                "cluster_id": len(clusters) + 1,
                "n_residues": len(member_indices),
                "residue_numbers": sorted({r["resnum"] for r in member_residues}),
                "residue_names": sorted({r["resname"] for r in member_residues}),
                "mean_plddt": round(mean_plddt, 2),
                "radius_of_gyration_angstrom": round(rog, 2),
                "centroid_offset_angstrom": round(centroid_offset, 2),
                # Volume of a sphere of radius ``rog``; not a cavity volume.
                "estimated_volume_angstrom3": round((4 / 3) * math.pi * rog**3, 1),
            }
        )

    return clusters


# ── Cluster geometry score ───────────────────────────────────────────────────
# The geometry score is the sum of four equally weighted sub-scores, each in
# ``[0, POCKET_SUBSCORE_MAX]`` (so the score runs 0–100). The constants below
# are uncalibrated geometry priors, not a validated pocket or druggability
# model: the score only orders clusters. See ``LIMITATIONS.md`` L11.
POCKET_SUBSCORE_MAX = 25.0
POCKET_IDEAL_RESIDUES = 12.0
"""Residue count at/above which the size sub-score saturates."""
POCKET_IDEAL_ROG_ANGSTROM = 5.0
"""Radius of gyration (Å) scoring peak compactness."""
POCKET_ROG_TOLERANCE_ANGSTROM = 5.0
"""Å of radius-of-gyration deviation that drives the compactness sub-score to 0."""
POCKET_CENTROID_OFFSET_SATURATION_ANGSTROM = 20.0
"""Centroid offset (Å) at/above which the offset sub-score saturates.

The sub-score rises with the cluster's offset from the model centre, so among
the core residues it ranks more peripheral clusters higher. This is an
uncalibrated prior: it measures neither solvent access nor burial, and it does
not indicate ligand binding.
"""


def _pocket_subscores(pocket: dict[str, Any]) -> dict[str, float]:
    """Return the four unrounded 0–25 geometry sub-scores for a cluster."""
    n_res: int = pocket.get("n_residues", 0)
    rog: float = pocket.get("radius_of_gyration_angstrom", 0.0)
    plddt: float = pocket.get("mean_plddt", 0.0)
    centroid_offset: float = pocket.get("centroid_offset_angstrom", 0.0)

    # Uncalibrated geometry prior: size, compactness, model confidence, offset.
    # None of these establishes a real cavity, solvent access or ligand binding.
    return {
        "residue_count": min(1.0, n_res / POCKET_IDEAL_RESIDUES) * POCKET_SUBSCORE_MAX,
        "radius_of_gyration": max(
            0.0, 1.0 - abs(rog - POCKET_IDEAL_ROG_ANGSTROM) / POCKET_ROG_TOLERANCE_ANGSTROM
        )
        * POCKET_SUBSCORE_MAX,
        "mean_plddt": (plddt / 100.0) * POCKET_SUBSCORE_MAX,
        "centroid_offset": min(1.0, centroid_offset / POCKET_CENTROID_OFFSET_SATURATION_ANGSTROM)
        * POCKET_SUBSCORE_MAX,
    }


def _geometry_score(cluster: dict[str, Any]) -> float:
    """Uncalibrated 0–100 geometry score of a cluster (sum of the sub-scores)."""
    return round(sum(_pocket_subscores(cluster).values()), 1)


def _geometry_score_components(cluster: dict[str, Any]) -> dict[str, float]:
    """Per-sub-score breakdown (rounded) so the 0–100 score is auditable."""
    return {name: round(value, 2) for name, value in _pocket_subscores(cluster).items()}


def _extract_plddt_residue_records(
    pdb_text: str,
) -> list[tuple[str, int, str, float]]:
    """Extract chain, author residue number, insertion code and pLDDT.

    No UniProt coordinate correspondence is inferred from PDB numbering.
    Alternative conformers are collapsed to blank/A for deterministic output.
    """
    records: list[tuple[str, int, str, float]] = []
    seen: set[tuple[str, int, str]] = set()
    for line in pdb_text.splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            if line[16].strip() not in ("", "A"):
                continue
            try:
                chain = line[21].strip()
                resnum = int(line[22:26].strip())
                insertion_code = line[26].strip()
                confidence = float(line[60:66].strip())
            except (ValueError, IndexError):
                continue
            if not math.isfinite(confidence) or not 0 <= confidence <= 100:
                continue
            key = (chain, resnum, insertion_code)
            if key not in seen:
                seen.add(key)
                records.append((chain, resnum, insertion_code, confidence))
    return records


def _extract_plddt_from_pdb(pdb_text: str) -> list[float]:
    """Project validated per-residue pLDDT values in model order."""
    return [record[3] for record in _extract_plddt_residue_records(pdb_text)]


def _detect_idr_segments(
    per_residue_plddt: list[float],
    cutoff: float = 50.0,
    min_length: int = 5,
    positions: list[tuple[str, int, str]] | None = None,
) -> list[dict[str, Any]]:
    """Find low-confidence runs without bridging missing PDB residues/chains.

    Returned start/end indices remain 1-based positions in model C-alpha
    order for backwards compatibility, not full-length UniProt positions.
    """
    segments: list[dict[str, Any]] = []
    n = len(per_residue_plddt)
    if positions is not None and len(positions) != n:
        raise ValueError("Number of PDB positions must match pLDDT values")
    in_idr = False
    start = 0

    for i, p in enumerate(per_residue_plddt):
        if positions is not None and i > 0:
            prev, cur = positions[i - 1], positions[i]
            gap = cur[0] != prev[0] or cur[1] != prev[1] + 1 or bool(prev[2]) or bool(cur[2])
            if gap and in_idr:
                length = i - start
                if length >= min_length:
                    mean_p = float(sum(per_residue_plddt[start:i]) / length)
                    segments.append(_classify_idr_segment(start + 1, i, length, mean_p, n))
                in_idr = False
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
    if start == 1 and end == total:
        kind = "Entire modeled span: low confidence"
    elif start == 1:
        kind = "Model N-terminal low-confidence region"
    elif end == total:
        kind = "Model C-terminal low-confidence region"
    elif length < 20:
        kind = "Short internal low-confidence region"
    else:
        kind = "Long internal low-confidence region"
    return {
        "start": start,
        "end": end,
        "length": length,
        "mean_plddt": round(mean_plddt, 2),
        "segment_type": kind,
    }


# ── pLDDT helpers ─────────────────────────────────────────────────────────────


def _plddt_tier(plddt: float | None) -> str:
    plddt, _ = validated_plddt(plddt)
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
        "VERY_HIGH": "pLDDT ≥ 90: high model-local confidence; ligand binding is not assessed.",
        "HIGH": "pLDDT 70–90: high model-local confidence; pockets require independent validation.",
        "LOW": "pLDDT 50–70: low model confidence; disorder or function is not established.",
        "VERY_LOW": "pLDDT < 50: very low model confidence; this does not establish disorder.",
        "UNKNOWN": "AlphaFold confidence data not available.",
    }.get(tier, "Unknown.")


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
    except Exception as exc:
        logger.debug(
            "ensembl.xref_uniprot.empty",
            exc=str(exc),
            ensembl_gene_id=ensembl_gene_id,
        )
    return ""


# ── TDA interpretation ────────────────────────────────────────────────────────


def _interpret_tda(tda: dict[str, Any]) -> str:
    betti = tda.get("betti_numbers", [])
    if not betti:
        return "Topology unavailable."
    scale = "15-Å Rips filtration" if tda.get("gudhi_available", True) else "4-Å contact graph"
    parts = [f"β₀={betti[0]} connected components at {scale}"]
    if len(betti) > 1 and betti[1] is not None:
        parts.append(f"β₁={betti[1]} one-dimensional classes at filtration endpoint")
    else:
        parts.append("β₁ not computed")
    parts.append("β₂ not computed; no inference about protein cavities")
    text = "; ".join(parts) + "."
    if tda.get("subsampled"):
        text += (
            f" Computed on {tda.get('n_residues_used')} evenly spaced Cα atoms of "
            f"{tda.get('n_residues_total')}; the values describe that subsample."
        )
    return text


# ── Evolutionary drift helpers ────────────────────────────────────────────────


def _drift_interpretation(drift: float | None, dn_ds: float | None) -> str:
    if drift is None:
        return "Feature-vector distance unavailable; sequence identity is reported separately."
    return (
        "Exploratory feature-vector distance only; no validated inference about "
        "evolutionary conservation, drug binding, or biological function."
    )


def _cross_reactivity_risk(identity: float | None, dn_ds: float | None) -> str:
    return (
        "NOT ASSESSED — whole-protein sequence identity and topology are "
        "insufficient to infer antibody cross-reactivity; requires epitope evidence."
    )


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
        # Feature-vector distance has no calibrated biological similarity scale.
        "similarity_pct": None,
    }
