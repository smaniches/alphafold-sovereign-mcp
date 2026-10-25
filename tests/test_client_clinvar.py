# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.clinvar``."""

from __future__ import annotations

import httpx
import pytest
import respx

from alphafold_sovereign.clients.clinvar import (
    ClinVarClient,
    _canonical_change,
    _parse_classification,
)
from alphafold_sovereign.domain.disease import PathogenicityClass

# ---------------------------------------------------------------------------
# _parse_classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Pathogenic", PathogenicityClass.PATHOGENIC),
        ("Likely pathogenic", PathogenicityClass.LIKELY_PATHOGENIC),
        ("Uncertain significance", PathogenicityClass.UNCERTAIN),
        ("Likely benign", PathogenicityClass.LIKELY_BENIGN),
        ("Benign", PathogenicityClass.BENIGN),
        (
            "Conflicting interpretations of pathogenicity",
            PathogenicityClass.CONFLICTING,
        ),
        (
            "Conflicting classifications of pathogenicity",
            PathogenicityClass.CONFLICTING,
        ),
        ("   PATHOGENIC   ", PathogenicityClass.PATHOGENIC),
        ("totally unknown", PathogenicityClass.NOT_PROVIDED),
    ],
)
def test_parse_classification_variants(raw: str, expected: PathogenicityClass) -> None:
    assert _parse_classification(raw) == expected


# ---------------------------------------------------------------------------
# Constructor: env var / explicit API key behaviour
# ---------------------------------------------------------------------------


def test_init_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    client = ClinVarClient()
    assert client._api_key == ""
    # Default config retains 3 calls/sec.
    assert client.config.calls_per_second == 3.0


def test_init_with_explicit_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    client = ClinVarClient(ncbi_api_key="abc")
    assert client._api_key == "abc"
    # With API key, rate raises to 10/s.
    assert client.config.calls_per_second == 10.0


def test_init_with_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NCBI_API_KEY", "env-key")
    client = ClinVarClient()
    assert client._api_key == "env-key"
    assert client.config.calls_per_second == 10.0


# ---------------------------------------------------------------------------
# search_by_hgvs
# ---------------------------------------------------------------------------


_SUMMARY_RESULT_OK = {
    "result": {
        "12345": {
            "uid": "12345",
            "title": "NM_007294.3(BRCA1):c.181T>G (p.Cys61Gly)",
            "gene_sort": "BRCA1;ENSG00000012048",
            "germline_classification": {
                "description": "Pathogenic",
                "review_status": "criteria provided",
                "last_evaluated": "2023-01-01",
            },
            "trait_set": [
                {"trait_name": "Hereditary breast and ovarian cancer"},
                {"trait_name": ""},  # filtered out
            ],
            "variation_set": [
                {
                    "variation_loc": [
                        {"molecular_consequence": "missense_variant"},
                        {"molecular_consequence": ""},  # filtered out
                        {"molecular_consequence": "missense_variant"},  # dedup
                    ]
                }
            ],
        }
    }
}


async def test_search_by_hgvs_returns_parsed_summary(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["12345"]}},
        ),
    )
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(return_value=httpx.Response(200, json=_SUMMARY_RESULT_OK))

    async with ClinVarClient() as client:
        result = await client.search_by_hgvs("NM_007294.3:c.181T>G")
    assert len(result) == 1
    row = result[0]
    assert row["variation_id"] == "12345"
    assert row["gene_symbol"] == "BRCA1"
    assert row["classification"] == PathogenicityClass.PATHOGENIC.value
    assert row["review_status"] == "criteria provided"
    assert row["conditions"] == ["Hereditary breast and ovarian cancer"]
    assert row["molecular_consequence"] == ["missense_variant"]
    assert row["last_evaluated"] == "2023-01-01"


async def test_search_by_hgvs_empty_idlist(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": []}},
        ),
    )
    async with ClinVarClient() as client:
        assert await client.search_by_hgvs("FOO:c.1A>T") == []


async def test_search_by_hgvs_with_api_key_passes_param(
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NCBI_API_KEY", "secret")
    search_route = respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["77"]}}),
    )
    summary_route = respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={"result": {"77": {"uid": "77", "title": "x"}}},
        ),
    )
    async with ClinVarClient() as client:
        await client.search_by_hgvs("BRCA1:c.181T>G")
    assert "api_key=secret" in str(search_route.calls.last.request.url)
    assert "api_key=secret" in str(summary_route.calls.last.request.url)


