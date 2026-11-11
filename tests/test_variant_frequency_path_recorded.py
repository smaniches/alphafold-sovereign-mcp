# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""AF-1 / AF-5: the gnomAD allele-frequency path over recorded live responses.

The real ``EnsemblClient``, ``GnomADClient`` and ``AlphaFoldClient`` run inside
``classify_variant_acmg`` and ``generate_variant_clinical_report``. Only the
HTTP transport is replaced (respx), by responses recorded from the live
services on 2026-11-10 UTC (``fixtures/variant_frequency_path_20261110.json``;
its ``meta`` block gives the requests, the trimming applied and the SHA-256
of every complete live body). ClinVar and the disease/drug sources are outside
this path and are stubbed.

Before the fix these assertions fail: ``vep_hgvs`` dropped the genomic locus,
so no gnomAD lookup was ever made for an HGVS expression; the transcript-strand
alleles of a reverse-strand gene do not name the gnomAD variant; gnomAD's
"Variant not found" reply was raised as an upstream failure; and allele
frequency and AlphaMissense thresholds were emitted as PM2/BS1/PP3/BP4.

Two later corrections are covered by the last two sections: sex-stratified
population records were listed beside the record they split, and a cohort
frequency that contradicted its allele count and number was accepted.

Tests marked synthetic alter a recorded response to exercise a failure that
cannot be recorded on demand; they say so in their docstring.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from alphafold_sovereign.clients.gnomad import _POP_LABELS, GnomADClient
from alphafold_sovereign.tools import precision_medicine as pm

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import respx

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "variant_frequency_path_20261110.json").read_text(
        encoding="utf-8"
    )
)
_RESPONSES: dict[str, dict[str, Any]] = _FIXTURE["responses"]
_VEP_PREFIX = "https://rest.ensembl.org/vep/human/hgvs/"
_GNOMAD_URL = "https://gnomad.broadinstitute.org/api"
_AFDB_PREFIX = "https://alphafold.ebi.ac.uk/api/prediction/"

_BRCA1_REVERSE = "NM_007294.4:c.181T>G"
_BRCA2_FORWARD = "NM_000059.4:c.7397T>C"
_NOT_ASSESSED_FREQUENCY = {"BA1": "NOT_ASSESSED", "BS1": "NOT_ASSESSED", "PM2": "NOT_ASSESSED"}
_NOT_ASSESSED_PREDICTION = {"PP3": "NOT_ASSESSED", "BP4": "NOT_ASSESSED"}


def _reply(table: str, key: str, unexpected: list[str]) -> httpx.Response:
    record = _RESPONSES[table].get(key)
    if record is None:
        unexpected.append(f"{table}/{key}")
        return httpx.Response(599, json={})
    return httpx.Response(record["status"], json=record["body"])


@pytest.fixture
async def recorded(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[str, list[Any]]]:
    """Replay the recorded responses through the real lazily-created clients."""
    seen: dict[str, list[Any]] = {"vep_params": [], "gnomad_variant": [], "unexpected": []}

    def vep(request: httpx.Request) -> httpx.Response:
        seen["vep_params"].append(dict(request.url.params))
        hgvs = request.url.path.removeprefix("/vep/human/hgvs/")
        return _reply("ensembl_vep", hgvs, seen["unexpected"])

    def gnomad(request: httpx.Request) -> httpx.Response:
        variables = json.loads(request.content)["variables"]
        if "variantId" in variables:
            seen["gnomad_variant"].append(variables)
            return _reply("gnomad_variant", variables["variantId"], seen["unexpected"])
        return _reply("gnomad_constraint", variables["geneSymbol"], seen["unexpected"])

    def afdb(request: httpx.Request) -> httpx.Response:
        accession = request.url.path.rpartition("/")[2]
        return _reply("alphafold_prediction", accession, seen["unexpected"])

    respx_mock.get(url__startswith=_VEP_PREFIX).mock(side_effect=vep)
    respx_mock.post(_GNOMAD_URL).mock(side_effect=gnomad)
    respx_mock.get(url__startswith=_AFDB_PREFIX).mock(side_effect=afdb)
    for record in _RESPONSES["alphamissense_csv"].values():
        respx_mock.get(record["url"]).mock(return_value=httpx.Response(200, text=record["text"]))

    pm._CLIENTS.clear()
    stubs: dict[str, MagicMock] = {}
    for name in ("clinvar", "disgenet", "opentargets", "chembl"):
        stubs[name] = MagicMock()
        monkeypatch.setattr(pm, f"_{name}", lambda stub=stubs[name]: stub)
    stubs["clinvar"].search_by_hgvs = AsyncMock(return_value=[])
    stubs["disgenet"].gene_disease_associations = AsyncMock(return_value=[])
    monkeypatch.setattr(pm._ensembl(), "gene_lookup", AsyncMock(return_value={}))

    yield seen

    for client in list(pm._CLIENTS.values()):
        await client.__aexit__(None, None, None)
    pm._CLIENTS.clear()
    assert seen["unexpected"] == [], "a request was made that the fixture does not record"


async def _classify(hgvs: str) -> dict[str, Any]:
    return await pm.classify_variant_acmg(pm.ACMGVariantInput(hgvs=hgvs))


async def _report(hgvs: str) -> dict[str, Any]:
    return await pm.generate_variant_clinical_report(
        pm.VariantClinicalReportInput(hgvs=hgvs, include_drug_context=False)
    )


