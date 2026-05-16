# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.ensembl``."""

from __future__ import annotations

import httpx
import pytest
import respx

from alphafold_sovereign.clients.ensembl import EnsemblClient


# ---------------------------------------------------------------------------
# parse_gene_from_hgvs (static helper)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hgvs", "expected"),
    [
        ("BRCA1:c.181T>G", "BRCA1"),
        ("brca1:c.181T>G", "BRCA1"),
        ("TP53:p.Arg175His", "TP53"),
        ("NM_007294.3:c.181T>G", None),
        ("garbage_input", None),
    ],
)
def test_parse_gene_from_hgvs(hgvs: str, expected: str | None) -> None:
    assert EnsemblClient.parse_gene_from_hgvs(hgvs) == expected


# ---------------------------------------------------------------------------
# _parse_tc (static helper)
# ---------------------------------------------------------------------------


def test_parse_tc_minimal_dict() -> None:
    parsed = EnsemblClient._parse_tc({})
    assert parsed["transcript_id"] == ""
    assert parsed["consequence_terms"] == []
    assert parsed["sift_score"] is None
    assert parsed["cadd_phred"] is None
    assert parsed["protein_start"] is None


def test_parse_tc_full_payload() -> None:
    tc = {
        "transcript_id": "ENST00000357654",
        "gene_id": "ENSG0001",
        "gene_symbol": "BRCA1",
        "biotype": "protein_coding",
        "canonical": 1,
        "impact": "HIGH",
        "consequence_terms": ["missense_variant"],
        "protein_id": "ENSP1",
        "protein_start": 61,
        "amino_acids": "A/B",
        "codons": "GCC/GCG",
        "hgvsp": "ENSP1:p.A1B",
        "hgvsc": "ENST1:c.1A>B",
        "exon": "5/24",
        "intron": "",
        "sift_score": 0.04,
        "sift_prediction": "deleterious",
        "polyphen_score": 0.95,
        "polyphen_prediction": "probably_damaging",
        "extra": {
            "CADD_PHRED": 27.3,
            "CADD_raw": 4.21,
            "SpliceAI_pred_DS_max": 0.85,
        },
    }
    parsed = EnsemblClient._parse_tc(tc)
    assert parsed["canonical"] is True
    assert parsed["protein_start"] == 61
    assert parsed["cadd_phred"] == 27.3
    assert parsed["spliceai_ds_max"] == 0.85


def test_parse_tc_handles_extra_none() -> None:
    parsed = EnsemblClient._parse_tc({"transcript_id": "T", "extra": None})
    assert parsed["cadd_phred"] is None


# ---------------------------------------------------------------------------
# _extract_xref_ids (static helper)
# ---------------------------------------------------------------------------


def test_extract_xref_ids_filters_by_db_prefix() -> None:
    xrefs = [
        {"dbname": "Uniprot/SWISSPROT", "primary_id": "P38398"},
        {"dbname": "Uniprot/SPTREMBL", "primary_id": "Q1234"},
        {"dbname": "EntrezGene", "primary_id": "672"},
        {"dbname": "Uniprot/SWISSPROT", "primary_id": ""},  # filtered: empty id
    ]
    ids = EnsemblClient._extract_xref_ids(xrefs, "Uniprot")
    assert ids == ["P38398", "Q1234"]


# ---------------------------------------------------------------------------
# vep_hgvs
# ---------------------------------------------------------------------------


async def test_vep_hgvs_parses_transcript_consequences(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/vep/human/hgvs/BRCA1:c.181T>G",
    ).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "input": "BRCA1:c.181T>G",
                    "transcript_consequences": [
                        {
                            "transcript_id": "ENST1",
                            "gene_symbol": "BRCA1",
                            "consequence_terms": ["missense_variant"],
                            "canonical": 1,
                        }
                    ],
                }
            ],
        ),
    )
    async with EnsemblClient() as client:
        rows = await client.vep_hgvs("BRCA1:c.181T>G")
    assert len(rows) == 1
    assert rows[0]["gene_symbol"] == "BRCA1"
    assert rows[0]["canonical"] is True


async def test_vep_hgvs_non_list_payload_returns_empty(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/vep/human/hgvs/X:c.1A>T",
    ).mock(return_value=httpx.Response(200, json={"weird": "payload"}))
    async with EnsemblClient() as client:
        assert await client.vep_hgvs("X:c.1A>T") == []