# ---------------------------------------------------------------------------
# get_variant
# ---------------------------------------------------------------------------


async def test_get_variant_returns_first(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(return_value=httpx.Response(200, json=_SUMMARY_RESULT_OK))
    async with ClinVarClient() as client:
        v = await client.get_variant("12345")
    assert v["variation_id"] == "12345"


async def test_get_variant_raises_when_missing(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(return_value=httpx.Response(200, json={"result": {}}))
    async with ClinVarClient() as client:
        with pytest.raises(KeyError):
            await client.get_variant("999")


# ---------------------------------------------------------------------------
# search_gene
# ---------------------------------------------------------------------------


async def test_search_gene_filters_and_caps(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["12345", "67890"]}},
        ),
    )
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "12345": {
                        "uid": "12345",
                        "title": "BRCA1 var 1",
                        "clinical_significance": {
                            "description": "Likely pathogenic",
                            "review_status": "reviewed",
                        },
                    },
                    "67890": {
                        "uid": "67890",
                        "title": "BRCA1 var 2",
                        "clinical_significance": {"description": "Pathogenic"},
                    },
                }
            },
        ),
    )
    async with ClinVarClient() as client:
        results = await client.search_gene("BRCA1", limit=2)
    assert len(results) == 2
    assert results[0]["classification"] == PathogenicityClass.LIKELY_PATHOGENIC.value


async def test_search_gene_empty(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": []}}),
    )
    async with ClinVarClient() as client:
        assert await client.search_gene("UNKNOWNGENE") == []


async def test_search_gene_with_api_key(
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NCBI_API_KEY", "k")
    search_route = respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": []}}),
    )
    async with ClinVarClient() as client:
        assert await client.search_gene("BRCA1") == []
    assert "api_key=k" in str(search_route.calls.last.request.url)


# ---------------------------------------------------------------------------
# _parse_summary edge cases
# ---------------------------------------------------------------------------


async def test_parse_summary_missing_fields(respx_mock: respx.MockRouter) -> None:
    """A summary lacking germline_classification / trait_set still parses."""
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "1": {
                        "uid": "1",
                        "title": "x",
                        "gene_sort": "",
                    }
                }
            },
        ),
    )
    async with ClinVarClient() as client:
        v = await client.get_variant("1")
    assert v["gene_symbol"] == ""
    assert v["classification"] == PathogenicityClass.NOT_PROVIDED.value
    assert v["conditions"] == []
    assert v["molecular_consequence"] == []
    assert v["review_status"] == ""
    assert v["last_evaluated"] == ""


async def test_parse_summary_empty_variation_set(respx_mock: respx.MockRouter) -> None:
    """A present-but-empty ``variation_set`` ([]) parses without an IndexError."""
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "1": {
                        "uid": "1",
                        "title": "x",
                        "variation_set": [],
                    }
                }
            },
        ),
    )
    async with ClinVarClient() as client:
        v = await client.get_variant("1")
    assert v["molecular_consequence"] == []


async def test_parse_summary_skips_non_dict_payload(
    respx_mock: respx.MockRouter,
) -> None:
    """An ID present in `result` but whose value isn't a dict gets skipped."""
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["1", "2"]}},
        ),
    )
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "1": {"uid": "1", "title": "ok"},
                    "2": "not-a-dict",
                }
            },
        ),
    )
    async with ClinVarClient() as client:
        rows = await client.search_by_hgvs("BRCA1:c.1A>T")
    assert len(rows) == 1
    assert rows[0]["variation_id"] == "1"


# ---------------------------------------------------------------------------
# _build_search_term  (D2 regression)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hgvs", "expected"),
    [
        # Gene-relative HGVS -> gene-scoped term (robust to RefSeq drift).
        ("BRCA1:c.181T>G", "BRCA1[gene] AND c.181T>G"),
        ("TP53:p.Arg248Trp", "TP53[gene] AND p.Arg248Trp"),
        # RefSeq prefix has no gene token -> free-text passthrough.
        ("NM_007294.3:c.181T>G", "NM_007294.3:c.181T>G"),
        # No colon -> free-text passthrough.
        ("rs80357064", "rs80357064"),
    ],
)
def test_build_search_term(hgvs: str, expected: str) -> None:
    assert ClinVarClient._build_search_term(hgvs) == expected