# ---------------------------------------------------------------------------
# Variant identity: assembly, strand, class
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hgvs", "variant_id", "variant_class", "lookup_status", "source_status"),
    [
        # BRCA1 is on the reverse strand: c.181T>G is A>C on the forward strand.
        (_BRCA1_REVERSE, "17-43106487-A-C", "snv", "found", "ok"),
        # BRCA2 is on the forward strand.
        (_BRCA2_FORWARD, "13-32355250-T-C", "snv", "found", "ok"),
        # The genomic expression of the BRCA1 variant names the same allele.
        ("NC_000017.11:g.43106487A>C", "17-43106487-A-C", "snv", "found", "ok"),
        # A substitution gnomAD does not hold: no record, never AF = 0.
        ("NM_007294.4:c.181T>A", "17-43106487-A-T", "snv", "not_found", "no_data"),
        # Reverse-strand deletion whose VEP representation gnomAD holds.
        ("NM_007294.4:c.68_69del", "17-43124027-ACT-A", "deletion", "found", "ok"),
        # CFTR F508del and BRCA1 c.5266dup: gnomAD holds both, but left-aligned
        # (7-117559590-ATCT-A, 17-43057062-T-TG), not as VEP writes them.
        (
            "NM_000492.4:c.1521_1523del",
            "7-117559591-TCTT-T",
            "deletion",
            "not_found_representation_unverified",
            "no_data",
        ),
        (
            "NM_007294.4:c.5266dup",
            "17-43057063-G-GG",
            "insertion",
            "not_found_representation_unverified",
            "no_data",
        ),
        # Multi-nucleotide change: not one gnomAD record, so no lookup.
        ("NM_007294.4:c.181_182delinsGC", None, "complex", "not_attempted", "skipped"),
        # Expressions that do not pin one genomic allele: no lookup, although
        # VEP returns a mapping for each (and silently accepts the stale
        # Ensembl transcript version .8).
        ("BRCA1:c.181T>G", None, None, "not_attempted", "skipped"),
        ("TP53:p.Arg248Trp", None, None, "not_attempted", "skipped"),
        ("ENST00000357654.8:c.181T>G", None, None, "not_attempted", "skipped"),
    ],
)
async def test_recorded_variant_identity_and_lookup_status(
    recorded: dict[str, list[Any]],
    hgvs: str,
    variant_id: str | None,
    variant_class: str | None,
    lookup_status: str,
    source_status: str,
) -> None:
    out = await _classify(hgvs)
    frequency = out["unassessed_evidence"]["population_frequency"]

    assert out["data_sources_status"]["ensembl_vep"] == "ok"
    assert out["data_sources_status"]["gnomad_variant"] == source_status
    assert frequency["variant_id"] == variant_id
    assert frequency["variant_class"] == variant_class
    assert frequency["lookup_status"] == lookup_status
    assert frequency["detail"]
    assert frequency["acmg_criteria"] == _NOT_ASSESSED_FREQUENCY
    # Exactly the resolved forward-strand ID is requested from gnomAD r4 (GRCh38).
    expected_requests = [{"variantId": variant_id, "datasetId": "gnomad_r4"}] if variant_id else []
    assert recorded["gnomad_variant"] == expected_requests
    if variant_id:
        assert frequency["mapping_basis"] == "versioned_hgvs_via_ensembl_vep"
        assert frequency["reference_genome"] == "GRCh38"
        assert frequency["dataset"] == "gnomad_r4"
    if lookup_status != "found":
        # Missing frequency data is never an allele frequency of 0.
        assert frequency["cohorts"] == {}
    assert out["draft_classification"] == "Not assessed"
    assert out["clinical_classification_performed"] is False
    assert all(params["vcf_string"] == "1" for params in recorded["vep_params"])


async def test_brca1_reverse_strand_frequency_and_provenance(
    recorded: dict[str, list[Any]],
) -> None:
    """The headline defect: this lookup was never made, and T>G is the wrong allele."""
    out = await _classify(_BRCA1_REVERSE)
    frequency = out["unassessed_evidence"]["population_frequency"]

    assert frequency["cohorts"] == {
        "exome": {
            "allele_count": 25,
            "allele_number": 1452604,
            "allele_frequency": pytest.approx(25 / 1452604),
            "homozygote_count": 0,
        },
        "genome": {
            "allele_count": 5,
            "allele_number": 152214,
            "allele_frequency": pytest.approx(5 / 152214),
            "homozygote_count": 0,
        },
    }
    # VEP writes the alleles on the transcript strand; that ID is not in gnomAD.
    locus = _RESPONSES["ensembl_vep"][_BRCA1_REVERSE]["body"][0]
    assert (locus["strand"], locus["allele_string"]) == (-1, "T/G")
    naive = _RESPONSES["gnomad_variant"]["17-43106487-T-G"]["body"]
    assert naive["errors"] == [{"message": "Variant not found"}]


async def test_brca2_common_variant_gets_no_benign_criterion(
    recorded: dict[str, list[Any]],
) -> None:
    """AF 0.998 used to be labelled BS1 (>5%); it is now a raw observation."""
    out = await _classify(_BRCA2_FORWARD)
    evidence = out["unassessed_evidence"]

    exome = evidence["population_frequency"]["cohorts"]["exome"]
    assert exome["allele_count"] == 1458237
    assert exome["allele_number"] == 1461288
    assert exome["allele_frequency"] == pytest.approx(0.99791, abs=1e-5)
    assert exome["homozygote_count"] == 727677
    assert evidence["population_frequency"]["cohorts"]["genome"]["allele_frequency"] == (
        pytest.approx(0.98057, abs=1e-5)
    )
    assert out["candidate_criteria"] == {}
    assert out["criteria_met"] == {}
    assert evidence["population_frequency"]["acmg_criteria"] == _NOT_ASSESSED_FREQUENCY
    assert evidence["clinically_calibrated_evidence"]["status"] == "NOT_ASSESSED"
    # AlphaFold DB has no entry for BRCA2 (recorded HTTP 404): no score, no criterion.
    assert evidence["computational_predictions"]["alphamissense"]["score"] is None
    assert evidence["computational_predictions"]["acmg_criteria"] == _NOT_ASSESSED_PREDICTION


async def test_rare_frequency_and_alphamissense_assign_no_criterion(
    recorded: dict[str, list[Any]],
) -> None:
    """AF 1.7e-5 used to be PM2 and AlphaMissense 0.9904 used to be PP3."""
    out = await _classify(_BRCA1_REVERSE)
    predictions = out["unassessed_evidence"]["computational_predictions"]

    assert predictions["alphamissense"] == {
        "status": "ok",
        "protein_variant": "C61G",
        "score": 0.9904,
        "source_class": "LPath",
    }
    # The recorded predictors disagree on this variant.
    assert predictions["ensembl_vep"] == {
        "transcript_id": "ENST00000357654",
        "sift_prediction": "deleterious",
        "sift_score": 0,
        "polyphen_prediction": "benign",
        "polyphen_score": 0.027,
        "cadd_phred": None,
    }
    assert predictions["acmg_criteria"] == _NOT_ASSESSED_PREDICTION
    assert out["candidate_criteria"] == {}
    assert out["summary"]["unreviewed_computational_signals"] == 0


