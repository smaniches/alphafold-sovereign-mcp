# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Unit tests for the pure druggability scoring heuristic — no I/O."""

from __future__ import annotations

import pytest

from alphafold_sovereign.domain.druggability import (
    SIGNAL_TOTAL,
    DruggabilityAssessment,
    has_small_molecule_tractability,
    resolve_drug_precedent,
    score_normalized,
    score_target_druggability,
    tier_for_score,
    validated_plddt,
)


# ── has_small_molecule_tractability ──────────────────────────────────────────
@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (None, False),
        ([], False),
        (["  ", ""], False),  # whitespace-only / empty are ignored
        (["Small molecule"], True),  # exact canonical label
        (["Discovery_small_molecule"], True),  # exact set member
        (["SM_clinical"], True),  # exact set member
        (["small_mol_bucket"], True),  # substring token
        (["Approved Small Molecule"], True),  # natural-language phrase
        (["clinical small-molecule"], True),  # punctuation normalised
        (["Antibody"], False),
        (["Unknown modality"], False),
    ],
)
def test_has_small_molecule_tractability(labels: list[str] | None, expected: bool) -> None:
    assert has_small_molecule_tractability(labels) is expected


def test_small_molecule_display_matches_score() -> None:
    """The canonical 'Small molecule' label is credited by the shared predicate.

    This is the exact inconsistency the display fix closes: the tier scoring
    credits the label, so the predicate must return True for it.
    """
    labels = ["Small molecule"]
    assert has_small_molecule_tractability(labels) is True
    assessment = score_target_druggability(
        drug_count=0, tractability_labels=labels, loeuf=None, plddt_mean=None
    )
    assert assessment.components["tractability"]["contribution"] == 2


# ── tier_for_score / score_normalized ────────────────────────────────────────
@pytest.mark.parametrize(
    ("score", "tier"),
    [
        (6, "HOT"),
        (4, "HOT"),
        (3, "WARM"),
        (2, "WARM"),
        (1, "COLD"),
        (0, "NOT_DRUGGABLE"),
        (-1, "NOT_DRUGGABLE"),
    ],
)
def test_tier_for_score(score: int, tier: str) -> None:
    assert tier_for_score(score) == tier


def test_score_normalized_range() -> None:
    # Reachable score range is [-1, 6] → normalised to [0, 1].
    assert score_normalized(-1) == 0.0
    assert score_normalized(6) == 1.0
    assert 0.0 < score_normalized(3) < 1.0


# ── score_target_druggability: tiers and exact scores ────────────────────────
@pytest.mark.parametrize(
    ("drug_count", "tract", "loeuf", "plddt", "score", "tier"),
    [
        (5, ["Small molecule"], None, 80.0, 6, "HOT"),  # 3+2+1
        (1, ["other_label"], None, None, 2, "WARM"),  # 2
        (0, [], None, 75.0, 1, "COLD"),  # pLDDT only
        (0, [], None, None, 0, "NOT_DRUGGABLE"),  # nothing
        (5, ["Small molecule"], 0.2, 80.0, 5, "HOT"),  # 3+2+1-1
        (1, ["small_mol_X"], 0.2, None, 3, "WARM"),  # 2+2-1
        (0, [], None, 50.0, 0, "NOT_DRUGGABLE"),  # pLDDT<70 → 0
        (3, [], None, None, 3, "WARM"),  # strong precedent alone
    ],
)
def test_score_and_tier(
    drug_count: int,
    tract: list[str],
    loeuf: float | None,
    plddt: float | None,
    score: int,
    tier: str,
) -> None:
    a = score_target_druggability(
        drug_count=drug_count, tractability_labels=tract, loeuf=loeuf, plddt_mean=plddt
    )
    assert a.total_score == score
    assert a.tier == tier
    assert a.rationale