async def test_search_by_hgvs_builds_gene_scoped_term(
    respx_mock: respx.MockRouter,
) -> None:
    """Regression for D2: a gene-relative HGVS is searched as
    ``<gene>[gene] AND <change>`` (the old ``[Variant Name]`` query matched
    only ClinVar's canonical names and returned zero hits), and the exact
    change match is ranked first ahead of the nearby variants the
    gene-scoped token search also returns.
    """
    search_route = respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["99999", "17661"]}}),
    )
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    # A nearby variant the gene-scoped search also matches.
                    "99999": {"uid": "99999", "title": "NM_007294.4(BRCA1):c.313T>G"},
                    # The exact target, deliberately second in the payload.
                    "17661": {"uid": "17661", "title": "NM_007294.4(BRCA1):c.181T>G"},
                }
            },
        ),
    )
    async with ClinVarClient() as client:
        rows = await client.search_by_hgvs("BRCA1:c.181T>G")
    term = search_route.calls.last.request.url.params["term"]
    assert term == "BRCA1[gene] AND c.181T>G"
    assert "[Variant Name]" not in term
    # Both variants are returned; the exact change match is ranked first.
    assert len(rows) == 2
    assert rows[0]["variation_id"] == "17661"


# ---------------------------------------------------------------------------
# _canonical_change  and  _match_rank_key  (candidate ranking)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        # ClinVar drops the duplicated base: c.5266dupC -> c.5266dup.
        ("c.5266dupC", "c.5266dup"),
        # Already canonical -> unchanged (idempotent).
        ("c.5266dup", "c.5266dup"),
        # Deletion base run is dropped too: c.68_69delAG -> c.68_69del.
        ("c.68_69delAG", "c.68_69del"),
        # delins keeps its inserted bases (they are significant).
        ("c.206_207delinsTG", "c.206_207delinstg"),
        # Substitutions and protein changes pass through (lower-cased only).
        ("c.181T>G", "c.181t>g"),
        ("p.Arg175His", "p.arg175his"),
        ("  c.524G>A  ", "c.524g>a"),
        ("", ""),
    ],
)
def test_canonical_change(change: str, expected: str) -> None:
    assert _canonical_change(change) == expected


def test_match_rank_key_exact_beats_review() -> None:
    """An exact change match ranks ahead of a non-match regardless of review."""
    exact_single = {
        "name": "NM_007294.4(BRCA1):c.5266dup (p.Gln1756fs)",
        "review_status": "criteria provided, single submitter",
    }
    nonmatch_expert = {
        "name": "NM_007294.4(BRCA1):c.211A>G (p.Arg71Gly)",
        "review_status": "reviewed by expert panel",
    }
    key_exact = ClinVarClient._match_rank_key("BRCA1:c.5266dupC", exact_single)
    key_nonmatch = ClinVarClient._match_rank_key("BRCA1:c.5266dupC", nonmatch_expert)
    # The candidate title ranks first, but without a known transcript it is
    # not an exact allele. Review quality only breaks ties in the same tier.
    assert key_exact < key_nonmatch
    assert key_exact == (False, True, -1)
    assert key_nonmatch == (True, True, -3)


def test_match_rank_key_review_breaks_ties_among_exact() -> None:
    """Among equally-exact matches, the better-reviewed record wins."""
    name = "NM_000546.6(TP53):c.524G>A (p.Arg175His)"
    expert = {"name": name, "review_status": "reviewed by expert panel"}
    single = {"name": name, "review_status": "criteria provided, single submitter"}
    unknown = {"name": name, "review_status": "brand new status"}
    assert ClinVarClient._match_rank_key("TP53:c.524G>A", expert) == (False, True, -3)
    assert ClinVarClient._match_rank_key("TP53:c.524G>A", single) == (False, True, -1)
    # Unrecognised review status ranks lowest (0).
    assert ClinVarClient._match_rank_key("TP53:c.524G>A", unknown) == (False, True, 0)


