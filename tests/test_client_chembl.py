# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.chembl``.

Exercises every method on ``ChEMBLClient`` against mocked ChEMBL REST
endpoints, including the ``asyncio.gather`` batch path which must
tolerate mixed BaseException + dict results.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from alphafold_sovereign.clients._base import UpstreamError
from alphafold_sovereign.clients.chembl import (
    ChEMBLClient,
    _bioactivity_nm,
    _coerce_phase,
    _valid_phase,
)

# ---------------------------------------------------------------------------
# target_by_gene
# ---------------------------------------------------------------------------


async def test_target_by_gene_returns_targets(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/target.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "targets": [
                    {
                        "target_chembl_id": "CHEMBL1824",
                        "pref_name": "Breast cancer type 1",
                        "target_type": "SINGLE PROTEIN",
                        "organism": "Homo sapiens",
                        "target_components": [
                            {"accession": "P38398"},
                            {"accession": ""},
                        ],
                    },
                    # Target with no components → empty uniprot list
                    {
                        "target_chembl_id": "CHEMBL2",
                        "pref_name": "X",
                        "target_type": "PROTEIN",
                        "organism": "Homo sapiens",
                        "target_components": [],
                    },
                ]
            },
        ),
    )
    async with ChEMBLClient() as client:
        results = await client.target_by_gene("BRCA1")
    assert results[0]["uniprot_accessions"] == ["P38398"]
    assert results[1]["uniprot_accessions"] == []


async def test_target_by_gene_empty(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/target.json").mock(
        return_value=httpx.Response(200, json={}),
    )
    async with ChEMBLClient() as client:
        results = await client.target_by_gene("XYZ")
    assert results == []


# ---------------------------------------------------------------------------
# target_by_uniprot
# ---------------------------------------------------------------------------


async def test_target_by_uniprot_found(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/target.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "targets": [
                    {
                        "target_chembl_id": "CHEMBL1824",
                        "pref_name": "BRCA1",
                        "target_type": "SINGLE PROTEIN",
                        "organism": "Homo sapiens",
                        "target_components": [{"accession": "P38398"}],
                    }
                ],
                "page_meta": {"total_count": 1},
            },
        ),
    )
    async with ChEMBLClient() as client:
        target = await client.target_by_uniprot("P38398")
    assert target is not None
    assert target["chembl_id"] == "CHEMBL1824"
    assert target["target_type"] == "SINGLE PROTEIN"
    assert "target_type=SINGLE+PROTEIN" in str(respx_mock.calls[0].request.url)


async def test_target_by_uniprot_none(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/target.json").mock(
        return_value=httpx.Response(200, json={"targets": [], "page_meta": {"total_count": 0}}),
    )
    async with ChEMBLClient() as client:
        target = await client.target_by_uniprot("NOTHING")
    assert target is None


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {},
        {"targets": None, "page_meta": {"total_count": 0}},
        {"targets": [], "page_meta": None},
        {"targets": [], "page_meta": {"total_count": None}},
        {"targets": [], "page_meta": {"total_count": True}},
        {"targets": [], "page_meta": {"total_count": 1}},
        {"targets": [None], "page_meta": {"total_count": 1}},
        {
            "targets": [{"target_type": "PROTEIN COMPLEX"}],
            "page_meta": {"total_count": 1},
        },
        {
            "targets": [{"target_type": "SINGLE PROTEIN", "target_components": None}],
            "page_meta": {"total_count": 1},
        },
        {
            "targets": [
                {
                    "target_type": "SINGLE PROTEIN",
                    "target_components": [None, {"accession": "P99999"}],
                }
            ],
            "page_meta": {"total_count": 1},
        },
        {
            "targets": [
                {
                    "target_type": "SINGLE PROTEIN",
                    "target_components": [{"accession": "P38398"}],
                    "target_chembl_id": None,
                }
            ],
            "page_meta": {"total_count": 1},
        },
        {
            "targets": [
                {
                    "target_type": "SINGLE PROTEIN",
                    "target_components": [{"accession": "P38398"}],
                    "target_chembl_id": "",
                }
            ],
            "page_meta": {"total_count": 1},
        },
    ],
)
async def test_target_by_uniprot_rejects_unverified_or_malformed_identity(
    respx_mock: respx.MockRouter, invalid_payload: dict[str, Any]
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/target.json").mock(
        return_value=httpx.Response(200, json=invalid_payload),
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="ChEMBL"):
            await client.target_by_uniprot("P38398")


