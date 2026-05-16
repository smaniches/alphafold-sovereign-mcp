# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.alphafold``.

Mocks every EBI AlphaFold DB endpoint the client touches and exercises
both the happy-path return values and the empty / not-found branches.
"""

from __future__ import annotations

import httpx
import respx

from alphafold_sovereign.clients.alphafold import AlphaFoldClient, _parse_alphamissense_csv


# ---------------------------------------------------------------------------
# get_prediction
# ---------------------------------------------------------------------------


async def test_get_prediction_returns_first_when_list(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(
            200,
            json=[{"uniprotAccession": "P04637", "entryId": "AF-P04637-F1"}],
        ),
    )
    async with AlphaFoldClient() as client:
        meta = await client.get_prediction("P04637")
    assert meta["entryId"] == "AF-P04637-F1"


async def test_get_prediction_returns_raw_when_dict(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/Q9Y6X8").mock(
        return_value=httpx.Response(200, json={"entryId": "AF-Q9Y6X8-F1"}),
    )
    async with AlphaFoldClient() as client:
        meta = await client.get_prediction("Q9Y6X8")
    assert meta["entryId"] == "AF-Q9Y6X8-F1"


async def test_get_prediction_returns_raw_when_empty_list(
    respx_mock: respx.MockRouter,
) -> None:
    """Empty list ⇒ falls through to the raw cast path (returns the [] itself)."""
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/EMPTY").mock(
        return_value=httpx.Response(200, json=[]),
    )
    async with AlphaFoldClient() as client:
        meta = await client.get_prediction("EMPTY")
    assert meta == []  # type: ignore[comparison-overlap]


# ---------------------------------------------------------------------------
# get_pdb_bytes
# ---------------------------------------------------------------------------


async def test_get_pdb_bytes_with_files_url(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "uniprotAccession": "P04637",
                    "entryId": "AF-P04637-F1",
                    "pdbUrl": "https://alphafold.ebi.ac.uk/files/AF-P04637-F1-model_v4.pdb",
                }
            ],
        ),
    )
    respx_mock.get("https://alphafold.ebi.ac.uk/api/AF-P04637-F1-model_v4.pdb").mock(
        return_value=httpx.Response(200, content=b"ATOM 1 N MET A 1"),
    )
    async with AlphaFoldClient() as client:
        body = await client.get_pdb_bytes("P04637")
    assert body == b"ATOM 1 N MET A 1"


async def test_get_pdb_bytes_when_pdb_url_missing(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/NONE").mock(
        return_value=httpx.Response(200, json=[{"entryId": "X"}]),
    )
    async with AlphaFoldClient() as client:
        body = await client.get_pdb_bytes("NONE")
    assert body == b""


# ---------------------------------------------------------------------------
# get_pae
# ---------------------------------------------------------------------------


async def test_get_pae_returns_json(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P12345").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "entryId": "AF-P12345-F1",
                    "paeDocUrl": "https://alphafold.ebi.ac.uk/files/AF-P12345-F1-pae.json",
                }
            ],
        ),
    )
    respx_mock.get("https://alphafold.ebi.ac.uk/api/AF-P12345-F1-pae.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "predicted_aligned_error": [[0, 1], [1, 0]],
                "max_predicted_aligned_error": 31.75,
            },
        ),
    )
    async with AlphaFoldClient() as client:
        pae = await client.get_pae("P12345")
    assert pae["max_predicted_aligned_error"] == 31.75


async def test_get_pae_when_pae_url_missing(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/NO_PAE").mock(
        return_value=httpx.Response(200, json=[{"entryId": "AF"}]),
    )
    async with AlphaFoldClient() as client:
        pae = await client.get_pae("NO_PAE")
    assert pae == {}


# ---------------------------------------------------------------------------
# get_alphamissense
# ---------------------------------------------------------------------------


async def test_get_alphamissense_returns_predictions(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "entryId": "AF-P04637-F1",
                    "amAnnotationsUrl": (
                        "https://alphafold.ebi.ac.uk/files/AF-P04637-F1-aa-substitutions.csv"
                    ),
                }
            ],
        ),
    )
    respx_mock.get("https://alphafold.ebi.ac.uk/api/AF-P04637-F1-aa-substitutions.csv").mock(
        return_value=httpx.Response(
            200,
            content=b"protein_variant,am_pathogenicity,am_class\nM1A,0.92,LPath\nM1C,0.10,LBen\n",
        ),
    )
    async with AlphaFoldClient() as client:
        am = await client.get_alphamissense("P04637")
    assert am["accession"] == "P04637"
    assert len(am["predictions"]) == 2
    assert am["predictions"][0] == {
        "protein_variant": "M1A",
        "am_pathogenicity": 0.92,
        "am_class": "LPath",
    }


async def test_get_alphamissense_when_url_missing(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/NO_AM").mock(
        return_value=httpx.Response(200, json=[{"entryId": "x"}]),
    )
    async with AlphaFoldClient() as client:
        am = await client.get_alphamissense("NO_AM")
    assert am == {}


def test_parse_alphamissense_csv_skips_bad_rows() -> None:
    csv_bytes = (
        b"protein_variant,am_pathogenicity,am_class\n"
        b"M1A,0.92,LPath\n"
        b",0.50,Amb\n"
        b"M1C,not-a-number,Amb\n"
        b"M1D,0.10,LBen\n"
    )
    predictions = _parse_alphamissense_csv(csv_bytes)
    assert [p["protein_variant"] for p in predictions] == ["M1A", "M1D"]
    assert predictions[0]["am_pathogenicity"] == 0.92


def test_parse_alphamissense_csv_missing_score_column() -> None:
    predictions = _parse_alphamissense_csv(b"protein_variant,am_class\nM1A,LPath\n")
    assert predictions == []


async def test_alphamissense_score_found(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P38398").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "entryId": "AF-P38398-F1",
                    "amAnnotationsUrl": (
                        "https://alphafold.ebi.ac.uk/files/AF-P38398-F1-aa-substitutions.csv"
                    ),
                }
            ],
        ),
    )
    respx_mock.get("https://alphafold.ebi.ac.uk/api/AF-P38398-F1-aa-substitutions.csv").mock(
        return_value=httpx.Response(
            200, content=b"protein_variant,am_pathogenicity,am_class\nC61G,0.9904,LPath\n"
        ),
    )
    async with AlphaFoldClient() as client:
        hit = await client.alphamissense_score("P38398", "c61g")
    assert hit is not None
    assert hit["am_pathogenicity"] == 0.9904


async def test_alphamissense_score_not_found(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P38398").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "entryId": "AF-P38398-F1",
                    "amAnnotationsUrl": (
                        "https://alphafold.ebi.ac.uk/files/AF-P38398-F1-aa-substitutions.csv"
                    ),
                }
            ],
        ),
    )
    respx_mock.get("https://alphafold.ebi.ac.uk/api/AF-P38398-F1-aa-substitutions.csv").mock(
        return_value=httpx.Response(
            200, content=b"protein_variant,am_pathogenicity,am_class\nC61G,0.9904,LPath\n"
        ),
    )
    async with AlphaFoldClient() as client:
        miss = await client.alphamissense_score("P38398", "M1A")
    assert miss is None


async def test_alphamissense_score_no_annotations(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/NO_AM").mock(
        return_value=httpx.Response(200, json=[{"entryId": "x"}]),
    )
    async with AlphaFoldClient() as client:
        miss = await client.alphamissense_score("NO_AM", "M1A")
    assert miss is None


# ---------------------------------------------------------------------------
# check_availability
# ---------------------------------------------------------------------------


async def test_check_availability_true(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json=[{"entryId": "AF-P04637-F1"}]),
    )
    async with AlphaFoldClient() as client:
        assert await client.check_availability("P04637") is True


async def test_check_availability_false_no_entry(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/MISS").mock(
        return_value=httpx.Response(200, json=[{}]),
    )
    async with AlphaFoldClient() as client:
        assert await client.check_availability("MISS") is False


async def test_check_availability_false_on_exception(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/BAD").mock(
        return_value=httpx.Response(404, text="nope"),
    )
    async with AlphaFoldClient() as client:
        assert await client.check_availability("BAD") is False


# ---------------------------------------------------------------------------
# search_by_taxonomy
# ---------------------------------------------------------------------------


async def test_search_by_taxonomy_returns_list_when_list_response(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/predictions/taxid").mock(
        return_value=httpx.Response(200, json=[{"entryId": "AF-A0A1-F1"}]),
    )
    async with AlphaFoldClient() as client:
        results = await client.search_by_taxonomy(9606)
    assert len(results) == 1


async def test_search_by_taxonomy_extracts_predictions_when_dict_response(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/predictions/taxid").mock(
        return_value=httpx.Response(
            200,
            json={"predictions": [{"entryId": "AF-A0A2-F1"}]},
        ),
    )
    async with AlphaFoldClient() as client:
        results = await client.search_by_taxonomy(9606, page_size=500)  # exercise min() clamp
    assert results[0]["entryId"] == "AF-A0A2-F1"
