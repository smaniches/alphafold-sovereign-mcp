# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Retrieval-state regressions for the structure tools.

Each behavioural test calls the public tool with the real
``AlphaFoldClient`` (and, where it matters, the real ``EnsemblClient``);
only the HTTP transport is replaced. Four reporting defects are covered:

* An HTTP 404 for the coordinate file that a prediction record advertises
  was reported as "no prediction returned", the answer reserved for an
  accession AlphaFold DB serves no model for.
* ``get_protein_structure`` fetched embedded coordinates through a second
  prediction lookup, so they could belong to another record than the one
  the response describes, and a failed download came back as an empty
  string without a reason.
* The tool descriptions said every model longer than 500 residues is
  compared on 500 C-alpha atoms. Only the GUDHI path subsamples; the fallback
  that runs without the ``[tda]`` extra uses every residue.
* The offline documentation promised ``retrieval_status`` for every
  structure tool. Five return it, one reports per accession, one fails on
  its Ensembl request.
"""

from __future__ import annotations

import ast
import builtins
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from alphafold_sovereign.clients import _base
from alphafold_sovereign.clients._base import AirGapError
from alphafold_sovereign.clients.alphafold import AlphaFoldClient
from alphafold_sovereign.clients.ensembl import EnsemblClient
from alphafold_sovereign.tools import structure_intelligence as si
from alphafold_sovereign.tools.structure_intelligence import (
    BindingPocketInput,
    EvolutionaryInput,
    MultiProteinInput,
    StructureRetrievalInput,
    UniProtInput,
    analyze_structural_confidence,
    compare_proteins_topologically,
    compute_topology_fingerprint,
    detect_intrinsically_disordered,
    find_evolutionary_structural_shifts,
    get_protein_structure,
    score_binding_pocket_geometry,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    import respx

_API = "https://alphafold.ebi.ac.uk/api/prediction"
_FILES = "https://alphafold.ebi.ac.uk/files"
_ENSEMBL = "https://rest.ensembl.org"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _pdb(n_residues: int = 30, tag: str = "") -> str:
    """A synthetic PDB: C-alpha atoms on a line, optionally marked with a REMARK."""
    lines = [f"REMARK {tag}"] if tag else []
    lines.extend(
        f"ATOM  {i + 1:5d}  CA  ALA A{i + 1:4d}    {1.0 * i:8.3f}{0.0:8.3f}{0.0:8.3f}"
        f"  1.00{85.0:6.2f}           C"
        for i in range(n_residues)
    )
    lines.append("END")
    return "\n".join(lines)


def _record(accession: str, version: int = 6) -> dict[str, Any]:
    """A prediction record in the current AlphaFold DB schema."""
    return {
        "uniprotAccession": accession,
        "modelEntityId": f"AF-{accession}-F1",
        "sequence": "M" * 30,
        "globalMetricValue": 85.0,
        "latestVersion": version,
        "pdbUrl": f"{_FILES}/AF-{accession}-F1-model_v{version}.pdb",
        "cifUrl": f"{_FILES}/AF-{accession}-F1-model_v{version}.cif",
    }


@pytest.fixture
async def alphafold(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AlphaFoldClient]:
    """Install a real AlphaFold DB client as the structure module's client."""
    client = AlphaFoldClient()
    monkeypatch.setattr(si, "_alphafold", lambda: client)
    yield client
    await client.__aexit__(None, None, None)