async def test_target_by_uniprot_refuses_ambiguous_single_protein_targets(
    respx_mock: respx.MockRouter,
) -> None:
    protein = {
        "target_type": "SINGLE PROTEIN",
        "target_components": [{"accession": "P38398"}],
        "target_chembl_id": "CHEMBL1",
    }
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/target.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "targets": [protein, {**protein, "target_chembl_id": "CHEMBL2"}],
                "page_meta": {"total_count": 2},
            },
        ),
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="ambiguous"):
            await client.target_by_uniprot("P38398")


# ---------------------------------------------------------------------------
# bioactivities
# ---------------------------------------------------------------------------


async def test_bioactivities_with_max_value(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/activity.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "activities": [
                    {
                        "molecule_chembl_id": "CHEMBL25",
                        "molecule_pref_name": "ASPIRIN",
                        "standard_type": "IC50",
                        "standard_value": "10.0",
                        "standard_relation": ">",
                        "standard_units": "nM",
                        "assay_description": "inhibition assay",
                        "document_year": 2020,
                        "canonical_smiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
                    },
                    # Test pref_name fallback to "" when None, and standard_value None
                    {
                        "molecule_chembl_id": "CHEMBL2",
                        "molecule_pref_name": None,
                        "standard_value": None,
                    },
                ]
            },
        ),
    )
    async with ChEMBLClient() as client:
        results = await client.bioactivities(
            "CHEMBL1824",
            activity_type="IC50",
            max_value_nm=100.0,
            limit=500,  # clamp via min()
        )
    assert results[0]["value_nm"] == 10.0
    # The server filters the reported numeric value, not the inequality's
    # direction: >10 nM is not independently verified as <=100 nM potency.
    assert results[0]["value_relation"] == ">"
    assert results[0]["units"] == "nM"
    assert results[1]["pref_name"] == ""
    assert results[1]["value_nm"] is None
    assert results[1]["value_relation"] is None
    assert results[1]["units"] is None


async def test_bioactivities_no_max_value(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/activity.json").mock(
        return_value=httpx.Response(200, json={"activities": []}),
    )
    async with ChEMBLClient() as client:
        results = await client.bioactivities("CHEMBL1824")
    assert results == []


# ---------------------------------------------------------------------------
# approved_drugs (and the gather-with-mixed-results path)
# ---------------------------------------------------------------------------


async def test_approved_drugs_no_mechanisms(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(200, json={"mechanisms": []}),
    )
    async with ChEMBLClient() as client:
        results = await client.approved_drugs("CHEMBL1824")
    assert results == []