async def test_protein_level_expression_reports_prediction_without_lookup(
    recorded: dict[str, list[Any]],
) -> None:
    out = await _classify("TP53:p.Arg248Trp")
    evidence = out["unassessed_evidence"]

    assert "do not pin one genomic allele" in evidence["population_frequency"]["detail"]
    assert evidence["computational_predictions"]["alphamissense"]["score"] == 0.9968
    assert evidence["computational_predictions"]["acmg_criteria"] == _NOT_ASSESSED_PREDICTION
    assert out["candidate_criteria"] == {}


async def test_indel_not_found_is_not_absence(recorded: dict[str, list[Any]]) -> None:
    """gnomAD holds CFTR F508del at AF 0.012 under its left-aligned ID."""
    out = await _classify("NM_000492.4:c.1521_1523del")
    frequency = out["unassessed_evidence"]["population_frequency"]
    assert frequency["lookup_status"] == "not_found_representation_unverified"
    assert "neither absence nor an allele frequency of 0" in frequency["detail"]
    assert "HGVS-derived position" in frequency["detail"]

    held = await pm._gnomad().variant_frequencies("7-117559590-ATCT-A")
    assert held["found"] is True
    assert held["cohorts"]["exome"]["allele_count"] == 18037
    assert held["global_af"] == pytest.approx(0.012353, abs=1e-6)


# ---------------------------------------------------------------------------
# Exome / genome provenance
# ---------------------------------------------------------------------------


async def test_exome_zero_does_not_hide_genome_carrier(recorded: dict[str, list[Any]]) -> None:
    """17-43104108-A-G: no exome carrier (AN 1,458,040) and one genome carrier."""
    report = await _report("NC_000017.11:g.43104108A>G")
    population = report["population_genetics"]
    cohorts = report["unassessed_evidence"]["population_frequency"]["cohorts"]

    # The summary fields keep their meaning: the exome cohort when gnomAD has one.
    assert (population["cohort"], population["global_ac"], population["global_af"]) == (
        "exome",
        0,
        0.0,
    )
    assert population["global_an"] == 1458040
    assert cohorts["exome"]["allele_count"] == 0
    assert cohorts["genome"]["allele_count"] == 1
    assert cohorts["genome"]["allele_number"] == 151840
    assert cohorts["genome"]["allele_frequency"] == pytest.approx(1 / 151840)


# ---------------------------------------------------------------------------
# Report tool
# ---------------------------------------------------------------------------


async def test_report_reverse_strand_variant(recorded: dict[str, list[Any]]) -> None:
    report = await _report(_BRCA1_REVERSE)

    assert report["gene_symbol"] == "BRCA1"
    assert report["data_sources_status"]["gnomad"] == "ok"
    assert report["data_sources_status"]["gnomad_constraint"] == "ok"
    population = report["population_genetics"]
    assert population["cohort"] == "exome"
    assert population["global_ac"] == 25
    assert population["global_an"] == 1452604
    assert population["global_af"] == pytest.approx(25 / 1452604)
    assert population["alphamissense_score"] == 0.9904
    assert report["acmg_criteria_draft"]["criteria"] == {}
    frequency = report["unassessed_evidence"]["population_frequency"]
    assert frequency["variant_id"] == "17-43106487-A-C"
    assert frequency["lookup_status"] == "found"
    assert report["clinical_tier"] == "NOT_ASSESSED"


async def test_report_missing_frequency_is_never_zero(recorded: dict[str, list[Any]]) -> None:
    report = await _report("NM_007294.4:c.181T>A")
    population = report["population_genetics"]

    assert report["data_sources_status"]["gnomad"] == "no_data"
    assert population["global_af"] is None
    assert population["global_ac"] is None
    assert population["global_an"] is None
    assert population["cohort"] is None
    assert report["unassessed_evidence"]["population_frequency"]["lookup_status"] == "not_found"


# ---------------------------------------------------------------------------
# Upstream failures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hgvs",
    [
        "NM_007294.4:c.181A>G",  # reference allele does not match the transcript
        "NM_007294.3:c.181T>G",  # stale RefSeq transcript version
        "NC_000017.10:g.41258504A>C",  # GRCh37 chromosome accession
    ],
)
async def test_recorded_vep_rejection_skips_lookup(
    recorded: dict[str, list[Any]], hgvs: str
) -> None:
    """Ensembl VEP answers each of these with HTTP 400 (recorded)."""
    assert _RESPONSES["ensembl_vep"][hgvs]["status"] == 400
    out = await _classify(hgvs)
    frequency = out["unassessed_evidence"]["population_frequency"]

    assert out["data_sources_status"]["ensembl_vep"] == "failed"
    assert out["data_sources_status"]["gnomad_variant"] == "skipped"
    assert frequency["lookup_status"] == "not_attempted"
    # The reason names the rejection; it is not "VEP returned no genomic mapping".
    assert frequency["detail"] == (
        "The Ensembl VEP request failed or was rejected, so this expression was not mapped "
        "to a genomic allele."
    )
    assert frequency["variant_id"] is None
    assert frequency["cohorts"] == {}
    assert recorded["gnomad_variant"] == []


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (503, {}),
        (200, {"errors": [{"message": "Internal server error"}]}),
        (200, _RESPONSES["gnomad_variant"]["13-32355250-T-C"]["body"]),
    ],
    ids=["http_503", "graphql_error", "record_for_another_variant"],
)
async def test_synthetic_gnomad_failure_is_not_absence(
    recorded: dict[str, list[Any]],
    respx_mock: respx.MockRouter,
    status: int,
    body: dict[str, Any],
) -> None:
    """Synthetic: gnomAD fails, errors, or answers with a different variant's record."""
    respx_mock.post(_GNOMAD_URL).mock(side_effect=lambda _: httpx.Response(status, json=body))
    out = await _classify(_BRCA1_REVERSE)
    frequency = out["unassessed_evidence"]["population_frequency"]

    assert out["data_sources_status"]["gnomad_variant"] == "failed"
    assert frequency["lookup_status"] == "failed"
    assert frequency["variant_id"] == "17-43106487-A-C"
    assert frequency["cohorts"] == {}
    assert frequency["acmg_criteria"] == _NOT_ASSESSED_FREQUENCY


