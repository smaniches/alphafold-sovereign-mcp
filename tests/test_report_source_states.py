# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Fabricated evidence-response regression tests; no clinical case data."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphafold_sovereign.tools import precision_medicine as pm


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Keep every external service offline while exercising real report orchestration."""
    clients: dict[str, MagicMock] = {}
    for name in ("ensembl", "clinvar", "gnomad", "disgenet", "opentargets", "chembl", "alphafold"):
        client = MagicMock()
        clients[name] = client
        monkeypatch.setattr(pm, f"_{name}", lambda value=client: value)
    clients["ensembl"].vep_hgvs = AsyncMock(return_value=[])
    clients["ensembl"].gene_lookup = AsyncMock(return_value={})
    clients["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    clients["gnomad"].variant_frequencies = AsyncMock(return_value={})
    clients["gnomad"].gene_constraint = AsyncMock(return_value={})
    clients["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    clients["opentargets"].associated_diseases = AsyncMock(return_value=[])
    clients["chembl"].find_repurposable_drugs = AsyncMock(return_value=[])
    clients["alphafold"].alphamissense_score = AsyncMock(return_value=None)
    return clients


def _response(value: Any) -> AsyncMock:
    """Represent genuine exceptions distinctly from returned exception-like data."""
    if isinstance(value, Exception):
        return AsyncMock(side_effect=value)
    return AsyncMock(return_value=value)


_VERSIONED_QUERY = "NM_999999.1(SYNTHX):c.42A>G"


def _locus_row(**locus: Any) -> dict[str, Any]:
    """A VEP row whose synthetic locus is self-consistent unless overridden."""
    return {
        "locus": {
            "input": _VERSIONED_QUERY,
            "assembly_name": "GRCh38",
            "seq_region_name": "1",
            "start": 42,
            "end": 42,
            "strand": 1,
            "allele_string": "A/G",
            "vcf_string": "1-42-A-G",
            **locus,
        }
    }


def _echoing(hgvs: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """VEP rows as the client returns them for ``hgvs``: each names it as the input VEP mapped."""
    return [{**row, "locus": {"input": hgvs}} for row in rows]


async def _report(hgvs: str = "SYNTHX:c.42A>G", *, drug_context: bool = False) -> dict[str, Any]:
    return await pm.generate_variant_clinical_report(
        pm.VariantClinicalReportInput(hgvs=hgvs, include_drug_context=drug_context)
    )


@pytest.mark.parametrize(
    ("hgvs", "vep", "clinvar", "expected"),
    [
        ("SYNTHX:c.42A>G", [], [], "SYNTHX"),
        ("NM_999999.1(SYNTHX):c.42A>G", [], [], "SYNTHX"),
        (
            "NM_999999.1:c.42A>G",
            [],
            [{"exact_change_match": True, "gene_symbol": "SYNTHX"}],
            "SYNTHX",
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"hgvsc": "NM_999999.1:c.42A>G", "gene_symbol": "SYNTHX"}],
            [],
            "SYNTHX",
        ),
        (
            "NM_999999.1:c.42A>G",
            [],
            [{"candidate_change_match": True, "gene_symbol": "SYNTHX"}],
            None,
        ),
        (
            "NM_999999.1:c.42A>G",
            [
                {"transcript_id": "NM_999999.1", "gene_symbol": "SYNTHX"},
                {"transcript_id": "NM_999999.1", "gene_symbol": "OTHERX"},
            ],
            [],
            None,
        ),
        (
            "NM_999999.1(SYNTHX):c.42A>G",
            [{"transcript_id": "NM_999999.1", "gene_symbol": "OTHERX"}],
            [],
            None,
        ),
        ("NM_999999.1:c.42A>G", [], [{"exact_change_match": True, "gene_symbol": None}], None),
        ("NM_999999.1:c.42A>G", [{"gene_symbol": 42}], [], None),
        ("NM_999999.1:c.42A>G", [], [{"exact_change_match": True, "gene_symbol": " "}], None),
        ("NM_999999.1:c.42A>G", [], [], None),
    ],
)
def test_report_gene_is_not_guessed(
    hgvs: str, vep: list[dict[str, Any]], clinvar: list[dict[str, Any]], expected: str | None
) -> None:
    assert pm._report_gene_from_sources(hgvs, vep, clinvar) == expected


@pytest.mark.parametrize(
    ("vep", "clinvar", "expected"),
    [
        (None, None, "invalid_response"),
        ({"malformed": True}, ["invalid"], "invalid_response"),
        ([], [], "no_data"),
        ([{"locus": {"input": "NM_999999.1:c.42A>G"}}], [{}], "ok"),
    ],
)
async def test_report_source_rows_are_not_mislabelled(
    sources: dict[str, MagicMock], vep: Any, clinvar: Any, expected: str
) -> None:
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=vep)
    sources["clinvar"].search_by_hgvs = AsyncMock(return_value=clinvar)
    report = await _report(hgvs="NM_999999.1:c.42A>G")
    assert report["data_sources_status"]["ensembl_vep"] == expected
    assert report["data_sources_status"]["clinvar"] == expected
    assert report["clinvar"]["found"] is False
    assert report["clinical_tier"] == "NOT_ASSESSED"


@pytest.mark.parametrize(
    ("variant", "constraint", "expected", "expected_lookup"),
    [
        (None, None, "invalid_response", "invalid_response"),
        (["malformed"], ["malformed"], "invalid_response", "invalid_response"),
        ({}, {}, "no_data", "no_frequency_data"),
        ({"global_af": 0.002}, {"loeuf": 0.75}, "ok", "found"),
        (
            {"found": False, "global_af": None},
            {"constraint_available": False, "gene_symbol": "SYNTHX"},
            "no_data",
            "not_found",
        ),
        (
            {"found": True, "global_af": None},
            {"constraint_available": False, "gene_symbol": "SYNTHX"},
            "no_data",
            "no_frequency_data",
        ),
        (
            {"found": True, "global_af": 0.002},
            {"constraint_available": True, "loeuf": 0.75},
            "ok",
            "found",
        ),
        (RuntimeError("variant down"), RuntimeError("constraint down"), "failed", "failed"),
    ],
)
async def test_report_gnomad_outcomes(
    sources: dict[str, MagicMock],
    variant: Any,
    constraint: Any,
    expected: str,
    expected_lookup: str,
) -> None:
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=[_locus_row()])
    sources["gnomad"].variant_frequencies = _response(variant)
    sources["gnomad"].gene_constraint = _response(constraint)
    report = await _report(_VERSIONED_QUERY)
    sources["gnomad"].variant_frequencies.assert_awaited_once_with("1-42-A-G")
    assert report["data_sources_status"]["gnomad"] == expected
    assert report["data_sources_status"]["gnomad_constraint"] == expected
    frequency = report["unassessed_evidence"]["population_frequency"]
    assert frequency["lookup_status"] == expected_lookup
    assert frequency["detail"]
    assert report["acmg_criteria_draft"]["criteria"] == {}
    assert report["clinical_tier"] == "NOT_ASSESSED"


async def test_report_gene_relative_query_is_not_looked_up(
    sources: dict[str, MagicMock],
) -> None:
    """A gene-relative expression does not pin one allele, whatever VEP maps."""
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=[_locus_row(input="SYNTHX:c.42A>G")])
    report = await _report("SYNTHX:c.42A>G")
    sources["gnomad"].variant_frequencies.assert_not_awaited()
    assert report["data_sources_status"]["ensembl_vep"] == "ok"
    assert report["data_sources_status"]["gnomad"] == "skipped"
    frequency = report["unassessed_evidence"]["population_frequency"]
    assert frequency["lookup_status"] == "not_attempted"
    assert frequency["variant_id"] is None
    assert report["population_genetics"]["global_af"] is None


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (None, "invalid_response"),
        (["malformed"], "invalid_response"),
        ([], "no_data"),
        ([{"disease_name": "synthetic"}], "ok"),
        (RuntimeError("disgenet down"), "failed"),
    ],
)
async def test_report_disgenet_outcomes(
    sources: dict[str, MagicMock], response: Any, expected: str
) -> None:
    sources["disgenet"].gene_disease_associations = _response(response)
    report = await _report()
    assert report["data_sources_status"]["disgenet"] == expected
    assert report["disease_associations"]["disgenet_top_associations"] == (
        response if expected == "ok" else []
    )


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (None, "invalid_response"),
        ({"malformed": True}, "invalid_response"),
        (["malformed"], "invalid_response"),
        ([], "no_data"),
        ([{"disease_name": "synthetic"}], "ok"),
        (RuntimeError("open targets down"), "failed"),
    ],
)
async def test_report_open_targets_outcomes(
    sources: dict[str, MagicMock], response: Any, expected: str
) -> None:
    sources["ensembl"].gene_lookup = AsyncMock(return_value={"ensembl_gene_id": "ENSGSYNTH"})
    sources["opentargets"].associated_diseases = _response(response)
    report = await _report()
    assert report["data_sources_status"]["open_targets"] == expected


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (None, "invalid_response"),
        ({"ensembl_gene_id": 44}, "invalid_response"),
        ({}, "no_data"),
        ({"ensembl_gene_id": "ENSGSYNTH"}, "ok"),
        (RuntimeError("gene service down"), "failed"),
    ],
)
async def test_report_gene_lookup_outcomes(
    sources: dict[str, MagicMock], response: Any, expected: str
) -> None:
    sources["ensembl"].gene_lookup = _response(response)
    report = await _report()
    assert report["data_sources_status"]["ensembl_gene_lookup"] == expected


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (None, "invalid_response"),
        (["malformed"], "invalid_response"),
        ([], "no_data"),
        ([{"molecule_chembl_id": "CHEMBLSYNTH"}], "ok"),
        (RuntimeError("chembl down"), "failed"),
    ],
)
async def test_report_chembl_outcomes(
    sources: dict[str, MagicMock], response: Any, expected: str
) -> None:
    sources["ensembl"].gene_lookup = AsyncMock(
        return_value={"ensembl_gene_id": "", "uniprot_ids": ["P00001"]}
    )
    sources["chembl"].find_repurposable_drugs = _response(response)
    report = await _report(drug_context=True)
    assert report["data_sources_status"]["chembl"] == expected
    assert len(report["drug_context"]["repurposing_candidates"]) == (1 if expected == "ok" else 0)


@pytest.mark.parametrize(
    ("drug_gene", "expected"),
    [
        (None, "invalid_response"),
        ({"uniprot_ids": "P00001"}, "invalid_response"),
        ({"uniprot_ids": None}, "invalid_response"),
        ({"uniprot_ids": ["P00001", None]}, "invalid_response"),
        ({"uniprot_ids": []}, "no_data"),
    ],
)
async def test_report_drug_gene_lookup_is_validated(
    sources: dict[str, MagicMock], drug_gene: Any, expected: str
) -> None:
    sources["ensembl"].gene_lookup = AsyncMock(side_effect=[{"ensembl_gene_id": ""}, drug_gene])
    report = await _report(drug_context=True)
    assert report["data_sources_status"]["chembl"] == expected


@pytest.mark.parametrize(
    ("query", "vep", "clinvar", "expected_gene"),
    [
        ("NM_999999.1(SYNTHX):c.42A>G", [], [], "SYNTHX"),
        (
            "NM_999999.1:c.42A>G",
            [],
            [{"exact_change_match": True, "gene_symbol": "SYNTHX"}],
            "SYNTHX",
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"hgvsc": "NM_999999.1:c.42A>G", "gene_symbol": "SYNTHX"}],
            [],
            "SYNTHX",
        ),
        (
            "NM_999999.1:c.42A>G",
            [
                {"transcript_id": "NM_999999.1", "gene_symbol": "SYNTHX"},
                {"transcript_id": "NM_999999.1", "gene_symbol": "OTHERX"},
            ],
            [],
            None,
        ),
    ],
)
async def test_transcript_queries_retain_verified_gene_context(
    sources: dict[str, MagicMock],
    query: str,
    vep: list[dict[str, Any]],
    clinvar: list[dict[str, Any]],
    expected_gene: str | None,
) -> None:
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=_echoing(query, vep))
    sources["clinvar"].search_by_hgvs = AsyncMock(return_value=clinvar)
    report = await _report(hgvs=query)
    assert report["gene_symbol"] == expected_gene
    if expected_gene:
        sources["gnomad"].gene_constraint.assert_awaited_once_with(expected_gene)
        sources["disgenet"].gene_disease_associations.assert_awaited_once()
    else:
        sources["gnomad"].gene_constraint.assert_not_awaited()
        sources["disgenet"].gene_disease_associations.assert_not_awaited()


async def test_report_caller_supplied_variant_id_is_still_looked_up(
    sources: dict[str, MagicMock],
) -> None:
    """An input that is itself a gnomAD-style ID keeps working; its assembly is unverified."""
    sources["ensembl"].vep_hgvs = AsyncMock(side_effect=RuntimeError("not an HGVS expression"))
    sources["gnomad"].variant_frequencies = AsyncMock(
        return_value={"found": True, "global_af": 0.002, "cohort": "exome"}
    )
    report = await _report("chr1:42:A:G")
    sources["gnomad"].variant_frequencies.assert_awaited_once_with("1-42-A-G")
    assert report["data_sources_status"]["gnomad"] == "ok"
    assert report["population_genetics"]["global_af"] == 0.002
    assert report["population_genetics"]["cohort"] == "exome"
    frequency = report["unassessed_evidence"]["population_frequency"]
    assert frequency["mapping_basis"] == "caller_supplied_variant_id"
    assert frequency["reference_genome"] is None
    assert frequency["lookup_status"] == "found"
    assert "assembly is not verified" in frequency["detail"]
    assert report["acmg_criteria_draft"]["criteria"] == {}


async def test_report_caller_supplied_indel_absence_names_its_own_provenance(
    sources: dict[str, MagicMock],
) -> None:
    """An indel ID from the caller that gnomAD does not hold is not explained through HGVS."""
    sources["ensembl"].vep_hgvs = AsyncMock(side_effect=RuntimeError("not an HGVS expression"))
    sources["gnomad"].variant_frequencies = AsyncMock(
        return_value={"variant_id": "7-117559591-TCTT-T", "found": False, "global_af": None}
    )
    report = await _report("chr7:117559591:TCTT:T")
    sources["gnomad"].variant_frequencies.assert_awaited_once_with("7-117559591-TCTT-T")
    frequency = report["unassessed_evidence"]["population_frequency"]
    assert frequency["mapping_basis"] == "caller_supplied_variant_id"
    assert frequency["lookup_status"] == "not_found_representation_unverified"
    assert "HGVS" not in frequency["detail"]
    assert "the supplied identifier was not checked against that alignment" in frequency["detail"]
    assert "neither absence nor an allele frequency of 0" in frequency["detail"]
    assert "supplied by the caller" in frequency["detail"]


@pytest.mark.parametrize(
    ("vep", "status", "reason"),
    [
        (RuntimeError("vep down"), "failed", "request failed or was rejected"),
        ({"malformed": True}, "invalid_response", "response could not be validated"),
        ([], "no_data", "returned no genomic mapping"),
    ],
)
async def test_report_unmapped_reason_keeps_the_vep_outcome(
    sources: dict[str, MagicMock], vep: Any, status: str, reason: str
) -> None:
    """A failed or invalid VEP call is not reported as a mapping that came back empty."""
    sources["ensembl"].vep_hgvs = _response(vep)
    report = await _report(_VERSIONED_QUERY)
    sources["gnomad"].variant_frequencies.assert_not_awaited()
    assert report["data_sources_status"]["ensembl_vep"] == status
    frequency = report["unassessed_evidence"]["population_frequency"]
    assert frequency["lookup_status"] == "not_attempted"
    assert reason in frequency["detail"]
    assert ("returned no genomic mapping" in frequency["detail"]) is (status == "no_data")


_TRANSCRIPT_QUERY = "NM_999999.1:c.42A>G"
_NO_FUNCTIONAL_CONSEQUENCE = {
    "consequence_terms": [],
    "impact": "",
    "amino_acids": "",
    "hgvsp": "",
    "sift_prediction": "",
    "sift_score": None,
    "polyphen_prediction": "",
    "polyphen_score": None,
    "cadd_phred": None,
    "cadd_phred_note": pm._CADD_NOT_RETRIEVED,
}


def _vep_values(predictions: dict[str, Any]) -> set[Any]:
    """Values read from VEP for the predictor block (the fixed CADD note is not one)."""
    return {value for key, value in predictions["ensembl_vep"].items() if key != "cadd_phred_note"}


def _usable_vep_row(echoed: str | None) -> dict[str, Any]:
    """A self-consistent VEP row that feeds every VEP-derived output when it is used.

    A start-lost substitution on the transcript ``_TRANSCRIPT_QUERY`` names:
    gene context, a loss-of-function signal, predictor outputs, an
    AlphaMissense key and a genomic mapping. ``echoed`` is the input VEP names.
    """
    return {
        **_locus_row(input=echoed),
        "canonical": True,
        "gene_symbol": "SYNTHX",
        "transcript_id": "NM_999999.1",
        "consequence_terms": ["start_lost"],
        "impact": "HIGH",
        "amino_acids": "M/V",
        "protein_start": 1,
        "hgvsp": "p.Met1?",
        "swissprot": "P00001.1",
        "sift_prediction": "deleterious",
        "sift_score": 0.0,
        "polyphen_prediction": "probably_damaging",
        "polyphen_score": 0.99,
        # The Ensembl client never reports CADD (it is not requested). The
        # value is here to show that the tools do not pass one through.
        "cadd_phred": 35.0,
    }


async def _run(report_kind: str, hgvs: str) -> tuple[dict[str, Any], str]:
    """One of the two variant tools, and its status key for the gnomAD variant lookup."""
    if report_kind == "variant":
        return await _report(hgvs), "gnomad"
    return await pm.classify_variant_acmg(pm.ACMGVariantInput(hgvs=hgvs)), "gnomad_variant"


@pytest.mark.parametrize("report_kind", ["variant", "acmg"])
async def test_vep_row_naming_the_query_feeds_every_vep_derived_output(
    sources: dict[str, MagicMock], report_kind: str
) -> None:
    """Control for the next test: the same row is used when VEP names the query."""
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=[_usable_vep_row(_TRANSCRIPT_QUERY)])
    out, gnomad_key = await _run(report_kind, _TRANSCRIPT_QUERY)

    assert out["data_sources_status"]["ensembl_vep"] == "ok"
    assert out["gene_symbol"] == "SYNTHX"
    sources["gnomad"].variant_frequencies.assert_awaited_once_with("1-42-A-G")
    sources["gnomad"].gene_constraint.assert_awaited_once_with("SYNTHX")
    sources["alphafold"].alphamissense_score.assert_awaited_once_with("P00001", "M1V")
    predictions = out["unassessed_evidence"]["computational_predictions"]
    assert predictions["ensembl_vep"]["transcript_id"] == "NM_999999.1"
    assert predictions["ensembl_vep"]["sift_prediction"] == "deleterious"
    # AF-11: CADD is not retrieved, and the output says so instead of a bare null.
    assert predictions["ensembl_vep"]["cadd_phred"] is None
    assert predictions["ensembl_vep"]["cadd_phred_note"].startswith("NOT_RETRIEVED")
    if report_kind == "variant":
        assert out["functional_consequence"]["hgvsp"] == "p.Met1?"
        assert out["functional_consequence"]["cadd_phred"] is None
        assert out["functional_consequence"]["cadd_phred_note"].startswith("NOT_RETRIEVED")
        assert out["functional_consequence"]["consequence_terms"] == ["start_lost"]
        assert set(out["acmg_criteria_draft"]["criteria"]) == {"PVS1"}
    else:
        assert set(out["candidate_criteria"]) == {"PVS1"}
    assert out["data_sources_status"][gnomad_key] == "no_data"


@pytest.mark.parametrize("report_kind", ["variant", "acmg"])
@pytest.mark.parametrize(
    "echoed", ["NM_999999.1:c.1A>G", None], ids=["another_expression", "no_input"]
)
async def test_vep_reply_that_does_not_name_the_query_is_an_invalid_response(
    sources: dict[str, MagicMock], report_kind: str, echoed: str | None
) -> None:
    """Nothing is read from a VEP hit that names another input, or none.

    The hit is for another variant of the queried transcript, so its gene,
    its loss-of-function signal, its predictor outputs and its mapping would
    all be attributed to the query. ClinVar is asked independently and kept.
    """
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=[_usable_vep_row(echoed)])
    sources["clinvar"].search_by_hgvs = AsyncMock(
        return_value=[
            {"exact_change_match": True, "classification": "Pathogenic", "variation_id": "12345"}
        ]
    )
    out, gnomad_key = await _run(report_kind, _TRANSCRIPT_QUERY)

    status = out["data_sources_status"]
    assert status["ensembl_vep"] == "invalid_response"
    assert status[gnomad_key] == "skipped"
    assert status["gnomad_constraint"] == "skipped"
    assert status["alphamissense"] == "skipped_upstream_invalid"
    sources["gnomad"].variant_frequencies.assert_not_awaited()
    sources["gnomad"].gene_constraint.assert_not_awaited()
    sources["alphafold"].alphamissense_score.assert_not_awaited()
    assert out["gene_symbol"] is None

    evidence = out["unassessed_evidence"]
    frequency = evidence["population_frequency"]
    assert frequency["lookup_status"] == "not_attempted"
    assert frequency["variant_id"] is None
    assert frequency["mapping_basis"] is None
    assert "response could not be validated" in frequency["detail"]
    predictions = evidence["computational_predictions"]
    assert _vep_values(predictions) == {None}
    assert predictions["alphamissense"] == {
        "status": "skipped_upstream_invalid",
        "protein_variant": None,
        "score": None,
        "source_class": None,
    }

    assert status["clinvar"] == "ok"
    if report_kind == "variant":
        assert out["functional_consequence"] == _NO_FUNCTIONAL_CONSEQUENCE
        assert out["acmg_criteria_draft"]["criteria"] == {}
        assert out["clinvar"]["found"] is True
        assert out["clinvar"]["classification"] == "Pathogenic"
        assert out["clinvar"]["variation_id"] == "12345"
    else:
        assert out["candidate_criteria"] == {}
        assert out["clinvar_reference"]["found"] is True
        assert out["clinvar_reference"]["classification"] == "Pathogenic"
        assert out["clinvar_reference"]["variation_id"] == "12345"


@pytest.mark.parametrize("report_kind", ["variant", "acmg"])
async def test_clinvar_gene_is_kept_when_the_vep_reply_is_rejected(
    sources: dict[str, MagicMock], report_kind: str
) -> None:
    """Gene context from an exact ClinVar match does not depend on the VEP reply."""
    row = {**_usable_vep_row("NM_999999.1:c.1A>G"), "gene_symbol": "OTHERX"}
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=[row])
    sources["clinvar"].search_by_hgvs = AsyncMock(
        return_value=[{"exact_change_match": True, "gene_symbol": "SYNTHX"}]
    )
    out, _ = await _run(report_kind, _TRANSCRIPT_QUERY)
    assert out["data_sources_status"]["ensembl_vep"] == "invalid_response"
    assert out["gene_symbol"] == "SYNTHX"
    sources["gnomad"].gene_constraint.assert_awaited_once_with("SYNTHX")


@pytest.mark.parametrize("report_kind", ["variant", "acmg"])
async def test_caller_supplied_variant_id_is_looked_up_whatever_vep_returns(
    sources: dict[str, MagicMock], report_kind: str
) -> None:
    """A variant ID from the caller does not rest on VEP: a hit for another input is dropped."""
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=[_usable_vep_row("NM_999999.1:c.1A>G")])
    sources["gnomad"].variant_frequencies = AsyncMock(
        return_value={"found": True, "global_af": 0.002, "cohort": "exome"}
    )
    out, gnomad_key = await _run(report_kind, "1-42-A-G")

    sources["gnomad"].variant_frequencies.assert_awaited_once_with("1-42-A-G")
    assert out["data_sources_status"][gnomad_key] == "ok"
    assert out["data_sources_status"]["ensembl_vep"] == "invalid_response"
    frequency = out["unassessed_evidence"]["population_frequency"]
    assert frequency["mapping_basis"] == "caller_supplied_variant_id"
    assert frequency["lookup_status"] == "found"
    assert "assembly is not verified" in frequency["detail"]
    predictions = out["unassessed_evidence"]["computational_predictions"]
    assert _vep_values(predictions) == {None}
    sources["alphafold"].alphamissense_score.assert_not_awaited()
    if report_kind == "variant":
        assert out["functional_consequence"] == _NO_FUNCTIONAL_CONSEQUENCE
        assert out["acmg_criteria_draft"]["criteria"] == {}
    else:
        assert out["candidate_criteria"] == {}


@pytest.mark.parametrize(
    ("rows", "accepted"),
    [
        ([], True),
        ([_locus_row()], True),
        # Identity only: whether two loci are one mapping is the resolver's question.
        ([_locus_row(), _locus_row(start=43)], True),
        ([_locus_row(input="NM_999999.1(SYNTHX):c.42A>C")], False),
        ([_locus_row(input="SYNTHX:c.42A>G")], False),
        ([_locus_row(input=None)], False),
        ([{"locus": {"vcf_string": "1-42-A-G"}}], False),
        ([{"locus": None}], False),
        ([{}], False),
        ([_locus_row(), _locus_row(input="SYNTHX:c.42A>G")], False),
        ([_locus_row(), {}], False),
    ],
)
def test_vep_rows_are_kept_only_when_every_one_names_the_query(
    rows: list[dict[str, Any]], accepted: bool
) -> None:
    before = "ok" if rows else "no_data"
    status = {"ensembl_vep": before}
    kept = pm._vep_rows_for_query(_VERSIONED_QUERY, rows, status)
    assert kept == (rows if accepted else [])
    assert status == {"ensembl_vep": before if accepted else "invalid_response"}


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([_locus_row()], "1-42-A-G"),
        ([_locus_row(seq_region_name=None)], None),
        ([_locus_row(allele_string=None)], None),
        ([_locus_row(start="42")], None),
        # A chromosome name that disagrees with the VCF allele is not repaired.
        ([_locus_row(seq_region_name="chr1")], None),
        # Two different mappings: none is chosen (the old builder took one).
        ([_locus_row(allele_string="A"), _locus_row(seq_region_name="2")], None),
        ([{"locus": None}, {}], None),
        # A locus VEP reports for another input, or without naming its input.
        ([_locus_row(input="NM_999999.1(SYNTHX):c.42A>C")], None),
        ([_locus_row(input=None)], None),
        ([_locus_row(), _locus_row(input="SYNTHX:c.42A>G")], None),
    ],
)
def test_malformed_vep_coordinates_do_not_form_variant_ids(
    rows: list[dict[str, Any]], expected: str | None
) -> None:
    resolved = pm._resolve_gnomad_variant(_VERSIONED_QUERY, rows)
    assert resolved["variant_id"] == expected
    assert bool(resolved["detail"]) is (expected is None)


async def test_open_targets_converter_failure_is_explicit(
    sources: dict[str, MagicMock],
) -> None:
    class BadRow:
        def to_dict(self) -> dict[str, Any]:
            raise ValueError("synthetic conversion error")

    sources["ensembl"].gene_lookup = AsyncMock(return_value={"ensembl_gene_id": "ENSGSYNTH"})
    sources["opentargets"].associated_diseases = AsyncMock(return_value=[BadRow()])
    report = await _report()
    assert report["data_sources_status"]["open_targets"] == "failed"
    assert report["disease_associations"]["open_targets_top_diseases"] == []


@pytest.mark.parametrize(
    ("payload", "availability_field", "expected"),
    [
        ({}, "found", "no_data"),
        ({"found": False, "global_af": None}, "found", "no_data"),
        ({"found": True, "global_af": None}, "found", "no_data"),
        # The summary is exome-first: a frequency in the other cohort is still evidence.
        (
            {
                "found": True,
                "global_af": None,
                "cohorts": {
                    "exome": {"allele_frequency": None},
                    "genome": {"allele_frequency": 3e-05},
                },
            },
            "found",
            "ok",
        ),
        (
            {"found": True, "global_af": None, "cohorts": {"exome": {"allele_frequency": None}}},
            "found",
            "no_data",
        ),
        ({"found": True, "global_af": 0.002}, "found", "ok"),
        ({"global_af": 0.002}, "found", "ok"),
        ({}, "constraint_available", "no_data"),
        (
            {"constraint_available": False, "gene_symbol": "SYNTHX"},
            "constraint_available",
            "no_data",
        ),
        ({"constraint_available": True, "loeuf": 0.75}, "constraint_available", "ok"),
        ({"loeuf": 0.75}, "constraint_available", "ok"),
    ],
)
def test_gnomad_sentinels_do_not_count_as_evidence(
    payload: dict[str, Any], availability_field: str, expected: str
) -> None:
    assert pm._gnomad_result_status(payload, availability_field) == expected


async def test_acmg_reports_gnomad_negative_sentinels(
    sources: dict[str, MagicMock],
) -> None:
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=[_locus_row()])
    sources["gnomad"].variant_frequencies = AsyncMock(
        return_value={"variant_id": "1-42-A-G", "found": False, "global_af": None}
    )
    sources["gnomad"].gene_constraint = AsyncMock(
        return_value={"gene_symbol": "SYNTHX", "constraint_available": False}
    )
    out = await pm.classify_variant_acmg(pm.ACMGVariantInput(hgvs=_VERSIONED_QUERY))
    sources["gnomad"].variant_frequencies.assert_awaited_once_with("1-42-A-G")
    assert out["data_sources_status"]["gnomad_variant"] == "no_data"
    assert out["data_sources_status"]["gnomad_constraint"] == "no_data"
    assert out["candidate_criteria"] == {}
    frequency = out["unassessed_evidence"]["population_frequency"]
    assert frequency["lookup_status"] == "not_found"
    assert frequency["cohorts"] == {}
    assert frequency["acmg_criteria"]["PM2"] == "NOT_ASSESSED"
    assert out["draft_classification"] == "Not assessed"


@pytest.mark.parametrize(
    ("query", "vep", "clinvar", "expected_gene"),
    [
        ("SYNTHX:c.42A>G", [], [], "SYNTHX"),
        ("NM_999999.1(SYNTHX):c.42A>G", [], [], "SYNTHX"),
        (
            "NM_999999.1:c.42A>G",
            [],
            [{"exact_change_match": True, "gene_symbol": "SYNTHX"}],
            "SYNTHX",
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"hgvsc": "NM_999999.1:c.42A>G", "gene_symbol": "SYNTHX"}],
            [],
            "SYNTHX",
        ),
        (
            "NM_999999.1:c.42A>G",
            [],
            [{"candidate_change_match": True, "gene_symbol": "SYNTHX"}],
            None,
        ),
        (
            "NM_999999.1:c.42A>G",
            [
                {"transcript_id": "NM_999999.1", "gene_symbol": "SYNTHX"},
                {"transcript_id": "NM_999999.1", "gene_symbol": "OTHERX"},
            ],
            [],
            None,
        ),
        (
            "NM_999999.1(SYNTHX):c.42A>G",
            [{"transcript_id": "NM_999999.1", "gene_symbol": "OTHERX"}],
            [],
            None,
        ),
    ],
)
async def test_acmg_gene_context_requires_nonconflicting_evidence(
    sources: dict[str, MagicMock],
    query: str,
    vep: list[dict[str, Any]],
    clinvar: list[dict[str, Any]],
    expected_gene: str | None,
) -> None:
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=_echoing(query, vep))
    sources["clinvar"].search_by_hgvs = AsyncMock(return_value=clinvar)
    out = await pm.classify_variant_acmg(pm.ACMGVariantInput(hgvs=query))
    assert out["gene_symbol"] == expected_gene
    if expected_gene:
        sources["gnomad"].gene_constraint.assert_awaited_once_with(expected_gene)
    else:
        sources["gnomad"].gene_constraint.assert_not_awaited()
    assert out["draft_classification"] == "Not assessed"


@pytest.mark.parametrize(
    ("hgvs", "vep", "clinvar", "expected"),
    [
        (
            "NM_999999.1:c.42A>G",
            [{"hgvsc": "ENST000001:c.42A>G", "gene_symbol": "OTHERX"}],
            [{"exact_change_match": True, "gene_symbol": "SYNTHX"}],
            "SYNTHX",
        ),
        (
            "NM_999999.1:c.42A>G",
            [
                {"transcript_id": "NM_999999.1", "gene_symbol": "SYNTHX"},
                {"transcript_id": "ENST000001", "gene_symbol": "OTHERX"},
            ],
            [],
            "SYNTHX",
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"hgvsc": "NM_999999.2:c.42A>G", "gene_symbol": "SYNTHX"}],
            [],
            None,
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"hgvsc": "NM_999999.1:c.42A>G", "gene_symbol": "OTHERX"}],
            [{"exact_change_match": True, "gene_symbol": "SYNTHX"}],
            None,
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"gene_symbol": "OTHERX"}],
            [{"exact_change_match": True, "gene_symbol": "SYNTHX"}],
            "SYNTHX",
        ),
        (
            "NM_999999.1(SYNTHX):c.42A>G",
            [{"transcript_id": "ENST000001", "gene_symbol": "OTHERX"}],
            [],
            "SYNTHX",
        ),
        (
            "NM_999999.1:c.42A>G",
            [
                {
                    "transcript_id": "ENST000001",
                    "refseq_transcript_ids": ["NM_999999.1"],
                    "gene_symbol": "SYNTHX",
                }
            ],
            [],
            "SYNTHX",
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"refseq_transcript_ids": ["NM_999999.2"], "gene_symbol": "SYNTHX"}],
            [],
            None,
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"refseq_transcript_ids": ["NM_999999"], "gene_symbol": "SYNTHX"}],
            [],
            None,
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"refseq_transcript_ids": "NM_999999.1", "gene_symbol": "SYNTHX"}],
            [],
            None,
        ),
        (
            "NM_999999.1:c.42A>G",
            [
                {"refseq_transcript_ids": ["NM_999999.2"], "gene_symbol": "OTHERX"},
                {"refseq_transcript_ids": ["NM_999999.1"], "gene_symbol": "SYNTHX"},
            ],
            [],
            "SYNTHX",
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"refseq_transcript_ids": ["NM_999999.1"], "gene_symbol": "OTHERX"}],
            [{"exact_change_match": True, "gene_symbol": "SYNTHX"}],
            None,
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"refseq_transcript_ids": [None, "NM_999999.1"], "gene_symbol": "SYNTHX"}],
            [],
            "SYNTHX",
        ),
        (
            "NC_000001.11:g.42A>G",
            [{"transcript_id": "ENST000001", "gene_symbol": "OTHERX"}],
            [],
            None,
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"transcript_id": "NM_999999.1", "gene_symbol": None}],
            [],
            None,
        ),
        (
            "NM_999999.1:c.42A>G",
            [{"transcript_id": None, "hgvsc": None, "gene_symbol": "OTHERX"}],
            [],
            None,
        ),
        (
            "NM_999999.1:c.42A>G",
            [
                {
                    "transcript_id": "ENST000001",
                    "hgvsc": "NM_999999.1:c.42A>G",
                    "gene_symbol": "SYNTHX",
                }
            ],
            [],
            "SYNTHX",
        ),
    ],
)
def test_transcript_gene_source_ignores_collateral_vep_genes(
    hgvs: str, vep: list[dict[str, Any]], clinvar: list[dict[str, Any]], expected: str | None
) -> None:
    assert pm._report_gene_from_sources(hgvs, vep, clinvar) == expected


@pytest.mark.parametrize("report_kind", ["variant", "acmg"])
async def test_exact_clinvar_gene_survives_collateral_vep_consequence(
    sources: dict[str, MagicMock], report_kind: str
) -> None:
    sources["ensembl"].vep_hgvs = AsyncMock(
        return_value=_echoing(
            "NM_999999.1:c.42A>G",
            [
                {"transcript_id": "ENST000001", "gene_symbol": "OTHERX"},
                {"transcript_id": "NM_999999.1", "gene_symbol": "SYNTHX"},
            ],
        )
    )
    sources["clinvar"].search_by_hgvs = AsyncMock(
        return_value=[{"exact_change_match": True, "gene_symbol": "SYNTHX"}]
    )
    if report_kind == "variant":
        report = await _report("NM_999999.1:c.42A>G")
    else:
        report = await pm.classify_variant_acmg(pm.ACMGVariantInput(hgvs="NM_999999.1:c.42A>G"))
    assert report["gene_symbol"] == "SYNTHX"
    sources["gnomad"].gene_constraint.assert_awaited_once_with("SYNTHX")


@pytest.mark.parametrize("report_kind", ["variant", "acmg"])
async def test_vep_refseq_alignment_recovers_only_version_matched_gene_context(
    sources: dict[str, MagicMock], report_kind: str
) -> None:
    """Ensembl aligned xrefs support gene-level lookup, never allele classification."""
    sources["ensembl"].vep_hgvs = AsyncMock(
        return_value=_echoing(
            "NM_999999.1:c.42A>G",
            [
                {
                    "transcript_id": "ENST000001",
                    "gene_symbol": "SYNTHX",
                    "refseq_transcript_ids": ["NM_999999.1"],
                },
                {
                    "transcript_id": "ENST000002",
                    "gene_symbol": "OTHERX",
                    "refseq_transcript_ids": ["NM_999999.2"],
                },
            ],
        )
    )
    if report_kind == "variant":
        report = await _report("NM_999999.1:c.42A>G")
        assert report["clinical_tier"] == "NOT_ASSESSED"
        assert report["clinvar"]["found"] is False
    else:
        report = await pm.classify_variant_acmg(pm.ACMGVariantInput(hgvs="NM_999999.1:c.42A>G"))
        assert report["draft_classification"] == "Not assessed"
        assert report["clinvar_reference"]["found"] is False
    assert report["gene_symbol"] == "SYNTHX"
    sources["gnomad"].gene_constraint.assert_awaited_once_with("SYNTHX")
