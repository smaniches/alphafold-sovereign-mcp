# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""AlphaFold Database async client.

Wraps the EBI AlphaFold DB v4 REST API, the AlphaMissense endpoint,
and the PAE (predicted aligned error) JSON endpoint.

Reference:
  Varadi M et al. AlphaFold Protein Structure Database: massively expanding
  the structural coverage of protein-sequence space with high-accuracy models.
  Nucleic Acids Res. 2022;50(D1):D439–D444.
  https://alphafold.ebi.ac.uk/
"""
from __future__ import annotations

import os
from typing import Any

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig

logger = structlog.get_logger(__name__)

_AF_BASE = "https://alphafold.ebi.ac.uk/api"
_AF_FILES = "https://alphafold.ebi.ac.uk/files"

_AF_CONFIG = UpstreamConfig(
    base_url=_AF_BASE,
    calls_per_second=float(os.getenv("ALPHAFOLD_RATE_LIMIT", "5")),
    max_retries=3,
    timeout=60.0,
)


class AlphaFoldClient(BaseAsyncClient):
    """Async client for the EBI AlphaFold DB v4 REST API."""

    upstream_name = "AlphaFold DB"
    config = _AF_CONFIG

    # ------------------------------------------------------------------
    # Metadata & structure
    # ------------------------------------------------------------------

    async def get_prediction(self, uniprot_id: str) -> dict[str, Any]:
        """Return prediction metadata for a UniProt accession.

        Args:
            uniprot_id: UniProt accession (e.g. 'P04637').

        Returns:
            Dict with ``uniprotAccession``, ``entryId``, ``pdbUrl``,
            ``cifUrl``, ``paeImageUrl``, ``paeDocUrl``, ``amAnnotationsUrl``,
            ``confidenceVersion`` and more.
        """
        data = await self._get(f"/prediction/{uniprot_id}")
        if isinstance(data, list) and data:
            return data[0]  # type: ignore[return-value]
        return data

    async def get_pdb_bytes(self, uniprot_id: str) -> bytes:
        """Download the PDB-format structure file for a UniProt accession."""
        meta = await self.get_prediction(uniprot_id)
        pdb_url = meta.get("pdbUrl", "")
        if not pdb_url:
            return b""
        path = pdb_url.replace(_AF_FILES, "").replace(_AF_BASE, "")
        return await self._get_bytes(path)

    async def get_pae(self, uniprot_id: str) -> dict[str, Any]:
        """Fetch the Predicted Aligned Error (PAE) JSON for a UniProt accession.

        Returns:
            Raw PAE JSON dict with ``predicted_aligned_error`` (residue × residue
            matrix) and ``max_predicted_aligned_error``.
        """
        meta = await self.get_prediction(uniprot_id)
        pae_url = meta.get("paeDocUrl", "")
        if not pae_url:
            return {}
        path = pae_url.replace(_AF_FILES, "").replace(_AF_BASE, "")
        return await self._get(path)

    async def get_alphamissense(self, uniprot_id: str) -> dict[str, Any]:
        """Fetch AlphaMissense per-residue pathogenicity annotations.

        Returns:
            Dict with ``accession`` and ``predictions`` (list of dicts with
            ``protein_variant``, ``am_pathogenicity``, ``am_class``).
        """
        meta = await self.get_prediction(uniprot_id)
        am_url = meta.get("amAnnotationsUrl", "")
        if not am_url:
            return {}
        path = am_url.replace(_AF_FILES, "").replace(_AF_BASE, "")
        return await self._get(path)

    async def check_availability(self, uniprot_id: str) -> bool:
        """Return True if AlphaFold DB has a prediction for the given accession."""
        try:
            meta = await self.get_prediction(uniprot_id)
            return bool(meta.get("entryId"))
        except Exception:  # noqa: BLE001
            return False

    async def search_by_taxonomy(
        self, taxon_id: int, *, page_size: int = 25
    ) -> list[dict[str, Any]]:
        """List predictions for a given NCBI taxonomy ID.

        Args:
            taxon_id: NCBI taxonomy identifier (e.g. 9606 for human).
            page_size: Number of results per page (max 100).
        """
        data = await self._get(
            "/predictions/taxid",
            params={"taxId": taxon_id, "size": min(page_size, 100)},
        )
        return data if isinstance(data, list) else data.get("predictions", [])  # type: ignore[return-value]