# ---------------------------------------------------------------------------
# Missing or ambiguous mappings (resolver, on rows the real client returns)
# ---------------------------------------------------------------------------


async def test_resolver_on_recorded_client_rows(recorded: dict[str, list[Any]]) -> None:
    rows = await pm._ensembl().vep_hgvs(_BRCA1_REVERSE)
    resolved = pm._resolve_gnomad_variant(_BRCA1_REVERSE, rows)
    assert resolved == {
        "variant_id": "17-43106487-A-C",
        "variant_class": "snv",
        "mapping_basis": "versioned_hgvs_via_ensembl_vep",
        "reference_genome": "GRCh38",
        "detail": "",
    }


@pytest.mark.parametrize(
    ("change", "expected_detail"),
    [
        ({"assembly_name": "GRCh37"}, "mapped this expression on assembly 'GRCh37'"),
        # What VEP returns when vcf_string=1 is not requested (the pre-fix request).
        ({"vcf_string": None}, "missing or disagrees"),
        # The transcript-strand alleles the pre-fix builder would have used.
        ({"vcf_string": "17-43106487-T-G"}, "missing or disagrees"),
        ({"vcf_string": ["17-43106487-A-C", "17-43106487-A-G"]}, "missing or disagrees"),
        ({"seq_region_name": "13"}, "missing or disagrees"),
        ({"start": 43106488}, "missing or disagrees"),
        ({"end": 43106488}, "missing or disagrees"),
        ({"strand": 1}, "missing or disagrees"),
        ({"strand": True}, "missing or disagrees"),
        ({"strand": 0}, "missing or disagrees"),
        ({"allele_string": None}, "missing or disagrees"),
        ({"allele_string": "T/G/A"}, "missing or disagrees"),
    ],
)
async def test_synthetic_unverifiable_mapping_is_not_looked_up(
    recorded: dict[str, list[Any]], change: dict[str, Any], expected_detail: str
) -> None:
    """Synthetic: one field of the recorded BRCA1 mapping is altered."""
    rows = await pm._ensembl().vep_hgvs(_BRCA1_REVERSE)
    for row in rows:
        row["locus"].update(change)
    resolved = pm._resolve_gnomad_variant(_BRCA1_REVERSE, rows)
    assert resolved["variant_id"] is None
    assert expected_detail in resolved["detail"]


async def test_synthetic_two_mappings_are_ambiguous(recorded: dict[str, list[Any]]) -> None:
    """Synthetic: the recorded BRCA1 and BRCA2 mappings offered for one expression."""
    ensembl = pm._ensembl()
    rows = await ensembl.vep_hgvs(_BRCA1_REVERSE) + await ensembl.vep_hgvs(_BRCA2_FORWARD)
    # The BRCA2 rows name another input, so the reply is not this expression's.
    resolved = pm._resolve_gnomad_variant(_BRCA1_REVERSE, rows)
    assert resolved["variant_id"] is None
    assert "does not name this expression as its input" in resolved["detail"]
    # Two mappings that both name the expression: none is chosen.
    for row in rows:
        row["locus"]["input"] = _BRCA1_REVERSE
    resolved = pm._resolve_gnomad_variant(_BRCA1_REVERSE, rows)
    assert resolved["variant_id"] is None
    assert "more than one genomic mapping" in resolved["detail"]


_NO_FUNCTIONAL_CONSEQUENCE = {
    "consequence_terms": [],
    "impact": "",
    "amino_acids": "",
    "hgvsp": "",
    "sift_prediction": "",
    "sift_score": None,
    "polyphen_prediction": "",
    "polyphen_score": None,
    "cadd_phred": None,
}


@pytest.mark.parametrize("served", ["another_gene", "same_transcript", "no_input"])
async def test_synthetic_vep_reply_that_does_not_name_the_query_is_rejected_by_both_tools(
    recorded: dict[str, list[Any]], respx_mock: respx.MockRouter, served: str
) -> None:
    """Synthetic: VEP answers the BRCA1 query with a self-consistent hit that does not name it.

    The query is c.181T>G. The hit is the recorded BRCA2 reply (another gene),
    the recorded reply for the BRCA1 frameshift c.68_69del (the queried
    transcript, another variant), or the recorded c.181T>G reply without
    ``input``. Read unchecked, the first gives the BRCA1 query the BRCA2
    variant's frequency (0.998), consequence and predictor outputs, and the
    second gives it the gene and the loss-of-function signal of the
    frameshift. Such a reply is an invalid response: nothing is read from it
    and no lookup follows from it. ClinVar, which is asked independently, is
    kept.
    """
    if served == "another_gene":
        body = _RESPONSES["ensembl_vep"][_BRCA2_FORWARD]["body"]
    elif served == "same_transcript":
        body = _RESPONSES["ensembl_vep"]["NM_007294.4:c.68_69del"]["body"]
    else:
        body = json.loads(json.dumps(_RESPONSES["ensembl_vep"][_BRCA1_REVERSE]["body"]))
        for hit in body:
            del hit["input"]
    respx_mock.get(url__startswith=_VEP_PREFIX).mock(return_value=httpx.Response(200, json=body))
    pm._clinvar().search_by_hgvs = AsyncMock(
        return_value=[
            {"exact_change_match": True, "classification": "Pathogenic", "variation_id": "17661"}
        ]
    )

    report = await _report(_BRCA1_REVERSE)
    acmg = await _classify(_BRCA1_REVERSE)

    # Only Ensembl VEP was asked: no frequency, no gene constraint and no
    # AlphaMissense score was looked up on the strength of the rejected hit.
    assert {call.request.url.host for call in respx_mock.calls} == {"rest.ensembl.org"}
    assert recorded["gnomad_variant"] == []
    for out, gnomad_key in ((report, "gnomad"), (acmg, "gnomad_variant")):
        status = out["data_sources_status"]
        assert status["ensembl_vep"] == "invalid_response"
        assert status[gnomad_key] == "skipped"
        assert status["gnomad_constraint"] == "skipped"
        assert status["alphamissense"] == "skipped_upstream_invalid"
        assert status["clinvar"] == "ok"
        assert out["gene_symbol"] is None
        evidence = out["unassessed_evidence"]
        frequency = evidence["population_frequency"]
        assert frequency["lookup_status"] == "not_attempted"
        assert frequency["variant_id"] is None
        assert frequency["mapping_basis"] is None
        assert frequency["cohorts"] == {}
        assert "response could not be validated" in frequency["detail"]
        predictions = evidence["computational_predictions"]
        assert set(predictions["ensembl_vep"].values()) == {None}
        assert predictions["alphamissense"] == {
            "status": "skipped_upstream_invalid",
            "protein_variant": None,
            "score": None,
            "source_class": None,
        }
    assert report["functional_consequence"] == _NO_FUNCTIONAL_CONSEQUENCE
    assert report["acmg_criteria_draft"]["criteria"] == {}
    assert report["population_genetics"]["global_af"] is None
    assert report["clinvar"]["found"] is True
    assert report["clinvar"]["classification"] == "Pathogenic"
    assert acmg["candidate_criteria"] == {}
    assert acmg["clinvar_reference"]["found"] is True
    assert acmg["clinvar_reference"]["classification"] == "Pathogenic"