# ── data completeness / missing signals ──────────────────────────────────────
@pytest.mark.parametrize(
    ("loeuf", "plddt", "available", "missing"),
    [
        (0.5, 80.0, 4, ()),
        (None, 80.0, 3, ("constraint_loeuf",)),
        (0.5, None, 3, ("structure_plddt",)),
        (None, None, 2, ("structure_plddt", "constraint_loeuf")),
    ],
)
def test_signal_completeness(
    loeuf: float | None,
    plddt: float | None,
    available: int,
    missing: tuple[str, ...],
) -> None:
    a = score_target_druggability(
        drug_count=1, tractability_labels=[], loeuf=loeuf, plddt_mean=plddt
    )
    assert a.signals_available == available
    assert a.signals_missing == missing
    assert a.signals_available == SIGNAL_TOTAL - len(missing)


# ── confidence grading ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("drug_count", "tract", "loeuf", "plddt", "confidence"),
    [
        (3, [], None, None, "HIGH"),  # decisive drug precedent, even w/o other signals
        (1, [], 0.5, 80.0, "HIGH"),  # all four signals observed
        (0, [], None, None, "LOW"),  # only the always-on signals, both absent
        (0, ["Small molecule"], None, None, "MODERATE"),  # tractability rescues from LOW
        (1, [], None, None, "MODERATE"),  # partial evidence base
        (0, [], None, 80.0, "MODERATE"),  # 3 signals available, no precedent
    ],
)
def test_confidence(
    drug_count: int,
    tract: list[str],
    loeuf: float | None,
    plddt: float | None,
    confidence: str,
) -> None:
    a = score_target_druggability(
        drug_count=drug_count, tractability_labels=tract, loeuf=loeuf, plddt_mean=plddt
    )
    assert a.confidence == confidence
    assert a.confidence_rationale


# ── borderline detection ─────────────────────────────────────────────────────
def test_borderline_true_and_note() -> None:
    # Score 4 (HOT); losing one point → WARM, so it is borderline.
    a = score_target_druggability(
        drug_count=1, tractability_labels=["Small molecule"], loeuf=None, plddt_mean=None
    )
    assert a.total_score == 4
    assert a.borderline is True
    assert a.borderline_note is not None
    assert "WARM" in a.borderline_note


def test_borderline_false_and_no_note() -> None:
    # Score 6 (HOT); a one-point change stays HOT, so not borderline.
    a = score_target_druggability(
        drug_count=5, tractability_labels=["Small molecule"], loeuf=None, plddt_mean=80.0
    )
    assert a.total_score == 6
    assert a.borderline is False
    assert a.borderline_note is None


# ── scoring_breakdown serialisation ──────────────────────────────────────────
def test_scoring_breakdown_shape() -> None:
    a = score_target_druggability(
        drug_count=2, tractability_labels=["Small molecule"], loeuf=0.2, plddt_mean=85.0
    )
    breakdown = a.scoring_breakdown()
    assert breakdown["total_score"] == a.total_score
    assert breakdown["score_normalized"] == score_normalized(a.total_score)
    assert breakdown["thresholds"] == {
        "HOT": ">=4",
        "WARM": ">=2",
        "COLD": ">=1",
        "NOT_DRUGGABLE": "<1",
    }
    assert set(breakdown["components"]) == {
        "drug_precedent",
        "tractability",
        "plddt",
        "loeuf_safety",
    }
    assert breakdown["signals"] == {"available": 4, "total": 4, "missing": []}
    assert breakdown["confidence"] == a.confidence
    assert breakdown["borderline"] == a.borderline
    assert isinstance(a, DruggabilityAssessment)


def test_components_report_inputs() -> None:
    """Component 'input' strings capture the exact thresholds crossed."""
    a = score_target_druggability(drug_count=0, tractability_labels=[], loeuf=0.5, plddt_mean=60.0)
    assert "not_available" not in a.components["loeuf_safety"]["input"]  # loeuf present
    assert ">=0.35" in a.components["loeuf_safety"]["input"]
    assert "<70" in a.components["plddt"]["input"]
    assert a.components["drug_precedent"]["input"] == "drug_count=0"


