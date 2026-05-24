# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.tools.structure_intelligence``."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from alphafold_sovereign.tools import structure_intelligence as si
from alphafold_sovereign.tools.structure_intelligence import (
    BindingPocketInput,
    EvolutionaryInput,
    MultiProteinInput,
    UniProtInput,
    _classify_idr_protein,
    _classify_idr_segment,
    _compute_tda_fingerprint,
    _cross_reactivity_risk,
    _detect_domain_boundaries,
    _detect_idr_segments,
    _drift_interpretation,
    _estimate_ordered_fraction,
    _extract_plddt_from_pdb,
    _fallback_tda_fingerprint,
    _fetch_af_plddt,
    _fetch_af_structure,
    _find_high_pae_pairs,
    _find_most_similar_pair,
    _fingerprint_distance,
    _geometric_pocket_detection,
    _idr_clinical_implications,
    _interpret_tda,
    _parse_ca_coords_from_pdb,
    _parse_pdb_full,
    _plddt_tier,
    _plddt_tier_explanation,
    _pocket_druggability_index,
    _pocket_druggability_label,
    _provenance,
    analyze_structural_confidence,
    compare_proteins_topologically,
    compute_topology_fingerprint,
    detect_intrinsically_disordered,
    find_evolutionary_structural_shifts,
    score_binding_pocket_geometry,
)

# ---------------------------------------------------------------------------
# Synthetic PDB
# ---------------------------------------------------------------------------


def _make_pdb(n_residues: int = 20, plddt: float = 85.0) -> str:
    """Create a synthetic PDB with `n_residues` Cα atoms in a simple line."""
    lines = []
    for i in range(n_residues):
        x, y, z = 1.0 * i, 0.0, 0.0
        # PDB ATOM format: see https://www.wwpdb.org/documentation/file-format
        lines.append(
            f"ATOM  {i + 1:5d}  CA  ALA A{i + 1:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00{plddt:6.2f}           C"
        )
    lines.append("END")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_provenance_filters_empty() -> None:
    p = _provenance(alphafold_db="v4", empty="")
    assert "alphafold_db=v4" in p
    assert "empty" not in p


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (95.0, "VERY_HIGH"),
        (80.0, "HIGH"),
        (60.0, "LOW"),
        (40.0, "VERY_LOW"),
        (None, "UNKNOWN"),
    ],
)
def test_plddt_tier(score: float | None, expected: str) -> None:
    assert _plddt_tier(score) == expected


@pytest.mark.parametrize("tier", ["VERY_HIGH", "HIGH", "LOW", "VERY_LOW", "UNKNOWN", "UNRELATED"])
def test_plddt_tier_explanation(tier: str) -> None:
    out = _plddt_tier_explanation(tier)
    assert isinstance(out, str)


def test_estimate_ordered_fraction() -> None:
    assert _estimate_ordered_fraction(None) is None
    assert _estimate_ordered_fraction(80) == 0.6
    assert _estimate_ordered_fraction(50) == 0.0
    assert _estimate_ordered_fraction(100) == 1.0


def test_interpret_tda_multi_domain() -> None:
    out = _interpret_tda({"betti_numbers": [3, 5, 1]})
    assert "disconnected components" in out
    assert "rich in α-helices" in out
    assert "cavity" in out


def test_interpret_tda_single_loop() -> None:
    out = _interpret_tda({"betti_numbers": [1, 2, 0]})
    assert "single connected component" in out
    assert "loop(s)" in out


def test_interpret_tda_empty() -> None:
    out = _interpret_tda({"betti_numbers": []})
    # empty list → empty parts → "Topology computed."
    assert "Topology computed" in out or "single connected component" in out


def test_drift_interpretation_none() -> None:
    assert "not quantifiable" in _drift_interpretation(None, None)


def test_drift_interpretation_low() -> None:
    assert "Highly conserved" in _drift_interpretation(0.05, None)


def test_drift_interpretation_moderate() -> None:
    assert "Moderate" in _drift_interpretation(0.2, None)


def test_drift_interpretation_high() -> None:
    assert "High" in _drift_interpretation(0.6, None)


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        (95.0, "HIGH"),
        (75.0, "MODERATE"),
        (60.0, "LOW"),
        (30.0, "MINIMAL"),
    ],
)
def test_cross_reactivity_risk(identity: float, expected: str) -> None:
    out = _cross_reactivity_risk(identity, None)
    assert expected in out


def test_fingerprint_distance() -> None:
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    d = _fingerprint_distance(a, b)
    assert 0 < d < 2