async def test_synthetic_unanchored_length_change_is_not_looked_up(
    recorded: dict[str, list[Any]],
) -> None:
    """Synthetic: a length-changing VCF allele without the shared anchor base."""
    rows = await pm._ensembl().vep_hgvs("NM_007294.4:c.68_69del")
    for row in rows:
        row["locus"]["vcf_string"] = "17-43124027-GCT-A"
    resolved = pm._resolve_gnomad_variant("NM_007294.4:c.68_69del", rows)
    assert resolved["variant_id"] is None
    assert "missing or disagrees" in resolved["detail"]


# ---------------------------------------------------------------------------
# Clients on recorded bodies
# ---------------------------------------------------------------------------


async def test_vep_client_requests_vcf_string_and_keeps_the_locus(
    recorded: dict[str, list[Any]],
) -> None:
    rows = await pm._ensembl().vep_hgvs(_BRCA1_REVERSE)

    assert recorded["vep_params"][-1]["vcf_string"] == "1"
    assert {json.dumps(row["locus"], sort_keys=True) for row in rows} == {
        json.dumps(
            {
                "input": _BRCA1_REVERSE,
                "assembly_name": "GRCh38",
                "seq_region_name": "17",
                "start": 43106487,
                "end": 43106487,
                "strand": -1,
                "allele_string": "T/G",
                "vcf_string": "17-43106487-A-C",
            },
            sort_keys=True,
        )
    }
    assert rows[0]["gene_symbol"] == "BRCA1"
    assert rows[0]["amino_acids"] == "C/G"


async def test_gnomad_client_reports_recorded_absence_as_not_found(
    recorded: dict[str, list[Any]],
) -> None:
    """gnomAD answers an unknown variant with HTTP 200 and a GraphQL error."""
    body = _RESPONSES["gnomad_variant"]["17-43106487-A-T"]["body"]
    assert body == {"errors": [{"message": "Variant not found"}], "data": {"variant": None}}

    result = await pm._gnomad().variant_frequencies("17-43106487-A-T")
    assert result == {
        "variant_id": "17-43106487-A-T",
        "found": False,
        "dataset": "gnomad_r4",
        "global_af": None,
        "populations": [],
    }


def test_default_gnomad_dataset_matches_the_resolver_assembly() -> None:
    """gnomad_r4 is the GRCh38 dataset the resolver's assembly check assumes."""
    assert GnomADClient().dataset == "gnomad_r4"
    assert pm._GNOMAD_REFERENCE_GENOME == "GRCh38"


# ---------------------------------------------------------------------------
# Population breakdown: sex strata are not listed beside the record they split
# ---------------------------------------------------------------------------

_GENOME_ONLY = "17-43105117-T-C"
_HELD_VARIANTS = sorted(
    variant_id
    for variant_id, record in _RESPONSES["gnomad_variant"].items()
    if record["body"]["data"]["variant"]
)


def _recorded_variant(variant_id: str) -> dict[str, Any]:
    variant: dict[str, Any] = _RESPONSES["gnomad_variant"][variant_id]["body"]["data"]["variant"]
    return variant


def _names_a_sex(record_id: str) -> bool:
    """Recorded identifiers that name a sex or a sex stratum all end in XX or XY."""
    return record_id.endswith(("XX", "XY"))


async def test_report_lists_each_exome_ancestry_group_once(
    recorded: dict[str, list[Any]],
) -> None:
    """BRCA1 c.181T>G, exome cohort: 29 population records, 20 of them sex strata.

    Before the correction the strata of every group were listed beside the
    group (27 rows), so the breakdown counted every allele twice.
    """
    by_id = {
        record["id"]: record
        for record in _recorded_variant("17-43106487-A-C")["exome"]["populations"]
    }
    assert len(by_id) == 29
    assert sum(map(_names_a_sex, by_id)) == 20

    population = (await _report(_BRCA1_REVERSE))["population_genetics"]
    rows = {row["population"]: row for row in population["populations"]}

    labels = {
        "afr": "African/African-American",
        "amr": "Admixed American",
        "asj": "Ashkenazi Jewish",
        "eas": "East Asian",
        "fin": "Finnish",
        "mid": "Middle Eastern",
        "nfe": "Non-Finnish European",
        "remaining": "remaining",
        "sas": "South Asian",
    }
    assert len(population["populations"]) == 9
    assert set(rows) == set(labels.values())
    for record_id, label in labels.items():
        # Each listed group carries gnomAD's own counts, unaltered.
        assert rows[label] == {
            "population": label,
            "allele_count": by_id[record_id]["ac"],
            "allele_number": by_id[record_id]["an"],
            "allele_frequency": by_id[record_id]["ac"] / by_id[record_id]["an"],
            "homozygote_count": by_id[record_id]["ac_hom"],
        }
    assert sum(row["allele_count"] for row in rows.values()) == population["global_ac"] == 25
    assert sum(row["allele_number"] for row in rows.values()) == population["global_an"] == 1452604


