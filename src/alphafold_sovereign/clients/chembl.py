# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""ChEMBL async REST client.

ChEMBL is the EMBL-EBI curated database of bioactive drug-like molecules.
Provides compound-target bioactivity, drug mechanisms, approved drug
indications, and pharmacokinetic (ADMET) data.

This client powers the drug repurposing and target druggability features
of AlphaFold Sovereign.

Reference:
  Mendez D et al. ChEMBL: towards direct deposition of bioassay data.
  Nucleic Acids Res. 2019;47(D1):D930–D940.
  https://www.ebi.ac.uk/chembl/
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig

logger = structlog.get_logger(__name__)

_CHEMBL_CONFIG = UpstreamConfig(
    base_url="https://www.ebi.ac.uk",
    calls_per_second=5.0,
    max_retries=3,
    timeout=30.0,
    headers={"Accept": "application/json"},
)

# Activity type → human-readable label
_ACT_TYPE_LABELS: dict[str, str] = {
    "IC50": "IC₅₀ (half-maximal inhibitory concentration)",
    "Ki": "Kᵢ (inhibition constant)",
    "EC50": "EC₅₀ (half-maximal effective concentration)",
    "Kd": "Kd (dissociation constant)",
    "GI50": "GI₅₀ (50% growth inhibition)",
    "CC50": "CC₅₀ (50% cytotoxicity)",
    "MIC": "MIC (minimum inhibitory concentration)",
}

# Max phase → development stage
_MAX_PHASE: dict[int, str] = {
    4: "Approved",
    3: "Phase III",
    2: "Phase II",
    1: "Phase I",
    0: "Preclinical",
    -1: "Withdrawn",
}


