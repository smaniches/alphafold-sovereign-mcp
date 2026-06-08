# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.tools.precision_medicine``."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphafold_sovereign.domain.disease import DiseaseRecord, PathogenicityClass
from alphafold_sovereign.tools import precision_medicine as pm
from alphafold_sovereign.tools.precision_medicine import (
    ACMGVariantInput,
    DiseaseDrugLandscapeInput,
    DruggabilityInput,
    DrugRepurposingInput,
    ProteinDossierInput,
    TargetSelectivityInput,
    VariantClinicalReportInput,
    _acmg_code,
    _acmg_strength,
    _alphafold,
    _alphamissense_for_variant,
    _am_to_acmg_evidence,
    _build_gnomad_id,
    _chembl,
    _clinvar,
    _compute_clinical_tier,
    _criteria_not_met,
    _disgenet,
    _druggability_actionability,
    _druggability_tier,
    _ensembl,
    _gnomad,
    _gnomad_to_acmg,
    _investability_rating,
    _mondo,
    _narrative_summary,
    _opentargets,
    _protein_variant_from_vep,
    _provenance,
    _tier_explanation,
    _vep_to_acmg,
    assess_target_druggability,
    classify_variant_acmg,
    find_drug_repurposing_candidates,
    generate_variant_clinical_report,
    map_disease_drug_landscape,
    synthesize_protein_dossier,
)


@pytest.fixture(autouse=True)
def _reset_singletons() -> Any:
    """Clear the lazy client singletons before each test."""
    pm._CLIENTS.clear()
    yield
    pm._CLIENTS.clear()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_provenance_contains_sources() -> None:
    p = _provenance(chembl="v36", gnomad="v4")
    assert "chembl=v36" in p
    assert "gnomad=v4" in p


def test_provenance_filters_empty() -> None:
    p = _provenance(chembl="", gnomad="v4")
    assert "chembl" not in p


@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        ("Pathogenic", "P"),
        ("Likely pathogenic", "LP"),
        ("Uncertain significance", "VUS"),
        ("Likely benign", "LB"),
        ("Benign", "B"),
        ("Conflicting interpretations", "CI"),
        ("Not provided", "NP"),
        ("not a real class", "NP"),
    ],
)
def test_acmg_code(cls: str, expected: str) -> None:
    assert _acmg_code(cls) == expected


@pytest.mark.parametrize(
    ("score", "expected_key"),
    [
        (0.9, "PP3"),
        (0.2, "BP4"),
        (0.5, None),
        (None, None),
    ],
)
def test_am_to_acmg_evidence(score: float | None, expected_key: str | None) -> None:
    out = _am_to_acmg_evidence(score)
    if expected_key:
        assert expected_key in out
    else:
        assert out == {}


@pytest.mark.parametrize(
    ("af", "expected_key"),
    [
        (0.1, "BS1"),
        (1e-5, "PM2"),
        (0.005, None),
        (None, None),
    ],
)
def test_gnomad_to_acmg(af: float | None, expected_key: str | None) -> None:
    out = _gnomad_to_acmg(af)
    if expected_key:
        assert expected_key in out
    else:
        assert out == {}


def test_vep_to_acmg_pvs1() -> None:
    out = _vep_to_acmg([{"canonical": True, "consequence_terms": ["stop_gained"]}])
    assert "PVS1" in out


def test_vep_to_acmg_pp3_missense() -> None:
    out = _vep_to_acmg(
        [
            {
                "canonical": True,
                "consequence_terms": ["missense_variant"],
                "sift_prediction": "deleterious",
                "polyphen_prediction": "probably_damaging",
                "cadd_phred": 25.0,
            }
        ]
    )
    assert "PP3" in out


def test_vep_to_acmg_pp3_low_confidence() -> None:
    out = _vep_to_acmg(
        [
            {
                "canonical": True,
                "consequence_terms": ["missense_variant"],
                "sift_prediction": "deleterious_low_confidence",
                "polyphen_prediction": "possibly_damaging",
            }
        ]
    )
    assert "PP3" in out


def test_vep_to_acmg_missense_single_signal() -> None:
    """Only one in-silico predictor → PP3 not triggered."""
    out = _vep_to_acmg(
        [
            {
                "canonical": True,
                "consequence_terms": ["missense_variant"],
                "sift_prediction": "deleterious",
                "polyphen_prediction": "benign",
            }
        ]
    )
    assert "PP3" not in out


def test_vep_to_acmg_synonymous() -> None:
    out = _vep_to_acmg([{"canonical": True, "consequence_terms": ["synonymous_variant"]}])
    assert "BP7" in out


def test_vep_to_acmg_non_canonical_skipped() -> None:
    out = _vep_to_acmg([{"canonical": False, "consequence_terms": ["stop_gained"]}])
    assert out == {}


def test_vep_to_acmg_cadd_below_threshold() -> None:
    out = _vep_to_acmg(
        [
            {
                "canonical": True,
                "consequence_terms": ["missense_variant"],
                "sift_prediction": "deleterious",
                "cadd_phred": 10.0,
            }
        ]
    )
    # CADD 10 < 20, only SIFT signal → PP3 not triggered
    assert "PP3" not in out


def test_vep_to_acmg_no_signals_at_all() -> None:
    """Missense with no in-silico predictors set."""
    out = _vep_to_acmg(
        [
            {
                "canonical": True,
                "consequence_terms": ["missense_variant"],
            }
        ]
    )
    assert out == {}


def test_vep_to_acmg_pp_only() -> None:
    """Single PolyPhen signal → no PP3."""
    out = _vep_to_acmg(
        [
            {
                "canonical": True,
                "consequence_terms": ["missense_variant"],
                "polyphen_prediction": "probably_damaging",
            }
        ]
    )
    assert out == {}


def test_vep_to_acmg_cadd_and_polyphen() -> None:
    """CADD + PolyPhen (no SIFT) triggers PP3."""
    out = _vep_to_acmg(
        [
            {
                "canonical": True,
                "consequence_terms": ["missense_variant"],
                "polyphen_prediction": "probably_damaging",
                "cadd_phred": 25.0,
            }
        ]
    )
    assert "PP3" in out


@pytest.mark.parametrize(
    ("drug_count", "tract", "loeuf", "plddt", "expected"),
    [
        (5, ["Small molecule"], None, 80.0, "HOT"),  # 3+2+1=6
        (1, ["other_label"], None, None, "WARM"),  # 2
        (0, [], None, 75.0, "COLD"),  # 1
        (0, [], None, None, "NOT_DRUGGABLE"),  # 0
        (5, ["Small molecule"], 0.2, 80.0, "HOT"),  # 3+2+1-1=5
        (1, ["small_mol_X"], 0.2, None, "WARM"),  # 2+2-1=3
        (0, [], None, 50.0, "NOT_DRUGGABLE"),  # pLDDT<70 → 0
    ],
)
def test_druggability_tier_branches(
    drug_count: int,
    tract: list[str],
    loeuf: float | None,
    plddt: float | None,
    expected: str,
) -> None:
    tier, _, scoring = _druggability_tier(
        drug_count=drug_count,
        tractability_labels=tract,
        loeuf=loeuf,
        plddt_mean=plddt,
    )
    assert tier == expected
    assert "total_score" in scoring
    assert "components" in scoring


