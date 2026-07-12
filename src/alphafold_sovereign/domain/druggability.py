# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Pure-Python target-druggability triage heuristic.

No I/O, no network, no MCP SDK — only the deterministic mapping from four
public-database signals onto a HOT / WARM / COLD / NOT_DRUGGABLE tier. Keeping
this logic free of side effects lets it be unit-tested exhaustively and, in
future, *calibrated* against a benchmark of approved-drug vs. failed-drug
targets (see ``LIMITATIONS.md`` L2, roadmap step 4) without touching the async
tool orchestration in ``tools/precision_medicine.py``.

Scientific status
-----------------
The signal weights and tier cut-offs below are **literature-informed priors
chosen by the author**, not validated against a benchmark. The tier is a triage
signal, never a validated prediction. To make that uncertainty legible to a
consumer, every assessment also reports:

* ``signals_available`` / ``signals_missing`` — how much of the evidence base
  was actually present. The structural (pLDDT) and constraint (LOEUF) signals
  carry an explicit ``None`` sentinel when their upstream lookup failed or the
  entity was absent; drug precedent and tractability are always evaluated from
  whatever the upstreams returned (an empty result is a real observation of
  *no* precedent, not missing data).
* ``confidence`` — how strongly the available evidence backs the tier.
* ``borderline`` — whether a one-point change in the additive score (i.e. a
  single signal gained or lost) would move the target to an adjacent tier.

The four signals
----------------
* **Drug precedent** — count of approved / clinical drugs acting on the target
  (ChEMBL, with an Open Targets fallback). The single strongest signal:
  an existing drug is direct proof the target is engageable.
* **Tractability** — an Open Targets small-molecule tractability label.
* **Structural confidence** — mean AlphaFold pLDDT; a confident model implies
  analysable binding pockets.
* **Population constraint** — gnomAD LOEUF; a highly constrained (essential)
  gene may carry on-target toxicity risk when inhibited, so it *lowers* the
  score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ── Signal weights (points added to the additive score) ──────────────────────
# The maximum reachable score is DRUG_PRECEDENT_STRONG_WEIGHT + TRACTABILITY_WEIGHT
# + PLDDT_WEIGHT (LOEUF only ever subtracts), and the minimum is LOEUF_SAFETY_PENALTY.
DRUG_PRECEDENT_STRONG_WEIGHT = 3
"""Drug precedent at or above ``DRUG_PRECEDENT_STRONG_COUNT`` distinct drugs."""

DRUG_PRECEDENT_WEAK_WEIGHT = 2
"""At least one, but fewer than ``DRUG_PRECEDENT_STRONG_COUNT``, drugs."""

TRACTABILITY_WEIGHT = 2
"""A small-molecule tractability label is present."""

PLDDT_WEIGHT = 1
"""Mean pLDDT at or above ``PLDDT_CONFIDENT_MIN`` (analysable pockets)."""

LOEUF_SAFETY_PENALTY = -1
"""Gene LOEUF below ``LOEUF_CONSTRAINED_MAX`` (essential → toxicity risk)."""

# ── Signal thresholds ────────────────────────────────────────────────────────
DRUG_PRECEDENT_STRONG_COUNT = 3
"""Distinct-drug count at which precedent is treated as strong."""

PLDDT_CONFIDENT_MIN = 70.0
"""Mean pLDDT at/above which a structure is confident enough for pocket work.

Matches the AlphaFold "high confidence" band (Jumper et al., Nature 2021;
Tunyasuvunakool et al., Nature 2021): pLDDT ≥ 70 → backbone generally reliable.
"""

LOEUF_CONSTRAINED_MAX = 0.35
"""LOEUF below which a gene is treated as loss-of-function intolerant.

The gnomAD LOEUF < 0.35 threshold for "constrained" follows Karczewski et al.,
Nature 2020 (gnomAD v2 constraint), reused here for gnomAD v4 LOEUF values.
"""

# ── Tier cut-offs on the additive score (descending) ─────────────────────────
TIER_CUTOFFS: tuple[tuple[str, int], ...] = (("HOT", 4), ("WARM", 2), ("COLD", 1))
"""Score at/above which each named tier is assigned, highest first."""

LOWEST_TIER = "NOT_DRUGGABLE"
"""Tier for any score below the lowest cut-off."""

# Signal accounting: drug precedent and tractability are always evaluated;
# structural pLDDT and constraint LOEUF are the two that can be genuinely absent.
SIGNAL_TOTAL = 4
_ALWAYS_EVALUATED_SIGNALS = 2

_SCORE_MIN = LOEUF_SAFETY_PENALTY
_SCORE_MAX = DRUG_PRECEDENT_STRONG_WEIGHT + TRACTABILITY_WEIGHT + PLDDT_WEIGHT