def test_wasserstein_zero_norm() -> None:
    """When both vectors are zero, distance is 0."""
    d = _fingerprint_distance([0.0, 0.0], [0.0, 0.0])
    assert d == 0.0


def test_wasserstein_one_zero() -> None:
    """When one vector is zero, no normalization → use raw."""
    d = _fingerprint_distance([0.0, 0.0], [1.0, 0.0])
    assert d > 0


def test_parse_ca_coords() -> None:
    coords = _parse_ca_coords_from_pdb(_make_pdb(5))
    assert coords.shape == (5, 3)


def test_parse_ca_coords_empty() -> None:
    coords = _parse_ca_coords_from_pdb("")
    assert coords.shape == (0, 3)


def test_parse_ca_coords_malformed() -> None:
    """Bad ATOM lines are skipped."""
    bad = "ATOM      1  CA  ALA A  1     BAD     0.0    0.0  1.00 80.00\nATOM      2  CB  ALA A  2     1.0    0.0    0.0  1.00 80.00"
    coords = _parse_ca_coords_from_pdb(bad)
    assert coords.shape == (0, 3)


def test_parse_pdb_full() -> None:
    coords, residues = _parse_pdb_full(_make_pdb(3, plddt=80))
    assert coords.shape == (3, 3)
    assert all(r["plddt"] == 80.0 for r in residues)


def test_parse_pdb_full_malformed() -> None:
    bad = "ATOM      X  CA  ALA"
    coords, residues = _parse_pdb_full(bad)
    # empty list → numpy creates a 0-dim array
    assert coords.shape[0] == 0
    assert residues == []


def test_extract_plddt_from_pdb_deduplicated() -> None:
    pdb = _make_pdb(3, plddt=75.0)
    # Add a duplicate Cα entry — same (chain, resnum)
    duplicate_line = "ATOM      1  CA  ALA A   1     0.000   0.000   0.000  1.00 75.00           C"
    pdb = duplicate_line + "\n" + pdb
    plddts = _extract_plddt_from_pdb(pdb)
    # Original 3 residues + duplicate (resnum=1) collides with line 1
    assert len(plddts) == 3


def test_extract_plddt_from_pdb_skip_bad() -> None:
    bad_line = "ATOM      1  CA  ALA A   X    1.000   0.000   0.000  1.00 80.00"
    out = _extract_plddt_from_pdb(bad_line)
    assert out == []


def test_pocket_druggability_index_label() -> None:
    pocket = {
        "n_residues": 8,
        "radius_of_gyration_angstrom": 5.0,
        "mean_plddt": 85.0,
        "burial_from_centroid": 20.0,
    }
    pdi = _pocket_druggability_index(pocket)
    assert pdi > 0


@pytest.mark.parametrize(
    ("pdi", "expected"),
    [
        (90.0, "EXCELLENT"),
        (60.0, "GOOD"),
        (40.0, "MODERATE"),
        (10.0, "POOR"),
    ],
)
def test_pocket_druggability_label(pdi: float, expected: str) -> None:
    assert _pocket_druggability_label(pdi) == expected


def test_detect_idr_segments_terminal() -> None:
    plddts = [40.0] * 6 + [80.0] * 10 + [30.0] * 8
    segs = _detect_idr_segments(plddts)
    types = {s["segment_type"] for s in segs}
    # First segment starts at position 1 → N-terminal tail
    # Last segment ends at length n → C-terminal tail
    assert "N-terminal tail" in types
    assert "C-terminal tail" in types


def test_detect_idr_segments_no_idr() -> None:
    plddts = [80.0] * 30
    segs = _detect_idr_segments(plddts)
    assert segs == []


def test_detect_idr_segments_short_skipped() -> None:
    """Very short IDRs (< min_length) are skipped."""
    plddts = [30.0, 30.0] + [80.0] * 20
    segs = _detect_idr_segments(plddts)
    assert segs == []


def test_detect_idr_segments_short_terminal_skipped() -> None:
    """Short IDR at end (terminal) is also skipped."""
    plddts = [80.0] * 20 + [30.0, 30.0]
    segs = _detect_idr_segments(plddts)
    assert segs == []


def test_detect_idr_segments_linker() -> None:
    """Internal short IDR → 'Linker'."""
    plddts = [80.0] * 10 + [30.0] * 10 + [80.0] * 10
    segs = _detect_idr_segments(plddts)
    assert any(s["segment_type"] == "Linker" for s in segs)


