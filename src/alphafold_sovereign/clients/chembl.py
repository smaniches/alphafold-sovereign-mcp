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
import math
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

# Max phase → development stage
_MAX_PHASE: dict[int, str] = {
    4: "Approved",
    3: "Phase III",
    2: "Phase II",
    1: "Phase I",
    0: "Preclinical",
    -1: "Withdrawn",
}


def _coerce_phase(value: Any) -> float:
    """Coerce a ChEMBL ``max_phase`` value to a float.

    ChEMBL serves ``max_phase`` as a JSON string (e.g. ``"4.0"``), a number,
    or ``null``. ``int("4.0")`` raises ``ValueError``; inside ``approved_drugs``
    that exception was absorbed by ``asyncio.gather(return_exceptions=True)``
    and silently dropped every drug. This coercion accepts any of those forms
    and returns ``0.0`` for anything unparseable.
    """
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _bioactivity_nm(value: Any) -> float | None:
    """Retain missing nM measurements as unknown, never as 0 nM."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("ChEMBL standard_value: invalid boolean measurement")
    try:
        measured = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("ChEMBL standard_value: invalid numeric measurement") from exc
    if not math.isfinite(measured) or measured < 0:
        raise ValueError("ChEMBL standard_value: nonfinite or negative measurement")
    return measured


def _valid_phase(value: Any) -> bool:
    """Only observed finite ChEMBL development phases can support drug counts."""
    if value is None or isinstance(value, bool):
        return False
    try:
        phase = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(phase) and -1 <= phase <= 4


MAX_MECHANISM_MOLECULES = 200
"""Upper bound on distinct mechanism-linked molecules fetched per target.

