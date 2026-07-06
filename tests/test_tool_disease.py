# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.tools.disease``."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from alphafold_sovereign.clients.hpo import DiseaseByPhenotype
from alphafold_sovereign.domain.disease import (
    DiseaseRecord,
    PathogenicityClass,
    PhenotypeAssociation,
    TargetEvidenceScore,
)
from alphafold_sovereign.server.app import mcp
from alphafold_sovereign.tools.disease import (
    COMMON_DISEASE_ROOTS,
    CommonDiseaseInput,
    DiseaseSimilarityInput,
    DiseaseTargetsInput,
    GenePhenotypeInput,
    HPOTermInput,
    ICD10ToMONDOInput,
    MONDOLookupInput,
    MONDOSearchInput,
    OrphanDiseaseInput,
    PhenotypeToStructureInput,
    TargetDiseaseInput,
    VariantTriageInput,
    _am_label,
    _compute_tier,
    _fetch_clinvar,
    _fetch_disease_context,
    _fetch_gnomad,
    _omim_to_mondo,
    _parse_clinvar_class,
    _parse_hgvs_gene,
    _provenance,
    _uniprot_to_ensembl,
    compare_disease_target_overlap,
    get_common_disease_targets,
    get_disease_targets,
    get_gene_phenotype_profile,
    get_orphan_disease_atlas,
    get_target_diseases,
    lookup_disease,
    lookup_phenotype,
    phenotype_to_structures,
    resolve_icd10_to_mondo,
    search_diseases,
    triage_variant_3d,
)

# ---------------------------------------------------------------------------
# Fixtures: helper builders
# ---------------------------------------------------------------------------


def _disease_record(mondo_id: str = "MONDO:0001234", name: str = "Test Disease") -> DiseaseRecord:
    return DiseaseRecord(
        mondo_id=mondo_id,
        name=name,
        synonyms=("alt",),
        definition="A disease.",
        icd10_codes=("Z99",),
    )


def _phenotype_assoc(disease_id: str = "OMIM:600100", name: str = "X") -> PhenotypeAssociation:
    return PhenotypeAssociation(
        hpo_id="HP:0001250",
        hpo_label="Seizure",
        mondo_id="MONDO:0001",
        disease_name=name,
    )


def _disease_by_phenotype(disease_id: str = "OMIM:600100", name: str = "X") -> DiseaseByPhenotype:
    return DiseaseByPhenotype(
        disease_id=disease_id,
        disease_name=name,
        hpo_id="HP:0001250",
        hpo_label="Seizure",
    )


def _evidence_score(
    ensembl_id: str = "ENSG000001", gene: str = "FOO", uniprot: str = "P1"
) -> TargetEvidenceScore:
    return TargetEvidenceScore(
        target_ensembl_id=ensembl_id,
        target_gene_symbol=gene,
        uniprot_id=uniprot,
        disease_mondo_id="MONDO:0001",
        disease_name="X",
        overall_score=0.8,
        drug_count=2,
        tractable=True,
    )


class _AsyncCtx:
    """Async context manager that returns a target object on __aenter__."""

    def __init__(self, target: Any) -> None:
        self._target = target

    async def __aenter__(self) -> Any:
        return self._target

    async def __aexit__(self, *_: object) -> None:
        return None


def _patch_client_class(monkeypatch: pytest.MonkeyPatch, path: str, instance: Any) -> Any:
    """Patch a client class constructor so it returns ``instance`` from ``async with``."""

    def factory(*_a: Any, **_kw: Any) -> Any:
        return _AsyncCtx(instance)

    monkeypatch.setattr(path, factory)
    return instance


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_provenance_includes_sources() -> None:
    p = _provenance(mondo="OLS4", hpo="JAX")
    assert "mondo=OLS4" in p
    assert "hpo=JAX" in p


def test_provenance_skips_empty_sources() -> None:
    p = _provenance(mondo="OLS4", missing="")
    assert "mondo=OLS4" in p
    assert "missing" not in p


def test_parse_hgvs_gene_simple() -> None:
    assert _parse_hgvs_gene("BRCA1:c.181T>G") == ("BRCA1", "c.181T>G")


def test_parse_hgvs_gene_refseq_returns_empty() -> None:
    gene, change = _parse_hgvs_gene("NM_007294.3:c.181T>G")
    assert gene == ""
    assert change == "c.181T>G"


def test_parse_hgvs_gene_refseq_NR() -> None:
    gene, change = _parse_hgvs_gene("NR_123:c.X")
    assert gene == ""
    assert change == "c.X"


def test_parse_hgvs_gene_invalid() -> None:
    assert _parse_hgvs_gene("invalid string") == ("", "")


def test_parse_hgvs_gene_refseq_with_gene_parens() -> None:
    # Canonical ClinVar form: gene carried in parentheses after the transcript.
    assert _parse_hgvs_gene("NM_007294.4(BRCA1):c.5266dupC") == ("BRCA1", "c.5266dupC")


def test_parse_hgvs_gene_hyphenated_symbol() -> None:
    assert _parse_hgvs_gene("HLA-A:c.100A>G") == ("HLA-A", "c.100A>G")


def test_parse_hgvs_gene_ensembl_transcript_returns_empty() -> None:
    gene, change = _parse_hgvs_gene("ENST00000357654:c.181T>G")
    assert gene == ""
    assert change == "c.181T>G"