# ── Small-molecule tractability recognition ──────────────────────────────────
SMALL_MOLECULE_LABELS = frozenset({"Small molecule", "Discovery_small_molecule", "SM_clinical"})
"""Exact Open Targets small-molecule bucket labels credited toward the score."""

_SMALL_MOLECULE_PHRASE = "small molecule"


def has_small_molecule_tractability(labels: list[str] | None) -> bool:
    """True if any label indicates small-molecule tractability.

    This is the single predicate the tier scoring, the user-facing
    tractability assessment, and the actionability text all share, so they can
    never disagree. A label counts when it is one of the exact
    :data:`SMALL_MOLECULE_LABELS`, contains the ``small_mol`` token, or — after
    normalising punctuation to spaces — contains the phrase "small molecule"
    (so natural-language Open Targets labels such as ``"Approved Small
    Molecule"`` are recognised). ``None``, empty, and whitespace-only labels
    are ignored.
    """
    for raw in labels or []:
        if not raw or not raw.strip():
            continue
        if raw in SMALL_MOLECULE_LABELS:
            return True
        lowered = raw.lower()
        if "small_mol" in lowered:
            return True
        if _SMALL_MOLECULE_PHRASE in re.sub(r"[^a-z0-9]+", " ", lowered):
            return True
    return False


def tier_for_score(score: int) -> str:
    """Map an additive score onto its tier name."""
    for name, cutoff in TIER_CUTOFFS:
        if score >= cutoff:
            return name
    return LOWEST_TIER


def score_normalized(score: int) -> float:
    """Map the additive score onto ``[0.0, 1.0]`` for readability.

    Linear rescaling of the reachable score range ``[_SCORE_MIN, _SCORE_MAX]``.
    A convenience for consumers; the tier is still decided by the integer score.
    """
    return round((score - _SCORE_MIN) / (_SCORE_MAX - _SCORE_MIN), 3)


_TIER_RATIONALE = {
    "HOT": "Strong drug precedent and tractability evidence.",
    "WARM": "Some drug precedent or tractability; further profiling recommended.",
    "COLD": "Limited precedent; additional evidence needed.",
    LOWEST_TIER: "No current evidence of druggability.",
}


def _confidence(
    *, signals_available: int, drug_count: int, has_tractability: bool
) -> tuple[str, str]:
    """Grade how strongly the *available* evidence backs the tier.

    HIGH when a decisive drug precedent exists or all four signals were
    observed; LOW when only the two always-evaluated signals were present and
    both were null observations (no drug, no tractability); MODERATE otherwise.
    """
    if drug_count >= DRUG_PRECEDENT_STRONG_COUNT:
        return (
            "HIGH",
            f"{drug_count} distinct drugs give decisive precedent for target engagement.",
        )
    if signals_available == SIGNAL_TOTAL:
        return (
            "HIGH",
            "All four signals (drug precedent, tractability, structure, constraint) were observed.",
        )
    if signals_available <= _ALWAYS_EVALUATED_SIGNALS and drug_count == 0 and not has_tractability:
        return (
            "LOW",
            "Only drug precedent and tractability were available, and both were absent; "
            "structural and constraint evidence is missing.",
        )
    return (
        "MODERATE",
        f"{signals_available} of {SIGNAL_TOTAL} signals available; "
        "the tier rests on a partial evidence base.",
    )


@dataclass(frozen=True, slots=True)
class DruggabilityAssessment:
    """Result of :func:`score_target_druggability`.

    Backward-compatible with the previous ``(tier, rationale, scoring)`` tuple:
    :meth:`scoring_breakdown` is a superset of the old ``scoring`` dict.
    """

    tier: str
    rationale: str
    total_score: int
    components: dict[str, dict[str, Any]]
    signals_available: int
    signals_missing: tuple[str, ...]
    confidence: str
    confidence_rationale: str
    borderline: bool
    borderline_note: str | None

    def scoring_breakdown(self) -> dict[str, Any]:
        """Auditable JSON view of how the tier was reached."""
        thresholds = {name: f">={cutoff}" for name, cutoff in TIER_CUTOFFS}
        thresholds[LOWEST_TIER] = f"<{TIER_CUTOFFS[-1][1]}"
        return {
            "total_score": self.total_score,
            "score_normalized": score_normalized(self.total_score),
            "thresholds": thresholds,
            "components": self.components,
            "signals": {
                "available": self.signals_available,
                "total": SIGNAL_TOTAL,
                "missing": list(self.signals_missing),
            },
            "confidence": self.confidence,
            "confidence_rationale": self.confidence_rationale,
            "borderline": self.borderline,
            "borderline_note": self.borderline_note,
        }


