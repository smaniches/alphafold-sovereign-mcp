# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Verify an explicit UniProt isoform against UniProtKB curated identity."""

from __future__ import annotations

from typing import Any

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig


class UniProtIsoformClient(BaseAsyncClient):
    """Source-restricted read-only lookup of UniProtKB canonical metadata."""

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
        """Require a curated Displayed isoform and an identical full sequence.

        An isoform suffix alone cannot establish canonical identity.
        """
        if not model_sequence:
            return False
        payload: Any = await self._get(f"/uniprotkb/{accession}.json")
        if not isinstance(payload, dict) or payload.get("primaryAccession") != accession:
            return False
        sequence = payload.get("sequence")
        if not isinstance(sequence, dict) or sequence.get("value") != model_sequence:
            return False
        comments = payload.get("comments")
        if not isinstance(comments, list):
            return False
        for comment in comments:
            if (
                not isinstance(comment, dict)
                or comment.get("commentType") != "ALTERNATIVE PRODUCTS"
            ):
                continue
            isoforms = comment.get("isoforms")
            if not isinstance(isoforms, list):
                continue
            for isoform in isoforms:
                if not isinstance(isoform, dict):
                    continue
                ids = isoform.get("isoformIds")
                if (
                    isoform.get("isoformSequenceStatus") == "Displayed"
                    and isinstance(ids, list)
                    and isoform_id in ids
                ):
                    return True
        return False