@pytest.mark.parametrize(
    ("hgvs", "vep_results", "expected_starts_with"),
    [
        ("X", [{"seq_region_name": "17", "start": 123, "allele_string": "A/G"}], "17-"),
        ("17-123-A-G", [], "17-123-A-G"),
        ("chrX:c.1T>G", [], None),
        ("X", [{"seq_region_name": "1", "start": 100, "allele_string": "A/-"}], None),
        # chr prefix removed
        ("X", [{"seq_region_name": "chr5", "start": 200, "allele_string": "T/C"}], "5-"),
    ],
)
def test_build_gnomad_id(
    hgvs: str, vep_results: list[dict[str, Any]], expected_starts_with: str | None
) -> None:
    out = _build_gnomad_id(hgvs, vep_results)
    if expected_starts_with is None:
        assert out is None
    else:
        assert out is not None
        assert out.startswith(expected_starts_with)


@pytest.mark.parametrize(
    ("clinvar_class", "am_score", "global_af", "criteria", "expected"),
    [
        ("Pathogenic", None, None, {}, "HIGH"),
        ("Likely pathogenic", 0.9, None, {}, "HIGH"),
        ("Likely pathogenic", 0.3, None, {}, "MEDIUM"),
        ("Benign", None, None, {}, "LOW"),
        ("Likely benign", None, None, {}, "LOW"),
        ("Not provided", None, None, {"PP3": "x", "PM2": "y"}, "MEDIUM"),
        ("Not provided", None, None, {"BP4": "x", "BS1": "y"}, "LOW"),
        ("Not provided", 0.9, None, {}, "MEDIUM"),
        ("Not provided", 0.2, None, {}, "LOW"),
        ("Not provided", None, None, {}, "UNKNOWN"),
    ],
)
def test_compute_clinical_tier(
    clinvar_class: str,
    am_score: float | None,
    global_af: float | None,
    criteria: dict[str, str],
    expected: str,
) -> None:
    assert (
        _compute_clinical_tier(
            clinvar_class=clinvar_class,
            am_score=am_score,
            global_af=global_af,
            acmg_criteria=criteria,
        )
        == expected
    )


@pytest.mark.parametrize("tier", ["HIGH", "MEDIUM", "LOW", "UNKNOWN", "OTHER"])
def test_tier_explanation(tier: str) -> None:
    out = _tier_explanation(tier)
    assert isinstance(out, str)


@pytest.mark.parametrize(
    ("tier", "expected_substr"),
    [
        ("HOT", "Prioritise"),
        ("WARM", "FBDD"),
        ("COLD", "phenotypic"),
        ("NOT_DRUGGABLE", "pathway"),
    ],
)
def test_druggability_actionability(tier: str, expected_substr: str) -> None:
    out = _druggability_actionability(tier, 1, ["SM"])
    assert expected_substr in out


def test_narrative_summary_constrained() -> None:
    out = _narrative_summary(
        sym="BRCA1",
        tier="HOT",
        drug_count=3,
        diseases=[{"disease_name": "Cancer A"}, {"disease_name": "Cancer B"}],
        constraint={"loeuf": 0.2},
    )
    assert "BRCA1" in out
    assert "highly constrained" in out


def test_narrative_summary_moderate_loeuf() -> None:
    out = _narrative_summary(
        sym="X",
        tier="WARM",
        drug_count=1,
        diseases=[],
        constraint={"loeuf": 0.5},
    )
    assert "moderately constrained" in out


def test_narrative_summary_tolerant_loeuf() -> None:
    out = _narrative_summary(
        sym="X",
        tier="COLD",
        drug_count=0,
        diseases=[],
        constraint={"loeuf": 0.9},
    )
    assert "tolerant" in out


def test_narrative_summary_no_constraint() -> None:
    out = _narrative_summary(
        sym="X",
        tier="WARM",
        drug_count=0,
        diseases=[],
        constraint={},
    )
    assert "not determined" in out


def test_acmg_strength_known() -> None:
    assert _acmg_strength("PVS1") == "Very Strong"
    assert _acmg_strength("PS1") == "Strong"
    assert _acmg_strength("PM2") == "Moderate"
    assert _acmg_strength("PP3") == "Supporting"
    assert _acmg_strength("BA1") == "Stand-alone"
    assert _acmg_strength("BS1") == "Strong"


def test_acmg_strength_default() -> None:
    assert _acmg_strength("UNKNOWN") == "Supporting"


def test_criteria_not_met() -> None:
    out = _criteria_not_met({"PVS1": {}, "PP3": {}})
    assert "PVS1" not in out
    assert "PP3" not in out
    assert "PM2" in out


@pytest.mark.parametrize(
    ("approved", "pipeline", "druggable", "expected_substr"),
    [
        (3, 0, 5, "HIGH"),
        (1, 0, 0, "MEDIUM"),
        (0, 3, 0, "MEDIUM"),
        (0, 0, 2, "EARLY"),
        (0, 0, 0, "EXPLORATORY"),
    ],
)
def test_investability_rating(
    approved: int, pipeline: int, druggable: int, expected_substr: str
) -> None:
    assert expected_substr in _investability_rating(
        approved_count=approved, pipeline_count=pipeline, druggable_targets=druggable
    )


# ---------------------------------------------------------------------------
# Lazy singleton accessors
# ---------------------------------------------------------------------------


def test_lazy_singletons_create_once() -> None:
    """Each accessor caches its client instance."""
    c1 = _ensembl()
    c2 = _ensembl()
    assert c1 is c2

    assert _clinvar() is _clinvar()
    assert _gnomad() is _gnomad()
    assert _mondo() is _mondo()
    assert _opentargets() is _opentargets()
    assert _disgenet() is _disgenet()
    assert _chembl() is _chembl()
    assert _alphafold() is _alphafold()


# ---------------------------------------------------------------------------
# generate_variant_clinical_report
# ---------------------------------------------------------------------------


def _make_vep_result() -> list[dict[str, Any]]:
    return [
        {
            "canonical": True,
            "consequence_terms": ["missense_variant"],
            "sift_prediction": "deleterious",
            "polyphen_prediction": "probably_damaging",
            "cadd_phred": 25.0,
            "impact": "MODERATE",
            "amino_acids": "R/H",
            "hgvsp": "p.Arg61His",
            "seq_region_name": "17",
            "start": 43094692,
            "allele_string": "T/G",
        }
    ]


def _make_clinvar() -> list[dict[str, Any]]:
    return [
        {
            "classification": "Pathogenic",
            "review_status": "criteria provided, multiple submitters",
            "variation_id": "55555",
            "conditions": ["Breast cancer"],
        }
    ]