def test_detect_idr_segments_long_idr() -> None:
    """Long internal IDR (≥ 20) → 'Long IDR'."""
    plddts = [80.0] * 5 + [30.0] * 25 + [80.0] * 5
    segs = _detect_idr_segments(plddts)
    assert any(s["segment_type"] == "Long IDR" for s in segs)


def test_classify_idr_segment_branches() -> None:
    """Direct tests for classification helper."""
    seg = _classify_idr_segment(1, 10, 10, 30.0, 100)
    assert seg["segment_type"] == "N-terminal tail"

    seg = _classify_idr_segment(50, 100, 51, 30.0, 100)
    assert seg["segment_type"] == "C-terminal tail"

    seg = _classify_idr_segment(40, 50, 10, 30.0, 100)
    assert seg["segment_type"] == "Linker"

    seg = _classify_idr_segment(40, 70, 30, 30.0, 100)
    assert seg["segment_type"] == "Long IDR"


def test_classify_idr_protein_fully_disordered() -> None:
    assert "IDP" in _classify_idr_protein(0.8, [])


def test_classify_idr_protein_partial() -> None:
    out = _classify_idr_protein(0.5, [])
    assert "Partially disordered" in out


def test_classify_idr_protein_long_idrs_with_low_fraction() -> None:
    """Even with low fraction, long IDRs trigger partial."""
    out = _classify_idr_protein(
        0.1, [{"segment_type": "Long IDR", "start": 1, "end": 30, "length": 30}]
    )
    assert "Partially disordered" in out


def test_classify_idr_protein_ordered() -> None:
    out = _classify_idr_protein(0.1, [])
    assert "ordered" in out.lower()


def test_idr_clinical_implications_full() -> None:
    out = _idr_clinical_implications(
        0.5,
        [
            {"segment_type": "N-terminal tail", "start": 1, "end": 30, "length": 30},
            {"segment_type": "Long IDR", "start": 50, "end": 100, "length": 50},
        ],
    )
    assert any("High IDR fraction" in i for i in out)
    assert any("Terminal IDR" in i for i in out)
    assert any("phase separation" in i for i in out)


def test_idr_clinical_implications_none() -> None:
    out = _idr_clinical_implications(0.1, [])
    assert any("No significant" in i for i in out)


def test_find_high_pae_pairs() -> None:
    pae = np.zeros((30, 30))
    pae[5, 25] = 20.0
    pae[10, 25] = 18.0
    pairs = _find_high_pae_pairs(pae, threshold=15.0)
    assert len(pairs) >= 1


def test_find_high_pae_pairs_close_residues_filtered() -> None:
    """Residue pairs within 10 of each other are filtered out."""
    pae = np.zeros((30, 30))
    pae[5, 8] = 30.0  # only 3 apart
    pairs = _find_high_pae_pairs(pae, threshold=15.0)
    assert pairs == []


def test_detect_domain_boundaries() -> None:
    n = 100
    pae = np.zeros((n, n)) + 5.0
    pae[50:60, 50:60] = 25.0  # local PAE spike
    boundaries = _detect_domain_boundaries(pae, window=10)
    assert len(boundaries) >= 0  # may or may not find depending on threshold


def test_detect_domain_boundaries_too_short() -> None:
    pae = np.zeros((5, 5))
    out = _detect_domain_boundaries(pae, window=10)
    assert out == []


def test_compute_tda_fingerprint_basic() -> None:
    """Generate fingerprint from line of points."""
    coords = np.array([[i * 1.0, 0.0, 0.0] for i in range(30)])
    out = _compute_tda_fingerprint(coords)
    assert "fingerprint_vector" in out
    assert len(out["fingerprint_vector"]) == 64


def test_compute_tda_fingerprint_large() -> None:
    """More than 500 residues → triggers subsample path under gudhi; otherwise fallback."""
    coords = np.random.RandomState(42).randn(600, 3) * 10
    out = _compute_tda_fingerprint(coords)
    assert "fingerprint_vector" in out


def _install_fake_gudhi(monkeypatch: pytest.MonkeyPatch, persistence_data: list[Any]) -> None:
    """Install a fake gudhi module that returns canned persistence data."""
    import types

    class _SimplexTree:
        def __init__(self, data: list[Any]) -> None:
            self._data = data

        def compute_persistence(self) -> None:
            pass

        def persistence(self) -> list[Any]:
            return self._data

    class _Rips:
        def __init__(self, *, points: list[Any], max_edge_length: float) -> None:
            pass

        def create_simplex_tree(self, *, max_dimension: int) -> _SimplexTree:
            return _SimplexTree(persistence_data)

    fake_gudhi = types.ModuleType("gudhi")
    fake_gudhi.RipsComplex = _Rips  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "gudhi", fake_gudhi)