@pytest.fixture
async def ensembl(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[list[EnsemblClient]]:
    """Let the tool build real Ensembl clients, and close them afterwards."""
    created: list[EnsemblClient] = []

    def build() -> EnsemblClient:
        created.append(EnsemblClient())
        return created[-1]

    monkeypatch.setattr(si, "EnsemblClient", build)
    yield created
    for client in created:
        await client.__aexit__(None, None, None)


@pytest.fixture
def without_gudhi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import gudhi`` fail, as on an installation without the ``[tda]`` extra."""
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "gudhi":
            raise ImportError("No module named 'gudhi'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


# ---------------------------------------------------------------------------
# 1. A 404 for an advertised coordinate file is a failed retrieval
# ---------------------------------------------------------------------------

_COORDINATE_TOOLS = [
    (compute_topology_fingerprint, UniProtInput),
    (score_binding_pocket_geometry, BindingPocketInput),
    (detect_intrinsically_disordered, UniProtInput),
]


@pytest.mark.parametrize(("tool", "model"), _COORDINATE_TOOLS)
async def test_missing_coordinate_file_is_a_failed_request_not_a_missing_prediction(
    respx_mock: respx.MockRouter, alphafold: AlphaFoldClient, tool: Any, model: Any
) -> None:
    """AlphaFold DB returned the record; only the file it names answered 404."""
    respx_mock.get(f"{_API}/P11111").mock(
        return_value=httpx.Response(200, json=[_record("P11111")])
    )
    file_route = respx_mock.get(f"{_FILES}/AF-P11111-F1-model_v6.pdb").mock(
        return_value=httpx.Response(404, text="Not Found")
    )

    out = await tool(model(uniprot_id="P11111"))

    assert file_route.call_count == 1
    assert out["structure_available"] is False
    assert out["retrieval_status"] == "request_failed"
    assert "the prediction record was returned" in out["error"]
    assert "HTTP 404" in out["error"]
    assert "not evidence that AlphaFold DB has no prediction" in out["note"]
    assert "No structure prediction returned" not in json.dumps(out)


@pytest.mark.parametrize(("tool", "model"), _COORDINATE_TOOLS)
async def test_prediction_endpoint_404_is_still_no_prediction_returned(
    respx_mock: respx.MockRouter, alphafold: AlphaFoldClient, tool: Any, model: Any
) -> None:
    """The prediction endpoint itself answering 404 keeps its meaning."""
    respx_mock.get(f"{_API}/P22222").mock(return_value=httpx.Response(404, text="Not Found"))

    out = await tool(model(uniprot_id="P22222"))

    assert out["structure_available"] is False
    assert out["retrieval_status"] == "no_prediction_returned"
    assert out["error"].startswith("No structure prediction returned by the AlphaFold DB REST API")


async def test_compare_proteins_separates_a_failed_file_request_from_a_missing_model(
    respx_mock: respx.MockRouter, alphafold: AlphaFoldClient
) -> None:
    respx_mock.get(f"{_API}/P33333").mock(
        return_value=httpx.Response(200, json=[_record("P33333")])
    )
    respx_mock.get(f"{_FILES}/AF-P33333-F1-model_v6.pdb").mock(
        return_value=httpx.Response(200, text=_pdb())
    )
    respx_mock.get(f"{_API}/P11111").mock(
        return_value=httpx.Response(200, json=[_record("P11111")])
    )
    respx_mock.get(f"{_FILES}/AF-P11111-F1-model_v6.pdb").mock(
        return_value=httpx.Response(404, text="Not Found")
    )
    respx_mock.get(f"{_API}/P22222").mock(return_value=httpx.Response(404, text="Not Found"))

    out = await compare_proteins_topologically(
        MultiProteinInput(uniprot_ids=["P33333", "P11111", "P22222"])
    )

    assert out["proteins_analyzed"] == ["P33333"]
    assert out["proteins_failed"]["P22222"] == "No AlphaFold model for this accession."
    failed_file = out["proteins_failed"]["P11111"]
    assert failed_file.startswith("AlphaFold model retrieval failed (")
    assert "HTTP 404" in failed_file
    assert failed_file.endswith("this is not evidence that no model exists.")


# ---------------------------------------------------------------------------
# 4. Embedded coordinates belong to the record the response reports
# ---------------------------------------------------------------------------


async def test_embedded_coordinates_come_from_the_reported_record(
    respx_mock: respx.MockRouter, alphafold: AlphaFoldClient
) -> None:
    """AlphaFold DB replaces the model while the tool runs.

    A second prediction lookup would see version 6. The response describes
    version 4, so the coordinates must be the version-4 file, and one
    prediction request is all it takes.
    """
    metadata = respx_mock.get(f"{_API}/P38398").mock(
        side_effect=[
            httpx.Response(200, json=[_record("P38398", 4)]),
            httpx.Response(200, json=[_record("P38398", 6)]),
        ]
    )
    v4_file = respx_mock.get(f"{_FILES}/AF-P38398-F1-model_v4.pdb").mock(
        return_value=httpx.Response(200, text=_pdb(5, tag="coordinates of model_v4"))
    )
    v6_file = respx_mock.get(f"{_FILES}/AF-P38398-F1-model_v6.pdb").mock(
        return_value=httpx.Response(200, text=_pdb(5, tag="coordinates of model_v6"))
    )

    out = await get_protein_structure(
        StructureRetrievalInput(uniprot_id="P38398", include_coordinates=True)
    )

    assert metadata.call_count == 1
    assert (v4_file.call_count, v6_file.call_count) == (1, 0)
    assert out["model_version"] == 4
    assert out["file_urls"]["pdb"] == f"{_FILES}/AF-P38398-F1-model_v4.pdb"
    assert "alphafold_db=v4" in out["provenance"]
    assert out["coordinates_pdb"] == _pdb(5, tag="coordinates of model_v4")
    assert out["coordinates_status"] == "retrieved"
    assert "coordinates_error" not in out


async def test_failed_coordinate_download_is_reported_with_its_reason(
    respx_mock: respx.MockRouter, alphafold: AlphaFoldClient
) -> None:
    """The metadata stands; the empty ``coordinates_pdb`` is explained."""
    respx_mock.get(f"{_API}/P38398").mock(
        return_value=httpx.Response(200, json=[_record("P38398")])
    )
    respx_mock.get(f"{_FILES}/AF-P38398-F1-model_v6.pdb").mock(
        return_value=httpx.Response(404, text="Not Found")
    )

    out = await get_protein_structure(
        StructureRetrievalInput(uniprot_id="P38398", include_coordinates=True)
    )

    assert out["structure_available"] is True
    assert out["entry_id"] == "AF-P38398-F1"
    assert "retrieval_status" not in out
    assert out["coordinates_pdb"] == ""
    assert out["coordinates_status"] == "request_failed"
    assert "HTTP 404" in out["coordinates_error"]
    assert "not evidence that the model has no coordinate file" in out["coordinates_error"]


async def test_record_without_a_pdb_file_reports_no_coordinates_returned(
    respx_mock: respx.MockRouter, alphafold: AlphaFoldClient
) -> None:
    record = _record("P38398")
    del record["pdbUrl"]
    respx_mock.get(f"{_API}/P38398").mock(return_value=httpx.Response(200, json=[record]))

    out = await get_protein_structure(
        StructureRetrievalInput(uniprot_id="P38398", include_coordinates=True)
    )

    assert len(respx_mock.calls) == 1  # nothing to download
    assert out["structure_available"] is True
    assert out["coordinates_pdb"] == ""
    assert out["coordinates_status"] == "no_coordinates_returned"
    assert "advertises no PDB file" in out["coordinates_error"]


async def test_metadata_only_retrieval_requests_no_file_and_reports_no_coordinates(
    respx_mock: respx.MockRouter, alphafold: AlphaFoldClient
) -> None:
    respx_mock.get(f"{_API}/P38398").mock(
        return_value=httpx.Response(200, json=[_record("P38398")])
    )

    out = await get_protein_structure(StructureRetrievalInput(uniprot_id="P38398"))

    assert len(respx_mock.calls) == 1
    assert not [key for key in out if key.startswith("coordinates")]


# ---------------------------------------------------------------------------
# 2. Only the GUDHI path reduces a long model to 500 C-alpha atoms
# ---------------------------------------------------------------------------


async def test_fallback_compares_every_residue_of_a_long_model(
    monkeypatch: pytest.MonkeyPatch, without_gudhi: None
) -> None:
    """Without GUDHI a 600-residue model is compared on all 600 residues."""
    lengths = {"P12345": 600, "P67890": 40}

    async def fake_fetch(uid: str) -> dict[str, Any]:
        return {"pdb_text": _pdb(lengths[uid]), "uniprot_id": uid, "model_version": 6}

    monkeypatch.setattr(si, "_fetch_af_structure", fake_fetch)
    out = await compare_proteins_topologically(MultiProteinInput(uniprot_ids=list(lengths)))

    long_model = out["protein_metadata"]["P12345"]
    assert (long_model["n_residues"], long_model["n_residues_used"]) == (600, 600)
    assert long_model["subsampled"] is False
    assert "methodology=geometric-proxy" in out["provenance"]


@pytest.mark.parametrize(
    "description",
    [
        pytest.param(si.__doc__, id="module"),
        pytest.param(compute_topology_fingerprint.__doc__, id="compute_topology_fingerprint"),
        pytest.param(compare_proteins_topologically.__doc__, id="compare_proteins_topologically"),
    ],
)
def test_descriptions_limit_the_500_residue_reduction_to_the_gudhi_path(
    description: str | None,
) -> None:
    text = " ".join((description or "").split())
    reductions = re.findall(r"[^.]*500 evenly spaced[^.]*\.", text)
    assert reductions, "the description no longer mentions the reduction"
    for sentence in reductions:
        assert "GUDHI" in sentence, f"reduction stated without its condition: {sentence!r}"
    # The fallback is described too, and as using the whole model.
    assert re.search(r"Without GUDHI,? the fallback[^.]*uses every residue", text)


# ---------------------------------------------------------------------------
# 3. What each structure tool reports in offline mode
# ---------------------------------------------------------------------------

# How a blocked AlphaFold DB request surfaces, per tool. The offline
# documentation states exactly this table.
_OFFLINE_REPORTING = {
    "get_protein_structure": "retrieval_status",
    "analyze_structural_confidence": "retrieval_status",
    "compute_topology_fingerprint": "retrieval_status",
    "score_binding_pocket_geometry": "retrieval_status",
    "detect_intrinsically_disordered": "retrieval_status",
    "compare_proteins_topologically": "proteins_failed",
    "find_evolutionary_structural_shifts": "raises",
}

_OFFLINE_CALLS: dict[str, Callable[[], Awaitable[dict[str, Any]]]] = {
    "get_protein_structure": lambda: get_protein_structure(
        StructureRetrievalInput(uniprot_id="P69905")
    ),
    "analyze_structural_confidence": lambda: analyze_structural_confidence(
        UniProtInput(uniprot_id="P69905")
    ),
    "compute_topology_fingerprint": lambda: compute_topology_fingerprint(
        UniProtInput(uniprot_id="P69905")
    ),
    "score_binding_pocket_geometry": lambda: score_binding_pocket_geometry(
        BindingPocketInput(uniprot_id="P69905")
    ),
    "detect_intrinsically_disordered": lambda: detect_intrinsically_disordered(
        UniProtInput(uniprot_id="P69905")
    ),
    "compare_proteins_topologically": lambda: compare_proteins_topologically(
        MultiProteinInput(uniprot_ids=["P69905", "P68871"])
    ),
    "find_evolutionary_structural_shifts": lambda: find_evolutionary_structural_shifts(
        EvolutionaryInput(gene_symbol="HBA1", target_species=["mus_musculus"])
    ),
}


def _registered_structure_tools() -> set[str]:
    """Names of the functions the structure module registers with ``@mcp.tool``."""
    source = Path(si.__file__).read_text(encoding="utf-8")
    return {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef)
        and any("mcp.tool" in ast.unparse(decorator) for decorator in node.decorator_list)
    }


def test_offline_reporting_table_covers_every_structure_tool() -> None:
    """A new structure tool must declare, and document, what it reports offline."""
    assert set(_OFFLINE_REPORTING) == _registered_structure_tools()
    assert set(_OFFLINE_CALLS) == set(_OFFLINE_REPORTING)


@pytest.mark.parametrize("tool_name", sorted(_OFFLINE_REPORTING))
async def test_offline_reporting_of_each_structure_tool(
    monkeypatch: pytest.MonkeyPatch,
    alphafold: AlphaFoldClient,
    ensembl: list[EnsemblClient],
    tool_name: str,
) -> None:
    """``ALPHAFOLD_OFFLINE=1`` with nothing allowlisted: no request leaves."""
    monkeypatch.setattr(_base, "_OFFLINE_MODE", True)
    monkeypatch.setattr(_base, "_ALWAYS_ALLOWED", frozenset())
    reporting = _OFFLINE_REPORTING[tool_name]

    if reporting == "raises":
        # Ensembl is queried first and its blocked request is not caught.
        with pytest.raises(AirGapError, match=r"outbound request to 'rest\.ensembl\.org' blocked"):
            await _OFFLINE_CALLS[tool_name]()
        return

    out = await _OFFLINE_CALLS[tool_name]()
    if reporting == "retrieval_status":
        assert out["structure_available"] is False
        assert out["retrieval_status"] == "request_failed"
        assert "AirGapError" in out["error"]
    else:
        assert "retrieval_status" not in out
        assert out["proteins_analyzed"] == []
        assert set(out["proteins_failed"]) == {"P69905", "P68871"}
        for reason in out["proteins_failed"].values():
            assert "AirGapError" in reason
            assert reason.endswith("this is not evidence that no model exists.")


async def test_evolutionary_shifts_with_only_ensembl_allowlisted_reports_sequence_identity_only(
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    alphafold: AlphaFoldClient,
    ensembl: list[EnsemblClient],
) -> None:
    """Partial air gap: Ensembl answers, the AlphaFold DB request is blocked.

    This pins what the tool does today, which the offline documentation
    describes: it returns sequence identity alone and does not say that the
    structure request was blocked. Should the tool gain an explicit source
    state, change this test and that documentation together.
    """
    monkeypatch.setattr(_base, "_OFFLINE_MODE", True)
    monkeypatch.setattr(_base, "_ALWAYS_ALLOWED", frozenset({"rest.ensembl.org"}))
    respx_mock.get(f"{_ENSEMBL}/lookup/symbol/human/HBA1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "ENSG00000206172",
                "display_name": "HBA1",
                "Xref": [{"dbname": "Uniprot/SWISSPROT", "primary_id": "P69905"}],
            },
        )
    )
    respx_mock.get(f"{_ENSEMBL}/homology/id/human/ENSG00000206172").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "homologies": [
                            {
                                "type": "ortholog_one2one",
                                "target": {
                                    "species": "mus_musculus",
                                    "id": "ENSMUSG00000069919",
                                    "perc_id": 86.6,
                                },
                            }
                        ]
                    }
                ]
            },
        )
    )

    out = await _OFFLINE_CALLS["find_evolutionary_structural_shifts"]()

    assert out["human_uniprot_id"] == "P69905"
    assert [row["divergence_method"] for row in out["evolutionary_profile"]] == [
        "sequence_identity"
    ]
    assert (out["sequence_identity_fallbacks"], out["tda_comparisons"]) == (1, 0)
    assert "alphafold_db=not-retrieved" in out["provenance"]
    assert "retrieval_status" not in out
    assert "AirGapError" not in json.dumps(out)


def _section(text: str, start: str, end: str) -> str:
    """The part of ``text`` from ``start`` up to the next ``end``."""
    begin = text.index(start)
    return text[begin : text.index(end, begin + len(start))]


def _offline_sections() -> dict[str, str]:
    """The offline-mode passage of each document that describes it."""

    def read(relative: str) -> str:
        return (_REPO_ROOT / relative).read_text(encoding="utf-8")

    return {
        "docs/installation.md": _section(
            read("docs/installation.md"), "## Offline / air-gap mode", "```bash"
        ),
        "README.md": _section(read("README.md"), "### Offline mode", "\n---"),
        "llms-install.md": _section(
            read("llms-install.md"), "- `ALPHAFOLD_OFFLINE`", "- `ALPHAFOLD_ALLOW_HOSTS`"
        ),
    }


@pytest.mark.parametrize("document", ["docs/installation.md", "README.md", "llms-install.md"])
def test_offline_documentation_states_the_contract_of_each_structure_tool(document: str) -> None:
    section = " ".join(_offline_sections()[document].split())

    # The promise that every structure tool returns ``retrieval_status`` is gone.
    assert "The structure tools report the AlphaFold DB request as failed" not in section
    # Every tool is named with the way it reports a blocked request.
    for tool_name in _OFFLINE_REPORTING:
        assert f"`{tool_name}`" in section, f"{document} does not name {tool_name}"
    assert '`retrieval_status: "request_failed"`' in section
    assert "`proteins_failed`" in section
    assert "Ensembl" in section