def _patch_clients(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Patch all client accessors to return mocks. Returns the mock dict."""
    mocks: dict[str, MagicMock] = {}

    for name in (
        "ensembl",
        "clinvar",
        "gnomad",
        "mondo",
        "opentargets",
        "disgenet",
        "chembl",
        "alphafold",
    ):
        mock = MagicMock()
        mocks[name] = mock
        monkeypatch.setattr(
            f"alphafold_sovereign.tools.precision_medicine._{name}", lambda m=mock: m
        )

    # assess_target_druggability and synthesize_protein_dossier resolve the
    # UniProt accession to an Ensembl target before any other Open Targets call.
    mocks["opentargets"].resolve_target = AsyncMock(
        return_value={"ensembl_id": "ENSG_TEST", "symbol": "TESTGENE"}
    )
    # AlphaMissense lookups default to "no annotation"; tests that exercise
    # the AlphaMissense path override this with a concrete record.
    mocks["alphafold"].alphamissense_score = AsyncMock(return_value=None)
    # Default pLDDT prediction metadata for druggability scoring.
    mocks["alphafold"].get_prediction = AsyncMock(
        return_value={"entryId": "AF-TEST-F1", "globalMetricValue": 85.0}
    )
    return mocks


async def test_generate_variant_report_full(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _patch_clients(monkeypatch)

    mocks["ensembl"].vep_hgvs = AsyncMock(return_value=_make_vep_result())
    mocks["ensembl"].gene_lookup = AsyncMock(
        return_value={"ensembl_gene_id": "ENSG0001", "uniprot_ids": ["P38398"]}
    )
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=_make_clinvar())
    mocks["gnomad"].variant_frequencies = AsyncMock(
        return_value={
            "global_af": 1e-5,
            "global_ac": 1,
            "global_an": 100000,
            "homozygote_count": 0,
            "alphamissense_score": 0.9,
            "populations": [{"pop": "nfe"}],
        }
    )
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={"pLI": 0.99, "loeuf": 0.2})

    disgenet_mock = MagicMock()
    disgenet_mock.score = 0.7
    mocks["disgenet"].gene_disease_associations = AsyncMock(
        return_value=[{"disease_name": "Cancer", "score": 0.7}]
    )

    ot_score = MagicMock()
    ot_score.to_dict.return_value = {"disease_name": "X", "overall_score": 0.9}
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[ot_score])

    mocks["chembl"].find_repurposable_drugs = AsyncMock(
        return_value=[
            {
                "molecule_chembl_id": "CHEMBL1",
                "pref_name": "Drug A",
                "max_phase": 4,
                "max_phase_label": "Approved",
                "mechanism": "Inhibitor",
            }
        ]
    )

    out = await generate_variant_clinical_report(VariantClinicalReportInput(hgvs="BRCA1:c.181T>G"))
    assert out["clinical_tier"] == "HIGH"
    assert out["gene_symbol"] == "BRCA1"
    assert "drug_context" in out


async def test_generate_variant_report_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(return_value=[])
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])

    out = await generate_variant_clinical_report(
        VariantClinicalReportInput(
            hgvs="BRCA1:c.181T>G",
            include_population_breakdown=False,
            include_drug_context=False,
        )
    )
    assert out["clinical_tier"] == "UNKNOWN"
    assert "drug_context" not in out
    assert out["population_genetics"]["populations"] == []


async def test_generate_variant_report_with_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(side_effect=RuntimeError("vep fail"))
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    mocks["clinvar"].search_by_hgvs = AsyncMock(side_effect=RuntimeError("cv fail"))
    mocks["gnomad"].variant_frequencies = AsyncMock(side_effect=RuntimeError("g fail"))
    mocks["gnomad"].gene_constraint = AsyncMock(side_effect=RuntimeError("c fail"))
    mocks["disgenet"].gene_disease_associations = AsyncMock(side_effect=RuntimeError("d fail"))

    out = await generate_variant_clinical_report(
        VariantClinicalReportInput(hgvs="BRCA1:c.181T>G", include_drug_context=False)
    )
    assert out["clinical_tier"] == "UNKNOWN"


async def test_generate_variant_report_drug_context_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(return_value=_make_vep_result())
    mocks["ensembl"].gene_lookup = AsyncMock(
        return_value={"ensembl_gene_id": "ENSG", "uniprot_ids": ["P38398"]}
    )
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[])
    mocks["chembl"].find_repurposable_drugs = AsyncMock(side_effect=RuntimeError("drug fail"))

    out = await generate_variant_clinical_report(VariantClinicalReportInput(hgvs="BRCA1:c.181T>G"))
    assert out["drug_context"]["repurposing_candidates"] == []


async def test_generate_variant_report_no_ensembl_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Branch where gene_lookup returns no ensembl_gene_id."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(return_value=_make_vep_result())
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={"uniprot_ids": []})
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])

    out = await generate_variant_clinical_report(
        VariantClinicalReportInput(hgvs="BRCA1:c.181T>G", include_drug_context=False)
    )
    assert out["disease_associations"]["open_targets_top_diseases"] == []


async def test_generate_variant_report_drug_context_no_uniprot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drug context branch where uniprot_ids is empty."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(return_value=_make_vep_result())
    # gene_lookup returns no uniprot
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={"ensembl_gene_id": "ENSG"})
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[])

    out = await generate_variant_clinical_report(VariantClinicalReportInput(hgvs="BRCA1:c.181T>G"))
    assert out["drug_context"]["repurposing_candidates"] == []


async def test_generate_variant_report_no_gene_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When HGVS doesn't parse to gene symbol, skip gene constraint and disease context."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(return_value=_make_vep_result())
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})

    out = await generate_variant_clinical_report(
        VariantClinicalReportInput(hgvs="NM_007294.3:c.181T>G", include_drug_context=False)
    )
    # No gene → no constraint, no disease
    assert out["gene_constraint"]["pLI"] is None
    assert out["data_sources_status"]["chembl"] == "skipped"


async def test_generate_variant_report_no_gene_drug_context_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """include_drug_context=True but no gene → chembl skipped."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(return_value=_make_vep_result())
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})

    out = await generate_variant_clinical_report(
        VariantClinicalReportInput(hgvs="NM_007294.3:c.181T>G", include_drug_context=True)
    )
    assert out["data_sources_status"]["chembl"] == "skipped"
    assert out["data_sources_status"]["disgenet"] == "skipped"
    assert out["data_sources_status"]["open_targets"] == "skipped"


async def test_generate_variant_report_non_canonical_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-canonical VEP entries are skipped (branch 519->518)."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(
        return_value=[
            {
                "canonical": False,
                "consequence_terms": ["missense_variant"],
                "seq_region_name": "17",
                "start": 1,
                "allele_string": "A/G",
            },
            {
                "canonical": True,
                "consequence_terms": ["missense_variant"],
                "seq_region_name": "17",
                "start": 2,
                "allele_string": "C/T",
                "amino_acids": "R/H",
            },
        ]
    )
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[])

    out = await generate_variant_clinical_report(
        VariantClinicalReportInput(hgvs="BRCA1:c.181T>G", include_drug_context=False)
    )
    assert out["functional_consequence"]["amino_acids"] == "R/H"