async def test_approved_drugs_clinical_filter(respx_mock: respx.MockRouter) -> None:
    """Include clinical=False ⇒ min_phase=4; filter out Phase < 4."""
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [
                    # Drug A: Phase 4 → included
                    {
                        "molecule_chembl_id": "CHEMBL_A",
                        "mechanism_of_action": "Inhibits A",
                    },
                    # Drug B: Phase 2 → filtered out
                    {
                        "molecule_chembl_id": "CHEMBL_B",
                        "mechanism_of_action": "Inhibits B",
                    },
                    # Drug C: returns None ⇒ skipped
                    {
                        "molecule_chembl_id": "CHEMBL_C",
                        "mechanism_of_action": "Inhibits C",
                    },
                    # Drug D: raises exception ⇒ BaseException branch
                    {
                        "molecule_chembl_id": "CHEMBL_D",
                        "mechanism_of_action": "Inhibits D",
                    },
                    # No molecule id → filtered out of chembl_ids set
                    {"molecule_chembl_id": None, "mechanism_of_action": ""},
                    # Mechanism with empty mechanism_of_action → not included in `mechs`
                    {
                        "molecule_chembl_id": "CHEMBL_A",
                        "mechanism_of_action": "",
                    },
                ]
            },
        ),
    )
    # Each unique molecule_chembl_id hits the molecule endpoint
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_A.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "molecule_chembl_id": "CHEMBL_A",
                "pref_name": "Drug A",
                "max_phase": "4.0",
                "molecule_properties": {"mw_freebase": 300.0},
                "oral": True,
                "black_box_warning": 1,
            },
        ),
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_B.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "molecule_chembl_id": "CHEMBL_B",
                "max_phase": "2.0",
            },
        ),
    )
    # C → returns content that decodes to None? Use molecule_properties null path; instead simulate
    # ``_get_molecule`` returning None by making the inner request raise → use bad JSON.
    # The simplest path: have C return JSON null → data.get(...) on None... but the function
    # expects a dict. Use a 404 + UpstreamError to take the `except Exception` branch.
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_C.json").mock(
        return_value=httpx.Response(404, text="missing"),
    )
    # D → raise via 500 → tenacity exhausts → UpstreamError → caught in _get_molecule → None
    # ALTERNATIVE: we want a BaseException. The asyncio.gather(return_exceptions=True) path
    # actually means _get_molecule itself catches exceptions and returns None, so the
    # ``isinstance(drug, BaseException)`` branch is not naturally reachable through
    # the public API. We must inject the BaseException into the gather directly.
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_D.json").mock(
        return_value=httpx.Response(500, text="boom"),
    )

    async with ChEMBLClient() as client:
        # Override _get_molecule for the BaseException branch to be reachable.
        original = client._get_molecule

        async def stub(chembl_id: str):  # type: ignore[no-untyped-def]
            if chembl_id == "CHEMBL_D":
                raise RuntimeError("network down")
            return await original(chembl_id)

        client._get_molecule = stub  # type: ignore[method-assign]
        results = await client.approved_drugs("CHEMBL1824", include_clinical=False)
    assert len(results) == 1  # only A passes Phase ≥ 4
    assert results[0]["molecule_chembl_id"] == "CHEMBL_A"
    assert results[0]["mechanism"] == "Inhibits A"


async def test_approved_drugs_include_clinical(respx_mock: respx.MockRouter) -> None:
    """include_clinical=True ⇒ min_phase=1 ⇒ Phase 1 included."""
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [
                    {"molecule_chembl_id": "CHEMBL_A"},
                ],
                "page_meta": {"total_count": 1},
            },
        ),
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_A.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "molecule_chembl_id": "CHEMBL_A",
                "max_phase": "1.0",
            },
        ),
    )
    async with ChEMBLClient() as client:
        results = await client.approved_drugs(
            "CHEMBL1824", include_clinical=True, require_complete=True
        )
    # Phase 1 → no mechanism entry was supplied → mech list empty → "" mechanism
    assert results[0]["mechanism"] == ""


# ---------------------------------------------------------------------------
# drug_indications
# ---------------------------------------------------------------------------


async def test_drug_indications_by_efo(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/drug_indication.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "drug_indications": [
                    {
                        "molecule_chembl_id": "CHEMBL25",
                        "molecule_pref_name": None,  # exercise `or ""`
                        "max_phase_for_ind": 4,
                        "efo_id": "EFO:0000228",
                        "efo_term": "breast carcinoma",
                        "mesh_id": "D001943",
                        "mesh_heading": "Breast Neoplasms",
                    }
                ]
            },
        ),
    )
    async with ChEMBLClient() as client:
        results = await client.drug_indications(efo_id="EFO:0000228", limit=999)
    # Regression test for D1-B: ChEMBL stores efo_id in colon form and orders
    # by max_phase_for_ind. The client must pass both through unchanged
    # (the old EFO_ rewrite returned 0 rows; -max_phase_for_indication = 400).
    sent = route.calls.last.request.url.params
    assert sent["efo_id"] == "EFO:0000228"
    assert sent["order_by"] == "-max_phase_for_ind"
    assert results[0]["pref_name"] == ""
    assert results[0]["molecule_chembl_id"] == "CHEMBL25"
    assert results[0]["max_phase_for_indication"] == 4


async def test_drug_indications_by_mesh(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/drug_indication.json").mock(
        return_value=httpx.Response(200, json={"drug_indications": []}),
    )
    async with ChEMBLClient() as client:
        results = await client.drug_indications(mesh_heading="Breast Neoplasms")
    assert results == []


@pytest.mark.parametrize(
    "body",
    [
        {"error": "upstream data unavailable"},
        {"drug_indications": None},
        {"drug_indications": {"molecule_chembl_id": "C1"}},
        {"drug_indications": [None]},
    ],
)
async def test_drug_indications_rejects_malformed_envelope(
    respx_mock: respx.MockRouter, body: dict[str, Any]
) -> None:
    """A 200 response without the documented list is not an empty page."""
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/drug_indication.json").mock(
        return_value=httpx.Response(200, json=body)
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="missing a valid list"):
            await client.drug_indications(efo_id="EFO:0000305")