def test_parse_hgvs_gene_genomic_accession_returns_empty() -> None:
    # Genomic RefSeq accessions are not gene symbols.
    assert _parse_hgvs_gene("NC_000017.11:g.43044295G>C") == ("", "g.43044295G>C")


def test_parse_hgvs_gene_chromosome_returns_empty() -> None:
    # Bare chromosome names are not gene symbols.
    assert _parse_hgvs_gene("chr17:g.43094692G>A") == ("", "g.43094692G>A")
    assert _parse_hgvs_gene("chrX:g.100A>G") == ("", "g.100A>G")


@pytest.mark.parametrize(
    ("score", "expected_substring"),
    [
        (None, "Not available"),
        (0.9, "Likely pathogenic"),
        (0.2, "Likely benign"),
        (0.4, "Uncertain"),
    ],
)
def test_am_label_branches(score: float | None, expected_substring: str) -> None:
    assert expected_substring in _am_label(score)


@pytest.mark.parametrize(
    ("cls", "am", "expected"),
    [
        (PathogenicityClass.PATHOGENIC, None, "HIGH"),
        (PathogenicityClass.LIKELY_PATHOGENIC, None, "HIGH"),
        (PathogenicityClass.BENIGN, None, "LOW"),
        (PathogenicityClass.NOT_PROVIDED, 0.9, "HIGH"),
        (PathogenicityClass.NOT_PROVIDED, 0.1, "LOW"),
        (PathogenicityClass.UNCERTAIN, None, "MEDIUM"),
        (PathogenicityClass.NOT_PROVIDED, None, "UNKNOWN"),
        (PathogenicityClass.NOT_PROVIDED, 0.4, "UNKNOWN"),
    ],
)
def test_compute_tier_branches(cls: PathogenicityClass, am: float | None, expected: str) -> None:
    assert _compute_tier(cls, am) == expected


def test_parse_clinvar_class_returns_pathogenicity() -> None:
    assert _parse_clinvar_class("Pathogenic") == PathogenicityClass.PATHOGENIC


# ---------------------------------------------------------------------------
# lookup_disease
# ---------------------------------------------------------------------------


async def test_lookup_disease_with_hierarchy(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _disease_record()
    parents = [MagicMock(id="MONDO:0002", label="Parent")]
    children = [MagicMock(id="MONDO:0003", label="Child")]

    mock_client = MagicMock()
    mock_client.lookup = AsyncMock(return_value=record)
    mock_client.ancestors = AsyncMock(return_value=parents)
    mock_client.children = AsyncMock(return_value=children)
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mock_client)

    result = await lookup_disease(MONDOLookupInput(mondo_id="MONDO:0001234"))
    parsed = json.loads(result.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert "hierarchy" in parsed
    assert parsed["hierarchy"]["parents"][0]["id"] == "MONDO:0002"


async def test_lookup_disease_no_hierarchy(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _disease_record()
    mock_client = MagicMock()
    mock_client.lookup = AsyncMock(return_value=record)
    mock_client.ancestors = AsyncMock(return_value=[])
    mock_client.children = AsyncMock(return_value=[])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mock_client)

    result = await lookup_disease(
        MONDOLookupInput(mondo_id="MONDO:0001234", include_hierarchy=False)
    )
    parsed = json.loads(result.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert "hierarchy" not in parsed


async def test_lookup_disease_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.lookup = AsyncMock(side_effect=KeyError("missing"))
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mock_client)

    result = await lookup_disease(MONDOLookupInput(mondo_id="MONDO:9999"))
    parsed = json.loads(result)
    assert parsed["status"] == "not_found"


async def test_lookup_disease_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.lookup = AsyncMock(side_effect=RuntimeError("oops"))
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mock_client)

    with pytest.raises(ToolError):
        await lookup_disease(MONDOLookupInput(mondo_id="MONDO:9999"))


# ---------------------------------------------------------------------------
# MCP contract: failures set isError, negative results do not (end-to-end)
# ---------------------------------------------------------------------------


