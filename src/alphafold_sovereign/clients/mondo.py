# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""MONDO Disease Ontology async client.

Data sources:
- OLS4 REST API  (EMBL-EBI Ontology Lookup Service v4)  — primary
- Monarch Initiative API                                 — cross-refs + genes

MONDO (Mondo Disease Ontology) is the canonical unified disease ontology
covering OMIM, Orphanet, DOID, ICD-10, ICD-11, MeSH, and more in a single
namespace.  Every disease in this system is identified by a MONDO ID.

Reference:
  Mungall CJ et al. The Monarch Initiative: an integrative data and analytic
  platform connecting phenotypes to genotypes across species.
  Nucleic Acids Res. 2017;45(D1):D712–D722.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig
from alphafold_sovereign.domain.disease import DiseaseRecord, OntologyTerm

logger = structlog.get_logger(__name__)

# ── OLS4 ──────────────────────────────────────────────────────────────────
_OLS4_BASE = "https://www.ebi.ac.uk/ols4/api"
_OLS4_CONFIG = UpstreamConfig(
    base_url=_OLS4_BASE,
    calls_per_second=3.0,
    max_retries=3,
    timeout=20.0,
)

# ── Monarch ────────────────────────────────────────────────────────────────
_MONARCH_BASE = "https://api.monarchinitiative.org/v3"
_MONARCH_CONFIG = UpstreamConfig(
    base_url=_MONARCH_BASE,
    calls_per_second=5.0,
    max_retries=3,
    timeout=20.0,
)

_MONDO_CURIE_RE = re.compile(r"^MONDO:\d{7}$", re.IGNORECASE)
_ICD10_RE = re.compile(r"^ICD10(?:CM)?:([A-Z]\d+(?:\.\d+)?)$", re.IGNORECASE)
_ICD11_RE = re.compile(r"^ICD11:(.+)$", re.IGNORECASE)
_OMIM_RE = re.compile(r"^OMIM:(\d+)$")
_ORPHANET_RE = re.compile(r"^Orphanet:(\d+)$", re.IGNORECASE)
_MESH_RE = re.compile(r"^MeSH:(.+)$", re.IGNORECASE)
_DOID_RE = re.compile(r"^DOID:(\d+)$", re.IGNORECASE)


def _normalise_mondo_id(raw: str) -> str:
    """Accept 'MONDO:0004995' or 'mondo:0004995' or '0004995'; return 'MONDO:0004995'."""
    raw = raw.strip()
    if re.match(r"^\d{7}$", raw):
        return f"MONDO:{raw}"
    return raw.upper().replace("MONDO_", "MONDO:")


def _extract_xrefs(xref_list: list[str]) -> dict[str, list[str]]:
    """Bucket raw xref strings into ICD-10, ICD-11, OMIM, Orphanet, MeSH, DOID."""
    buckets: dict[str, list[str]] = {
        "icd10": [],
        "icd11": [],
        "omim": [],
        "orphanet": [],
        "mesh": [],
        "doid": [],
    }
    for xref in xref_list:
        if m := _ICD10_RE.match(xref):
            buckets["icd10"].append(m.group(1))
        elif m := _ICD11_RE.match(xref):
            buckets["icd11"].append(m.group(1))
        elif m := _OMIM_RE.match(xref):
            buckets["omim"].append(m.group(1))
        elif m := _ORPHANET_RE.match(xref):
            buckets["orphanet"].append(m.group(1))
        elif m := _MESH_RE.match(xref):
            buckets["mesh"].append(m.group(1))
        elif m := _DOID_RE.match(xref):
            buckets["doid"].append(m.group(1))
    return buckets


@dataclass
class MONDOSearchResult:
    mondo_id: str
    label: str
    description: str
    synonyms: list[str]
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "mondo_id": self.mondo_id,
            "label": self.label,
            "description": self.description,
            "synonyms": self.synonyms,
            "score": round(self.score, 4),
        }