@pytest.mark.parametrize(
    ("raw", "observed", "status"),
    [
        (None, None, "missing"),
        (0, 0.0, "ok"),
        (70, 70.0, "ok"),
        (100.0, 100.0, "ok"),
        (-1.0, None, "invalid_response"),
        (100.01, None, "invalid_response"),
        (float("nan"), None, "invalid_response"),
        (float("inf"), None, "invalid_response"),
        (float("-inf"), None, "invalid_response"),
        (True, None, "invalid_response"),
        ("85", None, "invalid_response"),
    ],
)
def test_validated_plddt_preserves_valid_measurements_and_rejects_invalid(
    raw: object, observed: float | None, status: str
) -> None:
    assert validated_plddt(raw) == (observed, status)


@pytest.mark.parametrize("raw", [-1.0, 101.0, float("nan"), float("inf"), True, "95"])
def test_scoring_refuses_malformed_plddt(raw: object) -> None:
    assessed = score_target_druggability(
        drug_count=0,
        tractability_labels=[],
        loeuf=None,
        plddt_mean=raw,  # type: ignore[arg-type]
    )
    assert assessed.total_score == 0
    assert assessed.components["plddt"] == {"contribution": 0, "input": "invalid_response"}
    assert assessed.signals_missing == ("structure_plddt", "constraint_loeuf")


# ── resolve_drug_precedent: scope-aware source selection ─────────────────────
@pytest.mark.parametrize(
    ("chembl", "ot", "include_clinical", "expected"),
    [
        # Positive ChEMBL count in the requested scope always wins.
        (5, 82, True, (5, 5, "chembl_mechanism_distinct_molecules")),
        (2, 0, True, (2, 2, "chembl_mechanism_distinct_molecules")),
        (1, None, False, (1, 1, "chembl_mechanism_distinct_molecules")),
        # Live GABRA1 (2026-10-28): 1 ChEMBL single-subunit mechanism, 76 Open
        # Targets records; with approved-only scope ChEMBL is 0 and stays
        # authoritative because the Open Targets count spans every stage.
        (0, 76, False, (0, 0, "chembl_mechanism_distinct_molecules")),
        # Same target, approved plus clinical: scope-comparable presence.
        (0, 76, True, (76, 1, "open_targets_drug_and_clinical_candidates")),
        # Both observed zero (live BRCA1): ChEMBL's exact-scope zero.
        (0, 0, True, (0, 0, "chembl_mechanism_distinct_molecules")),
        (0, 0, False, (0, 0, "chembl_mechanism_distinct_molecules")),
        # ChEMBL unavailable: Open Targets presence only in comparable scope.
        (None, 9, True, (9, 1, "open_targets_drug_and_clinical_candidates")),
        # An all-stage zero bounds the approved-only scope (live B3GAT1).
        (None, 0, False, (0, 0, "open_targets_drug_and_clinical_candidates")),
        (None, 0, True, (0, 0, "open_targets_drug_and_clinical_candidates")),
        # ChEMBL observed zero with Open Targets unavailable.
        (0, None, True, (0, 0, "chembl_mechanism_distinct_molecules")),
        # No observed count in the requested scope: unavailable, never zero.
        (None, 9, False, None),
        (None, None, True, None),
        (None, None, False, None),
    ],
)
def test_resolve_drug_precedent(
    chembl: int | None,
    ot: int | None,
    include_clinical: bool,
    expected: tuple[int, int, str] | None,
) -> None:
    result = resolve_drug_precedent(
        chembl_count=chembl, open_targets_count=ot, include_clinical=include_clinical
    )
    if expected is None:
        assert result is None
    else:
        assert result is not None
        assert (result.drug_count, result.scoring_count, result.source) == expected