Live ChEMBL 37 totals for heavily drugged single proteins (EGFR 76 distinct
molecules over 90 mechanism rows, HRH1 72 rows, DRD2 68 rows) sit well below
this bound; beyond it a complete count is refused rather than truncated.
"""

_MECHANISM_PAGE_SIZE = 100
_MAX_MECHANISM_PAGES = 5


def _page_total(page_meta: Any) -> int:
    """Return the verified ``page_meta.total_count`` of a ChEMBL list response."""
    if not isinstance(page_meta, dict):
        raise ValueError("ChEMBL mechanism pagination cannot be verified")
    total_count = page_meta.get("total_count")
    if not isinstance(total_count, int) or isinstance(total_count, bool) or total_count < 0:
        raise ValueError("ChEMBL mechanism pagination incomplete")
    return total_count


def _verify_complete_mechanisms(mechanisms: list[Any], page_meta: Any, unique_ids: int) -> None:
    """Refuse counts when the paginated, identified upstream sample is incomplete."""
    if unique_ids > MAX_MECHANISM_MOLECULES:
        raise ValueError(
            f"ChEMBL target has more than {MAX_MECHANISM_MOLECULES} mechanism candidates"
        )
    if _page_total(page_meta) != len(mechanisms):
        raise ValueError("ChEMBL mechanism pagination incomplete")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("molecule_chembl_id"), str)
        or not item["molecule_chembl_id"]
        for item in mechanisms
    ):
        raise ValueError("ChEMBL mechanism identity incomplete")


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
        """Resolve an exact UniProt accession to an individual ChEMBL protein.

        The accession filter alone can also match complexes and protein
        families. These are not interchangeable with a single protein for
        drug-precedent attribution. Require an independently corroborated
        accession, a single-protein target, and complete mapping pagination.

        Returns None only when the filtered search has zero observed hits.
        An ambiguous or malformed response raises rather than inventing
        evidence of a specific target or absence of a target.
        """
        data = await self._get(
            f"{self._API_ROOT}/target.json",
            params={
                "target_components__accession": uniprot_id,
                "target_type": "SINGLE PROTEIN",
                "limit": 100,
                "format": "json",
            },
        )
        targets = data.get("targets")
        page_meta = data.get("page_meta")
        if not isinstance(targets, list) or not isinstance(page_meta, dict):
            raise ValueError("ChEMBL target response missing list or pagination metadata")
        total_count = page_meta.get("total_count")
        if (
            not isinstance(total_count, int)
            or isinstance(total_count, bool)
            or total_count != len(targets)
        ):
            raise ValueError("ChEMBL target lookup pagination cannot be verified")
        if not targets:
            return None
        if len(targets) != 1:
            raise ValueError("ChEMBL UniProt accession has ambiguous individual protein targets")
        target = targets[0]
        if not isinstance(target, dict) or target.get("target_type") != "SINGLE PROTEIN":
            raise ValueError("ChEMBL target result is not a verified single protein")
        components = target.get("target_components")
        if not isinstance(components, list) or not any(
            isinstance(component, dict) and component.get("accession") == uniprot_id
            for component in components
        ):
            raise ValueError("ChEMBL target result does not verify the requested UniProt accession")
        chembl_id = target.get("target_chembl_id")
        if not isinstance(chembl_id, str) or not chembl_id:
            raise ValueError("ChEMBL protein target has no valid identifier")
        return {
            "chembl_id": chembl_id,
            "pref_name": target.get("pref_name", ""),
            "target_type": target["target_type"],
            "organism": target.get("organism", ""),
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
            max_value_nm: Filter the source-reported numeric standard_value
                on the ChEMBL server. This does NOT prove a measurement is
                below the threshold: inequalities (e.g. ">10 nM") are
                censored observations, and must be interpreted using
                ``value_relation``.
            limit: Maximum results.

        Returns:
            List of activity dicts with keys:
            ``molecule_chembl_id``, ``pref_name``, ``activity_type``,
            ``value_nm``, ``units``, ``value_relation``,
            ``assay_description``, ``document_year``, ``molecule_smiles``.
            Missing nM values remain None. A numeric threshold filter and
            a censored bound do not constitute verified potency or binding.
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
                    "value_nm": _bioactivity_nm(a.get("standard_value")),
                    "value_relation": a.get("standard_relation"),
                    "units": a.get("standard_units"),
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
        require_complete: bool = False,
    ) -> list[dict[str, Any]]:
        """Return known drugs (Phase ≥ 1) for a ChEMBL target.

        Args:
            target_chembl_id: ChEMBL target ID.
            include_clinical: If ``True``, include Phase I–III (not just approved).
            require_complete: Reject partial molecule retrieval, truncated
                results, or invalid development-stage metadata. Required when
                computing counts or candidate lists that imply completeness.
                Default remains best-effort for existing callers.

        Returns:
            List of drug dicts with keys:
            ``molecule_chembl_id``, ``pref_name``, ``max_phase``,
            ``first_approval``, ``usan_stem``, ``indication_class``,
            ``mechanism``, ``oral``, ``parenteral``, ``topical``,
            ``black_box_warning``, ``molecule_type``.
        """
        min_phase = 1 if include_clinical else 4

        # Get mechanism of action entries for this target, following the
        # offset pagination that ChEMBL reports in ``page_meta`` so a heavily
        # drugged target (EGFR: 90 mechanism rows) is not silently truncated.
        mechanisms: list[Any] = []
        page_meta: Any = None
        for page in range(_MAX_MECHANISM_PAGES):
            data = await self._get(
                f"{self._API_ROOT}/mechanism.json",
                params={
                    "target_chembl_id": target_chembl_id,
                    "limit": _MECHANISM_PAGE_SIZE,
                    "offset": page * _MECHANISM_PAGE_SIZE,
                    "format": "json",
                },
            )
            page_rows = data.get("mechanisms")
            if not isinstance(page_rows, list):
                raise ValueError("ChEMBL mechanism response missing a valid mechanisms list")
            mechanisms.extend(page_rows)
            page_meta = data.get("page_meta")
            if (
                len(page_rows) < _MECHANISM_PAGE_SIZE
                or not isinstance(page_meta, dict)
                or not isinstance(page_meta.get("total_count"), int)
                or len(mechanisms) >= page_meta["total_count"]
            ):
                break
        chembl_ids = sorted(
            {
                molecule_id
                for item in mechanisms
                if isinstance(item, dict)
                for molecule_id in [item.get("molecule_chembl_id")]
                if isinstance(molecule_id, str) and molecule_id
            }
        )
        if not chembl_ids and not require_complete:
            return []

        # Best effort remains supported, but published counts must be complete.
        if require_complete:
            _verify_complete_mechanisms(mechanisms, page_meta, len(chembl_ids))
        if not chembl_ids:
            return []

        # Batch-fetch compound info in parallel
        target_ids = chembl_ids[:MAX_MECHANISM_MOLECULES]
        molecule_results = await asyncio.gather(
            *[self._get_molecule(cid) for cid in target_ids],
            return_exceptions=True,
        )
        incomplete = any(
            drug is None
            or isinstance(drug, BaseException)
            or not drug.get("max_phase_known", True)
            or not drug.get("molecule_id_verified", False)
            or drug.get("max_phase_label") == "Unknown"
            for drug in molecule_results
        )
        if require_complete and incomplete:
            raise ValueError("ChEMBL molecule metadata incomplete: drug count not assessed")

        drugs: list[dict[str, Any]] = []
        for cid, drug in zip(target_ids, molecule_results):
            if drug is None or isinstance(drug, BaseException):
                continue
            if not drug.get("max_phase_known", True) or drug.get("max_phase_label") == "Unknown":
                continue
            max_phase = _coerce_phase(drug.get("max_phase"))
            if max_phase < min_phase:
                continue
            mechs = [
                m.get("mechanism_of_action", "")
                for m in mechanisms
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
            # ChEMBL's orderable field is ``max_phase_for_ind``;
            # ``-max_phase_for_indication`` returns HTTP 400.
            "order_by": "-max_phase_for_ind",
        }
        if efo_id:
            # ChEMBL stores ontology IDs in native colon form (``EFO:0000305``);
            # rewriting the colon to an underscore returns zero rows.
            params["efo_id"] = efo_id
        elif mesh_heading:
            params["mesh_heading"] = mesh_heading
        else:
            raise ValueError("Provide efo_id or mesh_heading.")

        data = await self._get(
            f"{self._API_ROOT}/drug_indication.json",
            params=params,
        )
        # A 200 response without the documented list (for example an error
        # envelope) is malformed, not an observed empty indication page.
        rows = data.get("drug_indications")
        if not isinstance(rows, list) or not all(isinstance(i, dict) for i in rows):
            raise ValueError("ChEMBL drug_indication response missing a valid list")
        return [
            {
                "molecule_chembl_id": i.get("molecule_chembl_id", ""),
                "pref_name": i.get("molecule_pref_name") or "",
                "max_phase_for_indication": i.get("max_phase_for_ind"),
                "efo_id": i.get("efo_id", ""),
                "efo_term": i.get("efo_term", ""),
                "mesh_id": i.get("mesh_id", ""),
                "mesh_heading": i.get("mesh_heading", ""),
            }
            for i in rows
        ]

    async def molecule_names(self, chembl_ids: list[str]) -> dict[str, str]:
        """Resolve a batch of molecule ChEMBL IDs to their preferred names.

        The drug-indication endpoint returns molecule IDs but not names; this
        backfills them, chunking large inputs into requests of 50 IDs so no
        ID is silently dropped.

        Args:
            chembl_ids: Molecule ChEMBL IDs, e.g. ``['CHEMBL941', 'CHEMBL1421']``.

        Returns:
            Mapping of ``molecule_chembl_id`` → ``pref_name`` (entries without
            a name are omitted).
        """
        ids = [c for c in dict.fromkeys(chembl_ids) if c]  # dedupe, drop blanks
        if not ids:
            return {}
        names: dict[str, str] = {}
        for start in range(0, len(ids), 50):
            chunk = ids[start : start + 50]
            try:
                data = await self._get(
                    f"{self._API_ROOT}/molecule.json",
                    params={
                        "molecule_chembl_id__in": ",".join(chunk),
                        "limit": 50,
                        "format": "json",
                    },
                )
            except Exception as exc:
                logger.warning("chembl.molecule_names.failed", exc=str(exc))
                continue
            for m in data.get("molecules", []):
                cid = m.get("molecule_chembl_id")
                name = m.get("pref_name")
                if cid and name:
                    names[cid] = name
        return names

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
        Given a UniProt accession, find all Phase ≥ max_phase drugs whose
        ChEMBL mechanism-of-action record names that target.

        Args:
            uniprot_id: UniProt accession, e.g. ``'P38398'``.
            max_phase: Minimum development phase (4=Approved, 3=Phase III, …).
            activity_threshold_nm: Accepted for API stability but **not
                applied**: candidates come from mechanism records, which carry
                no potency value. Use :meth:`bioactivities` for IC50/Ki filtering.
            limit: Maximum drugs to return.

        Returns:
            List of drug repurposing candidates sorted by phase descending.
        """
        target = await self.target_by_uniprot(uniprot_id)
        if not target:
            return []

        target_id = target["chembl_id"]
        drugs = await self.approved_drugs(
            target_id, include_clinical=(max_phase < 4), require_complete=True
        )
        repurposable = [d for d in drugs if _coerce_phase(d.get("max_phase")) >= max_phase]
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
        except Exception as exc:
            logger.warning("chembl.molecule.failed", chembl_id=chembl_id, exc=str(exc))
            return None
        identity = data.get("molecule_chembl_id")
        if identity is not None and identity != chembl_id:
            raise ValueError("ChEMBL molecule response identifier mismatch")
        props = data.get("molecule_properties") or {}
        raw_phase = data.get("max_phase")
        phase = _coerce_phase(raw_phase)
        phase_known = _valid_phase(raw_phase)
        phase_label = "Unknown"
        if phase_known:
            phase_label = (
                _MAX_PHASE.get(int(phase), f"Phase {phase:g}")
                if phase.is_integer()
                else f"Phase {phase:g}"
            )
        return {
            "molecule_chembl_id": data.get("molecule_chembl_id", chembl_id),
            "pref_name": data.get("pref_name") or "",
            "max_phase": phase,
            "max_phase_known": phase_known,
            "molecule_id_verified": identity == chembl_id,
            "max_phase_label": phase_label,
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