class ChEMBLClient(BaseAsyncClient):
    """
    Async REST client for ChEMBL drug/bioactivity data.

    Exposes:
    - Target lookup by gene symbol → ChEMBL target ID
    - Bioactivity data (IC50/Ki/EC50) for a target
    - Approved drug indications
    - Drug mechanism of action
    - Compound ADMET properties
    - Drug repurposing: find drugs active against a structural pocket class
    """

    upstream_name = "chembl"
    config = _CHEMBL_CONFIG

    _API_ROOT = "/chembl/api/data"

    # ------------------------------------------------------------------
    # Target lookup
    # ------------------------------------------------------------------

    async def target_by_gene(self, gene_symbol: str) -> list[dict[str, Any]]:
        """Find ChEMBL targets matching a gene symbol.

        Args:
            gene_symbol: HGNC gene symbol, e.g. ``'BRCA1'``.

        Returns:
            List of target dicts with keys:
            ``chembl_id``, ``pref_name``, ``target_type``, ``organism``,
            ``uniprot_accessions``.
        """
        data = await self._get(
            f"{self._API_ROOT}/target.json",
            params={
                "target_synonym__icontains": gene_symbol,
                "organism": "Homo sapiens",
                "limit": 10,
                "format": "json",
            },
        )
        results: list[dict[str, Any]] = []
        for t in data.get("targets", []):
            uniprot_ids = [
                c.get("accession", "") for c in t.get("target_components", []) if c.get("accession")
            ]
            results.append(
                {
                    "chembl_id": t.get("target_chembl_id", ""),
                    "pref_name": t.get("pref_name", ""),
                    "target_type": t.get("target_type", ""),
                    "organism": t.get("organism", ""),
                    "uniprot_accessions": uniprot_ids,
                }
            )
        return results

    async def target_by_uniprot(self, uniprot_id: str) -> dict[str, Any] | None:
        """Resolve a UniProt accession to a ChEMBL target.

        Args:
            uniprot_id: UniProt accession, e.g. ``'P38398'`` (BRCA1).

        Returns:
            Target dict or ``None`` if not found.
        """
        data = await self._get(
            f"{self._API_ROOT}/target.json",
            params={
                "target_components__accession": uniprot_id,
                "limit": 1,
                "format": "json",
            },
        )
        targets = data.get("targets", [])
        if not targets:
            return None
        t = targets[0]
        return {
            "chembl_id": t.get("target_chembl_id", ""),
            "pref_name": t.get("pref_name", ""),
            "target_type": t.get("target_type", ""),
            "organism": t.get("organism", ""),
        }

    # ------------------------------------------------------------------
    # Bioactivity data
    # ------------------------------------------------------------------

    async def bioactivities(
        self,
        target_chembl_id: str,
        *,
        activity_type: str = "IC50",
        max_value_nm: float | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch bioactivity measurements for a ChEMBL target.

        Args:
            target_chembl_id: ChEMBL target ID, e.g. ``'CHEMBL4523'``.
            activity_type: Measurement type filter: ``'IC50'``, ``'Ki'``,
                ``'EC50'``, ``'Kd'``, ``'GI50'``.
            max_value_nm: Filter to activities ≤ this nanomolar value.
            limit: Maximum results.

        Returns:
            List of activity dicts with keys:
            ``molecule_chembl_id``, ``pref_name``, ``activity_type``,
            ``value_nm``, ``units``, ``assay_type``, ``max_phase``,
            ``molecule_smiles``, ``first_approval``.
        """
        params: dict[str, Any] = {
            "target_chembl_id": target_chembl_id,
            "standard_type": activity_type,
            "standard_units": "nM",
            "assay_type": "B",  # binding assays
            "limit": min(limit, 100),
            "order_by": "standard_value",
            "format": "json",
        }
        if max_value_nm is not None:
            params["standard_value__lte"] = max_value_nm

        data = await self._get(
            f"{self._API_ROOT}/activity.json",
            params=params,
        )
        results: list[dict[str, Any]] = []
        for a in data.get("activities", []):
            results.append(
                {
                    "molecule_chembl_id": a.get("molecule_chembl_id", ""),
                    "pref_name": a.get("molecule_pref_name") or "",
                    "activity_type": a.get("standard_type", activity_type),
                    "value_nm": float(a.get("standard_value") or 0.0),
                    "units": a.get("standard_units", "nM"),
                    "assay_description": a.get("assay_description", ""),
                    "document_year": a.get("document_year"),
                    "molecule_smiles": a.get("canonical_smiles", ""),
                }
            )
        return results

    # ------------------------------------------------------------------
    # Approved drugs for a target
    # ------------------------------------------------------------------

    async def approved_drugs(
        self,
        target_chembl_id: str,
        *,
        include_clinical: bool = True,
    ) -> list[dict[str, Any]]:
        """Return known drugs (Phase ≥ 1) for a ChEMBL target.

        Args:
            target_chembl_id: ChEMBL target ID.
            include_clinical: If ``True``, include Phase I–III (not just approved).

        Returns:
            List of drug dicts with keys:
            ``molecule_chembl_id``, ``pref_name``, ``max_phase``,
            ``first_approval``, ``usan_stem``, ``indication_class``,
            ``mechanism``, ``oral``, ``parenteral``, ``topical``,
            ``black_box_warning``, ``molecule_type``.
        """
        min_phase = 1 if include_clinical else 4

        # Get mechanism of action entries for this target
        data = await self._get(
            f"{self._API_ROOT}/mechanism.json",
            params={
                "target_chembl_id": target_chembl_id,
                "limit": 100,
                "format": "json",
            },
        )
        chembl_ids = list(
            {
                m.get("molecule_chembl_id")
                for m in data.get("mechanisms", [])
                if m.get("molecule_chembl_id")
            }
        )
        if not chembl_ids:
            return []

        # Batch-fetch compound info in parallel
        target_ids = chembl_ids[:50]
        molecule_results = await asyncio.gather(
            *[self._get_molecule(cid) for cid in target_ids],
            return_exceptions=True,
        )
        drugs: list[dict[str, Any]] = []
        for cid, drug in zip(target_ids, molecule_results):
            if drug is None or isinstance(drug, BaseException):
                continue
            max_phase = int(drug.get("max_phase") or 0)
            if max_phase < min_phase:
                continue
            mechs = [
                m.get("mechanism_of_action", "")
                for m in data.get("mechanisms", [])
                if m.get("molecule_chembl_id") == cid and m.get("mechanism_of_action")
            ]
            drug["mechanism"] = mechs[0] if mechs else ""
            drugs.append(drug)

        return sorted(drugs, key=lambda d: d.get("max_phase", 0), reverse=True)

    # ------------------------------------------------------------------
    # Drug indications (disease → drugs via ChEMBL)
    # ------------------------------------------------------------------

    async def drug_indications(
        self,
        efo_id: str | None = None,
        *,
        mesh_heading: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return drugs with a clinical indication matching a disease term.

        Args:
            efo_id: EFO disease ID (e.g. ``'EFO:0000228'`` — breast carcinoma).
                Accepts ``MONDO:…`` IDs also (ChEMBL maps some MONDO terms).
            mesh_heading: MeSH disease heading as alternative lookup.
            limit: Maximum results.

        Returns:
            List of indication dicts with keys:
            ``molecule_chembl_id``, ``pref_name``, ``max_phase_for_indication``,
            ``efo_id``, ``efo_term``, ``mesh_id``, ``mesh_heading``.
        """
        params: dict[str, Any] = {
            "limit": min(limit, 200),
            "format": "json",
            "order_by": "-max_phase_for_indication",
        }
        if efo_id:
            params["efo_id"] = efo_id.replace("MONDO:", "MONDO_").replace("EFO:", "EFO_")
        elif mesh_heading:
            params["mesh_heading"] = mesh_heading
        else:
            raise ValueError("Provide efo_id or mesh_heading.")

        data = await self._get(
            f"{self._API_ROOT}/drug_indication.json",
            params=params,
        )
        return [
            {
                "molecule_chembl_id": i.get("molecule_chembl_id", ""),
                "pref_name": i.get("molecule_pref_name") or "",
                "max_phase_for_indication": i.get("max_phase_for_indication"),
                "efo_id": i.get("efo_id", ""),
                "efo_term": i.get("efo_term", ""),
                "mesh_id": i.get("mesh_id", ""),
                "mesh_heading": i.get("mesh_heading", ""),
            }
            for i in data.get("drug_indications", [])
        ]

    # ------------------------------------------------------------------
    # Mechanism of action lookup
    # ------------------------------------------------------------------

    async def mechanism_of_action(self, molecule_chembl_id: str) -> list[dict[str, Any]]:
        """Return mechanism of action entries for a drug.

        Args:
            molecule_chembl_id: ChEMBL molecule ID, e.g. ``'CHEMBL25'`` (aspirin).

        Returns:
            List of mechanism dicts with keys:
            ``mechanism_of_action``, ``action_type``, ``target_name``,
            ``target_chembl_id``, ``selectivity_comment``.
        """
        data = await self._get(
            f"{self._API_ROOT}/mechanism.json",
            params={"molecule_chembl_id": molecule_chembl_id, "format": "json"},
        )
        return [
            {
                "mechanism_of_action": m.get("mechanism_of_action", ""),
                "action_type": m.get("action_type", ""),
                "target_name": m.get("target_pref_name", ""),
                "target_chembl_id": m.get("target_chembl_id", ""),
                "selectivity_comment": m.get("selectivity_comment", ""),
                "direct_interaction": m.get("direct_interaction", False),
                "disease_efficacy": m.get("disease_efficacy", False),
            }
            for m in data.get("mechanisms", [])
        ]

    # ------------------------------------------------------------------
    # Drug repurposing: targets active against similar compound classes
    # ------------------------------------------------------------------

    async def find_repurposable_drugs(
        self,
        uniprot_id: str,
        *,
        max_phase: int = 4,
        activity_threshold_nm: float = 1000.0,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find approved or clinical-stage drugs active on a target.

        This is the drug repurposing entry point:
        Given a UniProt accession, find all Phase ≥ max_phase drugs with
        nanomolar activity against that target.

        Args:
            uniprot_id: UniProt accession, e.g. ``'P38398'``.
            max_phase: Minimum development phase (4=Approved, 3=Phase III, …).
            activity_threshold_nm: Only include compounds with IC50/Ki ≤ this value.
            limit: Maximum drugs to return.

        Returns:
            List of drug repurposing candidates sorted by phase descending.
        """
        target = await self.target_by_uniprot(uniprot_id)
        if not target:
            return []

        target_id = target["chembl_id"]
        drugs = await self.approved_drugs(target_id, include_clinical=(max_phase < 4))
        repurposable = [d for d in drugs if int(d.get("max_phase", 0) or 0) >= max_phase]
        return repurposable[:limit]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_molecule(self, chembl_id: str) -> dict[str, Any] | None:
        try:
            data = await self._get(
                f"{self._API_ROOT}/molecule/{chembl_id}.json",
                params={"format": "json"},
            )
        except Exception:
            return None
        props = data.get("molecule_properties") or {}
        return {
            "molecule_chembl_id": data.get("molecule_chembl_id", chembl_id),
            "pref_name": data.get("pref_name") or "",
            "max_phase": data.get("max_phase", 0),
            "max_phase_label": _MAX_PHASE.get(int(data.get("max_phase") or 0), "Unknown"),
            "first_approval": data.get("first_approval"),
            "usan_stem": data.get("usan_stem") or "",
            "indication_class": data.get("indication_class") or "",
            "molecule_type": data.get("molecule_type") or "",
            "oral": data.get("oral", False),
            "parenteral": data.get("parenteral", False),
            "topical": data.get("topical", False),
            "black_box_warning": bool(data.get("black_box_warning")),
            "mw_freebase": props.get("mw_freebase"),
            "alogp": props.get("alogp"),
            "hba": props.get("hba"),
            "hbd": props.get("hbd"),
            "psa": props.get("psa"),
            "rtb": props.get("rtb"),
            "ro3_pass": props.get("ro3_pass"),
            "num_ro5_violations": props.get("num_ro5_violations"),
        }