async def test_vep_hgvs_canonical_false_kwarg(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.get(
        "https://rest.ensembl.org/vep/human/hgvs/X:c.1A>T",
    ).mock(return_value=httpx.Response(200, json=[]))
    async with EnsemblClient() as client:
        assert await client.vep_hgvs("X:c.1A>T", canonical=False) == []
    assert "canonical=0" in str(route.calls.last.request.url)


async def test_vep_hgvs_error_returns_empty(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/vep/human/hgvs/BAD",
    ).mock(return_value=httpx.Response(500))
    async with EnsemblClient() as client:
        assert await client.vep_hgvs("BAD") == []


# ---------------------------------------------------------------------------
# gene_lookup
# ---------------------------------------------------------------------------


async def test_gene_lookup_full_payload(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/lookup/symbol/human/BRCA1",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "ENSG0001",
                "display_name": "BRCA1",
                "description": "BRCA1 DNA repair associated [Source:HGNC]",
                "biotype": "protein_coding",
                "strand": -1,
                "seq_region_name": "17",
                "start": 100,
                "end": 200,
                "Xref": [{"dbname": "Uniprot/SWISSPROT", "primary_id": "P38398"}],
            },
        ),
    )
    async with EnsemblClient() as client:
        info = await client.gene_lookup("BRCA1")
    assert info["found"] is True
    assert info["ensembl_gene_id"] == "ENSG0001"
    assert info["description"] == "BRCA1 DNA repair associated"
    assert info["uniprot_ids"] == ["P38398"]


async def test_gene_lookup_missing_description(respx_mock: respx.MockRouter) -> None:
    """Missing description triggers the `or ''` fallback."""
    respx_mock.get(
        "https://rest.ensembl.org/lookup/symbol/human/X",
    ).mock(return_value=httpx.Response(200, json={"id": "ENSG"}))
    async with EnsemblClient() as client:
        info = await client.gene_lookup("X")
    assert info["description"] == ""


async def test_gene_lookup_error_returns_not_found(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/lookup/symbol/human/BAD",
    ).mock(return_value=httpx.Response(500))
    async with EnsemblClient() as client:
        info = await client.gene_lookup("BAD")
    assert info["found"] is False


# ---------------------------------------------------------------------------
# variant_info
# ---------------------------------------------------------------------------


async def test_variant_info_ok(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/variation/human/rs1799977",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "rs1799977",
                "minor_allele": "G",
                "MAF": 0.1,
                "evidence": ["1000G"],
                "mappings": [
                    {
                        "seq_region_name": "3",
                        "start": 100,
                        "end": 100,
                        "allele_string": "A/G",
                    }
                ],
            },
        ),
    )
    async with EnsemblClient() as client:
        info = await client.variant_info("rs1799977")
    assert info["found"] is True
    assert info["maf"] == 0.1
    assert info["mappings"][0]["ref"] == "A"


async def test_variant_info_no_mappings(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/variation/human/rs1",
    ).mock(return_value=httpx.Response(200, json={"name": "rs1"}))
    async with EnsemblClient() as client:
        info = await client.variant_info("rs1")
    assert info["mappings"] == []


async def test_variant_info_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/variation/human/rs0",
    ).mock(return_value=httpx.Response(500))
    async with EnsemblClient() as client:
        info = await client.variant_info("rs0")
    assert info["found"] is False


# ---------------------------------------------------------------------------
# orthologs
# ---------------------------------------------------------------------------


_GENE_LOOKUP_OK = {
    "id": "ENSG0001",
    "display_name": "BRCA1",
    "description": "",
    "biotype": "protein_coding",
    "Xref": [],
}


async def test_orthologs_filter_and_limit(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/lookup/symbol/human/BRCA1",
    ).mock(return_value=httpx.Response(200, json=_GENE_LOOKUP_OK))
    respx_mock.get(
        "https://rest.ensembl.org/homology/id/ENSG0001",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "homologies": [
                            {
                                "type": "ortholog_one2one",
                                "subtype": "Boreoeutheria",
                                "dn_ds": 0.05,
                                "target": {
                                    "species": "mus_musculus",
                                    "id": "MUSG0",
                                    "display_label": "Brca1",
                                    "perc_id": 76.0,
                                },
                            },
                            {
                                "type": "ortholog_one2one",
                                "target": {
                                    "species": "gallus_gallus",
                                    "id": "GG0",
                                    "perc_id": 55.0,
                                },
                            },
                            {
                                "type": "ortholog_one2one",
                                "target": {
                                    "species": "drosophila_melanogaster",
                                    "id": "DROS0",
                                    "perc_id": 30.0,
                                },
                            },
                        ]
                    }
                ]
            },
        ),
    )
    async with EnsemblClient() as client:
        rows = await client.orthologs(
            "BRCA1", target_species=["mus_musculus", "gallus_gallus"], limit=2
        )
    species = [r["species"] for r in rows]
    assert species == ["mus_musculus", "gallus_gallus"]


