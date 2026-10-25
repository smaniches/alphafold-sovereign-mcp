# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Offline end-to-end identity and source-failure contracts with fabricated data.

All accessions, genes, variation IDs, and responses below are synthetic software
fixtures, not captured biomedical records or validation of clinical claims.
The real ClinVar parser is exercised over an intercepted HTTP transport and
its result passes through the real variant-report orchestration code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from alphafold_sovereign.clients.clinvar import ClinVarClient
from alphafold_sovereign.tools import precision_medicine as pm
from alphafold_sovereign.tools.precision_medicine import (
    VariantClinicalReportInput,
    generate_variant_clinical_report,
)

_SYNTHETIC_ACCESSION = "NM_999999.1"
_SYNTHETIC_GENE = "SYNTHX"
_SYNTHETIC_ID = "999991"
_SYNTHETIC_TITLE = f"{_SYNTHETIC_ACCESSION}({_SYNTHETIC_GENE}):c.42A>G (synthetic)"


def _stub_other_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep all non-ClinVar sources offline and deterministically empty."""
    clients: dict[str, MagicMock] = {}
    for name in ("ensembl", "gnomad", "disgenet", "opentargets", "chembl", "alphafold"):
        mock = MagicMock()
        clients[name] = mock
        monkeypatch.setattr(pm, f"_{name}", lambda m=mock: m)

    clients["ensembl"].vep_hgvs = AsyncMock(return_value=[])
    clients["ensembl"].gene_lookup = AsyncMock(return_value={})
    clients["gnomad"].gene_constraint = AsyncMock(return_value={})
    clients["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    clients["alphafold"].alphamissense_score = AsyncMock(return_value=None)


@pytest.mark.parametrize(
    ("query", "expected_verified", "expected_candidate"),
    [
        (f"{_SYNTHETIC_GENE}:c.42A>G", False, True),
        (f"{_SYNTHETIC_ACCESSION}({_SYNTHETIC_GENE}):c.42A>G", True, False),
        ("NM_999999.2(SYNTHX):c.42A>G", False, False),
        (f"{_SYNTHETIC_GENE}:c.43A>G", False, False),
    ],
)
async def test_synthetic_clinvar_record_cannot_cross_reference_boundary(
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    query: str,
    expected_verified: bool,
    expected_candidate: bool,
) -> None:
    """Only a literal, same-version transcript match attributes source data."""
    _stub_other_sources(monkeypatch)
    respx_mock.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": [_SYNTHETIC_ID]}})
    )
    respx_mock.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    _SYNTHETIC_ID: {
                        "uid": _SYNTHETIC_ID,
                        "title": _SYNTHETIC_TITLE,
                        "gene_sort": _SYNTHETIC_GENE,
                        "germline_classification": {
                            "description": "Pathogenic",
                            "review_status": "reviewed by expert panel",
                        },
                        "trait_set": [{"trait_name": "synthetic condition"}],
                    }
                }
            },
        )
    )

    async with ClinVarClient() as clinvar:
        monkeypatch.setattr(pm, "_clinvar", lambda: clinvar)
        output = await generate_variant_clinical_report(
            VariantClinicalReportInput(hgvs=query, include_drug_context=False)
        )

    assert output["clinical_tier"] == "NOT_ASSESSED"
    assert "PP5" not in output["acmg_criteria_draft"]["criteria"]
    assert output["clinvar"]["found"] is expected_verified
    assert output["clinvar"]["variation_id"] == (
        _SYNTHETIC_ID if expected_verified else ""
    )
    assert output["clinvar"]["classification"] == (
        "Pathogenic" if expected_verified else "Not provided"
    )
    assert output["clinvar"]["unverified_candidates"] == (
        [{"variation_id": _SYNTHETIC_ID, "name": _SYNTHETIC_TITLE}]
        if expected_candidate
        else []
    )
    assert output["data_sources_status"]["clinvar"] == "ok"
    assert len(respx_mock.calls) == 2


@pytest.mark.parametrize(
    ("source_outcome", "expected_status"),
    [
        ("empty", "ok"),
        ("failed", "failed"),
    ],
)
async def test_synthetic_clinvar_empty_is_not_upstream_failure(
    monkeypatch: pytest.MonkeyPatch, source_outcome: str, expected_status: str
) -> None:
    """A successful empty search and a failed lookup cannot be conflated."""
    _stub_other_sources(monkeypatch)
    client = MagicMock()
    if source_outcome == "failed":
        client.search_by_hgvs = AsyncMock(side_effect=RuntimeError("synthetic outage"))
    else:
        client.search_by_hgvs = AsyncMock(return_value=[])
    monkeypatch.setattr(pm, "_clinvar", lambda: client)

    output = await generate_variant_clinical_report(
        VariantClinicalReportInput(hgvs=f"{_SYNTHETIC_GENE}:c.42A>G", include_drug_context=False)
    )

    assert output["data_sources_status"]["clinvar"] == expected_status
    assert output["clinvar"]["found"] is False
    assert output["clinvar"]["classification"] == "Not provided"
    assert output["clinvar"]["unverified_candidates"] == []
    assert output["clinical_tier"] == "NOT_ASSESSED"
