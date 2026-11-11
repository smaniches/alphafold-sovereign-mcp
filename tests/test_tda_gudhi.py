# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Persistent-homology checks that need the optional ``[tda]`` extra.

The default test environment has no GUDHI, so the suite reaches the GUDHI code
path of ``_compute_tda_fingerprint`` only through a stand-in module. This file
runs the real library and is skipped when it is not installed; the ``test-tda``
CI job installs the extra so that it does run.

Expected values are analytic: the homology of regular polygons and straight
lines at the 15 Å end of the Vietoris-Rips filtration is known in closed form.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("gudhi")

from alphafold_sovereign.tools.structure_intelligence import (
    _compute_tda_fingerprint,
    _fingerprint_distance,
)


def _circle(
    radius: float, n: int, centre: tuple[float, float, float] = (0.0, 0.0, 0.0)
) -> np.ndarray:
    angle = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    return np.c_[
        radius * np.cos(angle) + centre[0],
        radius * np.sin(angle) + centre[1],
        np.zeros(n) + centre[2],
    ]


def _line(n: int, spacing: float) -> np.ndarray:
    return np.c_[np.arange(n) * spacing, np.zeros(n), np.zeros(n)]


def test_real_gudhi_ran() -> None:
    out = _compute_tda_fingerprint(_circle(20.0, 60))
    assert out["gudhi_available"] is True
    assert out["subsampled"] is False


def test_betti_numbers_of_analytic_point_clouds() -> None:
    # A 60-gon of radius 20 Å closes only at 20*sqrt(3) Å, beyond the 15 Å end.
    assert _compute_tda_fingerprint(_circle(20.0, 60))["betti_numbers"] == [1, 1, None]
    two_circles = np.vstack([_circle(20.0, 60), _circle(20.0, 60, (100.0, 0.0, 0.0))])
    assert _compute_tda_fingerprint(two_circles)["betti_numbers"] == [2, 2, None]
    assert _compute_tda_fingerprint(_line(50, 3.8))["betti_numbers"] == [1, 0, None]


def test_small_circle_closes_before_the_filtration_ends() -> None:
    """A 30-gon of radius 5 Å: its loop is born at the side length, dies at R*sqrt(3)."""
    out = _compute_tda_fingerprint(_circle(5.0, 30))
    assert out["betti_numbers"] == [1, 0, None]
    loops = out["persistence_landscapes"][1]
    assert loops["n_intervals"] == 1
    bar = loops["representative_intervals"][0]
    assert bar["birth"] == pytest.approx(2.0 * 5.0 * math.sin(math.pi / 30.0), abs=1e-3)
    assert bar["death"] == pytest.approx(5.0 * math.sqrt(3.0), abs=1e-3)


def test_fingerprint_is_invariant_under_rigid_motion() -> None:
    rng = np.random.default_rng(7)
    rotation, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    cloud = rng.normal(size=(120, 3)) * 8.0
    moved = cloud @ rotation.T + np.array([10.0, -3.0, 7.0])
    original = _compute_tda_fingerprint(cloud)["fingerprint_vector"]
    transformed = _compute_tda_fingerprint(moved)["fingerprint_vector"]
    assert transformed == pytest.approx(original, abs=1e-5)


def test_fingerprint_holds_sixteen_statistics_and_forty_eight_zeros() -> None:
    """AF-4: the 64 slots carry eight H0 and eight H1 statistics, nothing else."""
    cloud = np.vstack([_circle(5.0, 30), _circle(6.0, 30, (100.0, 0.0, 0.0))])
    out = _compute_tda_fingerprint(cloud)
    vector = out["fingerprint_vector"]
    assert out["fingerprint_dimension"] == len(vector) == 64
    assert all(value != 0.0 for value in vector[:16])
    assert vector[16:] == [0.0] * 48
    # GUDHI computes no H2 for the 2-skeleton, which is why slots 16-23 are empty.
    assert out["persistence_landscapes"][2] == {"dimension": 2, "n_intervals": 0}
    assert out["betti_numbers"][2] is None


def test_normalised_vector_is_dominated_by_total_persistence() -> None:
    """AF-4: the two sum-of-lifetimes slots carry nearly all of the norm.

    Total H0 persistence grows with the number of points while the other
    statistics do not, so after length normalisation a chain and one four
    times longer are almost the same vector. The distance therefore says
    little beyond how the total-persistence slots compare.
    """
    short, long = _line(60, 3.8), _line(240, 3.8)
    a = _compute_tda_fingerprint(short)["fingerprint_vector"]
    b = _compute_tda_fingerprint(long)["fingerprint_vector"]
    for vector in (a, b):
        share = (vector[7] ** 2 + vector[15] ** 2) / sum(value**2 for value in vector)
        assert share > 0.99
    assert b[7] == pytest.approx(a[7] * 239 / 59, rel=1e-6)  # one 3.8 Å bar per added point
    assert _fingerprint_distance(a, b) < 0.1


def test_statistics_of_a_long_model_describe_the_subsample() -> None:
    """AF-4: above 500 residues the complex is built on 500 of them.

    Every H0 bar of a straight chain with 3.8 Å spacing ends at 3.8 Å. Taking
    500 of 1200 points leaves neighbours two or three steps apart, so the same
    chain is reported with a mean H0 lifetime of 9.13 Å: the statistics are
    those of the subsample. The audit saw the same effect on EGFR (6.11 Å
    against 3.84 Å for all residues).
    """
    chain = _line(1200, 3.8)
    whole = _compute_tda_fingerprint(chain[:500])
    assert whole["subsampled"] is False
    assert whole["persistence_landscapes"][0]["mean_lifetime"] == pytest.approx(3.8, abs=1e-3)

    out = _compute_tda_fingerprint(chain)
    assert out["subsampled"] is True
    assert (out["n_residues_total"], out["n_residues_used"]) == (1200, 500)
    assert out["persistence_landscapes"][0]["mean_lifetime"] == pytest.approx(
        3.8 * 1199 / 499, abs=1e-3
    )