class MONDOClient(BaseAsyncClient):
    """
    Async client for MONDO disease ontology via OLS4.

    Provides:
    - Exact MONDO ID lookup → ``DiseaseRecord``
    - Full-text search → list of ``MONDOSearchResult``
    - Ancestor / descendant traversal
    - Cross-reference resolution (ICD-10/11, OMIM, Orphanet → MONDO ID)
    - Gene-disease associations via Monarch
    """

    upstream_name = "mondo_ols4"
    config = _OLS4_CONFIG

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    async def lookup(self, mondo_id: str) -> DiseaseRecord:
        """Fetch a ``DiseaseRecord`` for the given MONDO ID.

        Args:
            mondo_id: MONDO compact URI, e.g. ``'MONDO:0004995'``.

        Returns:
            Populated ``DiseaseRecord`` with all available cross-references.

        Raises:
            UpstreamError: If the OLS4 API returns an error.
            KeyError: If the MONDO ID is not found.
        """
        mondo_id = _normalise_mondo_id(mondo_id)
        # OLS4 wants the short_form, e.g. 'MONDO_0004995'
        short_form = mondo_id.replace(":", "_")
        data = await self._get(
            f"/ontologies/mondo/terms",
            params={"short_form": short_form, "size": 1},
        )

        terms = data.get("_embedded", {}).get("terms", [])
        if not terms:
            raise KeyError(f"MONDO ID not found: {mondo_id}")

        return self._parse_term(terms[0])

    async def lookup_term(self, mondo_id: str) -> OntologyTerm:
        """Lightweight ``OntologyTerm`` (no full xref expansion)."""
        record = await self.lookup(mondo_id)
        return OntologyTerm(
            id=record.mondo_id,
            label=record.name,
            description=record.definition,
            synonyms=record.synonyms,
            xrefs=record.icd10_codes + record.omim_ids + record.orphanet_ids,
            namespace="MONDO",
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        obsolete: bool = False,
    ) -> list[MONDOSearchResult]:
        """Full-text search against the MONDO ontology.

        Args:
            query: Disease name or free text, e.g. ``'breast cancer'``.
            limit: Maximum results to return (1–100).
            obsolete: Include obsolete terms.

        Returns:
            List of ``MONDOSearchResult`` ordered by relevance score.
        """
        limit = max(1, min(limit, 100))
        data = await self._get(
            "/search",
            params={
                "q": query,
                "ontology": "mondo",
                "rows": limit,
                "obsoletes": str(obsolete).lower(),
                "local": "false",
                "fieldList": "id,iri,short_form,label,description,synonym,score",
            },
        )
        docs = data.get("response", {}).get("docs", [])
        results: list[MONDOSearchResult] = []
        for doc in docs:
            raw_id = doc.get("short_form", "")
            mondo_id = raw_id.replace("_", ":") if raw_id else ""
            if not mondo_id.upper().startswith("MONDO:"):
                continue
            results.append(
                MONDOSearchResult(
                    mondo_id=mondo_id.upper(),
                    label=doc.get("label", ""),
                    description=(doc.get("description") or [""])[0],
                    synonyms=doc.get("synonym", []),
                    score=float(doc.get("score", 0.0)),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Hierarchy
    # ------------------------------------------------------------------

    async def ancestors(
        self, mondo_id: str, *, limit: int = 50
    ) -> list[OntologyTerm]:
        """Return all ancestor terms (superclasses) of the given MONDO ID."""
        mondo_id = _normalise_mondo_id(mondo_id)
        short_form = mondo_id.replace(":", "_")
        iri = f"http://purl.obolibrary.org/obo/{short_form}"
        data = await self._get(
            f"/ontologies/mondo/terms/{_url_encode(iri)}/ancestors",
            params={"size": limit},
        )
        return [
            self._term_to_ontology(t)
            for t in data.get("_embedded", {}).get("terms", [])
        ]

    async def descendants(
        self, mondo_id: str, *, limit: int = 50
    ) -> list[OntologyTerm]:
        """Return direct children and all descendants of the given MONDO ID."""
        mondo_id = _normalise_mondo_id(mondo_id)
        short_form = mondo_id.replace(":", "_")
        iri = f"http://purl.obolibrary.org/obo/{short_form}"
        data = await self._get(
            f"/ontologies/mondo/terms/{_url_encode(iri)}/descendants",
            params={"size": limit},
        )
        return [
            self._term_to_ontology(t)
            for t in data.get("_embedded", {}).get("terms", [])
        ]

    async def children(self, mondo_id: str) -> list[OntologyTerm]:
        """Return direct children (one hop) of the given MONDO ID."""
        mondo_id = _normalise_mondo_id(mondo_id)
        short_form = mondo_id.replace(":", "_")
        iri = f"http://purl.obolibrary.org/obo/{short_form}"
        data = await self._get(
            f"/ontologies/mondo/terms/{_url_encode(iri)}/children",
        )
        return [
            self._term_to_ontology(t)
            for t in data.get("_embedded", {}).get("terms", [])
        ]

    # ------------------------------------------------------------------
    # Cross-reference resolution
    # ------------------------------------------------------------------

    async def from_icd10(self, icd10_code: str) -> list[MONDOSearchResult]:
        """Find MONDO terms that cross-reference the given ICD-10 code."""
        return await self.search(f"ICD10CM:{icd10_code}", limit=5)

    async def from_omim(self, omim_id: str) -> list[MONDOSearchResult]:
        """Find MONDO terms that cross-reference the given OMIM ID."""
        return await self.search(f"OMIM:{omim_id}", limit=5)

    async def from_orphanet(self, orphanet_id: str) -> list[MONDOSearchResult]:
        """Find MONDO terms for an Orphanet disease ID."""
        return await self.search(f"Orphanet:{orphanet_id}", limit=5)

    # ------------------------------------------------------------------
    # Internal parsers
    # ------------------------------------------------------------------

    def _parse_term(self, raw: dict[str, Any]) -> DiseaseRecord:
        short_form: str = raw.get("short_form", "")
        mondo_id = short_form.replace("_", ":").upper()

        synonyms: list[str] = raw.get("synonyms", []) or []
        # OLS4 may nest synonyms as list-of-str or list-of-dict
        cleaned_synonyms: list[str] = []
        for s in synonyms:
            if isinstance(s, str):
                cleaned_synonyms.append(s)
            elif isinstance(s, dict):
                cleaned_synonyms.append(s.get("val", ""))

        xref_list: list[str] = raw.get("annotation", {}).get("database_cross_reference", [])
        xrefs = _extract_xrefs(xref_list)

        description = raw.get("description") or []
        definition = description[0] if isinstance(description, list) and description else str(description)

        return DiseaseRecord(
            mondo_id=mondo_id,
            name=raw.get("label", ""),
            synonyms=tuple(s for s in cleaned_synonyms if s),
            definition=definition,
            icd10_codes=tuple(xrefs["icd10"]),
            icd11_codes=tuple(xrefs["icd11"]),
            omim_ids=tuple(xrefs["omim"]),
            orphanet_ids=tuple(xrefs["orphanet"]),
            mesh_ids=tuple(xrefs["mesh"]),
            doid_ids=tuple(xrefs["doid"]),
        )

    @staticmethod
    def _term_to_ontology(raw: dict[str, Any]) -> OntologyTerm:
        short_form: str = raw.get("short_form", "")
        term_id = short_form.replace("_", ":").upper()
        description = raw.get("description") or []
        defn = description[0] if isinstance(description, list) and description else ""
        return OntologyTerm(
            id=term_id,
            label=raw.get("label", ""),
            description=defn,
            synonyms=tuple(raw.get("synonyms", []) or []),
            namespace="MONDO",
            obsolete=raw.get("is_obsolete", False),
        )


def _url_encode(s: str) -> str:
    """Double-encode a string for OLS4 IRI embedding in path segments."""
    from urllib.parse import quote
    return quote(quote(s, safe=""), safe="")
