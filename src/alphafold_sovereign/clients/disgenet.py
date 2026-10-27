# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""DisGeNET async REST client.

DisGeNET is a discovery platform containing collections of genes and variants
associated to human diseases.  It integrates data from expert curated
repositories, GWAS catalogues, animal models, and the scientific literature.

This client provides gene-disease association scores (GDA), variant-disease
associations (VDA), and disease enrichment analysis.

Reference:
  Piñero J et al. DisGeNET: a comprehensive platform integrating information on
  human disease-associated genes and variants.  Nucleic Acids Res.
  2020;48(D1):D845–D855.
  https://www.disgenet.com

Authentication:
  DisGeNET requires a free API key for all endpoints.
  Set the ``DISGENET_API_KEY`` environment variable before using this client.
  Register at https://www.disgenet.com/signup
"""

from __future__ import annotations

import math
import os
from typing import Any

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig

logger = structlog.get_logger(__name__)


def _source_number(value: Any, field: str, *, maximum: float | None = None) -> float:
    """Parse a source-reported number without inventing missing values.

    Reject booleans, missing/invalid, non-finite, negative and out-of-range
    values. A real upstream zero remains exactly zero.
    """
    if value is None or isinstance(value, bool):
        raise ValueError(f"DisGeNET {field}: missing or invalid numeric value")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"DisGeNET {field}: invalid numeric value") from exc
    if not math.isfinite(number) or number < 0 or (maximum is not None and number > maximum):
        raise ValueError(f"DisGeNET {field}: out-of-range numeric value")
    return number


def _optional_number(value: Any, field: str, *, maximum: float | None = None) -> float | None:
    if value is None:
        return None
    return _source_number(value, field, maximum=maximum)


def _optional_count(value: Any, field: str) -> int | None:
    number = _optional_number(value, field)
    if number is None:
        return None
    if not number.is_integer():
        raise ValueError(f"DisGeNET {field}: count must be an integer")
    return int(number)


def _source_items(data: Any) -> list[Any]:
    """Do not report malformed upstream data as a legitimate empty result."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if not data:
            return []
        items = data.get("payload")
        if isinstance(items, list):
            return items
    raise ValueError("DisGeNET response: invalid payload, expected a list")


_DISGENET_CONFIG = UpstreamConfig(
    base_url="https://api.disgenet.com",
    calls_per_second=2.0,  # free tier; paid tier: 10/s
    max_retries=3,
    timeout=30.0,
    headers={"Content-Type": "application/json"},
)