async def test_lookup_disease_mcp_contract_iserror(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end MCP contract check via an in-memory FastMCP Client.

    A genuine upstream failure (RuntimeError) must surface as a real error
    result (``is_error is True``); a not-found negative result (KeyError →
    ``status: not_found``) must remain a successful result
    (``is_error is False``). Mirrors uniprot-mcp #88.
    """
    # 1. Upstream failure → isError True.
    failing = MagicMock()
    failing.lookup = AsyncMock(side_effect=RuntimeError("upstream boom"))
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", failing)

    async with Client(mcp) as client:
        error_result = await client.call_tool(
            "lookup_disease",
            {"params": {"mondo_id": "MONDO:9999"}},
            raise_on_error=False,
        )
        assert error_result.is_error is True

    # 2. Not-found negative result → isError False (guard clause preserved).
    not_found = MagicMock()
    not_found.lookup = AsyncMock(side_effect=KeyError("missing"))
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", not_found)

    async with Client(mcp) as client:
        ok_result = await client.call_tool(
            "lookup_disease",
            {"params": {"mondo_id": "MONDO:9999"}},
            raise_on_error=False,
        )
        assert ok_result.is_error is False


# ---------------------------------------------------------------------------
# search_diseases
# ---------------------------------------------------------------------------


async def test_search_diseases_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_result = MagicMock()
    mock_result.to_dict.return_value = {"mondo_id": "MONDO:0001"}
    mock_client = MagicMock()
    mock_client.search = AsyncMock(return_value=[mock_result])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mock_client)

    out = await search_diseases(MONDOSearchInput(query="cancer"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert parsed["count"] == 1


async def test_search_diseases_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.search = AsyncMock(return_value=[])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mock_client)

    out = await search_diseases(MONDOSearchInput(query="not found"))
    parsed = json.loads(out)
    assert parsed["status"] == "no_results"


async def test_search_diseases_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.search = AsyncMock(side_effect=RuntimeError("boom"))
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mock_client)

    with pytest.raises(ToolError):
        await search_diseases(MONDOSearchInput(query="xy"))


# ---------------------------------------------------------------------------
# lookup_phenotype
# ---------------------------------------------------------------------------


async def test_lookup_phenotype_with_diseases(monkeypatch: pytest.MonkeyPatch) -> None:
    term = MagicMock()
    term.to_dict.return_value = {"id": "HP:0001250"}
    disease = _phenotype_assoc()
    parents = [MagicMock(id="HP:0001", label="parent")]

    mock_client = MagicMock()
    mock_client.lookup = AsyncMock(return_value=term)
    mock_client.diseases_for_phenotype = AsyncMock(return_value=[disease])
    mock_client.ancestors = AsyncMock(return_value=parents)
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", mock_client)

    out = await lookup_phenotype(HPOTermInput(hpo_id="HP:0001250"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert "associated_diseases" in parsed


async def test_lookup_phenotype_no_diseases(monkeypatch: pytest.MonkeyPatch) -> None:
    term = MagicMock()
    term.to_dict.return_value = {"id": "HP:0001"}
    mock_client = MagicMock()
    mock_client.lookup = AsyncMock(return_value=term)
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", mock_client)

    out = await lookup_phenotype(HPOTermInput(hpo_id="HP:0001", include_diseases=False))
    parsed = json.loads(out.split("---")[0].strip())
    assert "associated_diseases" not in parsed


async def test_lookup_phenotype_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.lookup = AsyncMock(side_effect=RuntimeError("err"))
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", mock_client)

    with pytest.raises(ToolError):
        await lookup_phenotype(HPOTermInput(hpo_id="HP:0001"))


# ---------------------------------------------------------------------------
# get_gene_phenotype_profile
# ---------------------------------------------------------------------------


def _ensembl_mock(ncbi_gene_id: str) -> MagicMock:
    client = MagicMock()
    client.ncbi_gene_id = AsyncMock(return_value=ncbi_gene_id)
    return client


async def test_gene_phenotype_profile_full(monkeypatch: pytest.MonkeyPatch) -> None:
    pheno = MagicMock()
    pheno.to_dict.return_value = {"hpo_id": "HP:0001"}

    hpo_client = MagicMock()
    hpo_client.phenotypes_for_gene_id = AsyncMock(return_value=[pheno])

    gnomad_client = MagicMock()
    gnomad_client.gene_constraint = AsyncMock(return_value={"loeuf": 0.3})

    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.EnsemblClient", _ensembl_mock("672")
    )
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", hpo_client)
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.GnomADClient", gnomad_client
    )

    out = await get_gene_phenotype_profile(GenePhenotypeInput(gene_symbol="BRCA1"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert parsed["phenotype_count"] == 1
    assert parsed["gnomad_constraint"] == {"loeuf": 0.3}
    hpo_client.phenotypes_for_gene_id.assert_awaited_once_with("NCBIGene:672", gene_symbol="BRCA1")


async def test_gene_phenotype_profile_no_constraint(monkeypatch: pytest.MonkeyPatch) -> None:
    hpo_client = MagicMock()
    hpo_client.phenotypes_for_gene_id = AsyncMock(return_value=[])
    gnomad_client = MagicMock()
    gnomad_client.gene_constraint = AsyncMock(return_value={})
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.EnsemblClient", _ensembl_mock("672")
    )
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", hpo_client)
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.GnomADClient", gnomad_client
    )

    out = await get_gene_phenotype_profile(
        GenePhenotypeInput(gene_symbol="X", include_constraint=False)
    )
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert parsed["gnomad_constraint"] == {}


async def test_gene_phenotype_profile_no_entrez(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Entrez mapping ⇒ skip the HPO call, still report gnomAD constraint."""
    hpo_client = MagicMock()
    hpo_client.phenotypes_for_gene_id = AsyncMock(return_value=[MagicMock()])
    gnomad_client = MagicMock()
    gnomad_client.gene_constraint = AsyncMock(return_value={"loeuf": 0.5})
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.EnsemblClient", _ensembl_mock("")
    )
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", hpo_client)
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.GnomADClient", gnomad_client
    )

    out = await get_gene_phenotype_profile(GenePhenotypeInput(gene_symbol="OBSCURE"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert parsed["phenotype_count"] == 0
    assert parsed["gnomad_constraint"] == {"loeuf": 0.5}
    hpo_client.phenotypes_for_gene_id.assert_not_called()


async def test_gene_phenotype_profile_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    hpo_client = MagicMock()
    hpo_client.phenotypes_for_gene_id = AsyncMock(side_effect=RuntimeError("err1"))
    gnomad_client = MagicMock()
    gnomad_client.gene_constraint = AsyncMock(side_effect=RuntimeError("err2"))
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.EnsemblClient", _ensembl_mock("672")
    )
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", hpo_client)
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.GnomADClient", gnomad_client
    )

    out = await get_gene_phenotype_profile(GenePhenotypeInput(gene_symbol="X"))
    parsed = json.loads(out.split("---")[0].strip())
    # Both raised, returned empty lists/dicts
    assert parsed["phenotype_count"] == 0


