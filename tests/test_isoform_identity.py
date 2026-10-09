# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""AFDB isoform identity checks use UniProt's curated Displayed status.

No test contacts either upstream: every API response is an explicit fixture.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from alphafold_sovereign.clients._isoform import UniProtIsoformClient, UniProtVerificationError
from alphafold_sovereign.clients.alphafold import AlphaFoldClient, AlphaFoldPredictionSchemaError


def _uniprot_record(
    accession: str = "P04637",
    isoform_id: str = "P04637-1",
    status: str = "Displayed",
    sequence: str = "MKTV",
) -> dict[str, Any]:
    return {
        "primaryAccession": accession,
        "sequence": {"value": sequence},
        "comments": [
            {
                "commentType": "ALTERNATIVE PRODUCTS",
                "isoforms": [
                    {
                        "isoformIds": [isoform_id],
                        "isoformSequenceStatus": status,
                    }
                ],
            }
        ],
    }


def _model_record() -> dict[str, str]:
    return {
        "uniprotAccession": "P04637",
        "modelEntityId": "AF-P04637-F1",
        "sequence": "MKTV",
    }


@pytest.mark.parametrize("isoform", ["P04637-1", "P04637-2"])
async def test_displayed_isoform_reuses_only_sequence_identical_model(
    respx_mock: respx.MockRouter, isoform: str
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json=[_model_record()]),
    )
    respx_mock.get("https://rest.uniprot.org/uniprotkb/P04637.json").mock(
        return_value=httpx.Response(200, json=_uniprot_record(isoform_id=isoform)),
    )
    async with AlphaFoldClient() as client:
        model = await client.get_prediction(isoform)
    assert model["modelEntityId"] == "AF-P04637-F1"
    assert model["_sovereign_verified_isoform"] == isoform
    assert model["uniprotAccession"] == "P04637"


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (_uniprot_record(status="Described"), False),
        (_uniprot_record(sequence="MKTN"), False),
        (_uniprot_record(accession="Q9Y6X8"), False),
        (_uniprot_record(isoform_id="P04637-2"), False),
        ({"primaryAccession": "P04637", "sequence": {"value": "MKTV"}, "comments": []}, False),
        (_uniprot_record(), True),
    ],
)
async def test_curated_isoform_identity_is_fail_closed(
    respx_mock: respx.MockRouter, record: dict[str, Any], expected: bool
) -> None:
    respx_mock.get("https://rest.uniprot.org/uniprotkb/P04637.json").mock(
        return_value=httpx.Response(200, json=record),
    )
    async with UniProtIsoformClient() as client:
        result = await client.is_displayed_isoform("P04637", "P04637-1", "MKTV")
    assert result is expected


@pytest.mark.parametrize(
    "models",
    [
        [{"uniprotAccession": "P04637-2", "modelEntityId": "AF-P04637-2-F1"}],
        [_model_record(), _model_record()],
        [{"uniprotAccession": "P04637"}],
        [{"entryId": "AF-P04637-F1"}],
    ],
)
async def test_explicit_isoform_rejects_unverified_prediction(
    respx_mock: respx.MockRouter, models: list[Any]
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json=models),
    )
    async with AlphaFoldClient() as client:
        assert await client.get_prediction("P04637-1") == {}


async def test_exact_isoform_match_needs_no_uniprot_lookup(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(
            200,
            json=[
                _model_record(),
                {"uniprotAccession": "P04637-9", "modelEntityId": "AF-P04637-9-F1"},
            ],
        ),
    )
    async with AlphaFoldClient() as client:
        result = await client.get_prediction("P04637-9")
    assert result["modelEntityId"] == "AF-P04637-9-F1"
    assert len(respx_mock.calls) == 1


async def test_canonical_request_needs_no_uniprot_lookup(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json=[_model_record()]),
    )
    async with AlphaFoldClient() as client:
        result = await client.get_prediction("P04637")
    assert result["modelEntityId"] == "AF-P04637-F1"
    assert len(respx_mock.calls) == 1


async def test_missing_isoform_verification_propagates_source_error(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json=[_model_record()]),
    )

    async def unavailable(
        self: UniProtIsoformClient, accession: str, isoform_id: str, sequence: str
    ) -> bool:
        raise RuntimeError("UniProt service unavailable")

    monkeypatch.setattr(UniProtIsoformClient, "is_displayed_isoform", unavailable)
    async with AlphaFoldClient() as client:
        with pytest.raises(UniProtVerificationError, match="verification unavailable"):
            await client.get_prediction("P04637-1")


async def test_dict_prediction_mismatched_isoform_not_reassigned(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(
            200, json={"uniprotAccession": "P04637-2", "modelEntityId": "AF-P04637-2-F1"}
        ),
    )
    async with AlphaFoldClient() as client:
        assert await client.get_prediction("P04637-1") == {}


async def test_isoform_identity_empty_model_sequence(
    respx_mock: respx.MockRouter,
) -> None:
    async with UniProtIsoformClient() as client:
        assert not await client.is_displayed_isoform("P04637", "P04637-1", "")
    assert len(respx_mock.calls) == 0


async def test_isoform_verifier_skips_unrelated_comments(
    respx_mock: respx.MockRouter,
) -> None:
    record = _uniprot_record()
    record["comments"] = [{"commentType": "FUNCTION"}, *record["comments"]]
    respx_mock.get("https://rest.uniprot.org/uniprotkb/P04637.json").mock(
        return_value=httpx.Response(200, json=record),
    )
    async with UniProtIsoformClient() as client:
        assert await client.is_displayed_isoform("P04637", "P04637-1", "MKTV")