async def test_drug_indications_missing_required() -> None:
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError):
            await client.drug_indications()


# ---------------------------------------------------------------------------
# molecule_names
# ---------------------------------------------------------------------------


async def test_molecule_names_success(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "molecules": [
                    {"molecule_chembl_id": "CHEMBL941", "pref_name": "IMATINIB"},
                    {"molecule_chembl_id": "CHEMBL2", "pref_name": ""},  # blank name dropped
                    {"molecule_chembl_id": "", "pref_name": "X"},  # blank id dropped
                ]
            },
        ),
    )
    async with ChEMBLClient() as client:
        # Duplicates and blanks are de-duplicated / dropped before the request.
        names = await client.molecule_names(["CHEMBL941", "CHEMBL941", "CHEMBL2", ""])
    assert names == {"CHEMBL941": "IMATINIB"}
    url = str(route.calls.last.request.url)
    assert "molecule_chembl_id__in=" in url
    # Duplicates collapsed to a single occurrence; the blank ID is dropped.
    assert url.count("CHEMBL941") == 1
    assert "CHEMBL2" in url


async def test_molecule_names_empty_input_skips_request() -> None:
    async with ChEMBLClient() as client:
        assert await client.molecule_names([]) == {}
        assert await client.molecule_names(["", ""]) == {}


async def test_molecule_names_error_returns_empty(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule.json").mock(
        return_value=httpx.Response(500),
    )
    async with ChEMBLClient() as client:
        assert await client.molecule_names(["CHEMBL941"]) == {}


async def test_molecule_names_chunks_large_input(respx_mock: respx.MockRouter) -> None:
    """More than 50 IDs are chunked into multiple requests and aggregated."""
    ids = [f"CHEMBL{i}" for i in range(51)]  # 51 unique → two batches (50 + 1)
    route = respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule.json").mock(
        side_effect=[
            httpx.Response(
                200, json={"molecules": [{"molecule_chembl_id": "CHEMBL0", "pref_name": "DRUG0"}]}
            ),
            httpx.Response(
                200,
                json={"molecules": [{"molecule_chembl_id": "CHEMBL50", "pref_name": "DRUG50"}]},
            ),
        ]
    )
    async with ChEMBLClient() as client:
        names = await client.molecule_names(ids)
    assert route.call_count == 2
    assert names == {"CHEMBL0": "DRUG0", "CHEMBL50": "DRUG50"}


# ---------------------------------------------------------------------------
# mechanism_of_action
# ---------------------------------------------------------------------------


async def test_mechanism_of_action(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [
                    {
                        "mechanism_of_action": "Cyclooxygenase inhibitor",
                        "action_type": "INHIBITOR",
                        "target_pref_name": "PTGS1",
                        "target_chembl_id": "CHEMBL222",
                        "selectivity_comment": "non-selective",
                        "direct_interaction": True,
                        "disease_efficacy": True,
                    }
                ]
            },
        ),
    )
    async with ChEMBLClient() as client:
        moa = await client.mechanism_of_action("CHEMBL25")
    assert moa[0]["action_type"] == "INHIBITOR"
    assert moa[0]["direct_interaction"] is True


# ---------------------------------------------------------------------------
# find_repurposable_drugs
# ---------------------------------------------------------------------------


async def test_find_repurposable_drugs_no_target(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/target.json").mock(
        return_value=httpx.Response(200, json={"targets": [], "page_meta": {"total_count": 0}}),
    )
    async with ChEMBLClient() as client:
        results = await client.find_repurposable_drugs("P00000")
    assert results == []


async def test_find_repurposable_drugs_full_path(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/target.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "targets": [
                    {
                        "target_chembl_id": "CHEMBL_T",
                        "pref_name": "T",
                        "target_type": "SINGLE PROTEIN",
                        "organism": "Homo sapiens",
                        "target_components": [{"accession": "P38398"}],
                    }
                ],
                "page_meta": {"total_count": 1},
            },
        ),
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [{"molecule_chembl_id": "CHEMBL_X"}],
                "page_meta": {"total_count": 1},
            },
        ),
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_X.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "molecule_chembl_id": "CHEMBL_X",
                "max_phase": 4,
            },
        ),
    )
    async with ChEMBLClient() as client:
        results = await client.find_repurposable_drugs("P38398", max_phase=4, limit=10)
    assert len(results) == 1