async def test_gene_phenotype_profile_outer_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raise on context manager construction → outer exception path."""

    class _Boom:
        async def __aenter__(self) -> Any:
            raise RuntimeError("ctx fail")

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr("alphafold_sovereign.tools.disease.EnsemblClient", lambda *a, **kw: _Boom())
    monkeypatch.setattr("alphafold_sovereign.tools.disease.HPOClient", lambda *a, **kw: _Boom())
    with pytest.raises(ToolError):
        await get_gene_phenotype_profile(GenePhenotypeInput(gene_symbol="X"))


# ---------------------------------------------------------------------------
# get_disease_targets
# ---------------------------------------------------------------------------


async def test_get_disease_targets_success(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _evidence_score()
    untractable = TargetEvidenceScore(
        target_ensembl_id="ENSG2",
        target_gene_symbol="BAR",
        uniprot_id="P2",
        disease_mondo_id="X",
        disease_name="Y",
        overall_score=0.01,  # below default min_score
        tractable=False,
    )
    mock_client = MagicMock()
    mock_client.associated_targets = AsyncMock(return_value=[target, untractable])
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", mock_client
    )

    out = await get_disease_targets(DiseaseTargetsInput(disease_id="MONDO:0001"))
    parsed = json.loads(out.split("---")[0].strip())
    # min_score filtered the second
    assert parsed["total_returned"] == 1


async def test_get_disease_targets_tractable_only(monkeypatch: pytest.MonkeyPatch) -> None:
    nontract = TargetEvidenceScore(
        target_ensembl_id="E1",
        target_gene_symbol="G",
        uniprot_id="P",
        disease_mondo_id="X",
        disease_name="Y",
        overall_score=0.9,
        tractable=False,
    )
    mock_client = MagicMock()
    mock_client.associated_targets = AsyncMock(return_value=[nontract])
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", mock_client
    )

    out = await get_disease_targets(
        DiseaseTargetsInput(disease_id="MONDO:0001", include_tractable_only=True)
    )
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["total_returned"] == 0


async def test_get_disease_targets_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.associated_targets = AsyncMock(side_effect=RuntimeError("ot fail"))
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", mock_client
    )

    with pytest.raises(ToolError):
        await get_disease_targets(DiseaseTargetsInput(disease_id="MONDO:0001"))


# ---------------------------------------------------------------------------
# get_target_diseases
# ---------------------------------------------------------------------------


async def test_get_target_diseases_with_explicit_ensembl(monkeypatch: pytest.MonkeyPatch) -> None:
    score = MagicMock()
    score.to_dict.return_value = {"disease": "X"}
    mock_client = MagicMock()
    mock_client.associated_diseases = AsyncMock(return_value=[score])
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", mock_client
    )

    out = await get_target_diseases(TargetDiseaseInput(uniprot_id="P38398", ensembl_id="ENSG0001"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["ensembl_id"] == "ENSG0001"
    assert parsed["total_returned"] == 1


async def test_get_target_diseases_via_uniprot_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(uniprot_id: str) -> str:
        return "ENSG_lookup"

    monkeypatch.setattr("alphafold_sovereign.tools.disease._uniprot_to_ensembl", fake_resolve)

    score = MagicMock()
    score.to_dict.return_value = {"x": 1}
    mock_client = MagicMock()
    mock_client.associated_diseases = AsyncMock(return_value=[score])
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", mock_client
    )

    out = await get_target_diseases(TargetDiseaseInput(uniprot_id="P38398"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["ensembl_id"] == "ENSG_lookup"


async def test_get_target_diseases_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "alphafold_sovereign.tools.disease._uniprot_to_ensembl",
        AsyncMock(return_value=""),
    )
    mock_client = MagicMock()
    mock_client.associated_diseases = AsyncMock(side_effect=RuntimeError("bad"))
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", mock_client
    )

    with pytest.raises(ToolError):
        await get_target_diseases(TargetDiseaseInput(uniprot_id="P38398"))


# ---------------------------------------------------------------------------
# get_common_disease_targets
# ---------------------------------------------------------------------------


async def test_get_common_disease_targets_invalid_category() -> None:
    out = await get_common_disease_targets(CommonDiseaseInput(category="not_a_real_category"))
    parsed = json.loads(out)
    assert parsed["status"] == "error"


async def test_get_common_disease_targets_invalid_disease_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = await get_common_disease_targets(
        CommonDiseaseInput(category="oncology", disease_name="not_present_disease")
    )
    parsed = json.loads(out)
    assert parsed["status"] == "error"


async def test_get_common_disease_targets_no_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no disease_name is set, all diseases in the category are profiled."""
    target = _evidence_score()
    mock_client = MagicMock()
    mock_client.associated_targets = AsyncMock(return_value=[target])
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", mock_client
    )

    out = await get_common_disease_targets(CommonDiseaseInput(category="rare"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert parsed["diseases_profiled"] >= 1


async def test_get_common_disease_targets_filtered_disease(monkeypatch: pytest.MonkeyPatch) -> None:
    """Filter to a specific disease within the category."""
    target = _evidence_score()
    mock_client = MagicMock()
    mock_client.associated_targets = AsyncMock(return_value=[target])
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", mock_client
    )

    out = await get_common_disease_targets(
        CommonDiseaseInput(category="oncology", disease_name="breast carcinoma")
    )
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert "breast_carcinoma" in parsed["profile"]


async def test_get_common_disease_targets_with_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ot.associated_targets raises, the exception is captured per disease."""
    mock_client = MagicMock()
    mock_client.associated_targets = AsyncMock(side_effect=RuntimeError("ot fail"))
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", mock_client
    )

    out = await get_common_disease_targets(
        CommonDiseaseInput(category="rare", disease_name="phenylketonuria")
    )
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    # Each disease should carry an error
    for entry in parsed["profile"].values():
        assert "error" in entry


# ---------------------------------------------------------------------------
# triage_variant_3d
# ---------------------------------------------------------------------------


async def test_triage_variant_3d_invalid_hgvs() -> None:
    out = await triage_variant_3d(VariantTriageInput(hgvs="garbage"))
    parsed = json.loads(out)
    assert parsed["status"] == "error"


async def test_triage_variant_3d_full(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_clinvar(hgvs: str, gene: str) -> dict[str, Any]:
        return {
            "classification": "Pathogenic",
            "review_status": "criteria provided",
            "variation_id": "12345",
            "conditions": ["Breast cancer"],
        }

    async def fake_gnomad(hgvs: str, gene: str) -> dict[str, Any]:
        return {"alphamissense_score": 0.9, "global_af": 1e-5}

    async def fake_disease(gene: str) -> dict[str, Any]:
        return {"note": "context"}

    monkeypatch.setattr("alphafold_sovereign.tools.disease._fetch_clinvar", fake_clinvar)
    monkeypatch.setattr("alphafold_sovereign.tools.disease._fetch_gnomad", fake_gnomad)
    monkeypatch.setattr("alphafold_sovereign.tools.disease._fetch_disease_context", fake_disease)

    out = await triage_variant_3d(VariantTriageInput(hgvs="BRCA1:c.181T>G"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert parsed["pathogenicity_tier"] == "HIGH"
    assert "structure_note" in parsed


async def test_triage_variant_3d_without_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_clinvar(hgvs: str, gene: str) -> dict[str, Any]:
        return {}

    monkeypatch.setattr("alphafold_sovereign.tools.disease._fetch_clinvar", fake_clinvar)

    out = await triage_variant_3d(
        VariantTriageInput(
            hgvs="TP53:c.817C>T",
            include_gnomad=False,
            include_disease_context=False,
            include_structure=False,
        )
    )
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert "structure_note" not in parsed


async def test_triage_variant_3d_disease_only_no_gnomad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: with gnomAD off but disease context on, the disease
    result must land in disease_context (not population_genetics).

    The old positional unpacking assigned fetched[1] (the disease result,
    since coros == [clinvar, disease]) to gnomad_data, leaking it into
    population_genetics AND disease_context.
    """
    sentinel = {"note": "DISEASE_SENTINEL", "stub": True}

    async def fake_clinvar(hgvs: str, gene: str) -> dict[str, Any]:
        return {"classification": "Pathogenic"}

    async def fake_disease(gene: str) -> dict[str, Any]:
        return sentinel

    monkeypatch.setattr("alphafold_sovereign.tools.disease._fetch_clinvar", fake_clinvar)
    # Deliberately do NOT patch _fetch_gnomad: it must not be called.
    monkeypatch.setattr("alphafold_sovereign.tools.disease._fetch_disease_context", fake_disease)

    out = await triage_variant_3d(
        VariantTriageInput(
            hgvs="BRCA1:c.181T>G",
            include_gnomad=False,
            include_disease_context=True,
            include_structure=False,
        )
    )
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    # gnomAD was off → population_genetics empty (the bug leaked the disease here)
    assert parsed["population_genetics"] == {}
    # disease context correctly carries the sentinel
    assert parsed["disease_context"] == sentinel
    assert "gnomAD" not in parsed["sources_queried"]


async def test_triage_variant_3d_partial_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_clinvar(hgvs: str, gene: str) -> dict[str, Any]:
        raise RuntimeError("cv fail")

    async def fake_gnomad(hgvs: str, gene: str) -> dict[str, Any]:
        raise RuntimeError("gn fail")

    async def fake_disease(gene: str) -> dict[str, Any]:
        raise RuntimeError("dis fail")

    monkeypatch.setattr("alphafold_sovereign.tools.disease._fetch_clinvar", fake_clinvar)
    monkeypatch.setattr("alphafold_sovereign.tools.disease._fetch_gnomad", fake_gnomad)
    monkeypatch.setattr("alphafold_sovereign.tools.disease._fetch_disease_context", fake_disease)

    out = await triage_variant_3d(VariantTriageInput(hgvs="BRCA1:c.1T>G"))
    parsed = json.loads(out.split("---")[0].strip())
    # All exceptions captured → empty dicts, tier UNKNOWN
    assert parsed["status"] == "success"
    assert parsed["pathogenicity_tier"] == "UNKNOWN"


async def test_triage_variant_3d_outer_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    # Make _parse_hgvs_gene raise to force the outer except path
    def bad_parse(hgvs: str) -> tuple[str, str]:
        raise RuntimeError("parse fail")

    monkeypatch.setattr("alphafold_sovereign.tools.disease._parse_hgvs_gene", bad_parse)
    with pytest.raises(ToolError):
        await triage_variant_3d(VariantTriageInput(hgvs="BRCA1:c.1T>G"))


# ---------------------------------------------------------------------------
# phenotype_to_structures
# ---------------------------------------------------------------------------


async def test_phenotype_to_structures_success(monkeypatch: pytest.MonkeyPatch) -> None:
    disease = _disease_by_phenotype(disease_id="OMIM:1", name="D1")
    target = _evidence_score(uniprot="P9")

    hpo_client = MagicMock()
    hpo_client.diseases_for_phenotype = AsyncMock(return_value=[disease])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", hpo_client)

    ot_client = MagicMock()
    ot_client.associated_targets = AsyncMock(return_value=[target])
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", ot_client
    )

    async def fake_omim(disease_id: str) -> str | None:
        return "MONDO:0001"

    monkeypatch.setattr("alphafold_sovereign.tools.disease._omim_to_mondo", fake_omim)

    out = await phenotype_to_structures(PhenotypeToStructureInput(hpo_id="HP:0001"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert parsed["diseases_found"] == 1


async def test_phenotype_to_structures_uses_mondo_xref(monkeypatch: pytest.MonkeyPatch) -> None:
    """When HPO supplies a MONDO xref, use it directly and skip OMIM→MONDO."""
    disease = DiseaseByPhenotype(
        disease_id="OMIM:1", disease_name="D1", hpo_id="HP:0001", mondo_id="MONDO:0001"
    )
    hpo_client = MagicMock()
    hpo_client.diseases_for_phenotype = AsyncMock(return_value=[disease])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", hpo_client)

    ot_client = MagicMock()
    ot_client.associated_targets = AsyncMock(return_value=[_evidence_score(uniprot="P9")])
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", ot_client
    )

    async def boom_omim(disease_id: str) -> str | None:
        raise AssertionError("_omim_to_mondo must not be called when mondo_id is present")

    monkeypatch.setattr("alphafold_sovereign.tools.disease._omim_to_mondo", boom_omim)

    out = await phenotype_to_structures(PhenotypeToStructureInput(hpo_id="HP:0001"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    # Open Targets was queried with the HPO-provided MONDO id directly.
    assert ot_client.associated_targets.await_args.args[0] == "MONDO:0001"


async def test_phenotype_to_structures_skips_bad_mondo(monkeypatch: pytest.MonkeyPatch) -> None:
    disease_a = _disease_by_phenotype(disease_id="OMIM:1", name="D1")
    disease_b = _disease_by_phenotype(disease_id="OMIM:2", name="D2")

    hpo_client = MagicMock()
    hpo_client.diseases_for_phenotype = AsyncMock(return_value=[disease_a, disease_b])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", hpo_client)

    ot_client = MagicMock()
    # First call succeeds, second raises
    ot_client.associated_targets = AsyncMock(
        side_effect=[[_evidence_score()], RuntimeError("ot err")]
    )
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", ot_client
    )

    call_count = {"n": 0}

    async def fake_omim(disease_id: str) -> str | None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "MONDO:0001"
        return None  # skip

    monkeypatch.setattr("alphafold_sovereign.tools.disease._omim_to_mondo", fake_omim)

    out = await phenotype_to_structures(PhenotypeToStructureInput(hpo_id="HP:0001"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"


async def test_phenotype_to_structures_exception_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    disease_a = _disease_by_phenotype(disease_id="OMIM:1", name="D1")

    hpo_client = MagicMock()
    hpo_client.diseases_for_phenotype = AsyncMock(return_value=[disease_a])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", hpo_client)

    ot_client = MagicMock()
    ot_client.associated_targets = AsyncMock(side_effect=RuntimeError("ot err"))
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", ot_client
    )

    async def fake_omim(disease_id: str) -> str | None:
        return "MONDO:0001"

    monkeypatch.setattr("alphafold_sovereign.tools.disease._omim_to_mondo", fake_omim)

    out = await phenotype_to_structures(PhenotypeToStructureInput(hpo_id="HP:0001"))
    parsed = json.loads(out.split("---")[0].strip())
    # Exception in associated_targets → result list skipped, count stays low
    assert parsed["status"] == "success"
    assert parsed["diseases_found"] == 0


async def test_phenotype_to_structures_skipped_when_mondo_is_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disease_a = _disease_by_phenotype(disease_id="OMIM:1", name="D1")

    hpo_client = MagicMock()
    hpo_client.diseases_for_phenotype = AsyncMock(return_value=[disease_a])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", hpo_client)

    ot_client = MagicMock()
    ot_client.associated_targets = AsyncMock(return_value=[])
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", ot_client
    )

    # asyncio.gather with return_exceptions catches RuntimeError from _omim_to_mondo
    async def fake_omim(disease_id: str) -> str | None:
        raise RuntimeError("conv fail")

    monkeypatch.setattr("alphafold_sovereign.tools.disease._omim_to_mondo", fake_omim)

    out = await phenotype_to_structures(PhenotypeToStructureInput(hpo_id="HP:0001"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert parsed["diseases_found"] == 0


async def test_phenotype_to_structures_outer_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        async def __aenter__(self) -> Any:
            raise RuntimeError("ctx fail")

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr("alphafold_sovereign.tools.disease.HPOClient", lambda *a, **kw: _Boom())
    with pytest.raises(ToolError):
        await phenotype_to_structures(PhenotypeToStructureInput(hpo_id="HP:0001"))


# ---------------------------------------------------------------------------
# get_orphan_disease_atlas
# ---------------------------------------------------------------------------


async def test_orphan_atlas_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    mondo_client = MagicMock()
    mondo_client.from_orphanet = AsyncMock(return_value=[])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mondo_client)

    out = await get_orphan_disease_atlas(OrphanDiseaseInput(orphanet_id="9999"))
    parsed = json.loads(out)
    assert parsed["status"] == "not_found"


async def test_orphan_atlas_success(monkeypatch: pytest.MonkeyPatch) -> None:
    search_hit = MagicMock(mondo_id="MONDO:0001")

    mondo_client = MagicMock()
    mondo_client.from_orphanet = AsyncMock(return_value=[search_hit])
    mondo_client.lookup = AsyncMock(return_value=_disease_record())
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mondo_client)

    hpo_client = MagicMock()
    hpo_client.phenotypes_for_disease = AsyncMock(return_value=[_phenotype_assoc()])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", hpo_client)

    ot_client = MagicMock()
    ot_client.associated_targets = AsyncMock(return_value=[_evidence_score()])
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", ot_client
    )

    out = await get_orphan_disease_atlas(OrphanDiseaseInput(orphanet_id="79318"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert parsed["mondo_id"] == "MONDO:0001"
    # HPO phenotype annotations must be requested with the Orphanet CURIE,
    # not an OMIM prefix on an Orphanet number (a different disease).
    hpo_client.phenotypes_for_disease.assert_awaited_once_with("ORPHA:79318")


async def test_orphan_atlas_partial_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    search_hit = MagicMock(mondo_id="MONDO:0001")

    mondo_client = MagicMock()
    mondo_client.from_orphanet = AsyncMock(return_value=[search_hit])
    mondo_client.lookup = AsyncMock(side_effect=RuntimeError("lookup err"))
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mondo_client)

    hpo_client = MagicMock()
    hpo_client.phenotypes_for_disease = AsyncMock(side_effect=RuntimeError("hpo err"))
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.HPOClient", hpo_client)

    ot_client = MagicMock()
    ot_client.associated_targets = AsyncMock(side_effect=RuntimeError("ot err"))
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", ot_client
    )

    out = await get_orphan_disease_atlas(OrphanDiseaseInput(orphanet_id="79318"))
    parsed = json.loads(out.split("---")[0].strip())
    # All sub-tasks raised → only mondo_id and status present
    assert parsed["status"] == "success"
    assert "disease" not in parsed
    assert "phenotypes" not in parsed
    assert "protein_targets" not in parsed


async def test_orphan_atlas_outer_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        async def __aenter__(self) -> Any:
            raise RuntimeError("ctx fail")

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr("alphafold_sovereign.tools.disease.MONDOClient", lambda *a, **kw: _Boom())
    with pytest.raises(ToolError):
        await get_orphan_disease_atlas(OrphanDiseaseInput(orphanet_id="79318"))


# ---------------------------------------------------------------------------
# compare_disease_target_overlap
# ---------------------------------------------------------------------------


async def test_compare_disease_target_overlap_success(monkeypatch: pytest.MonkeyPatch) -> None:
    t_shared = _evidence_score(ensembl_id="ENSG_SHARED", gene="SH", uniprot="PU1")
    t_a_only = _evidence_score(ensembl_id="ENSG_A_ONLY", gene="OA", uniprot="PU2")
    t_b_only = _evidence_score(ensembl_id="ENSG_B_ONLY", gene="OB", uniprot="PU3")

    mock_client = MagicMock()
    mock_client.associated_targets = AsyncMock(
        side_effect=[[t_shared, t_a_only], [t_shared, t_b_only]]
    )
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", mock_client
    )

    out = await compare_disease_target_overlap(
        DiseaseSimilarityInput(mondo_id_a="MONDO:0001", mondo_id_b="MONDO:0002")
    )
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert parsed["shared_target_count"] == 1
    assert parsed["unique_to_a_count"] == 1


