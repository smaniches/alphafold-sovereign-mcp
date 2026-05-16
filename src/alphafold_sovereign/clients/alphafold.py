# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
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

import csv
import io
import os
from typing import Any, cast

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
        raw: Any = await self._get(f"/prediction/{uniprot_id}")
        if isinstance(raw, list) and raw:
            return cast("dict[str, Any]", raw[0])
        return cast("dict[str, Any]", raw)

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
        """Fetch AlphaMissense per-substitution pathogenicity annotations.

        AlphaFold DB serves these as a CSV file (one row per amino-acid
        substitution) at the ``amAnnotationsUrl`` advertised in the
        prediction metadata. The CSV header is
        ``protein_variant,am_pathogenicity,am_class``.

        Returns:
            Dict with ``accession`` and ``predictions`` (list of dicts with
            ``protein_variant``, ``am_pathogenicity`` (float) and
            ``am_class``). Empty dict if the accession has no AlphaMissense
            annotations.
        """
        meta = await self.get_prediction(uniprot_id)
        am_url = meta.get("amAnnotationsUrl", "")
        if not am_url:
            return {}
        path = am_url.replace(_AF_FILES, "").replace(_AF_BASE, "")
        raw = await self._get_bytes(path)
        return {
            "accession": uniprot_id,
            "predictions": _parse_alphamissense_csv(raw),
        }

    async def alphamissense_score(
        self, uniprot_id: str, protein_variant: str
    ) -> dict[str, Any] | None:
        """Return the AlphaMissense prediction for one amino-acid substitution.

        Args:
            uniprot_id: UniProt accession, e.g. ``'P38398'``.
            protein_variant: Substitution in single-letter form, e.g.
                ``'C61G'`` (reference residue, 1-based position, alternate
                residue).

        Returns:
            Dict with ``protein_variant``, ``am_pathogenicity`` (float) and
            ``am_class``; or ``None`` when the protein has no AlphaMissense
            annotations or the substitution is not present.
        """
        annotations = await self.get_alphamissense(uniprot_id)
        target = protein_variant.strip().upper()
        for pred in annotations.get("predictions", []):
            if pred["protein_variant"].upper() == target:
                return pred  # type: ignore[no-any-return]
        return None

    async def check_availability(self, uniprot_id: str) -> bool:
        """Return True if AlphaFold DB has a prediction for the given accession."""
        try:
            meta = await self.get_prediction(uniprot_id)
            return bool(meta.get("entryId"))
        except Exception:
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
        raw_list: Any = data
        return raw_list if isinstance(raw_list, list) else raw_list.get("predictions", [])


def _parse_alphamissense_csv(raw: bytes) -> list[dict[str, Any]]:
    """Parse an AlphaFold DB amino-acid-substitutions CSV.

    The file header is ``protein_variant,am_pathogenicity,am_class``. Rows
    with a missing variant key or a non-numeric pathogenicity value are
    skipped rather than raising.
    """
    text = raw.decode("utf-8", errors="replace")
    predictions: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(text)):
        variant = (row.get("protein_variant") or "").strip()
        if not variant:
            continue
        try:
            score = float(row["am_pathogenicity"])
        except (KeyError, TypeError, ValueError):
            continue
        predictions.append(
            {
                "protein_variant": variant,
                "am_pathogenicity": score,
                "am_class": (row.get("am_class") or "").strip(),
            }
        )
    return predictions