async def test_generate_variant_report_ot_diseases_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open Targets associated_diseases raises → ot_diseases stays empty (line 462->466)."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(return_value=_make_vep_result())
    mocks["ensembl"].gene_lookup = AsyncMock(
        return_value={"ensembl_gene_id": "ENSG0001", "uniprot_ids": []}
    )
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["opentargets"].associated_diseases = AsyncMock(side_effect=RuntimeError("ot fail"))

    out = await generate_variant_clinical_report(
        VariantClinicalReportInput(hgvs="BRCA1:c.181T>G", include_drug_context=False)
    )
    assert out["disease_associations"]["open_targets_top_diseases"] == []


async def test_generate_variant_report_gnomad_variant_freq_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gnomad.variant_frequencies raises - covers line 429-430."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(return_value=_make_vep_result())
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(side_effect=RuntimeError("var freq fail"))
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[])

    out = await generate_variant_clinical_report(
        VariantClinicalReportInput(hgvs="BRCA1:c.181T>G", include_drug_context=False)
    )
    assert out["population_genetics"]["global_af"] is None


# ---------------------------------------------------------------------------
# AlphaMissense helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("consequence", "expected"),
    [
        ({"amino_acids": "C/G", "protein_start": 61}, "C61G"),
        ({"amino_acids": "c/g", "protein_start": 61}, "C61G"),
        ({"amino_acids": "C/G", "protein_start": "61"}, "C61G"),
        ({"amino_acids": "", "protein_start": 61}, None),
        ({"amino_acids": "CC/G", "protein_start": 61}, None),
        ({"amino_acids": "C", "protein_start": 61}, None),
        ({"amino_acids": "C/G"}, None),
        ({"amino_acids": "C/G", "protein_start": None}, None),
        ({"amino_acids": "C/G", "protein_start": "x"}, None),
    ],
)
def test_protein_variant_from_vep(consequence: dict[str, Any], expected: str | None) -> None:
    assert _protein_variant_from_vep(consequence) == expected


def _missense_vep(swissprot: str | None = None) -> list[dict[str, Any]]:
    tc: dict[str, Any] = {
        "canonical": True,
        "consequence_terms": ["missense_variant"],
        "amino_acids": "C/G",
        "protein_start": 61,
    }
    if swissprot is not None:
        tc["swissprot"] = swissprot
    return [tc]


async def test_alphamissense_for_variant_not_missense() -> None:
    """A non-missense canonical consequence yields no AlphaMissense lookup."""
    vep = [{"canonical": True, "consequence_terms": ["stop_gained"]}]
    assert await _alphamissense_for_variant("BRCA1", vep) is None


async def test_alphamissense_for_variant_no_swissprot() -> None:
    """A canonical consequence without a SwissProt accession yields None."""
    assert await _alphamissense_for_variant("BRCA1", _missense_vep()) is None


async def test_alphamissense_for_variant_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """A SwissProt accession with a version suffix is stripped before lookup."""
    mocks = _patch_clients(monkeypatch)
    mocks["alphafold"].alphamissense_score = AsyncMock(
        return_value={
            "protein_variant": "C61G",
            "am_pathogenicity": 0.99,
            "am_class": "LPath",
        }
    )
    score = await _alphamissense_for_variant("BRCA1", _missense_vep("P38398.280"))
    assert score == 0.99
    mocks["alphafold"].alphamissense_score.assert_awaited_once_with("P38398", "C61G")


async def test_alphamissense_for_variant_no_record(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["alphafold"].alphamissense_score = AsyncMock(return_value=None)
    assert await _alphamissense_for_variant("BRCA1", _missense_vep("P38398")) is None


async def test_alphamissense_for_variant_score_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["alphafold"].alphamissense_score = AsyncMock(side_effect=RuntimeError("af fail"))
    assert await _alphamissense_for_variant("BRCA1", _missense_vep("P38398")) is None


async def test_generate_variant_report_alphamissense_scored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missense variant with a protein position resolves an AlphaMissense
    score from AlphaFold DB into the report and its ACMG criteria."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(
        return_value=[
            {
                "canonical": True,
                "consequence_terms": ["missense_variant"],
                "amino_acids": "C/G",
                "protein_start": 61,
                "swissprot": "P38398.280",
                "seq_region_name": "17",
                "start": 43094692,
                "allele_string": "T/G",
            }
        ]
    )
    mocks["ensembl"].gene_lookup = AsyncMock(
        return_value={"ensembl_gene_id": "ENSG0001", "uniprot_ids": ["P38398"]}
    )
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[])
    mocks["alphafold"].alphamissense_score = AsyncMock(
        return_value={
            "protein_variant": "C61G",
            "am_pathogenicity": 0.9904,
            "am_class": "LPath",
        }
    )

    out = await generate_variant_clinical_report(
        VariantClinicalReportInput(hgvs="BRCA1:c.181T>G", include_drug_context=False)
    )
    assert out["population_genetics"]["alphamissense_score"] == 0.9904
    assert "PP3" in out["acmg_criteria_draft"]["criteria"]


# ---------------------------------------------------------------------------
# assess_target_druggability
# ---------------------------------------------------------------------------


async def test_assess_target_druggability_full(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["chembl"].target_by_uniprot = AsyncMock(
        return_value={"chembl_id": "CHEMBL_TGT_1", "pref_name": "BRCA1"}
    )
    mocks["chembl"].approved_drugs = AsyncMock(
        return_value=[
            {
                "molecule_chembl_id": "CHEMBL1",
                "pref_name": "Drug",
                "max_phase": 4,
                "max_phase_label": "Approved",
                "mechanism": "Inhibitor",
                "oral": True,
                "first_approval": 2010,
            }
        ]
        * 4
    )
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(
        return_value={
            "tractability_labels": ["Small molecule"],
            "drug_count": 4,
        }
    )
    mocks["gnomad"].gene_constraint = AsyncMock(
        return_value={"pLI": 0.99, "loeuf": 0.25, "interpretation": "constrained"}
    )

    out = await assess_target_druggability(DruggabilityInput(uniprot_id="P38398"))
    assert out["druggability_tier"] in {"HOT", "WARM"}
    assert out["evidence"]["drug_count"] == 4


async def test_assess_target_druggability_no_chembl_no_ot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value=None)
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(
        side_effect=RuntimeError("ot fail")
    )
    mocks["gnomad"].gene_constraint = AsyncMock(side_effect=RuntimeError("g fail"))
    mocks["alphafold"].get_prediction = AsyncMock(side_effect=RuntimeError("af fail"))

    out = await assess_target_druggability(DruggabilityInput(uniprot_id="P38398"))
    assert out["druggability_tier"] == "NOT_DRUGGABLE"
    assert out["evidence"]["drug_count"] == 0