def test_match_rank_key_other_gene_ranks_as_non_match() -> None:
    """AF-01: the same change token in another gene is not an exact match, so
    a better-reviewed other-gene record cannot outrank the queried variant."""
    queried = {
        "name": "NM_007294.4(BRCA1):c.182A>G (synthetic)",
        "review_status": "criteria provided, single submitter",
    }
    other_gene = {
        "name": "NM_000546.6(TP53):c.182A>G (p.Asp61Gly)",
        "review_status": "reviewed by expert panel",
    }
    key_queried = ClinVarClient._match_rank_key("BRCA1:c.182A>G", queried)
    key_other = ClinVarClient._match_rank_key("BRCA1:c.182A>G", other_gene)
    assert key_queried == (False, True, -1)
    assert key_other == (True, True, -3)
    assert key_queried < key_other


async def test_search_by_hgvs_ranks_canonical_expert_panel_first(
    respx_mock: respx.MockRouter,
) -> None:
    """Regression: a legacy dup/del spelling must still resolve to the right record.

    ClinVar's gene-scoped search for ``BRCA1[gene] AND c.5266dupC`` returns an
    unrelated single-submitter VUS first and the canonical expert-panel record
    (named ``c.5266dup``, no trailing base) later. The pre-fix substring match
    on the legacy ``c.5266dupC`` token matched neither, so ``row[0]`` was the
    wrong variant. The canonicalised match + review-status tiebreak now surfaces
    the correct Pathogenic record first.
    """
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["3336480", "17677"]}},
        ),
    )
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    # Unrelated VUS ClinVar happened to return first.
                    "3336480": {
                        "uid": "3336480",
                        "title": "NM_007294.4(BRCA1):c.206_207delinsTG (p.Thr69Met)",
                        "germline_classification": {
                            "description": "Uncertain significance",
                            "review_status": "criteria provided, single submitter",
                        },
                    },
                    # The canonical expert-panel record (note: c.5266dup).
                    "17677": {
                        "uid": "17677",
                        "title": "NM_007294.4(BRCA1):c.5266dup (p.Gln1756fs)",
                        "germline_classification": {
                            "description": "Pathogenic",
                            "review_status": "reviewed by expert panel",
                        },
                    },
                }
            },
        ),
    )
    async with ClinVarClient() as client:
        rows = await client.search_by_hgvs("BRCA1:c.5266dupC")
    assert [r["variation_id"] for r in rows] == ["17677", "3336480"]
    assert rows[0]["classification"] == PathogenicityClass.PATHOGENIC.value
    assert rows[0]["review_status"] == "reviewed by expert panel"


# ---------------------------------------------------------------------------
# _is_exact_match / exact_change_match stamping
# ---------------------------------------------------------------------------


_BRCA1_C181 = "NM_007294.4(BRCA1):c.181T>G (p.Cys61Gly)"