class DisGeNETClient(BaseAsyncClient):
    """
    Async REST client for DisGeNET gene/variant-disease associations.

    GDA score (0–1) is a composite of:
    - Number of publications
    - Source provenance (curated > GWAS > inferred > animal > predicted)
    - Number of sources

    VDA score (0–1) analogous but for specific sequence variants.

    Requires ``DISGENET_API_KEY`` env var or ``api_key`` constructor argument.
    """

    upstream_name = "disgenet"
    config = _DISGENET_CONFIG

    def __init__(self, *, api_key: str = "", **kwargs: Any) -> None:
        self._api_key = api_key or os.environ.get("DISGENET_API_KEY", "")
        if not self._api_key:
            logger.warning(
                "disgenet.no_api_key",
                msg="DISGENET_API_KEY not set; requests will be rejected by the API.",
            )
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # Gene → disease associations
    # ------------------------------------------------------------------

    async def gene_disease_associations(
        self,
        gene_symbol: str,
        *,
        min_score: float = 0.0,
        limit: int = 20,
        source: str = "ALL",
    ) -> list[dict[str, Any]]:
        """Return disease associations for a gene, ranked by GDA score.

        Args:
            gene_symbol: HGNC gene symbol, e.g. ``'BRCA1'``.
            min_score: Filter out GDAs below this score (0.0–1.0).
            limit: Maximum results.
            source: Source filter — one of
                ``'ALL'``, ``'CURATED'``, ``'INFERRED'``, ``'ANIMAL_MODELS'``,
                ``'LITERATURE'``, ``'GWASCAT'``, ``'PREDICTED'``.

        Returns:
            List of GDA dicts with keys:
            ``gene_symbol``, ``disease_id``, ``disease_name``, ``score``,
            ``n_pmids``, ``n_snps``, ``source``, ``disease_class``,
            ``disease_semantictype``. Missing optional counts are ``None``;
            missing/malformed scores are not fabricated as zero.
        """
        params: dict[str, Any] = {
            "gene_symbol": gene_symbol,
            "source": source,
            "limit": min(limit, 100),
            "format": "json",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        try:
            data = await self._get("/api/v1/gda/gene", params=params)
        except Exception as exc:
            logger.warning("disgenet.gda.error", gene=gene_symbol, exc=str(exc))
            raise

        results: list[dict[str, Any]] = []
        _items = _source_items(data)
        for item in _items:
            if not isinstance(item, dict):
                continue
            score = _source_number(item.get("score"), "association score", maximum=1.0)
            if score < min_score:
                continue
            results.append(
                {
                    "gene_symbol": item.get("gene_symbol", gene_symbol),
                    "disease_id": item.get("disease_id", ""),
                    "disease_name": item.get("disease_name", ""),
                    "score": round(score, 4),
                    "n_pmids": _optional_count(item.get("n_pmids"), "n_pmids"),
                    "n_snps": _optional_count(item.get("n_snps"), "n_snps"),
                    "source": item.get("source", ""),
                    "disease_class": item.get("disease_class", []),
                    "disease_semantictype": item.get("disease_semantictype", []),
                    "year_initial": item.get("year_initial"),
                    "year_final": item.get("year_final"),
                }
            )
        return sorted(results, key=lambda x: x["score"], reverse=True)[:limit]

    # ------------------------------------------------------------------
    # Disease → gene associations
    # ------------------------------------------------------------------

    async def disease_gene_associations(
        self,
        disease_id: str,
        *,
        min_score: float = 0.1,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return gene associations for a disease, ranked by GDA score.

        Args:
            disease_id: UMLS Concept ID (CUI), MONDO, or OMIM ID.
                DisGeNET natively uses UMLS CUIs; MONDO/OMIM IDs are
                attempted via lookup if the exact ID is not found.
            min_score: Minimum GDA score threshold.
            limit: Maximum results.

        Returns:
            List of GDA dicts (same schema as ``gene_disease_associations``).
        """
        params: dict[str, Any] = {
            "disease_id": disease_id,
            "limit": min(limit, 100),
            "format": "json",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        try:
            data = await self._get("/api/v1/gda/disease", params=params)
        except Exception as exc:
            logger.warning("disgenet.gda.disease.error", disease=disease_id, exc=str(exc))
            raise

        results: list[dict[str, Any]] = []
        _items = _source_items(data)
        for item in _items:
            if not isinstance(item, dict):
                continue
            score = _source_number(item.get("score"), "association score", maximum=1.0)
            if score < min_score:
                continue
            results.append(
                {
                    "gene_symbol": item.get("gene_symbol", ""),
                    "gene_id": item.get("gene_id", ""),
                    "disease_id": item.get("disease_id", disease_id),
                    "disease_name": item.get("disease_name", ""),
                    "score": round(score, 4),
                    "n_pmids": _optional_count(item.get("n_pmids"), "n_pmids"),
                    "source": item.get("source", ""),
                }
            )
        return sorted(results, key=lambda x: x["score"], reverse=True)[:limit]

    # ------------------------------------------------------------------
    # Variant → disease associations
    # ------------------------------------------------------------------

    async def variant_disease_associations(
        self,
        variant_id: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return disease associations for a dbSNP variant.

        Args:
            variant_id: dbSNP rsID, e.g. ``'rs1799977'``.
            limit: Maximum results.

        Returns:
            List of VDA dicts with keys:
            ``variant_id``, ``disease_id``, ``disease_name``, ``score``,
            ``n_pmids``, ``p_value``, ``odds_ratio``, ``beta``.
            Source score is mandatory; missing/invalid values raise.
        """
        params: dict[str, Any] = {
            "variant_id": variant_id,
            "limit": min(limit, 50),
            "format": "json",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        try:
            data = await self._get("/api/v1/vda/variant", params=params)
        except Exception as exc:
            logger.warning("disgenet.vda.error", variant=variant_id, exc=str(exc))
            raise

        results: list[dict[str, Any]] = []
        _items = _source_items(data)
        for item in _items:
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "variant_id": item.get("variant_id", variant_id),
                    "disease_id": item.get("disease_id", ""),
                    "disease_name": item.get("disease_name", ""),
                    "score": round(
                        _source_number(item.get("score"), "variant score", maximum=1.0), 4
                    ),
                    "n_pmids": _optional_count(item.get("n_pmids"), "n_pmids"),
                    "p_value": item.get("p_value"),
                    "odds_ratio": item.get("odds_ratio"),
                    "beta": item.get("beta"),
                    "source": item.get("source", ""),
                }
            )
        return sorted(results, key=lambda x: x["score"], reverse=True)[:limit]

    # ------------------------------------------------------------------
    # Disease enrichment (gene-set → disease)
    # ------------------------------------------------------------------

    async def enrichment(
        self,
        gene_symbols: list[str],
        *,
        pvalue_threshold: float = 0.05,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Run DisGeNET enrichment analysis on a gene set.

        Given a list of genes, returns diseases statistically enriched
        in that set vs. the human background.

        Args:
            gene_symbols: List of HGNC gene symbols (max 100).
            pvalue_threshold: Bonferroni-corrected p-value cutoff.
            limit: Maximum diseases to return.

        Returns:
            List of enrichment results with keys:
            ``disease_id``, ``disease_name``, ``p_value``, ``fdr``,
            ``expected``, ``observed``, ``ratio``. Missing optional measures
            remain ``None``; zero-valued p-values and FDRs are preserved.
        """
        if not gene_symbols:
            return []
        gene_symbols = gene_symbols[:100]

        params: dict[str, Any] = {
            "gene_list": ",".join(gene_symbols),
            "format": "json",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        try:
            data = await self._get("/api/v1/enrichment/gene", params=params)
        except Exception as exc:
            logger.warning("disgenet.enrichment.error", exc=str(exc))
            raise

        results: list[dict[str, Any]] = []
        _items = _source_items(data)
        for item in _items:
            if not isinstance(item, dict):
                continue
            pval = _source_number(item.get("p_value"), "p_value", maximum=1.0)
            if pval > pvalue_threshold:
                continue
            results.append(
                {
                    "disease_id": item.get("disease_id", ""),
                    "disease_name": item.get("disease_name", ""),
                    "p_value": pval,
                    "fdr": _optional_number(item.get("fdr"), "fdr", maximum=1.0),
                    "expected": _optional_number(item.get("expected"), "expected"),
                    "observed": _optional_count(item.get("observed"), "observed"),
                    "ratio": _optional_number(item.get("ratio"), "ratio"),
                }
            )
        return sorted(results, key=lambda x: x["p_value"])[:limit]

    # ------------------------------------------------------------------
    # Gene-disease network (for network medicine)
    # ------------------------------------------------------------------

    async def shared_genes(
        self,
        disease_id_a: str,
        disease_id_b: str,
        *,
        min_score: float = 0.1,
    ) -> list[str]:
        """Return gene symbols shared between two diseases (disease comorbidity).

        Args:
            disease_id_a: First disease ID (UMLS CUI / MONDO / OMIM).
            disease_id_b: Second disease ID.
            min_score: Minimum GDA score for inclusion.

        Returns:
            Sorted list of HGNC gene symbols associated with both diseases.
        """
        genes_a, genes_b = await self._gather(
            self.disease_gene_associations(disease_id_a, min_score=min_score, limit=200),
            self.disease_gene_associations(disease_id_b, min_score=min_score, limit=200),
        )
        syms_a = {g["gene_symbol"] for g in genes_a if g.get("gene_symbol")}
        syms_b = {g["gene_symbol"] for g in genes_b if g.get("gene_symbol")}
        return sorted(syms_a & syms_b)

    @staticmethod
    async def _gather(*coros: Any) -> list[Any]:
        """Run coroutines concurrently."""
        import asyncio

        return list(await asyncio.gather(*coros))
