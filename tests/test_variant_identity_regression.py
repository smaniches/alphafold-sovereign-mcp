# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""AF-01: ``triage_variant_3d`` must never report another variant's ClinVar record.

End-to-end through the registered MCP tool: an in-memory FastMCP ``Client``
calls ``triage_variant_3d``; the real ``ClinVarClient`` builds the esearch
term, parses esummary, ranks and stamps candidates; ``_fetch_clinvar`` picks
the record. Only the NCBI HTTP transport is replaced (respx). The records are
synthetic software fixtures (``9000xx`` IDs, a placeholder condition), not
clinical evidence or captured ClinVar payloads; titles follow ClinVar's
observed ``ACCESSION.v(GENE):change (protein)`` spelling.

Before the fix, the empty, nearby, other-gene and other-transcript scenarios
attributed an unrelated record (via the gene-level fallback or a bare change
token match); the regression assertions below fail on that code.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastmcp import Client

from alphafold_sovereign.server.app import mcp
from alphafold_sovereign.tools import disease as disease_tools

if TYPE_CHECKING:
    import respx

_SUBMITTER = "criteria provided, single submitter"
_EXPERT = "reviewed by expert panel"

# Synthetic esummary records: uid -> (title, classification, review status).
# "{label}" is replaced by the parametrised source label.
_RECORDS: dict[str, tuple[str, str, str]] = {
    # Queried variant BRCA1:c.182A>G on ClinVar's current transcript.
    "900001": ("NM_007294.4(BRCA1):c.182A>G (synthetic)", "{label}", _SUBMITTER),
    # Nearby variant in the same gene: a different change.
    "900002": ("NM_007294.4(BRCA1):c.181T>G (p.Cys61Gly)", "Pathogenic", _EXPERT),
    # Same change token in another gene, better reviewed than the target.
    "900003": ("NM_000546.6(TP53):c.182A>G (p.Asp61Gly)", "Pathogenic", _EXPERT),
    # Legacy-spelling alias target: ClinVar writes c.5266dupC as c.5266dup.
    "900004": ("NM_007294.4(BRCA1):c.5266dup (p.Gln1756fs)", "{label}", _SUBMITTER),
    # A pathogenic gene-level record, only reachable via the old fallback.
    "900009": ("NM_007294.4(BRCA1):c.5251C>T (p.Arg1751Ter)", "Pathogenic", _EXPERT),
}

# Scenario -> (query HGVS, esearch idlist for the query, expected uid or None).
_SCENARIOS: dict[str, tuple[str, list[str], str | None]] = {
    "no_hit": ("BRCA1:c.182A>G", [], None),
    "nearby_only": ("BRCA1:c.182A>G", ["900002"], None),
    "other_gene_same_change": ("BRCA1:c.182A>G", ["900003"], None),
    "other_gene_ranked_first": ("BRCA1:c.182A>G", ["900003", "900002", "900001"], None),
    "gene_candidate": ("BRCA1:c.182A>G", ["900002", "900001"], None),
    "dup_alias": ("BRCA1:c.5266dupC", ["900002", "900004"], None),
    # The newer reference version may refer to the same allele, but this
    # title alone cannot prove it. Do not borrow its classification.
    "transcript_version_drift": ("NM_007294.3(BRCA1):c.182A>G", ["900001"], None),
    "transcript_version_exact": ("NM_007294.4(BRCA1):c.182A>G", ["900001"], "900001"),
    # Another BRCA1 transcript numbers c. positions differently.
    "other_transcript": ("NM_007300.4(BRCA1):c.182A>G", ["900001"], None),
}

# Source label -> source classification plus unassessed local tier. The
# source label remains available, but it never becomes a locally inferred
# clinical risk category.
_LABELS: dict[str, tuple[str, str]] = {
    "Pathogenic": ("Pathogenic", "NOT_ASSESSED"),
    "Likely pathogenic": ("Likely pathogenic", "NOT_ASSESSED"),
    "Pathogenic/Likely pathogenic": ("Not provided", "NOT_ASSESSED"),
    "Uncertain significance": ("Uncertain significance", "NOT_ASSESSED"),
    "Benign": ("Benign", "NOT_ASSESSED"),
}