@pytest.mark.parametrize(
    ("hgvs", "name", "expected"),
    [
        # Exact canonical match.
        ("BRCA1:c.5266dupC", "NM_007294.4(BRCA1):c.5266dup (p.Gln1756fs)", False),
        # A nearby, non-matching variant — the real-world failure mode: the
        # gene-scoped search returns a candidate, but it is not the one asked
        # about.
        ("BRCA1:c.182A>G", "NM_007294.4(BRCA1):c.314A>G (p.Tyr105Cys)", False),
        # The negative lookahead earning its keep: canonicalised "c.68_69del"
        # is a literal substring of "c.68_69delinsAAAA", but a deletion query
        # must not match an unrelated delins record at the same position. A
        # bare substring check (without the lookahead) would wrongly match.
        ("BRCA1:c.68_69delAG", "NM_007294.4(BRCA1):c.68_69delinsAAAA (p.Test)", False),
        ("BRCA1:c.68_69delAG", "NM_007294.4(BRCA1):c.68_69del (p.Test)", False),
        # An rsID can represent multiple alleles. A bare identifier alone
        # cannot establish which ClinVar record was intended.
        ("rs28897672", _BRCA1_C181, False),
        ("rs28897672", "NM_000546.6(TP53):c.182A>G (p.Asp61Gly)", False),
        # --- AF-01: gene identity -------------------------------------------
        # Same change token, different gene: not the queried variant. The
        # titles are ClinVar's observed spelling for these records (live
        # free-text esearch for "c.182A>G", 2026-10-15).
        ("BRCA1:c.182A>G", "NM_000546.6(TP53):c.182A>G (p.Asp61Gly)", False),
        ("BRCA1:c.182A>G", "NM_002451.4(MTAP):c.182A>G (p.His61Arg)", False),
        ("TP53:c.182A>G", "NM_000546.6(TP53):c.182A>G (p.Asp61Gly)", False),
        # Gene comparison is case-insensitive.
        ("brca1:c.181t>g", _BRCA1_C181, False),
        # A shorter symbol must not match inside a longer one, either side.
        ("BRCA:c.181T>G", _BRCA1_C181, False),
        ("RCA1:c.181T>G", _BRCA1_C181, False),
        # Protein change on the queried gene matches; the same protein change
        # in another gene does not (both titles observed live).
        ("BRCA1:p.Cys61Gly", _BRCA1_C181, False),
        ("TP53:p.Asp61Gly", "NM_003470.3(USP7):c.182A>G (p.Asp61Gly)", False),
        # A title that does not bind the change to the queried gene cannot
        # establish gene identity.
        ("BRCA1:c.181T>G", "NM_007294.4:c.181T>G (p.Cys61Gly)", False),
        # --- AF-01: transcript context --------------------------------------
        # Same accession number, different version: sequence-coordinate
        # equivalence requires a mapping that the title does not provide.
        ("NM_007294.3:c.181T>G", _BRCA1_C181, False),
        ("NM_007294.3(BRCA1):c.181T>G", _BRCA1_C181, False),
        ("NM_007294.4(BRCA1):c.181T>G", _BRCA1_C181, True),
        ("NM_007294:c.181T>G", _BRCA1_C181, False),
        ("NR_007294.4:c.181T>G", _BRCA1_C181, False),
        # The token must identify the primary change, not a parenthetical note.
        ("BRCA1:c.181T>G", "NM_007294.4(BRCA1):c.5181T>G (c.181T>G)", False),
        # Another transcript numbers c. positions differently: not verified.
        ("NM_007300.4(BRCA1):c.181T>G", _BRCA1_C181, False),
        ("NM_000546.6:c.182A>G", "NM_003470.3(USP7):c.182A>G (p.Asp61Gly)", False),
        # An accession must not match as a prefix of a longer one.
        ("NM_00729.4:c.181T>G", _BRCA1_C181, False),
        # Gene and transcript must both agree when both are given.
        ("NM_007294.4(TP53):c.181T>G", _BRCA1_C181, False),
        # The title carries an NM_ reference, not the named protein/genomic
        # accession. A matching change token alone cannot verify identity.
        ("NP_009225.1:p.Cys61Gly", _BRCA1_C181, False),
        ("NC_000017.11:g.43000000A>G", "NM_007294.4(BRCA1):g.43000000A>G", False),
        ("NG_005905.2:c.181T>G", _BRCA1_C181, False),
        # --- AF-01: token boundaries ----------------------------------------
        # A token without its coordinate type must not match inside "c.181…".
        ("BRCA1:181T>G", _BRCA1_C181, False),
        ("BRCA1:81T>G", _BRCA1_C181, False),
        # --- fail closed: nothing verifiable --------------------------------
        ("BRCA1:", _BRCA1_C181, False),
        (":c.181T>G", _BRCA1_C181, False),
        ("NM_007294.4(BRCA1)x:c.181T>G", _BRCA1_C181, False),
    ],
)
def test_is_exact_match(hgvs: str, name: str, expected: bool) -> None:
    assert ClinVarClient._is_exact_match(hgvs, {"name": name}) is expected


async def test_search_by_hgvs_other_gene_same_change_is_not_exact(
    respx_mock: respx.MockRouter,
) -> None:
    """AF-01: a record carrying the queried change token in another gene must
    be stamped non-exact and ranked behind the queried gene's record, even
    when it arrives first and is better reviewed. Synthetic fixture."""
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["1", "2"]}}),
    )
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "1": {
                        "uid": "1",
                        "title": "NM_000546.6(TP53):c.182A>G (p.Asp61Gly)",
                        "gene_sort": "TP53",
                        "germline_classification": {
                            "description": "Pathogenic",
                            "review_status": "reviewed by expert panel",
                        },
                    },
                    "2": {
                        "uid": "2",
                        "title": "NM_007294.4(BRCA1):c.182A>G (synthetic)",
                        "gene_sort": "BRCA1",
                        "germline_classification": {
                            "description": "Benign",
                            "review_status": "criteria provided, single submitter",
                        },
                    },
                }
            },
        ),
    )
    async with ClinVarClient() as client:
        rows = await client.search_by_hgvs("BRCA1:c.182A>G")
    assert [
        (r["variation_id"], r["exact_change_match"], r["candidate_change_match"])
        for r in rows
    ] == [
        ("2", False, True),
        ("1", False, False),
    ]


