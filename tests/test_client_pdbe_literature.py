# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Santiago Maniches and TOPOLOGICA LLC
"""PDBe/IUCr source-reported literature residue normalization and transport."""

from __future__ import annotations

import copy
import math
from typing import Any

import httpx
import pytest
import respx

from alphafold_sovereign.clients.pdbe_literature import (
    PDBeAnnotationSchemaError,
    PDBeLiteratureClient,
    _as_list,
    _normalize_residue_annotations,
)

ACCESSION = "Q8VH51"
POSITION = 495
URL = "https://www.ebi.ac.uk/pdbe/api/v2/uniprot/llm_annotations/summary/Q8VH51/495"


def _example() -> dict[str, Any]:
    """Minimal fixture derived from PDBe's public notebook schema, not a live recording."""
    return {
        ACCESSION: {
            "dataType": "ANNOTATIONS",
            "uniprotResidue": "495",
            "data": [
                {
                    "pdbId": "5cxt",
                    "providerList": [
                        {
                            "provider": "IUCr",
                            "residueList": [
                                {
                                    "indexType": "PDB",
                                    "startIndex": 79,
                                    "endIndex": 79,
                                    "additionalData": [
                                        {
                                            "pubmedId": 27050129,
                                            "pmcId": "PMC4822562",
                                            "doi": "10.1107/S2059798316001248",
                                            "primaryCitation": "Y",
                                            "openAccess": "N",
                                            "entityId": 1,
                                            "pdbResidue": 79,
                                            "authorResidueNumber": 495,
                                            "pdbChain": "A",
                                            "uniprotAccession": ACCESSION,
                                            "uniprotResidue": 495,
                                            "sentence": "Trp495 participates in protein binding.",
                                            "section": "display-objects",
                                            "exact": "Trp495",
                                            "entityType": "residue_name_number",
                                            "annotator": "autoannotator_v2.1_quant",
                                            "aiScore": 0.999,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    }


def test_list_guard() -> None:
    assert _as_list([], "x") == []
    with pytest.raises(PDBeAnnotationSchemaError):
        _as_list({}, "x")


def test_normalized_evidence_identity_and_provenance() -> None:
    out = _normalize_residue_annotations(_example(), ACCESSION, POSITION)
    assert out["status"] == "ok"
    assert out["total_matching_records"] == 1
    assert out["excluded_mismatched_records"] == 0
    assert out["truncated"] is False
    ann = out["records"][0]
    assert (ann["pdb_id"], ann["pdb_chain"], ann["pdb_residue"]) == ("5cxt", "A", 79)
    assert ann["author_residue_number"] == POSITION
    assert ann["uniprot_residue"] == POSITION
    assert ann["doi"] == "10.1107/S2059798316001248"
    assert ann["pubmed_id"] == 27050129
    assert ann["ai_score"] == 0.999
    assert ann["experimental_validation_metrics"] is None


async def test_client_calls_documented_v2_endpoint(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).mock(return_value=httpx.Response(200, json=_example()))
    async with PDBeLiteratureClient() as client:
        out = await client.get_residue_annotations(ACCESSION, POSITION)
    assert route.called
    assert out["status"] == "ok"


@pytest.mark.parametrize(
    ("accession", "position"),
    [
        ("x/../../external", 495),
        ("P04637-9", 495),
        ("Q8VH51", 0),
    ],
)
async def test_reject_invalid_coordinates_no_network(accession: str, position: int) -> None:
    async with PDBeLiteratureClient() as client:
        with pytest.raises(ValueError):
            await client.get_residue_annotations(accession, position)


def test_no_annotations_is_not_mapping_failure() -> None:
    assert _normalize_residue_annotations({}, ACCESSION, POSITION)["status"] == "no_annotations"
    empty = _example()
    empty[ACCESSION]["data"] = []
    assert _normalize_residue_annotations(empty, ACCESSION, POSITION)["status"] == "no_annotations"


def test_conflicting_mappings_are_excluded() -> None:
    example = _example()
    row = example[ACCESSION]["data"][0]["providerList"][0]["residueList"][0]["additionalData"][0]
    row["uniprotResidue"] = 496
    result = _normalize_residue_annotations(example, ACCESSION, POSITION)
    assert result["status"] == "no_verified_match"
    assert result["excluded_mismatched_records"] == 1
    row["uniprotResidue"] = 495
    row["uniprotAccession"] = "P04637"
    assert (
        _normalize_residue_annotations(example, ACCESSION, POSITION)["status"]
        == "no_verified_match"
    )


def test_long_result_is_bounded() -> None:
    example = _example()
    site = example[ACCESSION]["data"][0]["providerList"][0]["residueList"][0]
    site["additionalData"] = site["additionalData"] * 41
    out = _normalize_residue_annotations(example, ACCESSION, POSITION)
    assert out["status"] == "ok"
    assert out["total_matching_records"] == 41
    assert len(out["records"]) == 40
    assert out["truncated"] is True


@pytest.mark.parametrize(
    "mutator",
    [
        lambda x: [],
        lambda x: {"wrong": {}},
        lambda x: {ACCESSION: {"dataType": "BAD", "data": []}},
        lambda x: {ACCESSION: {"dataType": "ANNOTATIONS", "uniprotResidue": "496", "data": []}},
        lambda x: {ACCESSION: {"dataType": "ANNOTATIONS", "data": {}}},
        lambda x: _modify(x, ["data", 0], "bad"),
        lambda x: _modify(x, ["data", 0, "pdbId"], "../"),
        lambda x: _modify(x, ["data", 0, "providerList"], None),
        lambda x: _modify(x, ["data", 0, "providerList", 0], {}),
        lambda x: _modify(x, ["data", 0, "providerList", 0, "residueList"], None),
        lambda x: _modify(
            x, ["data", 0, "providerList", 0, "residueList", 0, "indexType"], "UniProt"
        ),
        lambda x: _modify(
            x, ["data", 0, "providerList", 0, "residueList", 0, "additionalData"], {}
        ),
        lambda x: _modify(
            x, ["data", 0, "providerList", 0, "residueList", 0, "additionalData", 0], []
        ),
        lambda x: _modify(
            x, ["data", 0, "providerList", 0, "residueList", 0, "additionalData", 0, "aiScore"], 2.0
        ),
        lambda x: _modify(
            x,
            ["data", 0, "providerList", 0, "residueList", 0, "additionalData", 0, "aiScore"],
            math.nan,
        ),
        lambda x: _modify(
            x,
            ["data", 0, "providerList", 0, "residueList", 0, "additionalData", 0, "aiScore"],
            True,
        ),
        lambda x: _modify(
            x,
            ["data", 0, "providerList", 0, "residueList", 0, "additionalData", 0, "sentence"],
            None,
        ),
        lambda x: _modify(
            x,
            ["data", 0, "providerList", 0, "residueList", 0, "additionalData", 0, "pdbResidue"],
            "79",
        ),
    ],
)
def test_fail_closed_on_invalid_schema(mutator: Any) -> None:
    with pytest.raises(PDBeAnnotationSchemaError):
        _normalize_residue_annotations(mutator(_example()), ACCESSION, POSITION)


def _modify(example: dict[str, Any], path: list[str | int], value: Any) -> dict[str, Any]:
    target = copy.deepcopy(example)
    current: Any = target[ACCESSION]
    for step in path[:-1]:
        current = current[step]
    current[path[-1]] = value
    return target
