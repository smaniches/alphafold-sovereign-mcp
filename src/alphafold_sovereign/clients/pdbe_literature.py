# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Santiago Maniches and TOPOLOGICA LLC
"""Source-attributed PDBe/IUCr literature residue annotations.

Endpoint and response contract are documented in PDBeurope/IUCr-annotation-pipeline,
pipeline/jupyter_notebooks/PDBe_API_for_text_mined_annotations.ipynb. PDBe's
UniProt residue correspondences originate upstream via SIFTS; this client
validates response identity but does not independently re-run SIFTS.
"""

from __future__ import annotations

import math
import re
from typing import Any

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig
from alphafold_sovereign.domain.uniprot import UNIPROT_ACCESSION_PATTERN

_LIMIT = 40


class PDBeAnnotationSchemaError(ValueError):
    """PDBe returned annotation data that cannot be safely attributed."""


def _as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PDBeAnnotationSchemaError(f"{label} must be an array")
    return value


def _normalize_residue_annotations(  # noqa: PLR0912 - nested PDBe schemas need explicit checks
    raw: Any, accession: str, residue: int
) -> dict[str, Any]:
    """Validate nested PDBe/IUCr data, retaining only exact source-reported joins."""
    endpoint = (
        f"https://www.ebi.ac.uk/pdbe/api/v2/uniprot/llm_annotations/summary/{accession}/{residue}"
    )
    result: dict[str, Any] = {
        "source": "PDBe / IUCr",
        "api_url": endpoint,
        "uniprot_accession": accession,
        "uniprot_residue": residue,
        "evidence_type": "AI-text-mined literature annotation",
        "mapping_status": "PDBe/SIFTS-reported; not independently verified",
        "clinical_use": "Research evidence only; not a clinical assertion or ACMG criterion",
        "records": [],
        "total_matching_records": 0,
        "excluded_mismatched_records": 0,
        "truncated": False,
        "status": "no_annotations",
    }
    if not isinstance(raw, dict):
        raise PDBeAnnotationSchemaError("PDBe response must be a JSON object")
    if not raw:
        return result
    root = raw.get(accession)
    if not isinstance(root, dict) or root.get("dataType") != "ANNOTATIONS":
        raise PDBeAnnotationSchemaError("PDBe response missing expected accession/annotation type")
    if "uniprotResidue" in root and str(root["uniprotResidue"]) != str(residue):
        raise PDBeAnnotationSchemaError("PDBe response refers to another UniProt residue")
    for pdb_group in _as_list(root.get("data"), "data"):
        if not isinstance(pdb_group, dict):
            raise PDBeAnnotationSchemaError("PDBe PDB group must be an object")
        pdb_id = pdb_group.get("pdbId")
        if not isinstance(pdb_id, str) or not re.fullmatch(r"[0-9][a-zA-Z0-9]{3}", pdb_id):
            raise PDBeAnnotationSchemaError("PDBe annotation has invalid PDB identity")
        for provider in _as_list(pdb_group.get("providerList"), "providerList"):
            if not isinstance(provider, dict) or not isinstance(provider.get("provider"), str):
                raise PDBeAnnotationSchemaError("PDBe provider is invalid")
            for site in _as_list(provider.get("residueList"), "residueList"):
                if not isinstance(site, dict) or site.get("indexType") != "PDB":
                    raise PDBeAnnotationSchemaError("PDBe residue index type is not PDB")
                for annotation in _as_list(site.get("additionalData"), "additionalData"):
                    if not isinstance(annotation, dict):
                        raise PDBeAnnotationSchemaError("PDBe annotation must be an object")
                    if annotation.get("uniprotAccession") != accession or str(
                        annotation.get("uniprotResidue")
                    ) != str(residue):
                        result["excluded_mismatched_records"] += 1
                        continue
                    score = annotation.get("aiScore")
                    if (
                        isinstance(score, bool)
                        or not isinstance(score, (int, float))
                        or not math.isfinite(score)
                        or not 0.0 <= score <= 1.0
                    ):
                        raise PDBeAnnotationSchemaError("PDBe annotation has invalid AI score")
                    if any(
                        not isinstance(annotation.get(key), str)
                        for key in ("pdbChain", "sentence", "exact", "entityType")
                    ):
                        raise PDBeAnnotationSchemaError("PDBe annotation lacks text/chain identity")
                    if any(
                        type(annotation.get(key)) is not int or annotation[key] < 1
                        for key in ("pdbResidue", "authorResidueNumber", "entityId")
                    ):
                        raise PDBeAnnotationSchemaError("PDBe annotation has invalid PDB residue")
                    record = {
                        "provider": provider["provider"],
                        "pdb_id": pdb_id.lower(),
                        "pdb_chain": annotation["pdbChain"],
                        "pdb_entity_id": annotation["entityId"],
                        "pdb_residue": annotation["pdbResidue"],
                        "author_residue_number": annotation["authorResidueNumber"],
                        "uniprot_accession": annotation["uniprotAccession"],
                        "uniprot_residue": annotation["uniprotResidue"],
                        "pubmed_id": annotation.get("pubmedId"),
                        "pmc_id": annotation.get("pmcId"),
                        "doi": annotation.get("doi"),
                        "primary_citation": annotation.get("primaryCitation"),
                        "open_access": annotation.get("openAccess"),
                        "sentence": annotation["sentence"],
                        "section": annotation.get("section"),
                        "exact": annotation["exact"],
                        "entity_type": annotation["entityType"],
                        "annotator": annotation.get("annotator"),
                        "ai_score": score,
                        "experimental_validation_metrics": None,
                    }
                    result["total_matching_records"] += 1
                    if len(result["records"]) < _LIMIT:
                        result["records"].append(record)
    result["truncated"] = result["total_matching_records"] > _LIMIT
    if result["total_matching_records"]:
        result["status"] = "ok"
    elif result["excluded_mismatched_records"]:
        result["status"] = "no_verified_match"
    return result


class PDBeLiteratureClient(BaseAsyncClient):
    """Read the documented PDBe/IUCr UniProt residue annotation endpoint."""

    upstream_name = "PDBe / IUCr literature"
    config = UpstreamConfig(
        base_url="https://www.ebi.ac.uk/pdbe/api/v2",
        calls_per_second=2.0,
        timeout=45.0,
        max_retries=3,
    )

    async def get_residue_annotations(self, accession: str, residue: int) -> dict[str, Any]:
        if (
            not re.fullmatch(UNIPROT_ACCESSION_PATTERN, accession)
            or "-" in accession
            or residue < 1
        ):
            raise ValueError("Expected canonical UniProt accession and positive residue index")
        raw: Any = await self._get(f"/uniprot/llm_annotations/summary/{accession}/{residue}")
        return _normalize_residue_annotations(raw, accession, residue)