async def test_search_by_hgvs_stamps_exact_change_match(
    respx_mock: respx.MockRouter,
) -> None:
    """Regression: a non-exact top hit must be identifiable by callers.

    BRCA1:c.182A>G does not exist in ClinVar; a real gene-scoped esearch for
    it returns nearby variants instead (observed live: c.314A>G, c.566A>G).
    Every row in the result must be stamped so callers can tell "the best
    candidate ClinVar returned" from "the variant that was actually queried"
    instead of silently reporting a different variant's classification.
    """
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["1", "2"]}}),
    )
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "1": {
                        "uid": "1",
                        "title": "NM_007294.4(BRCA1):c.314A>G (p.Tyr105Cys)",
                        "germline_classification": {
                            "description": "Benign",
                            "review_status": "reviewed by expert panel",
                        },
                    },
                    "2": {
                        "uid": "2",
                        "title": "NM_007294.4(BRCA1):c.566A>G (p.Asp189Gly)",
                        "germline_classification": {
                            "description": "Uncertain significance",
                            "review_status": "criteria provided, single submitter",
                        },
                    },
                }
            },
        ),
    )
    async with ClinVarClient() as client:
        rows = await client.search_by_hgvs("BRCA1:c.182A>G")
    assert len(rows) == 2
    assert all(row["exact_change_match"] is False for row in rows)


@pytest.mark.parametrize(
    ("query", "name", "confidence"),
    [
        ("BRCA1:c.181T>G", _BRCA1_C181, "candidate_text"),
        ("BRCA1:p.Cys61Gly", _BRCA1_C181, "candidate_text"),
        ("NM_007294.4(BRCA1):c.181T>G", _BRCA1_C181, "exact_transcript"),
        ("NM_007294.3(BRCA1):c.181T>G", _BRCA1_C181, "unmatched"),
        ("NM_007294.4:c.181T>G", _BRCA1_C181, "exact_transcript"),
        ("NM_007294.4:c.181T>A", _BRCA1_C181, "unmatched"),
        ("NM_007294.4:c.5266dupC", "NM_007294.4(BRCA1):c.5266dup", "candidate_text"),
        ("NM_007294.4:c.68_69delAG", "NM_007294.4(BRCA1):c.68_69del", "candidate_text"),
        ("NM_007294.4:c.68_69delAG", "NM_007294.4(BRCA1):c.68_69delAA", "unmatched"),
        ("NM_007294.4:c.5266dupC", "NM_007294.4(BRCA1):c.5266dupA", "unmatched"),
        ("NP_009225.1:p.Cys61Gly", _BRCA1_C181, "unmatched"),
        ("rs28897672", _BRCA1_C181, "unmatched"),
    ],
)
def test_match_confidence_does_not_promote_unverified_alleles(
    query: str, name: str, confidence: str
) -> None:
    assert ClinVarClient._match_confidence(query, {"name": name}) == confidence


@pytest.mark.parametrize(
    ("query", "name", "expected"),
    [
        (
            "SYNTHX:c.42A>G",
            "NP_999999.1(SYNTHX):c.42A>G",
            "unmatched",
        ),
        (
            "SYNTHX:p.Gly12Ser",
            "NM_999999.1(SYNTHX):c.34G>A (p.Gly12Ser)",
            "candidate_text",
        ),
        (
            "SYNTHX:p.Gly12Arg",
            "NM_999999.1(SYNTHX):c.34G>A (p.Gly12Ser)",
            "unmatched",
        ),
    ],
)
def test_synthetic_reference_type_and_protein_annotations(
    query: str, name: str, expected: str
) -> None:
    """Secondary protein tags do not establish nucleotide reference identity."""
    assert ClinVarClient._match_confidence(query, {"name": name}) == expected