async def test_find_repurposable_drugs_clinical_phase(respx_mock: respx.MockRouter) -> None:
    """max_phase < 4 should pass include_clinical=True downstream."""
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/target.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "targets": [
                    {
                        "target_chembl_id": "CHEMBL_T",
                        "target_type": "SINGLE PROTEIN",
                        "target_components": [{"accession": "P38398"}],
                    }
                ],
                "page_meta": {"total_count": 1},
            },
        ),
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [{"molecule_chembl_id": "CHEMBL_Y"}],
                "page_meta": {"total_count": 1},
            },
        ),
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_Y.json").mock(
        return_value=httpx.Response(
            200,
            json={"molecule_chembl_id": "CHEMBL_Y", "max_phase": 3},
        ),
    )
    async with ChEMBLClient() as client:
        results = await client.find_repurposable_drugs("P38398", max_phase=3)
    assert results[0]["molecule_chembl_id"] == "CHEMBL_Y"


async def test_find_repurposable_drugs_passes_unplaceable_phase_through(
    respx_mock: respx.MockRouter,
) -> None:
    """A -1 clinical candidate is not silently dropped at a clinical threshold."""
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/target.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "targets": [
                    {
                        "target_chembl_id": "CHEMBL_T",
                        "target_type": "SINGLE PROTEIN",
                        "target_components": [{"accession": "P38398"}],
                    }
                ],
                "page_meta": {"total_count": 1},
            },
        ),
    )
    _mechanism_and_molecules(respx_mock, {"CHEMBL_U": -1})
    async with ChEMBLClient() as client:
        results = await client.find_repurposable_drugs("P38398", max_phase=2)
        assert [d["molecule_chembl_id"] for d in results] == ["CHEMBL_U"]
        assert results[0]["max_phase_label"] == "Clinical phase unknown"
        # An approved-only request cannot place it and refuses to count.
        with pytest.raises(ValueError, match="clinical phase unknown"):
            await client.find_repurposable_drugs("P38398", max_phase=4)


# ---------------------------------------------------------------------------
# _get_molecule directly
# ---------------------------------------------------------------------------


async def test_get_molecule_exception_returns_none(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_BAD.json").mock(
        return_value=httpx.Response(404, text="missing"),
    )
    async with ChEMBLClient() as client:
        assert await client._get_molecule("CHEMBL_BAD") is None


async def test_get_molecule_known_phase_label(respx_mock: respx.MockRouter) -> None:
    """A max_phase=-1 (clinical phase unknown) must look up in _MAX_PHASE."""
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_W.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "molecule_chembl_id": "CHEMBL_W",
                "max_phase": -1,
                "molecule_properties": None,
            },
        ),
    )
    async with ChEMBLClient() as client:
        mol = await client._get_molecule("CHEMBL_W")
    assert mol is not None
    assert mol["max_phase_label"] == "Clinical phase unknown"


async def test_get_molecule_unknown_phase_label(respx_mock: respx.MockRouter) -> None:
    """An unmapped max_phase falls through to 'Unknown'."""
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_U.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "molecule_chembl_id": "CHEMBL_U",
                "max_phase": 99,
            },
        ),
    )
    async with ChEMBLClient() as client:
        mol = await client._get_molecule("CHEMBL_U")
    assert mol is not None
    assert mol["max_phase_label"] == "Unknown"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("4.0", 4.0),  # ChEMBL's real string form
        ("0.5", 0.5),  # Early Phase 1
        (4, 4.0),  # legacy integer form
        (3.0, 3.0),  # native float
        (-1, -1.0),  # clinical phase unknown
        (None, 0.0),  # null
        ("", 0.0),  # blank string
        ("n/a", 0.0),  # unparseable
    ],
)
def test_coerce_phase(value: object, expected: float) -> None:
    """``_coerce_phase`` tolerates every max_phase form ChEMBL emits."""
    assert _coerce_phase(value) == expected


@pytest.mark.parametrize(
    "value",
    [True, False, -0.1, float("nan"), float("inf"), "bad", object()],
)
def test_bioactivity_nm_rejects_invalid_or_nonfinite_measurements(value: Any) -> None:
    with pytest.raises(ValueError, match="standard_value"):
        _bioactivity_nm(value)


