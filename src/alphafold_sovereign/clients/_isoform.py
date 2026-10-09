# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Verify explicit UniProt isoforms against curated upstream sequence identity.

A verification outage or malformed upstream payload is never biological
evidence that an isoform or AlphaFold prediction does not exist.
"""

from __future__ import annotations

from typing import Any

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig


class UniProtVerificationError(RuntimeError):
    """Curated isoform identity cannot be established from trusted evidence."""


def _has_displayed_isoform(comments: list[Any], isoform_id: str) -> bool:
    """Validate curated isoform annotations before accepting an identity."""
    for comment in comments:
        if not isinstance(comment, dict):
            raise UniProtVerificationError("UniProtKB has a malformed annotation")
        if comment.get("commentType") != "ALTERNATIVE PRODUCTS":
            continue
        isoforms = comment.get("isoforms")
        if not isinstance(isoforms, list):
            raise UniProtVerificationError("UniProtKB has malformed isoform annotations")
        for isoform in isoforms:
            if not isinstance(isoform, dict):
                raise UniProtVerificationError("UniProtKB has a malformed isoform entry")
            ids = isoform.get("isoformIds")
            if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
                raise UniProtVerificationError("UniProtKB has invalid isoform identifiers")
            status = isoform.get("isoformSequenceStatus")
            if not isinstance(status, str):
                raise UniProtVerificationError("UniProtKB has no isoform sequence status")
            if status == "Displayed" and isoform_id in ids:
                return True
    return False


class UniProtIsoformClient(BaseAsyncClient):
    """Source-restricted read-only UniProtKB client; parent owns its lifespan."""

    upstream_name = "UniProtKB isoform verification"
    config = UpstreamConfig(
        base_url="https://rest.uniprot.org",
        calls_per_second=2.0,
        max_retries=2,
        timeout=20.0,
    )

    async def is_displayed_isoform(
        self, accession: str, isoform_id: str, model_sequence: str
    ) -> bool:
        """Require UniProtKB Displayed identity and identical full sequence.

        A valid, well-formed mismatch returns False. Network/HTTP failures,
        invalid JSON, and missing required identity fields instead raise.
        """
        if not model_sequence:
            return False
        response = await self._request("GET", f"/uniprotkb/{accession}.json")
        response.raise_for_status()
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise UniProtVerificationError("UniProtKB returned invalid JSON") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("primaryAccession"), str):
            raise UniProtVerificationError("UniProtKB entry has no valid primary accession")
        if payload["primaryAccession"] != accession:
            return False

        sequence = payload.get("sequence")
        if not isinstance(sequence, dict) or not isinstance(sequence.get("value"), str):
            raise UniProtVerificationError("UniProtKB entry has no valid sequence")
        if sequence["value"] != model_sequence:
            return False

        comments = payload.get("comments")
        if not isinstance(comments, list):
            raise UniProtVerificationError("UniProtKB entry has no valid annotation list")
        return _has_displayed_isoform(comments, isoform_id)
