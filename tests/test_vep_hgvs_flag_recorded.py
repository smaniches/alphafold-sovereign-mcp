# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""AF-11: VEP's own HGVS expressions, over responses recorded with ``hgvs=1``.

Release 1.5.12 did not send ``hgvs=1``, so Ensembl VEP returned neither
``hgvsc`` nor ``hgvsp`` and ``functional_consequence.hgvsp`` was empty in every
live report. The real ``EnsemblClient`` runs here against responses recorded
from rest.ensembl.org on 2026-11-11 UTC with that parameter
(``fixtures/vep_hgvs_flag_20261111.json``; its ``meta`` block gives the
requests, the trimming applied and the SHA-256 of every complete live body).
Only the HTTP transport is replaced (respx), and it answers as Ensembl does:
the HGVS fields are returned only to a request that carries ``hgvs=1``. The
other report sources are stubbed.

The responses in ``fixtures/variant_frequency_path_20261110.json`` were
recorded a day earlier without ``hgvs=1``. A comparison of both forms for its
fifteen expressions on 2026-11-11 found no difference other than the added
``hgvsc``, ``hgvsp`` and ``hgvs_offset`` fields, so that fixture still
describes everything else VEP returns.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from alphafold_sovereign.tools import precision_medicine as pm

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import respx

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "vep_hgvs_flag_20261111.json").read_text(encoding="utf-8")
)
_RESPONSES: dict[str, dict[str, Any]] = _FIXTURE["responses"]
_VEP_PREFIX = "https://rest.ensembl.org/vep/human/hgvs/"
_HGVS_FIELDS = ("hgvsc", "hgvsp", "hgvs_offset")

_MISSENSE = "NM_007294.4:c.181T>G"
_SYNONYMOUS = "NM_000546.6:c.375G>A"
_SPLICE_ACCEPTOR = "NM_007294.4:c.135-1G>T"
_FRAMESHIFT = "NM_007294.4:c.68_69del"

# (expression, transcript-level HGVS, protein-level HGVS) of the canonical
# consequence on the queried gene, as Ensembl returned them.
_CASES = [
    pytest.param(
        _MISSENSE, "ENST00000357654.9:c.181T>G", "ENSP00000350283.3:p.Cys61Gly", id="missense"
    ),
    pytest.param(
        _SYNONYMOUS, "ENST00000269305.9:c.375G>A", "ENSP00000269305.4:p.Thr125=", id="synonymous"
    ),
    pytest.param(_SPLICE_ACCEPTOR, "ENST00000357654.9:c.135-1G>T", "", id="splice-acceptor"),
    pytest.param(
        _FRAMESHIFT,
        "ENST00000357654.9:c.68_69del",
        "ENSP00000350283.3:p.Glu23ValfsTer17",
        id="frameshift",
    ),
]