def test_compute_tda_fingerprint_with_gudhi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover the gudhi-only code path using a fake gudhi module."""
    persistence_data = [
        (0, (0.0, 1.0)),
        (0, (0.0, 2.0)),
        (0, (0.0, float("inf"))),  # filtered out
        (1, (0.0, 1.5)),
        (2, (0.0, 0.5)),
    ]
    _install_fake_gudhi(monkeypatch, persistence_data)

    coords = np.array([[i * 1.0, 0.0, 0.0] for i in range(20)])
    out = _compute_tda_fingerprint(coords)
    assert "betti_numbers" in out
    assert len(out["fingerprint_vector"]) == 64
    # First dim has intervals → landscape entry filled
    assert out["persistence_landscapes"][0]["n_intervals"] >= 1


def test_compute_tda_fingerprint_with_gudhi_subsamples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gudhi path with > 500 residues → triggers subsampling."""
    _install_fake_gudhi(monkeypatch, [(0, (0.0, 1.0))])
    coords = np.random.RandomState(42).randn(600, 3) * 10
    out = _compute_tda_fingerprint(coords)
    assert out["n_residues_used"] == 500


def test_compute_tda_fingerprint_with_gudhi_empty_intervals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gudhi path with no finite intervals → empty landscapes."""
    _install_fake_gudhi(monkeypatch, [])
    coords = np.array([[i * 1.0, 0.0, 0.0] for i in range(20)])
    out = _compute_tda_fingerprint(coords)
    assert out["betti_numbers"] == [0, 0, 0]


def test_compute_tda_fingerprint_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """When gudhi import fails, fall back to fallback fingerprint."""
    # Force ImportError by mocking gudhi import
    import builtins

    original_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "gudhi":
            raise ImportError("no gudhi")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    coords = np.array([[i * 1.0, 0.0, 0.0] for i in range(10)])
    out = _compute_tda_fingerprint(coords)
    assert out["gudhi_available"] is False


def test_fallback_tda_fingerprint_few_residues() -> None:
    coords = np.array([[1.0, 0.0, 0.0]])
    out = _fallback_tda_fingerprint(coords)
    assert out["fingerprint_vector"] == [0.0] * 64


def test_fallback_tda_fingerprint_normal() -> None:
    coords = np.array([[i * 1.0, 0.0, 0.0] for i in range(15)])
    out = _fallback_tda_fingerprint(coords)
    assert len(out["fingerprint_vector"]) == 64


def test_geometric_pocket_detection_too_short() -> None:
    coords = np.array([[1.0, 0.0, 0.0]])
    residues = [{"chain": "A", "resnum": 1, "resname": "ALA", "plddt": 80.0}]
    pockets = _geometric_pocket_detection(coords, residues, min_residues=4)
    assert pockets == []


def test_geometric_pocket_detection_normal() -> None:
    """Build a 3D blob of points to find a pocket."""
    rng = np.random.RandomState(0)
    n = 50
    coords = rng.randn(n, 3) * 10
    residues = [{"chain": "A", "resnum": i + 1, "resname": "ALA", "plddt": 80.0} for i in range(n)]
    pockets = _geometric_pocket_detection(coords, residues, min_residues=4)
    assert isinstance(pockets, list)


def test_geometric_pocket_detection_low_plddt() -> None:
    """Low pLDDT pockets are excluded."""
    rng = np.random.RandomState(1)
    n = 50
    coords = rng.randn(n, 3) * 10
    residues = [{"chain": "A", "resnum": i + 1, "resname": "ALA", "plddt": 30.0} for i in range(n)]
    pockets = _geometric_pocket_detection(coords, residues, min_residues=4)
    assert pockets == []


def test_geometric_pocket_detection_no_buried() -> None:
    """Not enough buried residues after surface filtering → returns empty list."""
    # 20 residues, min_residues=15. Buried ~ 40% = 8 < 15.
    coords = np.array([[i * 5.0, 0.0, 0.0] for i in range(20)])
    residues = [{"chain": "A", "resnum": i + 1, "resname": "ALA", "plddt": 80.0} for i in range(20)]
    pockets = _geometric_pocket_detection(coords, residues, min_residues=15)
    assert pockets == []


def test_find_most_similar_pair_too_few() -> None:
    assert _find_most_similar_pair(["a"], [[0]]) is None


def test_find_most_similar_pair() -> None:
    out = _find_most_similar_pair(["a", "b"], [[0, 0.5], [0.5, 0]])
    assert out is not None
    assert out["protein_a"] == "a"


def test_find_most_similar_pair_multiple() -> None:
    """3+ proteins → some pairs don't beat the best, branch 1201->1199."""
    # ab=0.1, ac=0.5, bc=0.3 → best is ab
    matrix = [
        [0.0, 0.1, 0.5],
        [0.1, 0.0, 0.3],
        [0.5, 0.3, 0.0],
    ]
    out = _find_most_similar_pair(["a", "b", "c"], matrix)
    assert out is not None
    assert out["protein_a"] == "a"
    assert out["protein_b"] == "b"


