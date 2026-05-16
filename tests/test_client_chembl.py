# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.chembl``.

Exercises every method on ``ChEMBLClient`` against mocked ChEMBL REST
endpoints, including the ``asyncio.gather`` batch path which must
tolerate mixed BaseException + dict results.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from alphafold_sovereign.clients.chembl import ChEMBLClient, _coerce_phase


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
                    }
                ]
            },
        ),
    )
    async with ChEMBLClient() as client:
        target = await client.target_by_uniprot("P38398")
    assert target is not None
    assert target["chembl_id"] == "CHEMBL1824"


async def test_target_by_uniprot_none(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/target.json").mock(
        return_value=httpx.Response(200, json={"targets": []}),
    )
    async with ChEMBLClient() as client:
        target = await client.target_by_uniprot("NOTHING")
    assert target is None


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
    assert results[1]["pref_name"] == ""
    assert results[1]["value_nm"] == 0.0


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
                ]
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
        results = await client.approved_drugs("CHEMBL1824", include_clinical=True)
    # Phase 1 → no mechanism entry was supplied → mech list empty → "" mechanism
    assert results[0]["mechanism"] == ""


# ---------------------------------------------------------------------------
# drug_indications
# ---------------------------------------------------------------------------


async def test_drug_indications_by_efo(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(
        "https://www.ebi.ac.uk/chembl/api/data/drug_indication.json"
    ).mock(
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


async def test_drug_indications_missing_required() -> None:
    async with ChEMBLClient() as client:
        with pytest.raises(ValueError):
            await client.drug_indications()


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
        return_value=httpx.Response(200, json={"targets": []}),
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
                    }
                ]
            },
        ),
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={"mechanisms": [{"molecule_chembl_id": "CHEMBL_X"}]},
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
            json={"targets": [{"target_chembl_id": "CHEMBL_T"}]},
        ),
    )
    respx_mock.get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json").mock(
        return_value=httpx.Response(
            200,
            json={"mechanisms": [{"molecule_chembl_id": "CHEMBL_Y"}]},
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
    """A max_phase=-1 (Withdrawn) must look up in _MAX_PHASE."""
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
    assert mol["max_phase_label"] == "Withdrawn"


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
        (-1, -1.0),  # Withdrawn sentinel
        (None, 0.0),  # null
        ("", 0.0),  # blank string
        ("n/a", 0.0),  # unparseable
    ],
)
def test_coerce_phase(value: object, expected: float) -> None:
    """``_coerce_phase`` tolerates every max_phase form ChEMBL emits."""
    assert _coerce_phase(value) == expected