async def test_assess_target_druggability_no_drug_count_from_chembl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If chembl approved_drugs returns empty, drug_count should fall back to OT."""
    mocks = _patch_clients(monkeypatch)
    mocks["chembl"].target_by_uniprot = AsyncMock(
        return_value={"chembl_id": "CHEMBL_TGT", "pref_name": "X"}
    )
    mocks["chembl"].approved_drugs = AsyncMock(return_value=[])
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(
        return_value={"tractability_labels": [], "drug_count": 3}
    )
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})

    out = await assess_target_druggability(DruggabilityInput(uniprot_id="P38398"))
    assert out["evidence"]["drug_count"] == 3


async def test_assess_target_druggability_gnomad_constraint_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gnomad.gene_constraint raises after resolve_target supplies the gene symbol."""
    mocks = _patch_clients(monkeypatch)
    mocks["chembl"].target_by_uniprot = AsyncMock(
        return_value={"chembl_id": "CHEMBL_TGT", "pref_name": "BRCA1 protein"}
    )
    mocks["chembl"].approved_drugs = AsyncMock(return_value=[])
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(
        return_value={"tractability_labels": [], "drug_count": 0}
    )
    mocks["gnomad"].gene_constraint = AsyncMock(side_effect=RuntimeError("g fail"))

    out = await assess_target_druggability(DruggabilityInput(uniprot_id="P38398"))
    assert out["druggability_tier"] == "COLD"
    assert out["evidence"]["plddt_mean"] == 85.0


async def test_assess_target_druggability_resolve_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_target raising leaves OT/gnomAD evidence empty without failing the tool."""
    mocks = _patch_clients(monkeypatch)
    mocks["opentargets"].resolve_target = AsyncMock(side_effect=RuntimeError("resolve fail"))
    mocks["chembl"].target_by_uniprot = AsyncMock(
        return_value={"chembl_id": "CHEMBL_TGT", "pref_name": "X"}
    )
    mocks["chembl"].approved_drugs = AsyncMock(
        return_value=[{"molecule_chembl_id": "CHEMBL1", "max_phase": 4}] * 2
    )

    out = await assess_target_druggability(DruggabilityInput(uniprot_id="P38398"))
    assert out["evidence"]["drug_count"] == 2
    assert out["evidence"]["gene_constraint"]["loeuf"] is None


async def test_assess_target_druggability_plddt_non_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_prediction returns non-dict (e.g. list) → plddt stays None."""
    mocks = _patch_clients(monkeypatch)
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value=None)
    mocks["alphafold"].get_prediction = AsyncMock(return_value=[])

    out = await assess_target_druggability(DruggabilityInput(uniprot_id="P38398"))
    assert out["evidence"]["plddt_mean"] is None


# ---------------------------------------------------------------------------
# synthesize_protein_dossier
# ---------------------------------------------------------------------------


async def test_synthesize_protein_dossier_comprehensive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)

    ot_score = MagicMock()
    ot_score.to_dict.return_value = {
        "disease_name": "Cancer",
        "disease_mondo_id": "MONDO:0001",
        "overall_score": 0.8,
    }
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[ot_score])
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(
        return_value={"tractability_labels": ["Small molecule"], "drug_count": 4}
    )
    mocks["disgenet"].gene_disease_associations = AsyncMock(
        return_value=[
            {"disease_name": "Cancer", "score": 0.7},
            {"disease_name": "Other", "disease_id": "MONDO:0002", "score": 0.4},
        ]
    )
    mocks["gnomad"].gene_constraint = AsyncMock(
        return_value={"pLI": 0.99, "loeuf": 0.2, "mis_z": 3.5, "interpretation": "x"}
    )
    mocks["clinvar"].search_gene = AsyncMock(return_value=[{"variation_id": "v1"}])
    mocks["ensembl"].gene_lookup = AsyncMock(
        return_value={
            "ensembl_gene_id": "ENSG0001",
            "description": "BRCA1 protein",
        }
    )
    mocks["ensembl"].orthologs = AsyncMock(
        return_value=[{"species": "mus_musculus", "identity": 95.0}]
    )
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value={"chembl_id": "CHEMBL_TGT"})
    mocks["chembl"].approved_drugs = AsyncMock(
        return_value=[
            {
                "pref_name": "Drug",
                "max_phase": 4,
                "max_phase_label": "Approved",
                "oral": True,
                "first_approval": 2010,
            }
        ]
    )

    out = await synthesize_protein_dossier(
        ProteinDossierInput(uniprot_id="P38398", gene_symbol="BRCA1", depth="comprehensive")
    )
    assert out["target"]["uniprot_id"] == "P38398"
    assert "cross_species_orthologs" in out


async def test_synthesize_protein_dossier_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[])
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["clinvar"].search_gene = AsyncMock(return_value=[])
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value=None)

    out = await synthesize_protein_dossier(
        ProteinDossierInput(uniprot_id="P38398", gene_symbol="BRCA1", depth="brief")
    )
    assert "open_targets_detail" not in out
    assert "cross_species_orthologs" not in out


async def test_synthesize_protein_dossier_with_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["opentargets"].associated_diseases = AsyncMock(side_effect=RuntimeError("e"))
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(side_effect=RuntimeError("e"))
    mocks["disgenet"].gene_disease_associations = AsyncMock(side_effect=RuntimeError("e"))
    mocks["gnomad"].gene_constraint = AsyncMock(side_effect=RuntimeError("e"))
    mocks["clinvar"].search_gene = AsyncMock(side_effect=RuntimeError("e"))
    mocks["ensembl"].gene_lookup = AsyncMock(side_effect=RuntimeError("e"))
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value=None)
    mocks["alphafold"].get_prediction = AsyncMock(side_effect=RuntimeError("e"))

    out = await synthesize_protein_dossier(
        ProteinDossierInput(uniprot_id="P38398", gene_symbol="BRCA1", depth="standard")
    )
    assert out["disease_associations"] == []


async def test_synthesize_protein_dossier_plddt_non_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_prediction returns non-dict → dossier_plddt stays None."""
    mocks = _patch_clients(monkeypatch)
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[])
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["clinvar"].search_gene = AsyncMock(return_value=[])
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value=None)
    mocks["alphafold"].get_prediction = AsyncMock(return_value=[])

    out = await synthesize_protein_dossier(
        ProteinDossierInput(uniprot_id="P38398", gene_symbol="BRCA1", depth="standard")
    )
    assert out["druggability"]["tier"] in {"NOT_DRUGGABLE", "COLD", "WARM", "HOT"}


async def test_synthesize_protein_dossier_chembl_target_no_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ChEMBL target dict missing chembl_id → no drug lookup."""
    mocks = _patch_clients(monkeypatch)
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[])
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["clinvar"].search_gene = AsyncMock(return_value=[])
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value={})  # no chembl_id

    out = await synthesize_protein_dossier(
        ProteinDossierInput(uniprot_id="P38398", gene_symbol="BRCA1", depth="standard")
    )
    assert out["approved_drugs"] == []