async def test_genome_only_breakdown_drops_only_sex_strata(
    recorded: dict[str, list[Any]],
) -> None:
    """17-43105117-T-C (rs799912) is held in genomes only: 276 population records.

    186 name a sex or split a record by sex. The other 90 are the ten ancestry
    groups of the genome cohort and 80 populations of the 1000 Genomes and
    HGDP subsets. None of the 90 is removed and each keeps gnomAD's counts.
    """
    variant = _recorded_variant(_GENOME_ONLY)
    assert variant["exome"] is None
    by_id = {record["id"]: record for record in variant["genome"]["populations"]}
    kept = {record_id for record_id in by_id if not _names_a_sex(record_id)}
    assert (len(by_id), len(by_id) - len(kept)) == (276, 186)

    result = await pm._gnomad().variant_frequencies(_GENOME_ONLY)
    assert result["cohort"] == "genome"
    assert list(result["cohorts"]) == ["genome"]

    rows = {row["population"]: row for row in result["populations"]}
    assert len(result["populations"]) == len(rows) == 90
    assert set(rows) == {_POP_LABELS.get(record_id, record_id) for record_id in kept}
    for record_id in kept:
        row = rows[_POP_LABELS.get(record_id, record_id)]
        assert (row["allele_count"], row["allele_number"], row["homozygote_count"]) == (
            by_id[record_id]["ac"],
            by_id[record_id]["an"],
            by_id[record_id]["ac_hom"],
        )

    cohort_level = [record_id for record_id in kept if ":" not in record_id]
    assert sorted(cohort_level) == [
        "afr",
        "ami",
        "amr",
        "asj",
        "eas",
        "fin",
        "mid",
        "nfe",
        "remaining",
        "sas",
    ]
    # The ten cohort-level groups account for every allele of the cohort once.
    assert sum(by_id[record_id]["ac"] for record_id in cohort_level) == result["global_ac"] == 74859
    assert (
        sum(by_id[record_id]["an"] for record_id in cohort_level) == result["global_an"] == 152120
    )
    # Subset populations are named populations and stay, under their own identifiers.
    subsets = [record_id.split(":")[0] for record_id in kept if ":" in record_id]
    assert (subsets.count("1kg"), subsets.count("hgdp")) == (26, 54)


@pytest.mark.parametrize("variant_id", _HELD_VARIANTS)
async def test_recorded_breakdown_sums_to_its_cohort(
    recorded: dict[str, list[Any]], variant_id: str
) -> None:
    """In every recorded response the listed cohort-level groups sum to the cohort."""
    result = await pm._gnomad().variant_frequencies(variant_id)
    cohort_level = [row for row in result["populations"] if ":" not in row["population"]]

    assert len(cohort_level) == (9 if result["cohort"] == "exome" else 10)
    assert sum(row["allele_count"] for row in cohort_level) == result["global_ac"]
    assert sum(row["allele_number"] for row in cohort_level) == result["global_an"]


# ---------------------------------------------------------------------------
# Cohort allele count, allele number and frequency must agree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant_id", _HELD_VARIANTS)
async def test_recorded_cohort_frequency_is_count_over_number(
    recorded: dict[str, list[Any]], variant_id: str
) -> None:
    """Every recorded cohort reports AF = AC / AN exactly, so the rule rejects no real record."""
    variant = _recorded_variant(variant_id)
    result = await pm._gnomad().variant_frequencies(variant_id)

    assert set(result["cohorts"]) == {name for name in ("exome", "genome") if variant[name]}
    for name, cohort in result["cohorts"].items():
        source = variant[name]
        assert source["af"] == source["ac"] / source["an"]
        assert cohort["allele_count"] == source["ac"]
        assert cohort["allele_number"] == source["an"]
        assert cohort["allele_frequency"] == source["ac"] / source["an"]


@pytest.mark.parametrize(
    ("cohort", "changes"),
    [
        ("exome", {"af": 0.5}),
        ("exome", {"af": 1.7e-05}),
        ("exome", {"ac": 0}),
        ("exome", {"af": 0}),
        ("exome", {"ac": 0, "an": 0}),
        ("exome", {"ac": None, "af": 1.7e-05}),
        ("genome", {"af": 0.5}),
    ],
    ids=[
        "frequency_of_other_counts",
        "rounded_frequency",
        "no_carrier_but_positive_frequency",
        "carriers_but_zero_frequency",
        "frequency_without_sampled_alleles",
        "not_a_whole_number_of_alleles",
        "second_cohort",
    ],
)
async def test_synthetic_contradictory_cohort_values_are_a_failure(
    recorded: dict[str, list[Any]],
    respx_mock: respx.MockRouter,
    cohort: str,
    changes: dict[str, Any],
) -> None:
    """Synthetic: one value of the recorded BRCA1 c.181T>G record is altered.

    AC, AN and AF that cannot belong together are an upstream failure. They are
    neither a frequency, nor a measured zero, nor an absent variant.
    """
    body = json.loads(json.dumps(_RESPONSES["gnomad_variant"]["17-43106487-A-C"]["body"]))
    body["data"]["variant"][cohort].update(changes)

    def gnomad(request: httpx.Request) -> httpx.Response:
        variables = json.loads(request.content)["variables"]
        if "variantId" in variables:
            return httpx.Response(200, json=body)
        return httpx.Response(
            200, json=_RESPONSES["gnomad_constraint"][variables["geneSymbol"]]["body"]
        )

    respx_mock.post(_GNOMAD_URL).mock(side_effect=gnomad)
    report = await _report(_BRCA1_REVERSE)
    population = report["population_genetics"]
    frequency = report["unassessed_evidence"]["population_frequency"]

    assert report["data_sources_status"]["gnomad"] == "failed"
    assert report["data_sources_status"]["gnomad_constraint"] == "ok"
    assert frequency["lookup_status"] == "failed"
    assert frequency["variant_id"] == "17-43106487-A-C"
    assert frequency["cohorts"] == {}
    assert (population["global_ac"], population["global_an"], population["global_af"]) == (
        None,
        None,
        None,
    )
    assert population["populations"] == []
    assert frequency["acmg_criteria"] == _NOT_ASSESSED_FREQUENCY