def _esummary(uids: list[str], label: str) -> dict[str, Any]:
    result: dict[str, Any] = {"uids": uids}
    for uid in uids:
        title, classification, review = _RECORDS[uid]
        result[uid] = {
            "uid": uid,
            "title": title,
            "gene_sort": title.split("(", 1)[1].split(")", 1)[0],
            "germline_classification": {
                "description": classification.format(label=label),
                "review_status": review,
            },
            "trait_set": [{"trait_name": f"Synthetic condition {uid}"}],
        }
    return {"result": result}


@pytest.mark.parametrize("source_label", list(_LABELS))
@pytest.mark.parametrize("scenario", list(_SCENARIOS))
async def test_triage_reports_only_the_queried_variant(
    scenario: str, source_label: str, respx_mock: respx.MockRouter
) -> None:
    query, hits, expected_uid = _SCENARIOS[scenario]
    expected_term = query if query.startswith("NM_") else query.replace(":", "[gene] AND ", 1)
    terms: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if request.url.path.endswith("/esearch.fcgi"):
            terms.append(params["term"])
            # Any other search (e.g. the removed gene-level fallback) gets a
            # pathogenic gene record, so reintroducing it fails this test.
            ids = hits if params["term"] == expected_term else ["900009"]
            return httpx.Response(200, json={"esearchresult": {"idlist": ids}})
        assert request.url.path.endswith("/esummary.fcgi")
        return httpx.Response(200, json=_esummary(params["id"].split(","), source_label))

    # One host-scoped route for both E-utilities endpoints; any other host is
    # unmocked and fails the call (no live egress).
    respx_mock.route(method="GET", host="eutils.ncbi.nlm.nih.gov").mock(side_effect=respond)

    params = disease_tools.VariantTriageInput(
        hgvs=query,
        include_gnomad=False,
        include_disease_context=False,
        include_structure=False,
    )
    async with Client(mcp) as client:
        result = await client.call_tool(
            "triage_variant_3d", {"params": params.model_dump()}, raise_on_error=False
        )

    assert result.is_error is False
    report: dict[str, Any] = json.loads(result.content[0].text.split("\n\n---", 1)[0])
    assert report["status"] == "success"
    assert report["hgvs"] == query
    assert report["gene_symbol"] == "BRCA1"
    assert report["sources_queried"] == ["ClinVar"]
    # Exactly one ClinVar search: the variant's own. No gene-level fallback.
    assert terms == [expected_term]
    candidate_id = {
        "gene_candidate": "900001",
        "other_gene_ranked_first": "900001",
        "dup_alias": "900004",
    }.get(scenario)
    if candidate_id is None:
        assert report["clinvar_unverified_candidate"] is None
    else:
        assert report["clinvar_unverified_candidate"]["variation_id"] == candidate_id
        assert report["clinvar_unverified_candidate"]["identity_status"] == (
            "candidate_text_not_allele_verified"
        )
        assert report["data_sources_status"]["clinvar"] == "candidate_only"

    evidence = report["pathogenicity"]
    if expected_uid is None:
        assert evidence["clinvar_variation_id"] == ""
        assert evidence["clinvar_classification"] == "Not provided"
        assert evidence["clinvar_review_status"] == ""
        assert evidence["clinvar_conditions"] == []
        assert report["pathogenicity_tier"] == "NOT_ASSESSED"
    else:
        classification, tier = _LABELS[source_label]
        assert evidence["clinvar_variation_id"] == expected_uid
        assert evidence["clinvar_classification"] == classification
        assert evidence["clinvar_review_status"] == _SUBMITTER
        assert evidence["clinvar_conditions"] == [f"Synthetic condition {expected_uid}"]
        assert report["pathogenicity_tier"] == tier