async def test_synthesize_protein_dossier_drugs_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[])
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["clinvar"].search_gene = AsyncMock(return_value=[])
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value={"chembl_id": "CTID"})
    mocks["chembl"].approved_drugs = AsyncMock(side_effect=RuntimeError("drugs fail"))

    out = await synthesize_protein_dossier(
        ProteinDossierInput(uniprot_id="P38398", gene_symbol="BRCA1", depth="standard")
    )
    assert out["approved_drugs"] == []


async def test_synthesize_protein_dossier_disgenet_overlapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DisGeNET disease name overlaps with OT disease → merge branch (line 857)."""
    mocks = _patch_clients(monkeypatch)
    ot_score = MagicMock()
    ot_score.to_dict.return_value = {
        "disease_name": "Cancer",
        "disease_mondo_id": "MONDO:0001",
        "overall_score": 0.8,
    }
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[ot_score])
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(
        return_value=[
            {"disease_name": "", "score": 0.5},  # empty name skipped
            {"disease_name": "Cancer", "score": 0.6},  # overlaps with OT
        ]
    )
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["clinvar"].search_gene = AsyncMock(return_value=[])
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value=None)

    out = await synthesize_protein_dossier(
        ProteinDossierInput(uniprot_id="P38398", gene_symbol="BRCA1", depth="standard")
    )
    cancer = next((d for d in out["disease_associations"] if d["disease_name"] == "Cancer"), None)
    assert cancer is not None
    assert cancer["disgenet_score"] == 0.6


async def test_synthesize_protein_dossier_skip_empty_ot_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OT diseases with empty names are skipped (line 847->845)."""
    mocks = _patch_clients(monkeypatch)
    empty_score = MagicMock()
    empty_score.to_dict.return_value = {"disease_name": "", "overall_score": 0.5}
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[empty_score])
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["clinvar"].search_gene = AsyncMock(return_value=[])
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value=None)

    out = await synthesize_protein_dossier(
        ProteinDossierInput(uniprot_id="P38398", gene_symbol="BRCA1", depth="standard")
    )
    assert out["disease_associations"] == []


async def test_synthesize_protein_dossier_target_no_chembl_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chembl_target dict has chembl_id='' → no drug lookup attempted."""
    mocks = _patch_clients(monkeypatch)
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[])
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["clinvar"].search_gene = AsyncMock(return_value=[])
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    # chembl_target is dict but no chembl_id
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value={"chembl_id": ""})

    out = await synthesize_protein_dossier(
        ProteinDossierInput(uniprot_id="P38398", gene_symbol="BRCA1", depth="brief")
    )
    assert out["approved_drugs"] == []


async def test_synthesize_protein_dossier_orthologs_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[])
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["clinvar"].search_gene = AsyncMock(return_value=[])
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    mocks["ensembl"].orthologs = AsyncMock(side_effect=RuntimeError("o fail"))
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value=None)

    out = await synthesize_protein_dossier(
        ProteinDossierInput(uniprot_id="P38398", gene_symbol="BRCA1", depth="comprehensive")
    )
    assert out["cross_species_orthologs"] == []


async def test_synthesize_protein_dossier_resolve_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_target raising still yields a dossier (Ensembl ID falls back to empty)."""
    mocks = _patch_clients(monkeypatch)
    mocks["opentargets"].resolve_target = AsyncMock(side_effect=RuntimeError("resolve fail"))
    mocks["opentargets"].associated_diseases = AsyncMock(return_value=[])
    mocks["opentargets"].drug_count_and_tractability = AsyncMock(return_value={})
    mocks["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})
    mocks["clinvar"].search_gene = AsyncMock(return_value=[])
    mocks["ensembl"].gene_lookup = AsyncMock(return_value={})
    mocks["chembl"].target_by_uniprot = AsyncMock(return_value=None)

    out = await synthesize_protein_dossier(
        ProteinDossierInput(uniprot_id="P38398", gene_symbol="BRCA1")
    )
    assert out["target"]["gene_symbol"] == "BRCA1"


# ---------------------------------------------------------------------------
# map_disease_drug_landscape
# ---------------------------------------------------------------------------


async def test_map_disease_drug_landscape_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)
    # spec=DiseaseRecord so the mock carries the real attribute set:
    # lookup returns a DiseaseRecord (.name), never a .label.
    mondo_result = MagicMock(spec=DiseaseRecord)
    mondo_result.name = "breast cancer"
    mocks["mondo"].lookup = AsyncMock(return_value=mondo_result)

    target = MagicMock()
    target.to_dict.return_value = {"target_gene_symbol": "BRCA1", "tractable": True}
    mocks["opentargets"].associated_targets = AsyncMock(return_value=[target])

    mocks["chembl"].drug_indications = AsyncMock(
        return_value=[
            {"max_phase_for_indication": 4, "molecule_chembl_id": "C1"},
            {"max_phase_for_indication": 3, "molecule_chembl_id": "C2"},
            {"max_phase_for_indication": 2, "molecule_chembl_id": "C3"},
            {"max_phase_for_indication": 1, "molecule_chembl_id": "C4"},
        ]
    )

    out = await map_disease_drug_landscape(
        DiseaseDrugLandscapeInput(disease_mondo_id="MONDO:0007254")
    )
    assert out["disease"]["mondo_id"] == "MONDO:0007254"
    # D3 regression: the human-readable label, not the raw MONDO CURIE.
    assert out["disease"]["name"] == "breast cancer"
    assert out["competitive_intelligence"]["approved_count"] == 1


async def test_map_disease_drug_landscape_mondo_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["mondo"].lookup = AsyncMock(side_effect=RuntimeError("m fail"))
    mocks["opentargets"].associated_targets = AsyncMock(return_value=[])
    mocks["chembl"].drug_indications = AsyncMock(return_value=[])

    out = await map_disease_drug_landscape(
        DiseaseDrugLandscapeInput(disease_mondo_id="MONDO:0007254")
    )
    assert out["disease"]["name"] == ""


async def test_map_disease_drug_landscape_chembl_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)
    mondo_result = MagicMock(spec=DiseaseRecord)
    mondo_result.name = "X"
    mocks["mondo"].lookup = AsyncMock(return_value=mondo_result)
    mocks["opentargets"].associated_targets = AsyncMock(side_effect=RuntimeError("ot fail"))
    mocks["chembl"].drug_indications = AsyncMock(side_effect=RuntimeError("c fail"))

    out = await map_disease_drug_landscape(
        DiseaseDrugLandscapeInput(disease_mondo_id="MONDO:0007254")
    )
    assert out["drug_landscape"]["approved_drugs"] == []


# ---------------------------------------------------------------------------
# classify_variant_acmg
# ---------------------------------------------------------------------------