def test_bioactivity_nm_preserves_valid_zero_and_absence() -> None:
    assert _bioactivity_nm(None) is None
    assert _bioactivity_nm(0) == 0.0
    assert _bioactivity_nm("0.0") == 0.0
    assert _bioactivity_nm("25.5") == 25.5


async def test_bioactivities_missing_measurement_cannot_look_ultrapotent(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/activity.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "activities": [
                    {
                        "molecule_chembl_id": "CHEMBL_NULL",
                        "standard_value": None,
                        "standard_relation": "<",
                    },
                    {
                        "molecule_chembl_id": "CHEMBL_ZERO",
                        "standard_value": "0.0",
                        "standard_relation": "=",
                        "standard_units": "nM",
                    },
                ]
            },
        )
    )
    async with ChEMBLClient() as client:
        rows = await client.bioactivities("CHEMBL_TARGET")
    assert rows[0]["value_nm"] is None
    assert rows[0]["value_relation"] == "<"
    assert rows[1]["value_nm"] == 0.0
    assert rows[1]["value_relation"] == "="


async def test_bioactivities_invalid_upstream_value_is_not_silently_accepted(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/activity.json").mock(
        return_value=httpx.Response(
            200,
            json={"activities": [{"standard_value": "not a number"}]},
        )
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="standard_value"):
            await client.bioactivities("CHEMBL_TARGET")


@pytest.mark.parametrize(
    "raw", [None, True, False, "bad", float("nan"), -2, 5, 3.7, 1.5, "0.25", -0.5]
)
def test_valid_phase_rejects_missing_invalid_or_out_of_range(raw: Any) -> None:
    assert _valid_phase(raw) is False


@pytest.mark.parametrize("raw", [-1, 0, 0.5, "2.0", 4.0])
def test_valid_phase_preserves_observed_chembl_stages(raw: Any) -> None:
    assert _valid_phase(raw) is True


def _mechanism_and_molecules(respx_mock: respx.MockRouter, phases: dict[str, Any]) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [{"molecule_chembl_id": cid} for cid in phases],
                "page_meta": {"total_count": len(phases)},
            },
        )
    )
    for cid, phase in phases.items():
        respx_mock.get(f"https://www.ebi.ac.uk/chembl/api/data/molecule/{cid}.json").mock(
            return_value=httpx.Response(200, json={"molecule_chembl_id": cid, "max_phase": phase})
        )


async def test_approved_drugs_unknown_clinical_phase_counts_as_clinical_only(
    respx_mock: respx.MockRouter,
) -> None:
    """max_phase -1 is a drug or clinical candidate whose stage ChEMBL cannot place."""
    _mechanism_and_molecules(respx_mock, {"CHEMBL_A": 4, "CHEMBL_U": -1})
    async with ChEMBLClient() as client:
        clinical = await client.approved_drugs(
            "CHEMBL_T", include_clinical=True, require_complete=True
        )
        assert [d["molecule_chembl_id"] for d in clinical] == ["CHEMBL_A", "CHEMBL_U"]
        assert clinical[1]["max_phase_label"] == "Clinical phase unknown"
        # Best effort: the unplaceable molecule is left out of an approved-only list.
        approved = await client.approved_drugs("CHEMBL_T", include_clinical=False)
        assert [d["molecule_chembl_id"] for d in approved] == ["CHEMBL_A"]
        # Strict: an approved-only count cannot be exact with an unplaceable molecule.
        with pytest.raises(ValueError, match="clinical phase unknown"):
            await client.approved_drugs("CHEMBL_T", include_clinical=False, require_complete=True)


async def test_approved_drugs_strict_rejects_non_object_molecule_envelope(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [{"molecule_chembl_id": "CHEMBL_A"}],
                "page_meta": {"total_count": 1},
            },
        )
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_A.json").mock(
        return_value=httpx.Response(200, json=[{"molecule_chembl_id": "CHEMBL_A"}])
    )
    async with ChEMBLClient() as client:
        assert await client.approved_drugs("CHEMBL_T") == []
        with pytest.raises(ValueError, match="not an object"):
            await client.approved_drugs("CHEMBL_T", require_complete=True)


