# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""ClinVar async client via NCBI E-utilities.

ClinVar is the NCBI archive of variants and their clinical interpretations.
This client resolves HGVS expressions to ClinVar variant records, returning
pathogenicity classifications, review status, and associated conditions.

Reference:
  Landrum MJ et al. ClinVar: improvements to accessing data.
  Nucleic Acids Res. 2020;48(D1):D835–D844.
"""
from __future__ import annotations

import re
from typing import Any

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig
from alphafold_sovereign.domain.disease import PathogenicityClass

logger = structlog.get_logger(__name__)

_CLINVAR_CONFIG = UpstreamConfig(
    base_url="https://eutils.ncbi.nlm.nih.gov",
    calls_per_second=3.0,  # NCBI requests ≤ 3/s without API key; 10/s with
    max_retries=3,
    timeout=20.0,
)

# Mapping ClinVar free-text interpretations → PathogenicityClass enum
_PATHO_MAP: dict[str, PathogenicityClass] = {
    "pathogenic": PathogenicityClass.PATHOGENIC,
    "likely pathogenic": PathogenicityClass.LIKELY_PATHOGENIC,
    "uncertain significance": PathogenicityClass.UNCERTAIN,
    "likely benign": PathogenicityClass.LIKELY_BENIGN,
    "benign": PathogenicityClass.BENIGN,
    "conflicting interpretations of pathogenicity": PathogenicityClass.CONFLICTING,
    "conflicting classifications of pathogenicity": PathogenicityClass.CONFLICTING,
}


def _parse_classification(raw: str) -> PathogenicityClass:
    return _PATHO_MAP.get(raw.lower().strip(), PathogenicityClass.NOT_PROVIDED)


class ClinVarClient(BaseAsyncClient):
    """
    Async client for ClinVar variant interpretation data.

    Uses the NCBI E-utilities JSON API.  Set ``NCBI_API_KEY`` environment
    variable to raise rate limit from 3 to 10 req/s.
    """

    upstream_name = "clinvar"
    config = _CLINVAR_CONFIG

    def __init__(self, *, ncbi_api_key: str = "", **kwargs: Any) -> None:
        import os
        self._api_key = ncbi_api_key or os.environ.get("NCBI_API_KEY", "")
        if self._api_key:
            self.config = UpstreamConfig(
                base_url=_CLINVAR_CONFIG.base_url,
                calls_per_second=10.0,
                max_retries=3,
                timeout=20.0,
            )
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_by_hgvs(self, hgvs: str) -> list[dict[str, Any]]:
        """Search ClinVar for variants matching an HGVS expression.

        Args:
            hgvs: HGVS nucleotide or protein expression,
                e.g. ``'NM_007294.3:c.181T>G'`` or ``'BRCA1:c.181T>G'``.

        Returns:
            List of raw variant summary dicts.  Use ``get_variant`` to
            fetch full details for a specific variation ID.
        """
        params: dict[str, Any] = {
            "db": "clinvar",
            "term": f"{hgvs}[Variant Name]",
            "retmode": "json",
            "retmax": 10,
        }
        if self._api_key:
            params["api_key"] = self._api_key
        data = await self._get("/entrez/eutils/esearch.fcgi", params=params)
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        return await self._fetch_summaries(ids)

    async def get_variant(self, variation_id: str) -> dict[str, Any]:
        """Fetch a ClinVar variant by its numeric variation ID.

        Args:
            variation_id: ClinVar variation ID as string, e.g. ``'12375'``.

        Returns:
            Parsed variant dict with keys:
            ``variation_id``, ``name``, ``gene_symbol``, ``classification``,
            ``review_status``, ``conditions``, ``molecular_consequence``,
            ``last_evaluated``.
        """
        summaries = await self._fetch_summaries([variation_id])
        if not summaries:
            raise KeyError(f"ClinVar variation not found: {variation_id}")
        return summaries[0]

    async def search_gene(
        self, gene_symbol: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Fetch pathogenic / likely-pathogenic variants for a gene.

        Args:
            gene_symbol: HGNC gene symbol, e.g. ``'BRCA1'``.
            limit: Maximum variants to return.

        Returns:
            List of variant summary dicts filtered to P/LP.
        """
        params: dict[str, Any] = {
            "db": "clinvar",
            "term": (
                f"{gene_symbol}[Gene Name] AND "
                "(\"pathogenic\"[Significance] OR \"likely pathogenic\"[Significance])"
            ),
            "retmode": "json",
            "retmax": min(limit, 200),
        }
        if self._api_key:
            params["api_key"] = self._api_key
        data = await self._get("/entrez/eutils/esearch.fcgi", params=params)
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        return await self._fetch_summaries(ids[:limit])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _fetch_summaries(self, ids: list[str]) -> list[dict[str, Any]]:
        """Batch-fetch esummary records for a list of variation IDs."""
        params: dict[str, Any] = {
            "db": "clinvar",
            "id": ",".join(ids),
            "retmode": "json",
        }
        if self._api_key:
            params["api_key"] = self._api_key
        data = await self._get("/entrez/eutils/esummary.fcgi", params=params)
        result_map = data.get("result", {})
        parsed: list[dict[str, Any]] = []
        for vid in ids:
            raw = result_map.get(vid)
            if not isinstance(raw, dict):
                continue
            parsed.append(self._parse_summary(raw))
        return parsed

    @staticmethod
    def _parse_summary(raw: dict[str, Any]) -> dict[str, Any]:
        var_id = str(raw.get("uid", ""))
        name = raw.get("title", "")
        gene_info = (raw.get("gene_sort") or "").split(";")
        gene_symbol = gene_info[0].strip() if gene_info else ""

        # Clinical significance (may be nested)
        germline = raw.get("germline_classification") or {}
        clinical_sig = germline.get("description", "") or raw.get(
            "clinical_significance", {}).get("description", ""
        )

        review_status = germline.get("review_status", "") or raw.get(
            "clinical_significance", {}).get("review_status", ""
        )

        # Conditions
        conditions: list[str] = []
        for cond in raw.get("trait_set", []):
            trait_name = cond.get("trait_name", "")
            if trait_name:
                conditions.append(trait_name)

        # Molecular consequence
        mol_cons: list[str] = []
        for loc in raw.get("variation_set", [{}])[0].get("variation_loc", []):
            mc = loc.get("molecular_consequence", "")
            if mc:
                mol_cons.append(mc)

        return {
            "variation_id": var_id,
            "name": name,
            "gene_symbol": gene_symbol,
            "classification": _parse_classification(clinical_sig).value,
            "review_status": review_status,
            "conditions": conditions,
            "molecular_consequence": list(set(mol_cons)),
            "last_evaluated": (germline.get("last_evaluated") or ""),
        }