async def test_classify_variant_acmg_pathogenic(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _patch_clients(monkeypatch)
    # VEP with stop_gained → PVS1
    mocks["ensembl"].vep_hgvs = AsyncMock(
        return_value=[
            {
                "canonical": True,
                "consequence_terms": ["stop_gained"],
                "seq_region_name": "17",
                "start": 12345,
                "allele_string": "G/A",
            }
        ]
    )
    mocks["clinvar"].search_by_hgvs = AsyncMock(
        return_value=[
            {
                "classification": "Pathogenic",
                "review_status": "criteria provided",
            }
        ]
    )
    mocks["gnomad"].variant_frequencies = AsyncMock(
        return_value={"alphamissense_score": 0.9, "global_af": 1e-6}
    )
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={"loeuf": 0.2})

    out = await classify_variant_acmg(
        ACMGVariantInput(hgvs="BRCA1:c.181T>G", inheritance_pattern="AD")
    )
    assert "PVS1" in out["criteria_met"]
    assert "Pathogenic" in out["draft_classification"]


async def test_classify_variant_acmg_benign(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(
        return_value=[
            {
                "canonical": True,
                "consequence_terms": ["synonymous_variant"],
                "seq_region_name": "17",
                "start": 12345,
                "allele_string": "G/A",
            }
        ]
    )
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(
        return_value={"alphamissense_score": 0.1, "global_af": 0.1}
    )
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={"loeuf": 0.5})

    out = await classify_variant_acmg(ACMGVariantInput(hgvs="BRCA1:c.18T>G"))
    assert "BP7" in out["criteria_met"] or "BS1" in out["criteria_met"]
    assert "Benign" in out["draft_classification"]


async def test_classify_variant_acmg_clinvar_pathogenic_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No PVS1, but ClinVar Pathogenic → 'Pathogenic (ClinVar-supported)'."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(return_value=[])
    mocks["clinvar"].search_by_hgvs = AsyncMock(
        return_value=[{"classification": "Pathogenic", "review_status": "x"}]
    )
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})

    out = await classify_variant_acmg(ACMGVariantInput(hgvs="BRCA1:c.18T>G"))
    assert "ClinVar-supported" in out["draft_classification"]


async def test_classify_variant_acmg_clinvar_likely_pathogenic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(return_value=[])
    mocks["clinvar"].search_by_hgvs = AsyncMock(
        return_value=[{"classification": "Likely pathogenic", "review_status": "x"}]
    )
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})

    out = await classify_variant_acmg(ACMGVariantInput(hgvs="BRCA1:c.18T>G"))
    assert "Likely Pathogenic (ClinVar-supported)" == out["draft_classification"]


async def test_classify_variant_acmg_pvs1_with_high_loeuf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PVS1 with LOEUF >= 0.35 downgraded."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(
        return_value=[
            {
                "canonical": True,
                "consequence_terms": ["stop_gained"],
                "seq_region_name": "17",
                "start": 12345,
                "allele_string": "G/A",
            }
        ]
    )
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={"global_af": 1e-6})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={"loeuf": 0.5})

    out = await classify_variant_acmg(ACMGVariantInput(hgvs="BRCA1:c.18T>G"))
    assert "downgrade" in out["criteria_met"]["PVS1"]["evidence"]


async def test_classify_variant_acmg_with_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(side_effect=RuntimeError("e"))
    mocks["clinvar"].search_by_hgvs = AsyncMock(side_effect=RuntimeError("e"))
    mocks["gnomad"].variant_frequencies = AsyncMock(side_effect=RuntimeError("e"))
    mocks["gnomad"].gene_constraint = AsyncMock(side_effect=RuntimeError("e"))

    out = await classify_variant_acmg(ACMGVariantInput(hgvs="BRCA1:c.18T>G"))
    assert out["draft_classification"] == "Variant of Uncertain Significance"


async def test_classify_variant_acmg_no_gnomad_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no gnomad ID can be built, no variant_frequencies call."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(return_value=[])
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})

    out = await classify_variant_acmg(ACMGVariantInput(hgvs="X:c.18T>G"))
    assert "criteria_met" in out


async def test_classify_variant_acmg_gnomad_var_freq_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gnomad.variant_frequencies raises during classify (line 1090-1091)."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(
        return_value=[
            {
                "canonical": True,
                "consequence_terms": ["missense_variant"],
                "seq_region_name": "17",
                "start": 12345,
                "allele_string": "G/A",
            }
        ]
    )
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(side_effect=RuntimeError("g fail"))
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})

    out = await classify_variant_acmg(ACMGVariantInput(hgvs="BRCA1:c.18T>G"))
    assert "criteria_met" in out


async def test_classify_variant_acmg_pathogenic_strong_strong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hit final classification line 1165: 'Pathogenic' branch with PVS1 + Strong P*.

    The evidence-starts-with-P condition relies on internal criteria construction.
    Patch _acmg_strength to make PM2 a 'Strong' criterion with evidence starting 'P'.
    """
    import alphafold_sovereign.tools.precision_medicine as pm_mod

    original_strength = pm_mod._acmg_strength
    original_gnomad_to_acmg = pm_mod._gnomad_to_acmg

    def fake_strength(code: str) -> str:
        if code == "PM2":
            return "Strong"
        return original_strength(code)

    def fake_gnomad_to_acmg(af: float | None) -> dict[str, str]:
        # Inject evidence starting with "P"
        if af is None:
            return {}
        return {"PM2": "Pathogenic-leaning evidence: af present"}

    monkeypatch.setattr(pm_mod, "_acmg_strength", fake_strength)
    monkeypatch.setattr(pm_mod, "_gnomad_to_acmg", fake_gnomad_to_acmg)

    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(
        return_value=[
            {
                "canonical": True,
                "consequence_terms": ["stop_gained"],
                "seq_region_name": "17",
                "start": 12345,
                "allele_string": "G/A",
            }
        ]
    )
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={"global_af": 1e-6})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={"loeuf": 0.2})

    out = await classify_variant_acmg(ACMGVariantInput(hgvs="BRCA1:c.18T>G"))
    assert out["draft_classification"] == "Pathogenic"


async def test_classify_variant_acmg_likely_pathogenic_two_strong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hit line 1167: 'Likely Pathogenic' branch (no PVS1, ≥2 Strong P*)."""
    import alphafold_sovereign.tools.precision_medicine as pm_mod

    def fake_strength(code: str) -> str:
        if code in {"PM2", "PP3"}:
            return "Strong"
        return "Supporting"

    def fake_gnomad_to_acmg(af: float | None) -> dict[str, str]:
        return {"PM2": "Pathogenic evidence: rare"}

    def fake_am_to_acmg(am_score: float | None) -> dict[str, str]:
        return {"PP3": "Pathogenic evidence: AM high"}

    monkeypatch.setattr(pm_mod, "_acmg_strength", fake_strength)
    monkeypatch.setattr(pm_mod, "_gnomad_to_acmg", fake_gnomad_to_acmg)
    monkeypatch.setattr(pm_mod, "_am_to_acmg_evidence", fake_am_to_acmg)

    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(
        return_value=[
            {
                "canonical": True,
                "consequence_terms": ["missense_variant"],
                "seq_region_name": "17",
                "start": 12345,
                "allele_string": "G/A",
            }
        ]
    )
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(
        return_value={"alphamissense_score": 0.9, "global_af": 1e-6}
    )
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})

    out = await classify_variant_acmg(ACMGVariantInput(hgvs="BRCA1:c.18T>G"))
    assert out["draft_classification"] == "Likely Pathogenic"


