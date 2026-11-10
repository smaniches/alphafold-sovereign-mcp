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
        ([{}], [{}], "ok"),
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
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=[_locus_row()])
    report = await _report("SYNTHX:c.42A>G")
    sources["gnomad"].variant_frequencies.assert_not_awaited()
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
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=vep)
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
    sources["ensembl"].vep_hgvs = AsyncMock(return_value=vep)
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
        return_value=[
            {"transcript_id": "ENST000001", "gene_symbol": "OTHERX"},
            {"transcript_id": "NM_999999.1", "gene_symbol": "SYNTHX"},
        ]
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
        return_value=[
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
        ]
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
