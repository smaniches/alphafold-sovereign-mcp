# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Public MCP tools preserve verified isoform identity and uncertainty.

The fixtures intentionally distinguish "cannot verify" from no prediction.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from alphafold_sovereign.clients._isoform import UniProtVerificationError
from alphafold_sovereign.tools import structure_intelligence as si


@pytest.mark.parametrize(
    ("method", "tool"),
    [
        ("get_prediction", "get_protein_structure"),
        ("get_prediction", "_fetch_af_plddt"),
        ("get_pdb_bytes", "_fetch_af_structure"),
    ],
)
async def test_structural_tools_propagate_unavailable_isoform_verification(
    monkeypatch: pytest.MonkeyPatch, method: str, tool: str
) -> None:
    client = MagicMock()
    setattr(client, method, AsyncMock(side_effect=UniProtVerificationError("not verified")))
    monkeypatch.setattr(si, "_alphafold", lambda: client)

    with pytest.raises(UniProtVerificationError, match="not verified"):
        if tool == "get_protein_structure":
            await si.get_protein_structure(
                si.StructureRetrievalInput(uniprot_id="P04637-1")
            )
        elif tool == "_fetch_af_plddt":
            await si._fetch_af_plddt("P04637-1")
        else:
            await si._fetch_af_structure("P04637-1")


async def test_structure_retrieval_exposes_verified_isoform_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = {
        "uniprotAccession": "P04637",
        "modelEntityId": "AF-P04637-F1",
        "sequence": "MKTV",
        "_sovereign_verified_isoform": "P04637-1",
        "globalMetricValue": 81.0,
    }
    client = MagicMock()
    client.get_prediction = AsyncMock(return_value=metadata)
    monkeypatch.setattr(si, "_alphafold", lambda: client)

    result = await si.get_protein_structure(
        si.StructureRetrievalInput(uniprot_id="P04637-1")
    )
    assert result["structure_available"] is True
    assert result["model_uniprot_accession"] == "P04637"
    assert result["verified_displayed_isoform"] == "P04637-1"
    assert result["entry_id"] == "AF-P04637-F1"


async def test_confidence_data_preserves_verified_isoform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.get_prediction = AsyncMock(
        return_value={
            "uniprotAccession": "P04637",
            "modelEntityId": "AF-P04637-F1",
            "sequence": "MKTV",
            "globalMetricValue": 81.0,
            "_sovereign_verified_isoform": "P04637-1",
        }
    )
    client.get_pae = AsyncMock(return_value={})
    monkeypatch.setattr(si, "_alphafold", lambda: client)

    intermediate = await si._fetch_af_plddt("P04637-1")
    assert intermediate is not None
    assert intermediate["model_uniprot_accession"] == "P04637"
    assert intermediate["verified_displayed_isoform"] == "P04637-1"

    monkeypatch.setattr(si, "_fetch_af_plddt", AsyncMock(return_value=intermediate))
    output = await si.analyze_structural_confidence(si.UniProtInput(uniprot_id="P04637-1"))
    assert output["model_uniprot_accession"] == "P04637"
    assert output["verified_displayed_isoform"] == "P04637-1"


async def test_idr_summary_propagates_verified_isoform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = []
    for i in range(1, 7):
        rows.append(
            f"ATOM  {i:5d}  CA  ALA A{i:4d}    "
            f"{float(i):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00{30.0:6.2f}           C"
        )
    monkeypatch.setattr(
        si,
        "_fetch_af_plddt",
        AsyncMock(return_value={
            "model_entity_id": "AF-P04637-F1",
            "model_uniprot_accession": "P04637",
            "verified_displayed_isoform": "P04637-1",
        }),
    )
    monkeypatch.setattr(
        si,
        "_fetch_af_structure",
        AsyncMock(return_value={"pdb_text": "\n".join(rows), "uniprot_id": "P04637-1"}),
    )

    result = await si.detect_intrinsically_disordered(
        si.UniProtInput(uniprot_id="P04637-1")
    )
    assert result["model_uniprot_accession"] == "P04637"
    assert result["verified_displayed_isoform"] == "P04637-1"
    assert result["sequence_length"] == 6