async def test_compare_disease_target_overlap_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.associated_targets = AsyncMock(side_effect=[[], []])
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", mock_client
    )

    out = await compare_disease_target_overlap(
        DiseaseSimilarityInput(mondo_id_a="MONDO:0001", mondo_id_b="MONDO:0002")
    )
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"
    assert parsed["jaccard_similarity"] == 0.0


async def test_compare_disease_target_overlap_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.associated_targets = AsyncMock(side_effect=RuntimeError("fail"))
    _patch_client_class(
        monkeypatch, "alphafold_sovereign.tools.disease.OpenTargetsClient", mock_client
    )

    with pytest.raises(ToolError):
        await compare_disease_target_overlap(
            DiseaseSimilarityInput(mondo_id_a="MONDO:0001", mondo_id_b="MONDO:0002")
        )


# ---------------------------------------------------------------------------
# resolve_icd10_to_mondo
# ---------------------------------------------------------------------------


async def test_resolve_icd10_success(monkeypatch: pytest.MonkeyPatch) -> None:
    result = MagicMock()
    result.to_dict.return_value = {"mondo_id": "MONDO:0001"}
    mock_client = MagicMock()
    mock_client.from_icd10 = AsyncMock(return_value=[result])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mock_client)

    out = await resolve_icd10_to_mondo(ICD10ToMONDOInput(icd10_code="I21.0"))
    parsed = json.loads(out.split("---")[0].strip())
    assert parsed["status"] == "success"