async def test_approved_drugs_strict_rejects_undocumented_phase(
    respx_mock: respx.MockRouter,
) -> None:
    """A finite but undocumented stage such as 3.7 is malformed, not a phase."""
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [{"molecule_chembl_id": "CHEMBL_A"}],
                "page_meta": {"total_count": 1},
            },
        )
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_A.json").mock(
        return_value=httpx.Response(200, json={"molecule_chembl_id": "CHEMBL_A", "max_phase": 3.7})
    )
    async with ChEMBLClient() as client:
        assert await client.approved_drugs("CHEMBL_T", include_clinical=True) == []
        with pytest.raises(ValueError, match="incomplete"):
            await client.approved_drugs("CHEMBL_T", include_clinical=True, require_complete=True)


async def test_get_molecule_missing_phase_does_not_fabricate_preclinical_label(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_Q.json").mock(
        return_value=httpx.Response(200, json={"molecule_chembl_id": "CHEMBL_Q", "max_phase": None})
    )
    async with ChEMBLClient() as client:
        drug = await client._get_molecule("CHEMBL_Q")
    assert drug is not None
    assert drug["max_phase_known"] is False
    assert drug["max_phase_label"] == "Unknown"


async def test_get_molecule_fractional_phase_not_called_preclinical(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_H.json").mock(
        return_value=httpx.Response(200, json={"molecule_chembl_id": "CHEMBL_H", "max_phase": 0.5})
    )
    async with ChEMBLClient() as client:
        drug = await client._get_molecule("CHEMBL_H")
    assert drug is not None
    assert drug["max_phase_known"] is True
    assert drug["max_phase_label"] == "Phase 0.5"


async def test_get_molecule_mismatched_identity_rejected(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_A.json").mock(
        return_value=httpx.Response(200, json={"molecule_chembl_id": "CHEMBL_B", "max_phase": 4})
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="identifier mismatch"):
            await client._get_molecule("CHEMBL_A")


async def test_approved_drugs_best_effort_retained_but_strict_counts_fail_closed(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [
                    {"molecule_chembl_id": "CHEMBL_A"},
                    {"molecule_chembl_id": "CHEMBL_MISSING"},
                ],
                "page_meta": {"total_count": 2},
            },
        )
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_A.json").mock(
        return_value=httpx.Response(200, json={"molecule_chembl_id": "CHEMBL_A", "max_phase": 4})
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_MISSING.json").mock(
        return_value=httpx.Response(404)
    )
    async with ChEMBLClient() as client:
        partial = await client.approved_drugs("CHEMBL_T")
        assert [x["molecule_chembl_id"] for x in partial] == ["CHEMBL_A"]
        # A failed molecule request is a request failure in strict mode, not
        # malformed metadata: it must not be reported as ValueError.
        with pytest.raises(UpstreamError):
            await client.approved_drugs("CHEMBL_T", require_complete=True)


async def test_approved_drugs_strict_reports_unknown_phase_as_invalid(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [{"molecule_chembl_id": "CHEMBL_A"}],
                "page_meta": {"total_count": 1},
            },
        )
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_A.json").mock(
        return_value=httpx.Response(200, json={"molecule_chembl_id": "CHEMBL_A", "max_phase": "x"})
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="incomplete"):
            await client.approved_drugs("CHEMBL_T", require_complete=True)


async def test_approved_drugs_rejects_missing_mechanism_list(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(200, json={"not_mechanisms": []})
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="mechanisms list"):
            await client.approved_drugs("CHEMBL_T", require_complete=True)


async def test_approved_drugs_rejects_unretrieved_pagination_or_truncation(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [{"molecule_chembl_id": "CHEMBL_A"}],
                "page_meta": {"total_count": 2},
            },
        )
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="pagination incomplete"):
            await client.approved_drugs("CHEMBL_T", require_complete=True)

    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [{"molecule_chembl_id": f"CHEMBL_{i}"} for i in range(201)],
                "page_meta": {"total_count": 201},
            },
        )
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="more than 200"):
            await client.approved_drugs("CHEMBL_T", require_complete=True)


def _mechanism_page(start: int, size: int, total: int) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "mechanisms": [
                {"molecule_chembl_id": f"CHEMBL_{i}", "mechanism_of_action": "Inhibitor"}
                for i in range(start, min(start + size, total))
            ],
            "page_meta": {"limit": size, "offset": start, "total_count": total},
        },
    )