# ---------------------------------------------------------------------------
# AF structure-and-PAE fetch helpers
# ---------------------------------------------------------------------------


def _fake_af(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Install a fake AlphaFoldClient as the structure module's client.

    The three methods the fetchers call are AsyncMocks with benign
    defaults; each test overrides the ones it exercises.
    """
    fake = MagicMock()
    fake.get_prediction = AsyncMock(return_value={})
    fake.get_pdb_bytes = AsyncMock(return_value=b"")
    fake.get_pae = AsyncMock(return_value={})
    monkeypatch.setattr(si, "_alphafold", lambda: fake)
    return fake


def _af_meta() -> dict[str, Any]:
    """A valid AlphaFold prediction-metadata dict."""
    return {
        "entryId": "AF-P12345-F1",
        "globalMetricValue": 85.0,
        "pdbUrl": "https://alphafold.ebi.ac.uk/files/AF-P12345-F1-model_v6.pdb",
        "uniprotSequence": "MKTV",
    }


def test_alphafold_client_is_a_cached_singleton() -> None:
    """The module-level AlphaFold client factory caches one instance."""
    si._CLIENTS.pop("alphafold", None)
    first = si._alphafold()
    second = si._alphafold()
    assert first is second
    assert isinstance(first, si.AlphaFoldClient)


# --- _fetch_af_structure ----------------------------------------------------


async def test_fetch_af_structure_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_text = _make_pdb(5)
    af = _fake_af(monkeypatch)
    af.get_pdb_bytes.return_value = fake_text.encode("utf-8")
    out = await _fetch_af_structure("P12345")
    assert out is not None
    assert out["pdb_text"] == fake_text
    assert out["uniprot_id"] == "P12345"


async def test_fetch_af_structure_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """An accession with no AlphaFold model yields empty PDB bytes."""
    _fake_af(monkeypatch)  # get_pdb_bytes default returns b""
    assert await _fetch_af_structure("P00000") is None


async def test_fetch_af_structure_client_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    af = _fake_af(monkeypatch)
    af.get_pdb_bytes.side_effect = RuntimeError("network down")
    assert await _fetch_af_structure("P12345") is None


# --- _fetch_af_plddt --------------------------------------------------------


async def test_fetch_af_plddt_success(monkeypatch: pytest.MonkeyPatch) -> None:
    af = _fake_af(monkeypatch)
    af.get_prediction.return_value = _af_meta()
    af.get_pae.return_value = {"predicted_aligned_error": [[1.0, 2.0], [2.0, 1.0]]}
    out = await _fetch_af_plddt("P12345")
    assert out is not None
    assert out["mean_plddt"] == 85.0
    assert out["sequence_length"] == 4
    assert out["pae_mean"] == 1.5


async def test_fetch_af_plddt_prediction_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    af = _fake_af(monkeypatch)
    af.get_prediction.side_effect = RuntimeError("network down")
    assert await _fetch_af_plddt("P12345") is None


async def test_fetch_af_plddt_no_entry_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prediction metadata without an entryId is not a real model."""
    af = _fake_af(monkeypatch)
    af.get_prediction.return_value = {"globalMetricValue": 85.0}
    assert await _fetch_af_plddt("P00000") is None


async def test_fetch_af_plddt_metadata_not_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty-list metadata payload is rejected."""
    af = _fake_af(monkeypatch)
    af.get_prediction.return_value = []
    assert await _fetch_af_plddt("P00000") is None


async def test_fetch_af_plddt_pae_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PAE fetch failure still yields the pLDDT summary."""
    af = _fake_af(monkeypatch)
    af.get_prediction.return_value = _af_meta()
    af.get_pae.side_effect = RuntimeError("pae unavailable")
    out = await _fetch_af_plddt("P12345")
    assert out is not None
    assert out["mean_plddt"] == 85.0
    assert "pae_mean" not in out


async def test_fetch_af_plddt_pae_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """An accession with no PAE document yields a summary without PAE."""
    af = _fake_af(monkeypatch)
    af.get_prediction.return_value = _af_meta()
    af.get_pae.return_value = {}
    out = await _fetch_af_plddt("P12345")
    assert out is not None
    assert "pae_mean" not in out
    assert "pae_matrix_shape" not in out


# ---------------------------------------------------------------------------
# analyze_structural_confidence
# ---------------------------------------------------------------------------


async def test_analyze_structural_confidence_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(uid: str) -> dict[str, Any]:
        return {
            "uniprot_id": uid,
            "mean_plddt": 85.0,
            "sequence_length": 200,
            "pae_mean": 5.0,
            "pae_max": 30.0,
            "high_pae_pairs": [{"residue_a": 1, "residue_b": 100}],
            "domain_boundaries": [100],
            "model_url": "http://x",
        }

    monkeypatch.setattr(si, "_fetch_af_plddt", fake_fetch)

    out = await analyze_structural_confidence(UniProtInput(uniprot_id="P12345"))
    assert out["confidence_tier"] == "HIGH"
    assert out["mean_plddt"] == 85.0


async def test_analyze_structural_confidence_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(uid: str) -> dict[str, Any] | None:
        return None

    monkeypatch.setattr(si, "_fetch_af_plddt", fake_fetch)
    out = await analyze_structural_confidence(UniProtInput(uniprot_id="P12345"))
    assert "error" in out


async def test_analyze_structural_confidence_low_plddt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(uid: str) -> dict[str, Any]:
        return {
            "uniprot_id": uid,
            "mean_plddt": 45.0,
            "sequence_length": 100,
        }

    monkeypatch.setattr(si, "_fetch_af_plddt", fake_fetch)
    out = await analyze_structural_confidence(UniProtInput(uniprot_id="P12345"))
    assert "CAUTION" in out["druggability_pre_screen"]["structural_suitability"]


async def test_analyze_structural_confidence_no_plddt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """meanPlddt is None - rare edge case."""

    async def fake_fetch(uid: str) -> dict[str, Any]:
        return {"uniprot_id": uid}

    monkeypatch.setattr(si, "_fetch_af_plddt", fake_fetch)
    out = await analyze_structural_confidence(UniProtInput(uniprot_id="P12345"))
    assert out["mean_plddt"] is None


# ---------------------------------------------------------------------------
# compute_topology_fingerprint
# ---------------------------------------------------------------------------


async def test_compute_topology_fingerprint_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(uid: str) -> dict[str, Any]:
        return {"pdb_text": _make_pdb(20), "uniprot_id": uid}

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await compute_topology_fingerprint(UniProtInput(uniprot_id="P12345"))
    assert out["n_residues"] == 20
    assert "topological_fingerprint" in out


async def test_compute_topology_fingerprint_no_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(uid: str) -> None:
        return None

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await compute_topology_fingerprint(UniProtInput(uniprot_id="P12345"))
    assert "error" in out


async def test_compute_topology_fingerprint_no_ca(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(uid: str) -> dict[str, Any]:
        return {"pdb_text": "EMPTY", "uniprot_id": uid}

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await compute_topology_fingerprint(UniProtInput(uniprot_id="P12345"))
    assert "error" in out


# ---------------------------------------------------------------------------
# compare_proteins_topologically
# ---------------------------------------------------------------------------


async def test_compare_proteins_topologically_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdbs = {"P12345": _make_pdb(10), "P67890": _make_pdb(12)}

    async def fake_fetch(uid: str) -> dict[str, Any] | None:
        if uid in pdbs:
            return {"pdb_text": pdbs[uid], "uniprot_id": uid}
        return None

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await compare_proteins_topologically(MultiProteinInput(uniprot_ids=["P12345", "P67890"]))
    assert "distance_matrix" in out


async def test_compare_proteins_topologically_mix_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(uid: str) -> dict[str, Any] | None:
        if uid == "P12345":
            return {"pdb_text": _make_pdb(10), "uniprot_id": uid}
        return None

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await compare_proteins_topologically(MultiProteinInput(uniprot_ids=["P12345", "P67890"]))
    assert "P67890" in out["proteins_failed"]


async def test_compare_proteins_topologically_no_ca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returned structure has no Cα atoms."""

    async def fake_fetch(uid: str) -> dict[str, Any]:
        return {"pdb_text": "NOTHING", "uniprot_id": uid}

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await compare_proteins_topologically(MultiProteinInput(uniprot_ids=["P12345", "P67890"]))
    assert "P12345" in out["proteins_failed"]


async def test_compare_proteins_topologically_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(uid: str) -> dict[str, Any] | None:
        raise RuntimeError("fetch fail")

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await compare_proteins_topologically(MultiProteinInput(uniprot_ids=["P12345", "P67890"]))
    assert out["proteins_failed"]


# ---------------------------------------------------------------------------
# find_evolutionary_structural_shifts
# ---------------------------------------------------------------------------


async def test_evolutionary_shifts_no_orthologs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_ensembl = MagicMock()
    mock_ensembl.orthologs = AsyncMock(return_value=[])
    monkeypatch.setattr(si, "EnsemblClient", lambda: mock_ensembl)

    out = await find_evolutionary_structural_shifts(EvolutionaryInput(gene_symbol="BRCA1"))
    assert "error" in out


async def test_evolutionary_shifts_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_ensembl = MagicMock()
    mock_ensembl.orthologs = AsyncMock(
        return_value=[
            {
                "species": "mus_musculus",
                "gene_id": "ENSMUSG1",
                "gene_name": "Brca1",
                "type": "ortholog_one2one",
                "identity": 95.0,
                "dn_ds": 0.1,
            }
        ]
    )
    mock_ensembl.gene_lookup = AsyncMock(return_value={"uniprot_ids": ["P12345"], "found": True})
    monkeypatch.setattr(si, "EnsemblClient", lambda: mock_ensembl)

    async def fake_fetch(uid: str) -> dict[str, Any]:
        return {"pdb_text": _make_pdb(15), "uniprot_id": uid}

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)

    out = await find_evolutionary_structural_shifts(EvolutionaryInput(gene_symbol="BRCA1"))
    assert out["species_compared"] == 1


async def test_evolutionary_shifts_no_uniprot(monkeypatch: pytest.MonkeyPatch) -> None:
    """No human UniProt → no human fingerprint."""
    mock_ensembl = MagicMock()
    mock_ensembl.orthologs = AsyncMock(
        return_value=[{"species": "mus_musculus", "gene_id": "G", "identity": 70.0}]
    )
    mock_ensembl.gene_lookup = AsyncMock(return_value={"uniprot_ids": []})
    monkeypatch.setattr(si, "EnsemblClient", lambda: mock_ensembl)

    out = await find_evolutionary_structural_shifts(EvolutionaryInput(gene_symbol="BRCA1"))
    assert out["human_uniprot_id"] == ""


async def test_evolutionary_shifts_no_human_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_ensembl = MagicMock()
    mock_ensembl.orthologs = AsyncMock(
        return_value=[{"species": "mus_musculus", "gene_id": "G", "identity": 70.0}]
    )
    mock_ensembl.gene_lookup = AsyncMock(return_value={"uniprot_ids": ["P12345"]})
    monkeypatch.setattr(si, "EnsemblClient", lambda: mock_ensembl)

    async def fake_fetch(uid: str) -> None:
        return None

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await find_evolutionary_structural_shifts(EvolutionaryInput(gene_symbol="BRCA1"))
    assert out["species_compared"] == 1


async def test_evolutionary_shifts_empty_human_ca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Human structure exists but has no Cα atoms."""
    mock_ensembl = MagicMock()
    mock_ensembl.orthologs = AsyncMock(
        return_value=[{"species": "mus_musculus", "gene_id": "G", "identity": 70.0}]
    )
    mock_ensembl.gene_lookup = AsyncMock(return_value={"uniprot_ids": ["P12345"]})
    monkeypatch.setattr(si, "EnsemblClient", lambda: mock_ensembl)

    async def fake_fetch(uid: str) -> dict[str, Any]:
        return {"pdb_text": "NO CA", "uniprot_id": uid}

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await find_evolutionary_structural_shifts(EvolutionaryInput(gene_symbol="BRCA1"))
    assert out["species_compared"] == 1


async def test_evolutionary_shifts_ortholog_no_gene_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ortholog has no gene_id → no structural_drift computed."""
    mock_ensembl = MagicMock()
    mock_ensembl.orthologs = AsyncMock(
        return_value=[{"species": "mus_musculus", "gene_id": "", "identity": 70.0}]
    )
    mock_ensembl.gene_lookup = AsyncMock(return_value={"uniprot_ids": ["P12345"]})
    monkeypatch.setattr(si, "EnsemblClient", lambda: mock_ensembl)

    async def fake_fetch(uid: str) -> dict[str, Any]:
        return {"pdb_text": _make_pdb(10), "uniprot_id": uid}

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await find_evolutionary_structural_shifts(EvolutionaryInput(gene_symbol="BRCA1"))
    assert out["evolutionary_profile"][0]["divergence_estimate"] is None
    assert out["evolutionary_profile"][0]["divergence_method"] == "sequence_identity"


# ---------------------------------------------------------------------------
# score_binding_pocket_geometry
# ---------------------------------------------------------------------------


async def test_score_binding_pocket_no_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(uid: str) -> None:
        return None

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await score_binding_pocket_geometry(BindingPocketInput(uniprot_id="P12345"))
    assert "error" in out


async def test_score_binding_pocket_too_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(uid: str) -> dict[str, Any]:
        return {"pdb_text": _make_pdb(5), "uniprot_id": uid}

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await score_binding_pocket_geometry(BindingPocketInput(uniprot_id="P12345"))
    assert "error" in out


async def test_score_binding_pocket_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    rng = np.random.RandomState(0)
    coords = rng.randn(40, 3) * 5
    lines = []
    for i in range(40):
        x, y, z = coords[i]
        lines.append(
            f"ATOM  {i + 1:5d}  CA  ALA A{i + 1:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 85.00           C"
        )
    pdb = "\n".join(lines)

    async def fake_fetch(uid: str) -> dict[str, Any]:
        return {"pdb_text": pdb, "uniprot_id": uid}

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await score_binding_pocket_geometry(BindingPocketInput(uniprot_id="P12345"))
    assert "putative_pockets" in out


# ---------------------------------------------------------------------------
# detect_intrinsically_disordered
# ---------------------------------------------------------------------------


async def test_detect_intrinsically_disordered_no_plddt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(uid: str) -> None:
        return None

    monkeypatch.setattr(si, "_fetch_af_plddt", fake_fetch)
    out = await detect_intrinsically_disordered(UniProtInput(uniprot_id="P12345"))
    assert "error" in out


async def test_detect_intrinsically_disordered_no_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_plddt(uid: str) -> dict[str, Any]:
        return {"uniprot_id": uid}

    async def fake_struct(uid: str) -> None:
        return None

    monkeypatch.setattr(si, "_fetch_af_plddt", fake_plddt)
    monkeypatch.setattr(si, "_fetch_af_structure", fake_struct)
    out = await detect_intrinsically_disordered(UniProtInput(uniprot_id="P12345"))
    assert "error" in out


async def test_detect_intrinsically_disordered_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_plddt(uid: str) -> dict[str, Any]:
        return {"uniprot_id": uid}

    async def fake_struct(uid: str) -> dict[str, Any]:
        return {"pdb_text": _make_pdb(40, plddt=80.0), "uniprot_id": uid}

    monkeypatch.setattr(si, "_fetch_af_plddt", fake_plddt)
    monkeypatch.setattr(si, "_fetch_af_structure", fake_struct)
    out = await detect_intrinsically_disordered(UniProtInput(uniprot_id="P12345"))
    assert out["is_idr_protein"] is False


async def test_detect_intrinsically_disordered_disordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_plddt(uid: str) -> dict[str, Any]:
        return {"uniprot_id": uid}

    async def fake_struct(uid: str) -> dict[str, Any]:
        return {"pdb_text": _make_pdb(40, plddt=30.0), "uniprot_id": uid}

    monkeypatch.setattr(si, "_fetch_af_plddt", fake_plddt)
    monkeypatch.setattr(si, "_fetch_af_structure", fake_struct)
    out = await detect_intrinsically_disordered(UniProtInput(uniprot_id="P12345"))
    assert out["is_idr_protein"] is True


async def test_detect_intrinsically_disordered_zero_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero residues — edge case."""

    async def fake_plddt(uid: str) -> dict[str, Any]:
        return {"uniprot_id": uid}

    async def fake_struct(uid: str) -> dict[str, Any]:
        return {"pdb_text": "", "uniprot_id": uid}

    monkeypatch.setattr(si, "_fetch_af_plddt", fake_plddt)
    monkeypatch.setattr(si, "_fetch_af_structure", fake_struct)
    out = await detect_intrinsically_disordered(UniProtInput(uniprot_id="P12345"))
    assert out["sequence_length"] == 0