def score_target_druggability(
    *,
    drug_count: int,
    tractability_labels: list[str],
    loeuf: float | None,
    plddt_mean: float | None,
) -> DruggabilityAssessment:
    """Score a target's druggability from four independent signals.

    Args:
        drug_count: Distinct approved/clinical drugs acting on the target.
        tractability_labels: Open Targets tractability labels.
        loeuf: gnomAD LOEUF constraint (lower = more constrained); ``None`` if
            the constraint lookup was unavailable.
        plddt_mean: Mean AlphaFold pLDDT; ``None`` if no model was available.

    Returns:
        A :class:`DruggabilityAssessment` with the tier, its rationale, and the
        full auditable breakdown (score, components, data completeness,
        confidence, and borderline flag).
    """
    components: dict[str, dict[str, Any]] = {}

    # Drug precedent is the strongest signal.
    if drug_count >= DRUG_PRECEDENT_STRONG_COUNT:
        drug_contrib = DRUG_PRECEDENT_STRONG_WEIGHT
        components["drug_precedent"] = {
            "contribution": DRUG_PRECEDENT_STRONG_WEIGHT,
            "input": f"drug_count={drug_count}, >={DRUG_PRECEDENT_STRONG_COUNT}",
        }
    elif drug_count >= 1:
        drug_contrib = DRUG_PRECEDENT_WEAK_WEIGHT
        components["drug_precedent"] = {
            "contribution": DRUG_PRECEDENT_WEAK_WEIGHT,
            "input": f"drug_count={drug_count}, >=1",
        }
    else:
        drug_contrib = 0
        components["drug_precedent"] = {"contribution": 0, "input": f"drug_count={drug_count}"}

    # Tractability labels from Open Targets (same predicate as the display + text).
    has_tractability = has_small_molecule_tractability(tractability_labels)
    tract_contrib = TRACTABILITY_WEIGHT if has_tractability else 0
    components["tractability"] = {
        "contribution": tract_contrib,
        "input": "small_molecule label present" if has_tractability else "no small_molecule label",
    }

    # pLDDT ≥ threshold → confident structure → analysable binding pockets.
    if plddt_mean is not None and plddt_mean >= PLDDT_CONFIDENT_MIN:
        plddt_contrib = PLDDT_WEIGHT
        components["plddt"] = {
            "contribution": PLDDT_WEIGHT,
            "input": f"plddt_mean={plddt_mean:.1f}, >={PLDDT_CONFIDENT_MIN:.0f}",
        }
    elif plddt_mean is not None:
        plddt_contrib = 0
        components["plddt"] = {
            "contribution": 0,
            "input": f"plddt_mean={plddt_mean:.1f}, <{PLDDT_CONFIDENT_MIN:.0f}",
        }
    else:
        plddt_contrib = 0
        components["plddt"] = {"contribution": 0, "input": "not_available"}

    # LOEUF: highly constrained genes may cause toxicity on inhibition.
    if loeuf is not None and loeuf < LOEUF_CONSTRAINED_MAX:
        loeuf_contrib = LOEUF_SAFETY_PENALTY
        components["loeuf_safety"] = {
            "contribution": LOEUF_SAFETY_PENALTY,
            "input": f"loeuf={loeuf:.3f}, <{LOEUF_CONSTRAINED_MAX} — safety concern",
        }
    else:
        loeuf_contrib = 0
        loeuf_input = (
            f"loeuf={loeuf:.3f}, >={LOEUF_CONSTRAINED_MAX}"
            if loeuf is not None
            else "not_available"
        )
        components["loeuf_safety"] = {"contribution": 0, "input": loeuf_input}

    score = drug_contrib + tract_contrib + plddt_contrib + loeuf_contrib
    tier = tier_for_score(score)

    # Data completeness: the two signals with an explicit missing sentinel.
    missing: list[str] = []
    if plddt_mean is None:
        missing.append("structure_plddt")
    if loeuf is None:
        missing.append("constraint_loeuf")
    signals_available = SIGNAL_TOTAL - len(missing)

    confidence, confidence_rationale = _confidence(
        signals_available=signals_available,
        drug_count=drug_count,
        has_tractability=has_tractability,
    )

    # Borderline: would a one-point score change (one signal gained/lost) flip the tier?
    neighbours = {tier_for_score(score - 1), tier_for_score(score + 1)} - {tier}
    borderline = bool(neighbours)
    borderline_note = (
        f"Score {score} sits one point from a tier boundary; a single signal change "
        f"could shift the tier to {' or '.join(sorted(neighbours))}."
        if borderline
        else None
    )

    return DruggabilityAssessment(
        tier=tier,
        rationale=_TIER_RATIONALE[tier],
        total_score=score,
        components=components,
        signals_available=signals_available,
        signals_missing=tuple(missing),
        confidence=confidence,
        confidence_rationale=confidence_rationale,
        borderline=borderline,
        borderline_note=borderline_note,
    )