async def test_synthetic_exome_without_frequency_does_not_hide_genome_frequency(
    recorded: dict[str, list[Any]], respx_mock: respx.MockRouter
) -> None:
    """Synthetic: the recorded BRCA1 c.181T>G record with an exome cohort of AN 0.

    The exome-first summary then has no frequency, but the genome cohort has
    one. The lookup is ``found``; it is not ``no_frequency_data``.
    """
    body = json.loads(json.dumps(_RESPONSES["gnomad_variant"]["17-43106487-A-C"]["body"]))
    body["data"]["variant"]["exome"].update({"ac": 0, "an": 0, "af": None})

    def gnomad(request: httpx.Request) -> httpx.Response:
        variables = json.loads(request.content)["variables"]
        if "variantId" in variables:
            return httpx.Response(200, json=body)
        return httpx.Response(
            200, json=_RESPONSES["gnomad_constraint"][variables["geneSymbol"]]["body"]
        )

    respx_mock.post(_GNOMAD_URL).mock(side_effect=gnomad)
    report = await _report(_BRCA1_REVERSE)
    population = report["population_genetics"]
    frequency = report["unassessed_evidence"]["population_frequency"]

    assert report["data_sources_status"]["gnomad"] == "ok"
    assert frequency["lookup_status"] == "found"
    assert frequency["cohorts"]["exome"]["allele_frequency"] is None
    assert frequency["cohorts"]["genome"]["allele_frequency"] == pytest.approx(5 / 152214)
    # The summary keeps its meaning: the exome cohort, which has no frequency here.
    assert (population["cohort"], population["global_an"], population["global_af"]) == (
        "exome",
        0,
        None,
    )


# ---------------------------------------------------------------------------
# Homozygote counts must be possible for their allele counts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant_id", _HELD_VARIANTS)
async def test_recorded_homozygote_counts_fit_their_allele_counts(
    recorded: dict[str, list[Any]], variant_id: str
) -> None:
    """Every recorded count is one of diploid homozygotes, so the rule rejects no real record."""
    variant = _recorded_variant(variant_id)
    result = await pm._gnomad().variant_frequencies(variant_id)

    assert variant_id.partition("-")[0].isdigit()  # every recorded variant is autosomal
    for name, cohort in result["cohorts"].items():
        source = variant[name]
        assert cohort["homozygote_count"] == source["ac_hom"]
        for record in (source, *source["populations"]):
            assert type(record["ac_hom"]) is int
            assert 0 <= 2 * record["ac_hom"] <= record["ac"]
    assert result["homozygote_count"] == variant[result["cohort"]]["ac_hom"]


@pytest.mark.parametrize(
    ("where", "value"),
    [
        ("genome", -1),
        ("exome", True),
        ("exome", 26),
        ("exome", 13),
        ("nfe", 2.5),
        ("nfe", 12),
    ],
    ids=[
        "negative_in_second_cohort",
        "boolean",
        "more_homozygotes_than_alleles",
        "more_than_half_the_alleles_on_an_autosome",
        "population_not_a_whole_number",
        "population_more_than_half_its_alleles",
    ],
)
async def test_synthetic_impossible_homozygote_count_is_a_failure(
    recorded: dict[str, list[Any]],
    respx_mock: respx.MockRouter,
    where: str,
    value: Any,
) -> None:
    """Synthetic: one homozygote count of the recorded BRCA1 c.181T>G record is altered.

    The record has 25 exome alleles, 23 of them in ``nfe``, on chromosome 17,
    where every genotype is diploid. A count that is not a non-negative whole
    number, or that needs more alleles than were counted, is an upstream
    failure. It is not passed on as population evidence.
    """
    body = json.loads(json.dumps(_RESPONSES["gnomad_variant"]["17-43106487-A-C"]["body"]))
    variant = body["data"]["variant"]
    assert (variant["exome"]["ac"], variant["exome"]["ac_hom"]) == (25, 0)
    if where == "nfe":
        (record,) = [p for p in variant["exome"]["populations"] if p["id"] == "nfe"]
        assert record["ac"] == 23
    else:
        record = variant[where]
    record["ac_hom"] = value

    def gnomad(request: httpx.Request) -> httpx.Response:
        variables = json.loads(request.content)["variables"]
        if "variantId" in variables:
            return httpx.Response(200, json=body)
        return httpx.Response(
            200, json=_RESPONSES["gnomad_constraint"][variables["geneSymbol"]]["body"]
        )

    respx_mock.post(_GNOMAD_URL).mock(side_effect=gnomad)
    report = await _report(_BRCA1_REVERSE)
    acmg = await _classify(_BRCA1_REVERSE)
    population = report["population_genetics"]
    frequency = report["unassessed_evidence"]["population_frequency"]

    assert report["data_sources_status"]["gnomad"] == "failed"
    assert acmg["data_sources_status"]["gnomad_variant"] == "failed"
    assert frequency["lookup_status"] == "failed"
    assert frequency["variant_id"] == "17-43106487-A-C"
    assert frequency["cohorts"] == {}
    assert acmg["unassessed_evidence"]["population_frequency"]["cohorts"] == {}
    assert population["homozygote_count"] is None
    assert population["populations"] == []


# ---------------------------------------------------------------------------
# A VEP hit without transcript consequences
# ---------------------------------------------------------------------------

