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
from urllib.parse import urlsplit

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig

logger = structlog.get_logger(__name__)

_AF_BASE = "https://alphafold.ebi.ac.uk/api"
# Host that must serve every AlphaFold DB file URL. Derived from _AF_BASE
# so the expected host has a single source of truth.
_AF_HOST = urlsplit(_AF_BASE).hostname or ""

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
        return await self._get_bytes(_validate_af_file_url(pdb_url))

    async def get_pae(self, uniprot_id: str) -> dict[str, Any]:
        """Fetch the Predicted Aligned Error (PAE) JSON for a UniProt accession.

        AlphaFold DB serves the PAE document as a single-element JSON
        array; this method unwraps it to the inner object, the same way
        ``get_prediction`` unwraps the prediction-metadata array.

        Returns:
            PAE JSON dict with ``predicted_aligned_error`` (residue ×
            residue matrix) and ``max_predicted_aligned_error``; an empty
            dict when the accession advertises no PAE document.
        """
        meta = await self.get_prediction(uniprot_id)
        pae_url = meta.get("paeDocUrl", "")
        if not pae_url:
            return {}
        raw: Any = await self._get(_validate_af_file_url(pae_url))
        if isinstance(raw, list):
            return cast("dict[str, Any]", raw[0]) if raw else {}
        return cast("dict[str, Any]", raw)

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
        raw = await self._get_bytes(_validate_af_file_url(am_url))
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


def _validate_af_file_url(url: str) -> str:
    """Return ``url`` unchanged when it is an AlphaFold DB file URL.

    AlphaFold DB prediction metadata advertises absolute URLs for the PDB
    model, the PAE matrix, and the AlphaMissense substitutions CSV. Those
    resources are served from a host and path prefix distinct from the JSON
    API base, so they must be fetched verbatim. This guard rejects any
    advertised URL that is not an HTTPS URL on the AlphaFold DB host, so a
    changed or malformed upstream response fails loudly here instead of
    triggering a request to an unintended location.

    Args:
        url: A non-empty absolute URL taken from prediction metadata.

    Returns:
        ``url`` unchanged, when its scheme is ``https`` and its host equals
        the AlphaFold DB host derived from ``_AF_BASE``.

    Raises:
        ValueError: when ``url`` is not an HTTPS URL on the AlphaFold DB
            host. The message names the expected host and the offending URL.

    Complexity:
        O(len(url)) for a single URL parse.

    Example::

        >>> _validate_af_file_url(
        ...     "https://alphafold.ebi.ac.uk/files/AF-P38398-F1-model_v6.pdb"
        ... )
        'https://alphafold.ebi.ac.uk/files/AF-P38398-F1-model_v6.pdb'
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or host != _AF_HOST:
        raise ValueError(
            f"AlphaFold DB advertised a file URL on an unexpected host: "
            f"expected an https URL on {_AF_HOST!r}, got {url!r}."
        )
    return url


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