async def test_orthologs_limit_breaks_outer_loop(
    respx_mock: respx.MockRouter,
) -> None:
    """Two homology groups; limit=1 forces both inner & outer breaks."""
    respx_mock.get(
        "https://rest.ensembl.org/lookup/symbol/human/BRCA1",
    ).mock(return_value=httpx.Response(200, json=_GENE_LOOKUP_OK))
    respx_mock.get(
        "https://rest.ensembl.org/homology/id/ENSG0001",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"homologies": [{"type": "x", "target": {"species": "mouse", "id": "M"}}]},
                    {"homologies": [{"type": "y", "target": {"species": "rat", "id": "R"}}]},
                ]
            },
        ),
    )
    async with EnsemblClient() as client:
        rows = await client.orthologs("BRCA1", limit=1)
    assert len(rows) == 1


async def test_orthologs_filter_skips_non_matching(
    respx_mock: respx.MockRouter,
) -> None:
    """When target_species filters out a hit, the `continue` branch fires."""
    respx_mock.get(
        "https://rest.ensembl.org/lookup/symbol/human/BRCA1",
    ).mock(return_value=httpx.Response(200, json=_GENE_LOOKUP_OK))
    respx_mock.get(
        "https://rest.ensembl.org/homology/id/ENSG0001",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "homologies": [
                            {
                                "type": "x",
                                "target": {
                                    "species": "drosophila_melanogaster",
                                    "id": "DROS",
                                    "perc_id": 30,
                                },
                            },
                            {
                                "type": "x",
                                "target": {
                                    "species": "mus_musculus",
                                    "id": "MUSG",
                                    "perc_id": 80,
                                },
                            },
                        ]
                    }
                ]
            },
        ),
    )
    async with EnsemblClient() as client:
        rows = await client.orthologs("BRCA1", target_species=["mus_musculus"])
    assert [r["species"] for r in rows] == ["mus_musculus"]


async def test_orthologs_no_filter_returns_all(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/lookup/symbol/human/BRCA1",
    ).mock(return_value=httpx.Response(200, json=_GENE_LOOKUP_OK))
    respx_mock.get(
        "https://rest.ensembl.org/homology/id/ENSG0001",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "homologies": [
                            {
                                "type": "ortholog_one2many",
                                "target": {"species": "frog", "id": "F"},
                            }
                        ]
                    }
                ]
            },
        ),
    )
    async with EnsemblClient() as client:
        rows = await client.orthologs("BRCA1")
    assert rows[0]["species"] == "frog"


async def test_orthologs_gene_lookup_fails(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/lookup/symbol/human/UNKNOWN",
    ).mock(return_value=httpx.Response(404))
    async with EnsemblClient() as client:
        rows = await client.orthologs("UNKNOWN")
    assert rows == []


async def test_orthologs_homology_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/lookup/symbol/human/BRCA1",
    ).mock(return_value=httpx.Response(200, json=_GENE_LOOKUP_OK))
    respx_mock.get(
        "https://rest.ensembl.org/homology/id/ENSG0001",
    ).mock(return_value=httpx.Response(500))
    async with EnsemblClient() as client:
        rows = await client.orthologs("BRCA1")
    assert rows == []


# ---------------------------------------------------------------------------
# transcript_protein
# ---------------------------------------------------------------------------


async def test_transcript_protein_ok(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/lookup/id/ENST00000357654",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "Translation": {"id": "ENSP1", "length": 1863},
                "Xref": [{"dbname": "Uniprot/SWISSPROT", "primary_id": "P38398"}],
            },
        ),
    )
    async with EnsemblClient() as client:
        info = await client.transcript_protein("ENST00000357654")
    assert info["protein_id"] == "ENSP1"
    assert info["uniprot_id"] == "P38398"
    assert info["length"] == 1863


async def test_transcript_protein_no_uniprot(respx_mock: respx.MockRouter) -> None:
    """When the Xref list contains no Uniprot entries, ``uniprot_id`` is ''."""
    respx_mock.get(
        "https://rest.ensembl.org/lookup/id/ENST0",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "Translation": {"id": "ENSP0"},
                "Xref": [{"dbname": "EntrezGene", "primary_id": "1"}],
            },
        ),
    )
    async with EnsemblClient() as client:
        info = await client.transcript_protein("ENST0")
    assert info["uniprot_id"] == ""


async def test_transcript_protein_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://rest.ensembl.org/lookup/id/BAD",
    ).mock(return_value=httpx.Response(500))
    async with EnsemblClient() as client:
        info = await client.transcript_protein("BAD")
    assert info["found"] is False