async def test_unverified_canonical_model_sequence_is_not_reassigned(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json=[_model_record()]),
    )
    respx_mock.get("https://rest.uniprot.org/uniprotkb/P04637.json").mock(
        return_value=httpx.Response(200, json=_uniprot_record(sequence="MKTN")),
    )
    async with AlphaFoldClient() as client:
        assert await client.get_prediction("P04637-1") == {}


async def test_invalid_upstream_prediction_scalar_returns_no_model(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json="unexpected scalar"),
    )
    async with AlphaFoldClient() as client:
        with pytest.raises(AlphaFoldPredictionSchemaError, match="not a record"):
            await client.get_prediction("P04637")

def _uniprot_record_with_isoform(value: Any) -> dict[str, Any]:
    record = _uniprot_record()
    record["comments"][0]["isoforms"] = [value]
    return record


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"primaryAccession": None},
        {"primaryAccession": "P04637", "sequence": None},
        {"primaryAccession": "P04637", "sequence": {"value": None}},
        {"primaryAccession": "P04637", "sequence": {"value": "MKTV"}},
        {"primaryAccession": "P04637", "sequence": {"value": "MKTV"}, "comments": None},
        {
            "primaryAccession": "P04637",
            "sequence": {"value": "MKTV"},
            "comments": [None],
        },
        {
            "primaryAccession": "P04637",
            "sequence": {"value": "MKTV"},
            "comments": [{"commentType": "ALTERNATIVE PRODUCTS", "isoforms": None}],
        },
        _uniprot_record_with_isoform(None),
        _uniprot_record_with_isoform({"isoformSequenceStatus": "Displayed"}),
        _uniprot_record_with_isoform(
            {"isoformIds": [None], "isoformSequenceStatus": "Displayed"}
        ),
        _uniprot_record_with_isoform({"isoformIds": ["P04637-1"]}),
    ],
)
async def test_invalid_uniprot_metadata_is_source_failure(
    respx_mock: respx.MockRouter, payload: Any
) -> None:
    respx_mock.get("https://rest.uniprot.org/uniprotkb/P04637.json").mock(
        return_value=httpx.Response(200, json=payload),
    )
    async with UniProtIsoformClient() as client:
        with pytest.raises(UniProtVerificationError):
            await client.is_displayed_isoform("P04637", "P04637-1", "MKTV")


@pytest.mark.parametrize("status", [403, 404])
async def test_uniprot_http_errors_are_not_biological_absence(
    respx_mock: respx.MockRouter, status: int
) -> None:
    respx_mock.get("https://rest.uniprot.org/uniprotkb/P04637.json").mock(
        return_value=httpx.Response(status, json={"messages": ["not available"]}),
    )
    async with UniProtIsoformClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.is_displayed_isoform("P04637", "P04637-1", "MKTV")


async def test_uniprot_malformed_json_is_source_failure(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://rest.uniprot.org/uniprotkb/P04637.json").mock(
        return_value=httpx.Response(200, content=b"not json"),
    )
    async with UniProtIsoformClient() as client:
        with pytest.raises(UniProtVerificationError, match="invalid JSON"):
            await client.is_displayed_isoform("P04637", "P04637-1", "MKTV")


async def test_alphafold_isoform_verification_http_error_propagates(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json=[_model_record()]),
    )
    respx_mock.get("https://rest.uniprot.org/uniprotkb/P04637.json").mock(
        return_value=httpx.Response(403, json={"messages": ["denied"]}),
    )
    async with AlphaFoldClient() as client:
        with pytest.raises(UniProtVerificationError, match="verification unavailable"):
            await client.get_prediction("P04637-1")


async def test_alphafold_isoform_verification_is_shared_and_closed(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json=[_model_record()]),
    )
    respx_mock.get("https://rest.uniprot.org/uniprotkb/P04637.json").mock(
        return_value=httpx.Response(200, json=_uniprot_record()),
    )
    async with AlphaFoldClient() as client:
        verifier = client._uniprot_isoform
        await client.get_prediction("P04637-1")
        await client.get_prediction("P04637-1")
        assert client._uniprot_isoform is verifier
        assert verifier._client is not None
        assert len(respx_mock.calls) == 4
    assert verifier._client is None


async def test_malformed_mixed_model_array_never_confirms_isoform(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json=[_model_record(), "malformed"]),
    )
    async with AlphaFoldClient() as client:
        with pytest.raises(AlphaFoldPredictionSchemaError, match="malformed"):
            await client.get_prediction("P04637-1")
    assert len(respx_mock.calls) == 1


async def test_check_availability_propagates_verification_failure(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json=[_model_record()]),
    )
    respx_mock.get("https://rest.uniprot.org/uniprotkb/P04637.json").mock(
        return_value=httpx.Response(403, json={"messages": ["denied"]}),
    )
    async with AlphaFoldClient() as client:
        with pytest.raises(UniProtVerificationError):
            await client.check_availability("P04637-1")

async def test_only_nondict_upstream_model_is_a_schema_error(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json=["not a record"]),
    )
    async with AlphaFoldClient() as client:
        with pytest.raises(AlphaFoldPredictionSchemaError, match="malformed"):
            await client.get_prediction("P04637")


async def test_check_availability_rejects_afdb_schema_corruption(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://alphafold.ebi.ac.uk/api/prediction/P04637").mock(
        return_value=httpx.Response(200, json=[_model_record(), 7]),
    )
    async with AlphaFoldClient() as client:
        with pytest.raises(AlphaFoldPredictionSchemaError):
            await client.check_availability("P04637")