def _molecule_from_path(request: httpx.Request) -> httpx.Response:
    chembl_id = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
    return httpx.Response(200, json={"molecule_chembl_id": chembl_id, "max_phase": 4})


async def test_approved_drugs_follows_mechanism_pagination(respx_mock: respx.MockRouter) -> None:
    """A target with more mechanism rows than one page is fully retrieved.

    Live ChEMBL 37 reports 90 mechanism rows for EGFR (CHEMBL203); the first
    page alone would silently truncate the distinct molecule count.
    """
    route = respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json")
    route.side_effect = [_mechanism_page(0, 100, 150), _mechanism_page(100, 100, 150)]
    respx_mock.get(url__regex=r".*/chembl/api/data/molecule/CHEMBL_\d+\.json").mock(
        side_effect=_molecule_from_path
    )
    async with ChEMBLClient() as client:
        drugs = await client.approved_drugs("CHEMBL203", require_complete=True)
    assert len(drugs) == 150
    assert len({d["molecule_chembl_id"] for d in drugs}) == 150
    assert [c.request.url.params["offset"] for c in route.calls] == ["0", "100"]


@pytest.mark.parametrize("total_count", [None, True, -1, "2"])
async def test_approved_drugs_require_complete_rejects_invalid_total_count(
    respx_mock: respx.MockRouter, total_count: Any
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [{"molecule_chembl_id": "CHEMBL_A"}],
                "page_meta": {"total_count": total_count},
            },
        )
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="pagination incomplete"):
            await client.approved_drugs("CHEMBL_T", require_complete=True)


async def test_approved_drugs_page_bound_does_not_truncate_silently(
    respx_mock: respx.MockRouter,
) -> None:
    """Beyond the page bound a complete count is refused, never truncated."""
    route = respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json")
    route.side_effect = [_mechanism_page(100 * i, 100, 10_000) for i in range(5)]
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="more than 200"):
            await client.approved_drugs("CHEMBL_T", require_complete=True)
    assert route.call_count == 5


async def test_approved_drugs_does_not_promote_unknown_phase(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [{"molecule_chembl_id": "CHEMBL_X"}],
                "page_meta": {"total_count": 1},
            },
        )
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_X.json").mock(
        return_value=httpx.Response(200, json={"molecule_chembl_id": "CHEMBL_X", "max_phase": 99})
    )
    async with ChEMBLClient() as client:
        assert await client.approved_drugs("CHEMBL_T") == []
        with pytest.raises(ValueError, match="incomplete"):
            await client.approved_drugs("CHEMBL_T", require_complete=True)


async def test_get_molecule_missing_response_id_uses_requested_endpoint_identity(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_A.json").mock(
        return_value=httpx.Response(200, json={"max_phase": 4})
    )
    async with ChEMBLClient() as client:
        drug = await client._get_molecule("CHEMBL_A")
    assert drug is not None
    assert drug["molecule_chembl_id"] == "CHEMBL_A"
    assert drug["max_phase_known"] is True
    assert drug["molecule_id_verified"] is False


async def test_approved_drugs_require_complete_needs_page_metadata(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(200, json={"mechanisms": [{"molecule_chembl_id": "CHEMBL_A"}]})
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="pagination cannot be verified"):
            await client.approved_drugs("CHEMBL_T", require_complete=True)


async def test_approved_drugs_require_complete_rejects_bad_mechanism_identity(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [{"molecule_chembl_id": None}],
                "page_meta": {"total_count": 1},
            },
        )
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="identity incomplete"):
            await client.approved_drugs("CHEMBL_T", require_complete=True)


async def test_approved_drugs_require_complete_rejects_unverified_molecule_identity(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "mechanisms": [{"molecule_chembl_id": "CHEMBL_A"}],
                "page_meta": {"total_count": 1},
            },
        )
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL_A.json").mock(
        return_value=httpx.Response(200, json={"max_phase": 4})
    )
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError, match="incomplete"):
            await client.approved_drugs("CHEMBL_T", require_complete=True)


async def test_approved_drugs_require_complete_observed_zero_remains_zero(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(200, json={"mechanisms": [], "page_meta": {"total_count": 0}})
    )
    async with ChEMBLClient() as client:
        assert await client.approved_drugs("CHEMBL_T", require_complete=True) == []