async def test_classify_variant_acmg_canonical_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VEP results contain non-canonical entries that are skipped."""
    mocks = _patch_clients(monkeypatch)
    mocks["ensembl"].vep_hgvs = AsyncMock(
        return_value=[
            {
                "canonical": False,
                "consequence_terms": ["stop_gained"],
            },
            {
                "canonical": True,
                "consequence_terms": ["synonymous_variant"],
                "seq_region_name": "1",
                "start": 100,
                "allele_string": "A/G",
            },
        ]
    )
    mocks["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    mocks["gnomad"].variant_frequencies = AsyncMock(return_value={})
    mocks["gnomad"].gene_constraint = AsyncMock(return_value={})

    out = await classify_variant_acmg(ACMGVariantInput(hgvs="BRCA1:c.18T>G"))
    assert "BP7" in out["criteria_met"]


# ---------------------------------------------------------------------------
# find_drug_repurposing_candidates
# ---------------------------------------------------------------------------


async def test_find_drug_repurposing_candidates_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)

    target = MagicMock()
    target.uniprot_id = "P38398"
    target.to_dict.return_value = {
        "overall_score": 0.8,
        "target_gene_symbol": "BRCA1",
        "uniprot_id": "P38398",
    }
    mocks["opentargets"].associated_targets = AsyncMock(return_value=[target])
    mocks["chembl"].find_repurposable_drugs = AsyncMock(
        return_value=[
            {
                "molecule_chembl_id": "CHEMBL1",
                "pref_name": "Drug",
                "max_phase": 4,
                "max_phase_label": "Approved",
                "mechanism": "Inhibitor",
                "oral": True,
                "first_approval": 2010,
            }
        ]
    )

    out = await find_drug_repurposing_candidates(
        DrugRepurposingInput(disease_mondo_id="MONDO:0007254")
    )
    assert out["candidate_count"] >= 1


async def test_find_drug_repurposing_no_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    mocks = _patch_clients(monkeypatch)
    mocks["opentargets"].associated_targets = AsyncMock(return_value=[])
    out = await find_drug_repurposing_candidates(
        DrugRepurposingInput(disease_mondo_id="MONDO:0007254")
    )
    assert out["candidates"] == []


async def test_find_drug_repurposing_target_no_uniprot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Target without uniprot is skipped in lookup."""
    mocks = _patch_clients(monkeypatch)
    target = MagicMock()
    target.uniprot_id = ""
    target.to_dict.return_value = {
        "overall_score": 0.5,
        "target_gene_symbol": "X",
        "uniprot_id": "",
    }
    mocks["opentargets"].associated_targets = AsyncMock(return_value=[target])

    out = await find_drug_repurposing_candidates(
        DrugRepurposingInput(disease_mondo_id="MONDO:0007254")
    )
    assert out["candidates"] == []


async def test_find_drug_repurposing_chembl_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _patch_clients(monkeypatch)
    target = MagicMock()
    target.uniprot_id = "P12345"
    target.to_dict.return_value = {
        "overall_score": 0.5,
        "target_gene_symbol": "X",
        "uniprot_id": "P12345",
    }
    mocks["opentargets"].associated_targets = AsyncMock(return_value=[target])
    mocks["chembl"].find_repurposable_drugs = AsyncMock(side_effect=RuntimeError("e"))

    out = await find_drug_repurposing_candidates(
        DrugRepurposingInput(disease_mondo_id="MONDO:0007254")
    )
    assert out["candidates"] == []


async def test_find_drug_repurposing_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same drug ID across targets should be deduplicated."""
    mocks = _patch_clients(monkeypatch)

    t1 = MagicMock()
    t1.uniprot_id = "P1"
    t1.to_dict.return_value = {
        "overall_score": 0.7,
        "target_gene_symbol": "G1",
        "uniprot_id": "P1",
    }
    t2 = MagicMock()
    t2.uniprot_id = "P2"
    t2.to_dict.return_value = {
        "overall_score": 0.6,
        "target_gene_symbol": "G2",
        "uniprot_id": "P2",
    }
    mocks["opentargets"].associated_targets = AsyncMock(return_value=[t1, t2])

    shared_drug = {
        "molecule_chembl_id": "SHARED",
        "pref_name": "Drug",
        "max_phase": 3,
        "max_phase_label": "P3",
        "mechanism": "x",
        "oral": False,
        "first_approval": None,
    }
    mocks["chembl"].find_repurposable_drugs = AsyncMock(return_value=[shared_drug])

    out = await find_drug_repurposing_candidates(
        DrugRepurposingInput(disease_mondo_id="MONDO:0007254")
    )
    assert out["candidate_count"] == 1


async def test_find_drug_repurposing_target_uses_dict_not_attr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover the branch where target is a dict (not an object with uniprot_id attr)."""
    mocks = _patch_clients(monkeypatch)
    target_dict = {
        "overall_score": 0.6,
        "target_gene_symbol": "G",
        "uniprot_id": "P1",
    }
    mocks["opentargets"].associated_targets = AsyncMock(return_value=[target_dict])
    mocks["chembl"].find_repurposable_drugs = AsyncMock(
        return_value=[
            {
                "molecule_chembl_id": "C1",
                "pref_name": "Drug",
                "max_phase": 2,
                "max_phase_label": "P2",
                "mechanism": "x",
                "oral": False,
                "first_approval": None,
            }
        ]
    )

    out = await find_drug_repurposing_candidates(
        DrugRepurposingInput(disease_mondo_id="MONDO:0007254")
    )
    assert out["candidate_count"] == 1


async def test_find_drug_repurposing_gather_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a target raises within gather, it is skipped."""
    mocks = _patch_clients(monkeypatch)
    target = MagicMock()
    target.uniprot_id = "P1"
    target.to_dict.return_value = {
        "overall_score": 0.5,
        "target_gene_symbol": "G",
        "uniprot_id": "P1",
    }
    mocks["opentargets"].associated_targets = AsyncMock(return_value=[target])

    # Pump exception path via gather's return_exceptions
    import asyncio

    original_gather = asyncio.gather

    async def fake_gather(*coros: Any, **kwargs: Any) -> Any:
        # Force the gather call inside the candidate building loop to
        # return exception objects (the first call gathers our helpers)
        called_for_helpers = len(coros) >= 1 and len(kwargs) > 0 and kwargs.get("return_exceptions")
        if called_for_helpers and len(coros) == 1:
            # Drain the coro before returning
            for c in coros:
                try:
                    await c
                except Exception:
                    pass
            return [RuntimeError("inner fail")]
        return await original_gather(*coros, **kwargs)

    monkeypatch.setattr("alphafold_sovereign.tools.precision_medicine.asyncio.gather", fake_gather)

    out = await find_drug_repurposing_candidates(
        DrugRepurposingInput(disease_mondo_id="MONDO:0007254")
    )
    assert out["candidate_count"] == 0