async def test_resolve_icd10_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.from_icd10 = AsyncMock(return_value=[])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mock_client)

    out = await resolve_icd10_to_mondo(ICD10ToMONDOInput(icd10_code="Z99"))
    parsed = json.loads(out)
    assert parsed["status"] == "not_found"


async def test_resolve_icd10_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.from_icd10 = AsyncMock(side_effect=RuntimeError("err"))
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mock_client)

    with pytest.raises(ToolError):
        await resolve_icd10_to_mondo(ICD10ToMONDOInput(icd10_code="X99"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def test_fetch_clinvar_uses_hgvs_results(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_cv = MagicMock()
    mock_cv.search_by_hgvs = AsyncMock(return_value=[{"variation_id": "1"}])
    mock_cv.search_gene = AsyncMock(return_value=[])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.ClinVarClient", mock_cv)

    out = await _fetch_clinvar("BRCA1:c.181T>G", "BRCA1")
    assert out == {"variation_id": "1"}


async def test_fetch_clinvar_falls_back_to_gene(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_cv = MagicMock()
    mock_cv.search_by_hgvs = AsyncMock(return_value=[])
    mock_cv.search_gene = AsyncMock(return_value=[{"variation_id": "2"}])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.ClinVarClient", mock_cv)

    out = await _fetch_clinvar("BRCA1:c.181T>G", "BRCA1")
    assert out == {"variation_id": "2"}


async def test_fetch_clinvar_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_cv = MagicMock()
    mock_cv.search_by_hgvs = AsyncMock(return_value=[])
    mock_cv.search_gene = AsyncMock(return_value=[])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.ClinVarClient", mock_cv)

    out = await _fetch_clinvar("X:c.1T>G", "X")
    assert out == {}


async def test_fetch_clinvar_no_gene_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """When gene_symbol is empty, fallback to search_gene is skipped."""
    mock_cv = MagicMock()
    mock_cv.search_by_hgvs = AsyncMock(return_value=[])
    mock_cv.search_gene = AsyncMock(return_value=[{"a": 1}])  # would be wrong path
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.ClinVarClient", mock_cv)

    out = await _fetch_clinvar("X:c.1T>G", "")
    assert out == {}
    mock_cv.search_gene.assert_not_called()


async def test_fetch_gnomad(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_gn = MagicMock()
    mock_gn.gene_constraint = AsyncMock(return_value={"loeuf": 0.5})
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.GnomADClient", mock_gn)

    out = await _fetch_gnomad("x", "BRCA1")
    assert out == {"loeuf": 0.5}


async def test_fetch_disease_context() -> None:
    out = await _fetch_disease_context("BRCA1")
    assert "BRCA1" in out["note"]


async def test_omim_to_mondo_success(monkeypatch: pytest.MonkeyPatch) -> None:
    hit = MagicMock(mondo_id="MONDO:0001")
    mock_mc = MagicMock()
    mock_mc.search = AsyncMock(return_value=[hit])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mock_mc)

    out = await _omim_to_mondo("OMIM:1234")
    assert out == "MONDO:0001"


async def test_omim_to_mondo_empty_id() -> None:
    assert await _omim_to_mondo("") is None


async def test_omim_to_mondo_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_mc = MagicMock()
    mock_mc.search = AsyncMock(return_value=[])
    _patch_client_class(monkeypatch, "alphafold_sovereign.tools.disease.MONDOClient", mock_mc)

    out = await _omim_to_mondo("OMIM:9999")
    assert out is None


async def test_omim_to_mondo_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        async def __aenter__(self) -> Any:
            raise RuntimeError("err")

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr("alphafold_sovereign.tools.disease.MONDOClient", lambda *a, **kw: _Boom())
    out = await _omim_to_mondo("OMIM:9999")
    assert out is None


def test_get_ot_client_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_ot_client creates a singleton OpenTargetsClient."""
    from alphafold_sovereign.tools.disease import _get_ot_client

    monkeypatch.setattr("alphafold_sovereign.tools.disease._OT_SINGLETON", None)
    client = _get_ot_client()
    assert client is not None
    assert _get_ot_client() is client


async def test_uniprot_to_ensembl_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Singleton OT client resolves UniProt to Ensembl via resolve_target."""
    mock_ot = MagicMock()
    mock_ot.resolve_target = AsyncMock(
        return_value={"ensembl_id": "ENSG00000012048", "symbol": "BRCA1"}
    )
    monkeypatch.setattr("alphafold_sovereign.tools.disease._get_ot_client", lambda: mock_ot)
    out = await _uniprot_to_ensembl("P38398")
    assert out == "ENSG00000012048"


async def test_uniprot_to_ensembl_no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_ot = MagicMock()
    mock_ot.resolve_target = AsyncMock(return_value={})
    monkeypatch.setattr("alphafold_sovereign.tools.disease._get_ot_client", lambda: mock_ot)
    out = await _uniprot_to_ensembl("P00001")
    assert out == ""


async def test_uniprot_to_ensembl_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_ot = MagicMock()
    mock_ot.resolve_target = AsyncMock(side_effect=RuntimeError("oops"))
    monkeypatch.setattr("alphafold_sovereign.tools.disease._get_ot_client", lambda: mock_ot)
    out = await _uniprot_to_ensembl("P00001")
    assert out == ""


# ---------------------------------------------------------------------------
# COMMON_DISEASE_ROOTS sanity
# ---------------------------------------------------------------------------


def test_common_disease_roots_categories() -> None:
    expected = {
        "cardiovascular",
        "oncology",
        "neurodegeneration",
        "metabolic",
        "autoimmune",
        "respiratory",
        "infectious",
        "psychiatric",
        "rare",
    }
    assert expected.issubset(COMMON_DISEASE_ROOTS.keys())