_INTERGENIC = "NC_000005.10:g.25500000T>C"
# Recorded 2026-11-10 17:35 UTC with the clients' own requests: the complete
# Ensembl VEP reply for this intergenic expression, which has no
# ``transcript_consequences``, and gnomAD's reply for the variant ID it maps to.
_INTERGENIC_VEP_BODY: list[dict[str, Any]] = [
    {
        "input": _INTERGENIC,
        "id": _INTERGENIC,
        "assembly_name": "GRCh38",
        "seq_region_name": "5",
        "start": 25500000,
        "end": 25500000,
        "strand": 1,
        "allele_string": "T/C",
        "vcf_string": "5-25500000-T-C",
        "most_severe_consequence": "intergenic_variant",
        "intergenic_consequences": [
            {
                "consequence_terms": ["intergenic_variant"],
                "impact": "MODIFIER",
                "variant_allele": "C",
            }
        ],
    }
]
_INTERGENIC_GNOMAD_BODY = {"errors": [{"message": "Variant not found"}], "data": {"variant": None}}


async def test_recorded_intergenic_expression_is_looked_up(
    recorded: dict[str, list[Any]], respx_mock: respx.MockRouter
) -> None:
    """The locus of a hit without transcript consequences reaches the gnomAD lookup."""
    asked: list[dict[str, Any]] = []

    def gnomad(request: httpx.Request) -> httpx.Response:
        asked.append(json.loads(request.content)["variables"])
        return httpx.Response(200, json=_INTERGENIC_GNOMAD_BODY)

    respx_mock.get(url__startswith=_VEP_PREFIX).mock(
        side_effect=lambda request: httpx.Response(200, json=_INTERGENIC_VEP_BODY)
    )
    respx_mock.post(_GNOMAD_URL).mock(side_effect=gnomad)

    rows = await pm._ensembl().vep_hgvs(_INTERGENIC)
    assert [(row["transcript_id"], row["canonical"]) for row in rows] == [("", False)]
    assert rows[0]["locus"]["vcf_string"] == "5-25500000-T-C"

    out = await _classify(_INTERGENIC)
    frequency = out["unassessed_evidence"]["population_frequency"]
    assert out["data_sources_status"]["ensembl_vep"] == "ok"
    assert out["data_sources_status"]["gnomad_variant"] == "no_data"
    assert asked == [{"variantId": "5-25500000-T-C", "datasetId": "gnomad_r4"}]
    assert frequency["variant_id"] == "5-25500000-T-C"
    assert frequency["mapping_basis"] == "versioned_hgvs_via_ensembl_vep"
    assert frequency["lookup_status"] == "not_found"


async def test_recorded_intergenic_consequence_is_reported_without_a_transcript(
    recorded: dict[str, list[Any]], respx_mock: respx.MockRouter
) -> None:
    """The terms and impact VEP reports as intergenic are the functional consequence.

    No transcript is named, no transcript-level field is filled in, and no
    criterion or prediction follows from them.
    """
    respx_mock.get(url__startswith=_VEP_PREFIX).mock(
        return_value=httpx.Response(200, json=_INTERGENIC_VEP_BODY)
    )
    respx_mock.post(_GNOMAD_URL).mock(
        return_value=httpx.Response(200, json=_INTERGENIC_GNOMAD_BODY)
    )

    rows = await pm._ensembl().vep_hgvs(_INTERGENIC)
    assert [
        (
            row["consequence_source"],
            row["consequence_terms"],
            row["impact"],
            row["transcript_id"],
            row["gene_symbol"],
            row["canonical"],
        )
        for row in rows
    ] == [("intergenic_consequences", ["intergenic_variant"], "MODIFIER", "", "", False)]

    report = await _report(_INTERGENIC)
    assert report["functional_consequence"] == {
        "consequence_terms": ["intergenic_variant"],
        "impact": "MODIFIER",
        "amino_acids": "",
        "hgvsp": "",
        "sift_prediction": "",
        "sift_score": None,
        "polyphen_prediction": "",
        "polyphen_score": None,
        "cadd_phred": None,
    }
    assert report["gene_symbol"] is None
    assert report["acmg_criteria_draft"]["criteria"] == {}
    assert report["data_sources_status"]["alphamissense"] == "skipped_no_canonical"
    predictions = report["unassessed_evidence"]["computational_predictions"]
    assert predictions["ensembl_vep"]["transcript_id"] is None
    assert predictions["acmg_criteria"] == _NOT_ASSESSED_PREDICTION

    acmg = await _classify(_INTERGENIC)
    assert acmg["candidate_criteria"] == {}
    assert acmg["criteria_met"] == {}
    acmg_predictions = acmg["unassessed_evidence"]["computational_predictions"]
    assert acmg_predictions["ensembl_vep"] == predictions["ensembl_vep"]


# ---------------------------------------------------------------------------
# A variant ID supplied by the caller
# ---------------------------------------------------------------------------

_CALLER_ID = "17-43106487-A-C"
# Recorded 2026-11-10 21:08 UTC with the client's own request: Ensembl VEP's
# complete HTTP 400 reply to this identifier, which is not an HGVS expression.
_CALLER_ID_VEP_ERROR = {
    "error": (
        "Unable to parse HGVS notation '17-43106487-A-C': "
        "Could not parse the HGVS notation 17-43106487-A-C"
    )
}


async def test_recorded_caller_supplied_variant_id_is_looked_up_without_vep(
    recorded: dict[str, list[Any]], respx_mock: respx.MockRouter
) -> None:
    """A gnomAD-style ID is looked up as supplied; it does not rest on a VEP reply."""
    respx_mock.get(url__startswith=_VEP_PREFIX).mock(
        return_value=httpx.Response(400, json=_CALLER_ID_VEP_ERROR)
    )

    report = await _report(_CALLER_ID)
    acmg = await _classify(_CALLER_ID)

    assert recorded["gnomad_variant"] == [{"variantId": _CALLER_ID, "datasetId": "gnomad_r4"}] * 2
    for out, gnomad_key in ((report, "gnomad"), (acmg, "gnomad_variant")):
        assert out["data_sources_status"]["ensembl_vep"] == "failed"
        assert out["data_sources_status"][gnomad_key] == "ok"
        frequency = out["unassessed_evidence"]["population_frequency"]
        assert frequency["variant_id"] == _CALLER_ID
        assert frequency["mapping_basis"] == "caller_supplied_variant_id"
        assert frequency["reference_genome"] is None
        assert frequency["lookup_status"] == "found"
        assert frequency["cohorts"]["exome"]["allele_count"] == 25
        assert "supplied by the caller" in frequency["detail"]