def _without_hgvs_fields(body: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same response as Ensembl returns it when ``hgvs=1`` is not sent."""
    stripped = copy.deepcopy(body)
    for hit in stripped:
        for consequence in hit["transcript_consequences"]:
            for field in _HGVS_FIELDS:
                consequence.pop(field, None)
    return stripped


@pytest.fixture
async def vep(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[str, Any]]:
    """Replay the recorded VEP responses through the real client inside the report tools."""
    state: dict[str, Any] = {"queries": [], "strip_hgvs_fields": False}

    def reply(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params)
        state["queries"].append(query)
        record = _RESPONSES[request.url.path.removeprefix("/vep/human/hgvs/")]
        body = record["body"]
        # Ensembl returns these fields only to a request that asks for them.
        if query.get("hgvs") != "1" or state["strip_hgvs_fields"]:
            body = _without_hgvs_fields(body)
        return httpx.Response(record["status"], json=body)

    respx_mock.get(url__startswith=_VEP_PREFIX).mock(side_effect=reply)

    pm._CLIENTS.clear()
    for name in ("clinvar", "gnomad", "disgenet", "opentargets", "chembl", "alphafold"):
        stub = MagicMock()
        monkeypatch.setattr(pm, f"_{name}", lambda value=stub: value)
        state[name] = stub
    state["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    state["gnomad"].variant_frequencies = AsyncMock(return_value={})
    state["gnomad"].gene_constraint = AsyncMock(return_value={})
    state["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    state["alphafold"].alphamissense_score = AsyncMock(return_value=None)
    monkeypatch.setattr(pm._ensembl(), "gene_lookup", AsyncMock(return_value={}))

    yield state

    for client in list(pm._CLIENTS.values()):
        await client.__aexit__(None, None, None)
    pm._CLIENTS.clear()


async def _report(hgvs: str) -> dict[str, Any]:
    return await pm.generate_variant_clinical_report(
        pm.VariantClinicalReportInput(hgvs=hgvs, include_drug_context=False)
    )


def _queried_gene_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return next(row for row in rows if row["canonical"] and row["hgvsc"])


def test_fixture_was_recorded_with_the_parameters_the_client_sends() -> None:
    assert _FIXTURE["meta"]["request"].endswith("&vcf_string=1&hgvs=1")
    assert set(_RESPONSES) == {_MISSENSE, _SYNONYMOUS, _SPLICE_ACCEPTOR, _FRAMESHIFT}


@pytest.mark.parametrize(("hgvs", "hgvsc", "hgvsp"), _CASES)
async def test_client_returns_the_hgvs_expressions_vep_reports(
    vep: dict[str, Any], hgvs: str, hgvsc: str, hgvsp: str
) -> None:
    rows = await pm._ensembl().vep_hgvs(hgvs)

    assert vep["queries"] == [
        {
            "canonical": "1",
            "numbers": "1",
            "protein": "1",
            "uniprot": "1",
            "xref_refseq": "1",
            "Genoverse": "0",
            "vcf_string": "1",
            "hgvs": "1",
        }
    ]
    row = _queried_gene_row(rows)
    assert row["hgvsc"] == hgvsc
    assert row["hgvsp"] == hgvsp
    # VEP writes its expressions on Ensembl identifiers, whatever the query used.
    assert row["hgvsc"].startswith(row["transcript_id"] + ".")
    assert all(row["locus"]["input"] == hgvs for row in rows)
    assert all(row["cadd_phred"] is None and row["spliceai_ds_max"] is None for row in rows)


async def test_a_consequence_on_a_neighbouring_gene_has_no_hgvs_expression(
    vep: dict[str, Any],
) -> None:
    """The BRCA1 deletion lies upstream of NBR2, whose canonical transcript VEP also lists."""
    rows = await pm._ensembl().vep_hgvs(_FRAMESHIFT)

    neighbour = next(row for row in rows if row["gene_symbol"] == "NBR2")
    assert neighbour["consequence_terms"] == ["upstream_gene_variant"]
    assert neighbour["hgvsc"] == ""
    assert neighbour["hgvsp"] == ""


@pytest.mark.parametrize(("hgvs", "hgvsc", "hgvsp"), _CASES)
async def test_report_gives_the_protein_level_expression(
    vep: dict[str, Any], hgvs: str, hgvsc: str, hgvsp: str
) -> None:
    report = await _report(hgvs)

    assert report["data_sources_status"]["ensembl_vep"] == "ok"
    assert report["functional_consequence"]["hgvsp"] == hgvsp
    assert report["functional_consequence"]["cadd_phred"] is None
    assert report["functional_consequence"]["cadd_phred_note"] == pm._CADD_NOT_RETRIEVED


@pytest.mark.parametrize(("hgvs", "hgvsc", "hgvsp"), _CASES)
async def test_the_flag_changes_nothing_in_the_report_but_hgvsp(
    vep: dict[str, Any], hgvs: str, hgvsc: str, hgvsp: str
) -> None:
    """Gene context, variant identity and candidate criteria do not depend on the new fields.

    ``hgvsc`` names an Ensembl transcript, so it never matches the RefSeq
    transcript of a query and cannot add or change the gene a report resolves.
    """
    with_flag = await _report(hgvs)
    vep["strip_hgvs_fields"] = True
    without_flag = await _report(hgvs)

    assert without_flag["functional_consequence"]["hgvsp"] == ""
    for report in (with_flag, without_flag):
        report["functional_consequence"].pop("hgvsp")
        report.pop("provenance")
    assert with_flag == without_flag
    assert with_flag["gene_symbol"] == ("TP53" if hgvs == _SYNONYMOUS else "BRCA1")


@pytest.mark.parametrize("hgvs", [_MISSENSE, _FRAMESHIFT])
async def test_the_flag_changes_nothing_in_the_acmg_evidence_review(
    vep: dict[str, Any], hgvs: str
) -> None:
    with_flag = await pm.classify_variant_acmg(pm.ACMGVariantInput(hgvs=hgvs))
    vep["strip_hgvs_fields"] = True
    without_flag = await pm.classify_variant_acmg(pm.ACMGVariantInput(hgvs=hgvs))

    for review in (with_flag, without_flag):
        review.pop("provenance")
    assert with_flag == without_flag
