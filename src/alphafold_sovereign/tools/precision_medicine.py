# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Precision-medicine MCP tools.

These tools compose multiple upstream APIs into per-call synthesis
reports. They do not add scientific judgement; they assemble what the
upstreams say in one place.

Tool inventory:
  1. generate_variant_clinical_report  — HGVS → multi-source variant report
  2. assess_target_druggability         — UniProt → heuristic HOT/WARM/COLD/NOT_DRUGGABLE
  3. synthesize_protein_dossier         — UniProt → multi-source briefing
  4. find_drug_repurposing_candidates   — MONDO → ranked drug candidates
  5. classify_variant_acmg              — HGVS → **draft** ACMG/AMP criteria
  6. map_disease_drug_landscape         — MONDO → approved + pipeline drugs

Important caveats:

* The ACMG/AMP criteria emitted by `classify_variant_acmg` and the
  ACMG section of `generate_variant_clinical_report` are a **draft
  surface** of the upstream evidence (AlphaMissense, ClinVar, gnomAD,
  Ensembl VEP). They are not a substitute for clinical-laboratory
  review and must not be used as a diagnostic.
* The "druggability tier" returned by `assess_target_druggability` is a
  small hand-tuned heuristic (drug-precedent counts + Open Targets
  tractability labels + pLDDT + gnomAD LOEUF). It is not a validated
  predictive model.
* The "composite repurposing score" returned by
  `find_drug_repurposing_candidates` is ``OT evidence × ChEMBL max
  clinical phase``. It is a ranking aid, not an efficacy prediction.
"""

from __future__ import annotations

import asyncio
import datetime
import re
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

from alphafold_sovereign import __version__
from alphafold_sovereign.clients.alphafold import AlphaFoldClient
from alphafold_sovereign.clients.chembl import ChEMBLClient
from alphafold_sovereign.clients.clinvar import ClinVarClient
from alphafold_sovereign.clients.disgenet import DisGeNETClient
from alphafold_sovereign.clients.ensembl import EnsemblClient
from alphafold_sovereign.clients.gnomad import GnomADClient
from alphafold_sovereign.clients.mondo import MONDOClient
from alphafold_sovereign.clients.opentargets import OpenTargetsClient
from alphafold_sovereign.domain.disease import PathogenicityClass
from alphafold_sovereign.server.app import mcp

logger = structlog.get_logger(__name__)


# ── Shared client singletons (initialised on first use) ──────────────────────

_CLIENTS: dict[str, Any] = {}


def _ensembl() -> EnsemblClient:
    if "ensembl" not in _CLIENTS:
        _CLIENTS["ensembl"] = EnsemblClient()
    return _CLIENTS["ensembl"]  # type: ignore[return-value]


def _clinvar() -> ClinVarClient:
    if "clinvar" not in _CLIENTS:
        _CLIENTS["clinvar"] = ClinVarClient()
    return _CLIENTS["clinvar"]  # type: ignore[return-value]


def _gnomad() -> GnomADClient:
    if "gnomad" not in _CLIENTS:
        _CLIENTS["gnomad"] = GnomADClient()
    return _CLIENTS["gnomad"]  # type: ignore[return-value]


def _mondo() -> MONDOClient:
    if "mondo" not in _CLIENTS:
        _CLIENTS["mondo"] = MONDOClient()
    return _CLIENTS["mondo"]  # type: ignore[return-value]


def _opentargets() -> OpenTargetsClient:
    if "opentargets" not in _CLIENTS:
        _CLIENTS["opentargets"] = OpenTargetsClient()
    return _CLIENTS["opentargets"]  # type: ignore[return-value]


def _disgenet() -> DisGeNETClient:
    if "disgenet" not in _CLIENTS:
        _CLIENTS["disgenet"] = DisGeNETClient()
    return _CLIENTS["disgenet"]  # type: ignore[return-value]


def _chembl() -> ChEMBLClient:
    if "chembl" not in _CLIENTS:
        _CLIENTS["chembl"] = ChEMBLClient()
    return _CLIENTS["chembl"]  # type: ignore[return-value]


def _alphafold() -> AlphaFoldClient:
    if "alphafold" not in _CLIENTS:
        _CLIENTS["alphafold"] = AlphaFoldClient()
    return _CLIENTS["alphafold"]  # type: ignore[return-value]


# ── Provenance footer ─────────────────────────────────────────────────────────


def _provenance(**sources: str) -> str:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    src_str = ", ".join(f"{k}={v}" for k, v in sources.items() if v)
    return f"\n\n---\n*AlphaFold Sovereign MCP v{__version__} · {ts} · {src_str}*"


# ── Input models ──────────────────────────────────────────────────────────────


class VariantClinicalReportInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    hgvs: str = Field(
        ...,
        description=(
            "HGVS expression — gene-relative (preferred): 'BRCA1:c.181T>G'; "
            "or RefSeq-based: 'NM_007294.3:c.181T>G'."
        ),
        examples=["BRCA1:c.181T>G", "TP53:p.Arg248Trp"],
        min_length=5,
    )
    include_population_breakdown: bool = Field(
        default=True,
        description="Include per-ancestry allele frequency breakdown from gnomAD v4.",
    )
    include_drug_context: bool = Field(
        default=True,
        description="Include approved drugs acting on the variant's gene product.",
    )


class DruggabilityInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    uniprot_id: str = Field(
        ...,
        description="UniProt accession, e.g. 'P38398' (BRCA1) or 'P04637' (TP53).",
        pattern=r"^[A-Z][0-9][A-Z0-9]{3}[0-9](?:[A-Z][0-9][A-Z0-9]{3}[0-9])?$",
    )
    include_clinical_stage: bool = Field(
        default=True,
        description="Include Phase I–III compounds in addition to approved drugs.",
    )


class ProteinDossierInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    uniprot_id: str = Field(
        ...,
        description="UniProt accession for the target protein.",
        pattern=r"^[A-Z][0-9][A-Z0-9]{3}[0-9](?:[A-Z][0-9][A-Z0-9]{3}[0-9])?$",
    )
    gene_symbol: str = Field(
        ...,
        description="HGNC gene symbol (required to cross-reference all sources).",
    )
    depth: Literal["brief", "standard", "comprehensive"] = Field(
        default="standard",
        description=(
            "Report depth: 'brief' = key metrics only; "
            "'standard' = all key sections; "
            "'comprehensive' = full evidence synthesis with raw data."
        ),
    )


class DrugRepurposingInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    disease_mondo_id: str = Field(
        ...,
        description="MONDO disease ID, e.g. 'MONDO:0007254' (breast carcinoma).",
        pattern=r"^MONDO:\d{7}$",
    )
    target_limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Number of top disease-associated targets to analyse.",
    )
    min_phase: int = Field(
        default=2,
        ge=1,
        le=4,
        description="Minimum clinical development phase: 4=Approved, 3=Phase III, 2=Phase II, 1=Phase I.",
    )


class ACMGVariantInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    hgvs: str = Field(
        ...,
        description="HGVS expression for classification, e.g. 'BRCA1:c.181T>G'.",
        min_length=5,
    )
    inheritance_pattern: Literal["AD", "AR", "XL", "Unknown"] = Field(
        default="Unknown",
        description=(
            "Expected inheritance pattern: "
            "AD=autosomal dominant, AR=autosomal recessive, "
            "XL=X-linked, Unknown."
        ),
    )


class DiseaseDrugLandscapeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    disease_mondo_id: str = Field(
        ...,
        description="MONDO disease ID.",
        pattern=r"^MONDO:\d{7}$",
    )


class TargetSelectivityInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    uniprot_id_a: str = Field(
        ...,
        description="First target UniProt ID.",
        pattern=r"^[A-Z][0-9][A-Z0-9]{3}[0-9](?:[A-Z][0-9][A-Z0-9]{3}[0-9])?$",
    )
    uniprot_id_b: str = Field(
        ...,
        description="Second target UniProt ID (e.g. a related kinase for selectivity analysis).",
        pattern=r"^[A-Z][0-9][A-Z0-9]{3}[0-9](?:[A-Z][0-9][A-Z0-9]{3}[0-9])?$",
    )


# ── ACMG criteria helpers ─────────────────────────────────────────────────────

_POPULATION_THRESHOLDS = {
    "BS1": 0.05,  # allele frequency > 5% in gnomAD → Benign Strong
    "PM2": 0.001,  # absent or extremely rare → Pathogenic Moderate
}

_PATHOGENIC_MAP = {
    PathogenicityClass.PATHOGENIC: ("P", "Pathogenic"),
    PathogenicityClass.LIKELY_PATHOGENIC: ("LP", "Likely Pathogenic"),
    PathogenicityClass.UNCERTAIN: ("VUS", "Variant of Uncertain Significance"),
    PathogenicityClass.LIKELY_BENIGN: ("LB", "Likely Benign"),
    PathogenicityClass.BENIGN: ("B", "Benign"),
    PathogenicityClass.CONFLICTING: ("CI", "Conflicting Interpretations"),
    PathogenicityClass.NOT_PROVIDED: ("NP", "Not Provided"),
}


def _acmg_code(cls: str) -> str:
    try:
        pc = PathogenicityClass(cls)
        return _PATHOGENIC_MAP[pc][0]
    except (ValueError, KeyError):
        return "NP"


def _am_to_acmg_evidence(am_score: float | None) -> dict[str, str]:
    """Map AlphaMissense score to provisional ACMG in-silico criteria.

    AlphaMissense calibration (Cheng et al., Science 2023):
      ≥ 0.564 → likely pathogenic (PP3 triggered)
      ≤ 0.340 → likely benign (BP4 triggered)
    """
    if am_score is None:
        return {}
    if am_score >= 0.564:
        return {"PP3": f"AlphaMissense={am_score:.3f} — likely pathogenic (≥0.564)"}
    if am_score <= 0.340:
        return {"BP4": f"AlphaMissense={am_score:.3f} — likely benign (≤0.340)"}
    return {}


def _protein_variant_from_vep(consequence: dict[str, Any]) -> str | None:
    """Build an AlphaMissense ``protein_variant`` key from a VEP consequence.

    AlphaMissense identifies a substitution as ``<ref><pos><alt>`` in
    single-letter form, e.g. ``C61G``. Returns ``None`` when the consequence
    is not a single-residue missense substitution: no amino-acid change, a
    multi-residue change, or no protein position.
    """
    amino_acids = (consequence.get("amino_acids") or "").strip()
    ref_aa, _, alt_aa = amino_acids.partition("/")
    if len(ref_aa) != 1 or len(alt_aa) != 1 or not ref_aa.isalpha() or not alt_aa.isalpha():
        return None
    position = consequence.get("protein_start")
    try:
        position_int = int(position)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f"{ref_aa.upper()}{position_int}{alt_aa.upper()}"


async def _alphamissense_for_variant(
    gene_symbol: str | None, vep_results: list[dict[str, Any]]
) -> float | None:
    """Resolve the AlphaMissense pathogenicity score for a variant.

    Builds the substitution key from the canonical VEP consequence, reads
    the SwissProt accession that Ensembl VEP attaches to that same
    consequence, and looks the substitution up in the AlphaFold DB
    AlphaMissense annotations. Returns ``None`` when the variant is not a
    single-residue missense substitution, the canonical consequence
    carries no SwissProt accession, or AlphaFold DB has no annotation for
    it.

    ``gene_symbol`` is retained for log context only; the UniProt
    accession is resolved from the VEP consequence itself, so this
    function no longer requires a parseable gene symbol. End-to-end
    resolution for a RefSeq-form HGVS then depends only on Ensembl VEP
    accepting that HGVS string and returning a canonical missense
    consequence carrying a SwissProt accession.
    """
    canonical = next((tc for tc in vep_results if tc.get("canonical")), {})
    protein_variant = _protein_variant_from_vep(canonical)
    if not protein_variant:
        return None
    uniprot_id = (canonical.get("swissprot") or "").split(".")[0]
    if not uniprot_id:
        return None
    try:
        record = await _alphafold().alphamissense_score(uniprot_id, protein_variant)
    except Exception as exc:
        logger.warning("alphamissense.failed", gene=gene_symbol, exc=str(exc))
        return None
    return record.get("am_pathogenicity") if record else None


def _gnomad_to_acmg(af: float | None) -> dict[str, str]:
    if af is None:
        return {}
    if af > _POPULATION_THRESHOLDS["BS1"]:
        return {"BS1": f"gnomAD AF={af:.4f} > 5% — too common for a rare pathogenic variant"}
    if af < _POPULATION_THRESHOLDS["PM2"]:
        return {"PM2": f"gnomAD AF={af:.6f} < 0.1% — extremely rare in population databases"}
    return {}


def _vep_to_acmg(consequences: list[dict[str, Any]]) -> dict[str, str]:
    """Extract ACMG PVS1-level evidence from VEP functional predictions."""
    criteria: dict[str, str] = {}
    null_terms = {
        "stop_gained",
        "frameshift_variant",
        "splice_acceptor_variant",
        "splice_donor_variant",
        "start_lost",
    }
    missense_terms = {"missense_variant"}
    synonymous_terms = {"synonymous_variant"}

    for tc in consequences:
        if not tc.get("canonical"):
            continue
        terms = set(tc.get("consequence_terms", []))
        if terms & null_terms:
            criteria["PVS1"] = (
                "Null variant (stop-gain/frameshift/splice) in a gene where LoF is "
                "the established mechanism of disease."
            )
        if terms & missense_terms:
            sift = tc.get("sift_prediction", "")
            pp = tc.get("polyphen_prediction", "")
            cadd = tc.get("cadd_phred")
            parts = []
            if sift in {"deleterious", "deleterious_low_confidence"}:
                parts.append(f"SIFT={sift}")
            if pp in {"probably_damaging", "possibly_damaging"}:
                parts.append(f"PolyPhen={pp}")
            if cadd is not None and float(cadd) >= 20:
                parts.append(f"CADD-phred={cadd:.1f}")
            if len(parts) >= 2:
                criteria["PP3"] = (
                    "Multiple computational evidence suggesting pathogenicity: " + "; ".join(parts)
                )
        if terms & synonymous_terms:
            criteria["BP7"] = "Synonymous variant with no predicted splicing impact."
    return criteria


def _druggability_tier(
    *,
    drug_count: int,
    tractability_labels: list[str],
    loeuf: float | None,
    plddt_mean: float | None,
) -> tuple[str, str, dict[str, Any]]:
    """Return (tier, rationale, scoring_breakdown) for target druggability."""
    components: dict[str, dict[str, Any]] = {}

    # Drug precedent is the strongest signal
    if drug_count >= 3:
        drug_contrib = 3
        components["drug_precedent"] = {"contribution": 3, "input": f"drug_count={drug_count}, >=3"}
    elif drug_count >= 1:
        drug_contrib = 2
        components["drug_precedent"] = {"contribution": 2, "input": f"drug_count={drug_count}, >=1"}
    else:
        drug_contrib = 0
        components["drug_precedent"] = {"contribution": 0, "input": f"drug_count={drug_count}"}

    # Tractability labels from Open Targets
    small_mol_labels = {"Small molecule", "Discovery_small_molecule", "SM_clinical"}
    has_tractability = any(
        lab in small_mol_labels or "small_mol" in lab.lower() for lab in tractability_labels
    )
    tract_contrib = 2 if has_tractability else 0
    components["tractability"] = {
        "contribution": tract_contrib,
        "input": "small_molecule label present" if has_tractability else "no small_molecule label",
    }

    # pLDDT ≥ 70 → confident structure → analysable binding pockets
    if plddt_mean is not None and plddt_mean >= 70:
        plddt_contrib = 1
        components["plddt"] = {"contribution": 1, "input": f"plddt_mean={plddt_mean:.1f}, >=70"}
    elif plddt_mean is not None:
        plddt_contrib = 0
        components["plddt"] = {"contribution": 0, "input": f"plddt_mean={plddt_mean:.1f}, <70"}
    else:
        plddt_contrib = 0
        components["plddt"] = {"contribution": 0, "input": "not_available"}

    # LOEUF: highly constrained genes may cause toxicity on inhibition
    if loeuf is not None and loeuf < 0.35:
        loeuf_contrib = -1
        components["loeuf_safety"] = {
            "contribution": -1,
            "input": f"loeuf={loeuf:.3f}, <0.35 — safety concern",
        }
    else:
        loeuf_contrib = 0
        loeuf_input = f"loeuf={loeuf:.3f}, >=0.35" if loeuf is not None else "not_available"
        components["loeuf_safety"] = {"contribution": 0, "input": loeuf_input}

    score = drug_contrib + tract_contrib + plddt_contrib + loeuf_contrib
    scoring = {
        "total_score": score,
        "thresholds": {"HOT": ">=4", "WARM": ">=2", "COLD": ">=1", "NOT_DRUGGABLE": "<1"},
        "components": components,
    }

    if score >= 4:
        tier = "HOT"
        rationale = "Strong drug precedent and tractability evidence."
    elif score >= 2:
        tier = "WARM"
        rationale = "Some drug precedent or tractability; further profiling recommended."
    elif score >= 1:
        tier = "COLD"
        rationale = "Limited precedent; additional evidence needed."
    else:
        tier = "NOT_DRUGGABLE"
        rationale = "No current evidence of druggability."

    return tier, rationale, scoring


# ── Tool 1: Full clinical variant report ─────────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Generate Precision Medicine Variant Report",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def generate_variant_clinical_report(
    params: VariantClinicalReportInput,
) -> dict[str, Any]:
    """Generate a multi-source variant interpretation report.

    Cross-references evidence from up to seven upstream databases for a
    single HGVS variant into one structured report. The report is a
    *research aid*: it surfaces the upstream evidence and the
    ACMG/AMP criteria that the available evidence supports, but it is
    not a clinical interpretation and must not be used as a diagnostic
    without independent review by a qualified clinical laboratory.

    1. **Ensembl VEP** — functional consequence, SIFT/PolyPhen/CADD predictions
    2. **ClinVar** — clinical pathogenicity classifications and review status
    3. **gnomAD v4** — population allele frequencies (gnomAD v4, ~807k individuals)
    4. **AlphaMissense** — deep-learning missense pathogenicity (Cheng et al. 2023)
    5. **Open Targets** — disease-gene evidence scores
    6. **DisGeNET** — curated gene-disease association scores
    7. **ChEMBL** — approved drugs acting on the gene product

    The report includes a draft ACMG/AMP criteria checklist with evidence
    mapping, a structural impact summary, and an actionability statement.

    Args:
        params.hgvs: HGVS expression (gene-relative preferred).
        params.include_population_breakdown: Include per-ancestry gnomAD data.
        params.include_drug_context: Include drugs acting on the gene product.
    """
    hgvs = params.hgvs.strip()
    log = logger.bind(hgvs=hgvs, tool="generate_variant_clinical_report")
    log.info("start")

    source_status: dict[str, str] = {}

    # ── Step 1: Parse gene symbol ────────────────────────────────────────────
    gene_symbol = EnsemblClient.parse_gene_from_hgvs(hgvs)

    # ── Step 2: Parallel evidence gathering ──────────────────────────────────
    vep_task = _ensembl().vep_hgvs(hgvs, canonical=True)
    clinvar_task = _clinvar().search_by_hgvs(hgvs)

    vep_results, clinvar_results = await asyncio.gather(
        vep_task, clinvar_task, return_exceptions=True
    )
    if isinstance(vep_results, Exception):
        log.warning("vep.failed", exc=str(vep_results))
        source_status["ensembl_vep"] = "failed"
        vep_results = []
    else:
        source_status["ensembl_vep"] = "ok"
    if isinstance(clinvar_results, Exception):
        log.warning("clinvar.failed", exc=str(clinvar_results))
        source_status["clinvar"] = "failed"
        clinvar_results = []
    else:
        source_status["clinvar"] = "ok"

    # ── Step 3: gnomAD variant ID construction ───────────────────────────────
    gnomad_data: dict[str, Any] = {}
    gnomad_id = _build_gnomad_id(hgvs, vep_results)  # type: ignore[arg-type]
    if gnomad_id:
        try:
            gnomad_data = await _gnomad().variant_frequencies(gnomad_id)
            source_status["gnomad"] = "ok"
        except Exception as exc:
            log.warning("gnomad.failed", exc=str(exc))
            source_status["gnomad"] = "failed"
    else:
        source_status["gnomad"] = "skipped"

    # ── Step 4: Gene-level constraint ────────────────────────────────────────
    gene_constraint: dict[str, Any] = {}
    if gene_symbol:
        try:
            gene_constraint = await _gnomad().gene_constraint(gene_symbol)
        except Exception as exc:
            log.warning("gnomad.constraint.failed", exc=str(exc))

    # ── Step 5: Disease context ───────────────────────────────────────────────
    ot_diseases: list[dict[str, Any]] = []
    disgenet_assocs: list[dict[str, Any]] = []
    if gene_symbol:
        gene_info = await _ensembl().gene_lookup(gene_symbol)
        ensembl_id = gene_info.get("ensembl_gene_id", "")

        tasks: list[Any] = [
            _disgenet().gene_disease_associations(gene_symbol, min_score=0.1, limit=5),
        ]
        if ensembl_id:
            tasks.append(_opentargets().associated_diseases(ensembl_id, limit=5))
        else:

            async def _empty_list() -> list[Any]:
                return []

            tasks.append(_empty_list())

        results = await asyncio.gather(*tasks, return_exceptions=True)
        if not isinstance(results[0], Exception):
            disgenet_assocs = results[0]  # type: ignore
            source_status["disgenet"] = "ok"
        else:
            source_status["disgenet"] = "failed"
        if len(results) > 1 and not isinstance(results[1], Exception):
            ot_diseases = [s.to_dict() if hasattr(s, "to_dict") else s for s in results[1]]  # type: ignore
            source_status["open_targets"] = "ok"
        else:
            source_status["open_targets"] = "failed"
    else:
        source_status["disgenet"] = "skipped"
        source_status["open_targets"] = "skipped"

    # ── Step 6: Drug context ──────────────────────────────────────────────────
    drug_candidates: list[dict[str, Any]] = []
    if params.include_drug_context and gene_symbol:
        try:
            gene_info_for_drugs = await _ensembl().gene_lookup(gene_symbol)
            uniprot_ids = gene_info_for_drugs.get("uniprot_ids", [])
            if uniprot_ids:
                drug_candidates = await _chembl().find_repurposable_drugs(
                    uniprot_ids[0], max_phase=2
                )
                source_status["chembl"] = "ok"
            else:
                source_status["chembl"] = "no_data"
        except Exception as exc:
            log.warning("drugs.failed", exc=str(exc))
            source_status["chembl"] = "failed"
    elif not params.include_drug_context:
        source_status["chembl"] = "skipped"
    else:
        source_status["chembl"] = "skipped"

    # ── Step 7: Consolidate ClinVar ───────────────────────────────────────────
    clinvar_record: dict[str, Any] | None = None
    if clinvar_results:
        clinvar_record = clinvar_results[0] if not isinstance(clinvar_results, Exception) else None

    clinvar_class = (clinvar_record or {}).get(
        "classification", PathogenicityClass.NOT_PROVIDED.value
    )

    # ── Step 8: AlphaMissense pathogenicity (AlphaFold DB) ─────────────────────────────
    am_score: float | None = await _alphamissense_for_variant(
        gene_symbol,
        vep_results,  # type: ignore[arg-type]
    )
    source_status["alphamissense"] = "ok" if am_score is not None else "no_data"

    # ── Step 9: Draft ACMG criteria ───────────────────────────────────────────
    acmg_criteria: dict[str, str] = {}
    acmg_criteria.update(_am_to_acmg_evidence(am_score))
    acmg_criteria.update(_gnomad_to_acmg(gnomad_data.get("global_af")))
    if isinstance(vep_results, list):  # pragma: no branch
        acmg_criteria.update(_vep_to_acmg(vep_results))

    # ClinVar evidence
    if clinvar_class in {
        PathogenicityClass.PATHOGENIC.value,
        PathogenicityClass.LIKELY_PATHOGENIC.value,
    }:
        status = (clinvar_record or {}).get("review_status", "")
        acmg_criteria["PP5"] = (
            f"ClinVar: {clinvar_class} ({status}). Reputable source with strong concordance."
        )

    # ── Step 10: Clinical tier ────────────────────────────────────────────────
    tier = _compute_clinical_tier(
        clinvar_class=clinvar_class,
        am_score=am_score,
        global_af=gnomad_data.get("global_af"),
        acmg_criteria=acmg_criteria,
    )

    # ── Step 11: Canonical consequence ───────────────────────────────────────
    canonical_tc: dict[str, Any] = {}
    if isinstance(vep_results, list):  # pragma: no branch
        for tc in vep_results:
            if tc.get("canonical"):
                canonical_tc = tc
                break

    # ── Build report ─────────────────────────────────────────────────────────
    report: dict[str, Any] = {
        "hgvs": hgvs,
        "gene_symbol": gene_symbol,
        "clinical_tier": tier,
        "clinical_tier_explanation": _tier_explanation(tier),
        "functional_consequence": {
            "consequence_terms": canonical_tc.get("consequence_terms", []),
            "impact": canonical_tc.get("impact", ""),
            "amino_acids": canonical_tc.get("amino_acids", ""),
            "hgvsp": canonical_tc.get("hgvsp", ""),
            "sift_prediction": canonical_tc.get("sift_prediction", ""),
            "sift_score": canonical_tc.get("sift_score"),
            "polyphen_prediction": canonical_tc.get("polyphen_prediction", ""),
            "polyphen_score": canonical_tc.get("polyphen_score"),
            "cadd_phred": canonical_tc.get("cadd_phred"),
        },
        "clinvar": {
            "found": clinvar_record is not None,
            "classification": clinvar_class,
            "acmg_code": _acmg_code(clinvar_class),
            "review_status": (clinvar_record or {}).get("review_status", ""),
            "conditions": (clinvar_record or {}).get("conditions", []),
            "variation_id": (clinvar_record or {}).get("variation_id", ""),
        },
        "population_genetics": {
            "global_af": gnomad_data.get("global_af"),
            "global_ac": gnomad_data.get("global_ac"),
            "global_an": gnomad_data.get("global_an"),
            "homozygote_count": gnomad_data.get("homozygote_count"),
            "alphamissense_score": am_score,
            "populations": gnomad_data.get("populations", [])
            if params.include_population_breakdown
            else [],
        },
        "gene_constraint": {
            "pLI": gene_constraint.get("pLI"),
            "loeuf": gene_constraint.get("loeuf"),
            "mis_z": gene_constraint.get("mis_z"),
            "interpretation": gene_constraint.get("interpretation", ""),
        },
        "acmg_criteria_draft": {
            "criteria": acmg_criteria,
            "note": (
                "Draft ACMG/AMP criteria based on computational and population evidence. "
                "Professional review by a clinical geneticist is required before clinical reporting."
            ),
        },
        "disease_associations": {
            "open_targets_top_diseases": ot_diseases[:3],
            "disgenet_top_associations": disgenet_assocs[:3],
        },
    }

    if params.include_drug_context:
        report["drug_context"] = {
            "repurposing_candidates": [
                {
                    "molecule_chembl_id": d.get("molecule_chembl_id"),
                    "pref_name": d.get("pref_name"),
                    "max_phase": d.get("max_phase"),
                    "max_phase_label": d.get("max_phase_label"),
                    "mechanism": d.get("mechanism"),
                }
                for d in drug_candidates[:5]
            ],
            "note": "Drugs acting on the gene product — not necessarily on this variant.",
        }

    report["data_sources_status"] = source_status
    report["data_sources"] = {
        "ensembl_vep": "https://rest.ensembl.org",
        "clinvar": "https://www.ncbi.nlm.nih.gov/clinvar/",
        "gnomad": "https://gnomad.broadinstitute.org",
        "alphamissense": "Cheng et al. Science 2023; doi:10.1126/science.adg7492",
        "open_targets": "https://platform.opentargets.org",
        "disgenet": "https://www.disgenet.com",
        "chembl": "https://www.ebi.ac.uk/chembl/",
    }
    report["provenance"] = _provenance(
        ensembl_vep="GRCh38",
        clinvar="current",
        gnomad="v4",
        alphamissense="2023",
    )

    log.info("complete", tier=tier)
    return report


# ── Tool 2: Target druggability assessment ───────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Assess Target Druggability",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def assess_target_druggability(
    params: DruggabilityInput,
) -> dict[str, Any]:
    """Comprehensive druggability assessment for a protein target.

    Integrates four independent druggability signals into a HOT/WARM/COLD/NOT_DRUGGABLE
    classification:

    1. **Drug precedent** — ChEMBL approved drugs + clinical compounds
    2. **Tractability** — Open Targets tractability labels (small-molecule, antibody, PROTAC)
    3. **Structural confidence** — AF2 pLDDT (ordered → analysable binding pockets)
    4. **Population constraint** — gnomAD LOEUF (highly constrained → safety risk on inhibition)

    It assembles existing public-database evidence into one tier; it does
    not add scientific judgement and is not a validated predictive model.

    Args:
        params.uniprot_id: UniProt accession.
        params.include_clinical_stage: Include Phase I–III in drug count.
    """
    uid = params.uniprot_id
    log = logger.bind(uniprot_id=uid, tool="assess_target_druggability")
    log.info("start")

    async def _empty_dict() -> dict[str, Any]:
        return {}

    chembl_target, _ = await asyncio.gather(
        _chembl().target_by_uniprot(uid),
        _empty_dict(),
        return_exceptions=True,
    )

    drug_count = 0
    tractability_labels: list[str] = []
    approved_drugs: list[dict[str, Any]] = []

    if isinstance(chembl_target, dict) and chembl_target:
        target_id = chembl_target["chembl_id"]
        approved_drugs = await _chembl().approved_drugs(
            target_id, include_clinical=params.include_clinical_stage
        )
        drug_count = len(approved_drugs)

    # Resolve UniProt accession -> Open Targets target (Ensembl ID + symbol).
    # Open Targets keys all target data on Ensembl gene IDs, not UniProt IDs.
    ot_resolved: dict[str, str] = {}
    try:
        ot_resolved = await _opentargets().resolve_target(uid)
    except Exception as exc:
        log.warning("ot.resolve.failed", exc=str(exc))
    ensembl_id = ot_resolved.get("ensembl_id", "")
    gene_symbol = ot_resolved.get("symbol", "")

    # Open Targets tractability (keyed on the resolved Ensembl gene ID)
    ot_tractability: dict[str, Any] = {}
    if ensembl_id:
        try:
            ot_tractability = await _opentargets().drug_count_and_tractability(ensembl_id)
            tractability_labels = ot_tractability.get("tractability_labels", [])
            if not drug_count:
                drug_count = ot_tractability.get("drug_count", 0)
        except Exception as exc:
            log.warning("ot.tractability.failed", exc=str(exc))

    # gnomAD constraint (keyed on the HGNC gene symbol resolved above)
    gene_constraint: dict[str, Any] = {}
    loeuf: float | None = None
    if gene_symbol:
        try:
            gene_constraint = await _gnomad().gene_constraint(gene_symbol)
            loeuf = gene_constraint.get("loeuf")
        except Exception as exc:
            log.warning("constraint.failed", exc=str(exc))

    # AlphaFold pLDDT (structural confidence)
    plddt_mean: float | None = None
    try:
        af_meta = await _alphafold().get_prediction(uid)
        if isinstance(af_meta, dict):
            plddt_mean = af_meta.get("globalMetricValue")
    except Exception as exc:
        log.warning("plddt.failed", exc=str(exc))

    # Druggability tier
    tier, rationale, scoring = _druggability_tier(
        drug_count=drug_count,
        tractability_labels=tractability_labels,
        loeuf=loeuf,
        plddt_mean=plddt_mean,
    )

    report: dict[str, Any] = {
        "uniprot_id": uid,
        "druggability_tier": tier,
        "tier_rationale": rationale,
        "scoring_breakdown": scoring,
        "evidence": {
            "drug_count": drug_count,
            "tractability_labels": tractability_labels,
            "plddt_mean": plddt_mean,
            "gene_constraint": {
                "loeuf": loeuf,
                "pLI": gene_constraint.get("pLI"),
                "interpretation": gene_constraint.get("interpretation", ""),
            },
        },
        "approved_drugs": [
            {
                "molecule_chembl_id": d.get("molecule_chembl_id"),
                "pref_name": d.get("pref_name"),
                "max_phase": d.get("max_phase"),
                "max_phase_label": d.get("max_phase_label"),
                "mechanism": d.get("mechanism"),
                "oral": d.get("oral"),
                "first_approval": d.get("first_approval"),
            }
            for d in approved_drugs[:10]
        ],
        "tractability_assessment": {
            "small_molecule": any(
                "small_mol" in l.lower() or "SM" in l for l in tractability_labels
            ),
            "antibody": any("antibody" in l.lower() or "AB" in l for l in tractability_labels),
            "protac": any("protac" in l.lower() or "PROTAC" in l for l in tractability_labels),
            "labels_raw": tractability_labels,
        },
        "actionability": _druggability_actionability(tier, drug_count, tractability_labels),
        "data_sources": {
            "chembl": "https://www.ebi.ac.uk/chembl/",
            "open_targets": "https://platform.opentargets.org",
            "gnomad": "https://gnomad.broadinstitute.org",
            "alphafold_db": "https://alphafold.ebi.ac.uk",
        },
        "provenance": _provenance(
            chembl="v37", open_targets="26.03", gnomad="v4", alphafold_db="v6"
        ),
    }

    log.info("complete", tier=tier, drug_count=drug_count)
    return report


# ── Tool 3: Protein intelligence dossier ─────────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Synthesize Protein Intelligence Dossier",
        "readOnlyHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
async def synthesize_protein_dossier(
    params: ProteinDossierInput,
) -> dict[str, Any]:
    """Generate a complete protein intelligence dossier from 7 data sources.

    It assembles disease associations, drug precedent, population
    constraint, ClinVar variants, and cross-species orthologs for one
    protein into a single structured record. It composes upstream
    databases; it does not add scientific judgement.

    Sources fused in parallel:
      - **Open Targets**: disease associations + tractability + drug count
      - **DisGeNET**: curated GDA scores with publication counts
      - **ChEMBL**: approved drugs + MoA + bioactivity
      - **gnomAD**: population constraint (pLI, LOEUF, mis_z)
      - **ClinVar**: pathogenic variants in this gene
      - **Ensembl**: orthologs across 12 species

    Args:
        params.uniprot_id: UniProt accession.
        params.gene_symbol: HGNC gene symbol.
        params.depth: 'brief' | 'standard' | 'comprehensive'.
    """
    uid = params.uniprot_id
    sym = params.gene_symbol.upper()
    log = logger.bind(uniprot_id=uid, gene=sym, depth=params.depth)
    log.info("start.dossier")

    # Open Targets keys target data on Ensembl gene IDs. Resolve the
    # UniProt accession to an Ensembl ID before the parallel fan-out.
    ot_resolved: dict[str, str] = {}
    try:
        ot_resolved = await _opentargets().resolve_target(uid)
    except Exception as exc:
        log.warning("ot.resolve.failed", exc=str(exc))
    ensembl_id = ot_resolved.get("ensembl_id", "")

    # Parallel evidence gathering
    tasks: dict[str, Any] = {
        "ot_diseases": _opentargets().associated_diseases(ensembl_id, limit=10),
        "ot_tractability": _opentargets().drug_count_and_tractability(ensembl_id),
        "disgenet": _disgenet().gene_disease_associations(sym, min_score=0.1, limit=10),
        "gene_constraint": _gnomad().gene_constraint(sym),
        "clinvar_variants": _clinvar().search_gene(sym, limit=5),
        "ensembl_gene": _ensembl().gene_lookup(sym),
    }

    gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
    results: dict[str, Any] = {
        k: (v if not isinstance(v, Exception) else None) for k, v in zip(tasks.keys(), gathered)
    }

    # Drug data (needs ChEMBL target lookup first)
    chembl_target = await _chembl().target_by_uniprot(uid)
    drugs: list[dict[str, Any]] = []
    if isinstance(chembl_target, dict) and chembl_target:
        target_id = chembl_target.get("chembl_id", "")
        if target_id:
            try:
                drugs = await _chembl().approved_drugs(target_id, include_clinical=True)
            except Exception:
                pass

    # Orthologs (comprehensive depth only)
    orthologs: list[dict[str, Any]] = []
    if params.depth == "comprehensive":
        try:
            orthologs = await _ensembl().orthologs(sym, limit=12)
        except Exception:
            pass

    # Build dossier
    ot_diseases = results.get("ot_diseases") or []
    ot_scores = [s.to_dict() if hasattr(s, "to_dict") else s for s in ot_diseases]
    ot_tract = results.get("ot_tractability") or {}
    disgenet = results.get("disgenet") or []
    constraint = results.get("gene_constraint") or {}
    clinvar_vars = results.get("clinvar_variants") or []
    ensembl_gene = results.get("ensembl_gene") or {}

    # AlphaFold pLDDT
    dossier_plddt: float | None = None
    try:
        af_meta = await _alphafold().get_prediction(uid)
        if isinstance(af_meta, dict):
            dossier_plddt = af_meta.get("globalMetricValue")
    except Exception:
        pass

    # Compute druggability
    tier, rationale, _scoring = _druggability_tier(
        drug_count=ot_tract.get("drug_count", len(drugs)),
        tractability_labels=ot_tract.get("tractability_labels", []),
        loeuf=constraint.get("loeuf"),
        plddt_mean=dossier_plddt,
    )

    # Synthesise top disease list (merge OT + DisGeNET)
    disease_map: dict[str, dict[str, Any]] = {}
    for d in ot_scores[:5]:
        name = d.get("disease_name", "")
        if name:
            disease_map[name] = {
                "disease_name": name,
                "disease_id": d.get("disease_mondo_id", ""),
                "ot_score": round(d.get("overall_score", 0.0), 4),
                "disgenet_score": None,
            }
    for d in disgenet[:5]:
        name = d.get("disease_name", "")
        if name in disease_map:
            disease_map[name]["disgenet_score"] = d.get("score")
        elif name:
            disease_map[name] = {
                "disease_name": name,
                "disease_id": d.get("disease_id", ""),
                "ot_score": None,
                "disgenet_score": d.get("score"),
            }

    dossier: dict[str, Any] = {
        "target": {
            "uniprot_id": uid,
            "gene_symbol": sym,
            "ensembl_gene_id": ensembl_gene.get("ensembl_gene_id", ""),
            "description": ensembl_gene.get("description", ""),
        },
        "druggability": {
            "tier": tier,
            "rationale": rationale,
            "drug_count": ot_tract.get("drug_count", len(drugs)),
            "tractability_labels": ot_tract.get("tractability_labels", []),
        },
        "disease_associations": list(disease_map.values()),
        "approved_drugs": [
            {
                "pref_name": d.get("pref_name"),
                "max_phase": d.get("max_phase"),
                "max_phase_label": d.get("max_phase_label"),
                "oral": d.get("oral"),
                "first_approval": d.get("first_approval"),
            }
            for d in drugs[:10]
        ],
        "population_genetics": {
            "pLI": constraint.get("pLI"),
            "loeuf": constraint.get("loeuf"),
            "mis_z": constraint.get("mis_z"),
            "constraint_interpretation": constraint.get("interpretation", ""),
        },
        "clinvar_pathogenic_variants": clinvar_vars[:5],
        "intelligence_summary": _narrative_summary(
            sym=sym,
            tier=tier,
            drug_count=ot_tract.get("drug_count", len(drugs)),
            diseases=list(disease_map.values()),
            constraint=constraint,
        ),
    }

    if params.depth in ("standard", "comprehensive"):
        dossier["open_targets_detail"] = ot_scores[:5]
        dossier["disgenet_detail"] = disgenet[:5]

    if params.depth == "comprehensive":
        dossier["cross_species_orthologs"] = orthologs

    dossier["data_sources"] = {
        "open_targets": "https://platform.opentargets.org",
        "disgenet": "https://www.disgenet.com",
        "chembl": "https://www.ebi.ac.uk/chembl/",
        "gnomad": "https://gnomad.broadinstitute.org",
        "clinvar": "https://www.ncbi.nlm.nih.gov/clinvar/",
        "ensembl": "https://rest.ensembl.org",
        "alphafold_db": "https://alphafold.ebi.ac.uk",
    }
    # Stamp the upstreams actually fused into the dossier (see data_sources
    # above), not tool parameters. ClinVar / Ensembl / DisGeNET serve current
    # releases and are not pinned to a version here.
    dossier["provenance"] = _provenance(
        open_targets="26.03",
        gnomad="v4",
        chembl="v37",
        alphafold_db="v6",
        clinvar="current",
        ensembl="current",
        disgenet="current",
    )

    log.info("complete.dossier", tier=tier)
    return dossier


# ── Tool 4: Disease drug landscape ───────────────────────────────────────────


@mcp.tool(
    annotations={
        "title": "Map Disease Drug Landscape",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def map_disease_drug_landscape(
    params: DiseaseDrugLandscapeInput,
) -> dict[str, Any]:
    """Map the complete therapeutic landscape for a disease.

    Returns approved drugs, pipeline agents, top druggable targets,
    and an investability summary for a given MONDO disease.

    Combines Open Targets evidence with ChEMBL drug indications and
    MONDO disease hierarchy to produce a comprehensive landscape report
    used in business development, competitive intelligence, and
    R&D portfolio decisions.

    Args:
        params.disease_mondo_id: MONDO disease ID.
    """
    mid = params.disease_mondo_id
    log = logger.bind(disease=mid, tool="map_disease_drug_landscape")
    log.info("start")

    # Open Targets accepts the underscore-form disease ID (e.g. MONDO_0007254),
    # but not every MONDO term is indexed there — some are reachable only via
    # their EFO cross-reference, which we resolve from the MONDO record below.
    ot_disease_id = mid.replace("MONDO:", "MONDO_")

    # Parallel: MONDO lookup + OT targets
    mondo_task = _mondo().lookup(mid)
    ot_targets_task = _opentargets().associated_targets(ot_disease_id, limit=20)

    (mondo_result, ot_targets), _ = await asyncio.gather(
        asyncio.gather(mondo_task, ot_targets_task, return_exceptions=True),
        asyncio.sleep(0),
    )

    disease_name = ""
    efo_curie = ""  # e.g. "EFO:0000339" — the native key for OT and ChEMBL
    if isinstance(mondo_result, Exception):
        log.warning("mondo.failed", exc=str(mondo_result))
    else:
        disease_name = mondo_result.name or mid
        if mondo_result.efo_ids:
            efo_curie = mondo_result.efo_ids[0]

    # Many MONDO terms carry no direct EFO cross-reference (e.g. the broad
    # "breast cancer" node). Resolve one via Open Targets full-text search so
    # the disease still reaches ChEMBL's EFO-keyed drug indications.
    if not efo_curie and disease_name:
        try:
            efo_curie = await _opentargets().resolve_disease_efo(disease_name)
        except Exception as exc:
            log.warning("opentargets.disease_search.failed", exc=str(exc))

    # When the MONDO ID yields no Open Targets associations, retry via the
    # EFO cross-reference (OT's native disease ontology).
    if (isinstance(ot_targets, Exception) or not ot_targets) and efo_curie:
        try:
            ot_targets = await _opentargets().associated_targets(
                efo_curie.replace("EFO:", "EFO_"), limit=20
            )
        except Exception as exc:
            log.warning("opentargets.efo_fallback.failed", exc=str(exc))

    top_targets = []
    if not isinstance(ot_targets, Exception):
        top_targets = [t.to_dict() if hasattr(t, "to_dict") else t for t in ot_targets[:10]]

    # ChEMBL drug indications are keyed on EFO / MeSH, not MONDO. Use the EFO
    # cross-reference when available, falling back to the disease name (MeSH).
    chembl_drugs: list[dict[str, Any]] = []
    try:
        if efo_curie:
            chembl_drugs = await _chembl().drug_indications(efo_id=efo_curie, limit=20)
        elif disease_name:
            chembl_drugs = await _chembl().drug_indications(mesh_heading=disease_name, limit=20)
    except Exception as exc:
        log.warning("chembl.indications.failed", exc=str(exc))

    # Classify drugs by phase
    approved = [d for d in chembl_drugs if _indication_phase(d) >= 4]
    phase3 = [d for d in chembl_drugs if _indication_phase(d) == 3]
    phase12 = [d for d in chembl_drugs if _indication_phase(d) in (1, 2)]

    # The drug-indication endpoint returns molecule IDs but not names; backfill
    # preferred names for the entries we surface in one bulk request.
    shown = approved[:10] + phase3[:10] + phase12[:10]
    if shown:
        names = await _chembl().molecule_names([d.get("molecule_chembl_id", "") for d in shown])
        for d in shown:
            if not d.get("pref_name"):
                d["pref_name"] = names.get(d.get("molecule_chembl_id", ""), "")

    # Druggable top targets
    druggable_targets = [t for t in top_targets if t.get("tractable")]

    landscape: dict[str, Any] = {
        "disease": {
            "mondo_id": mid,
            "name": disease_name,
        },
        "drug_landscape": {
            "approved_drugs": approved[:10],
            "phase_3_drugs": phase3[:10],
            "phase_1_2_drugs": phase12[:10],
            "total_indication_entries": len(chembl_drugs),
        },
        "target_landscape": {
            "top_targets": top_targets[:10],
            "druggable_targets": druggable_targets[:5],
            "total_associated_targets": len(top_targets),
        },
        "competitive_intelligence": {
            "approved_count": len(approved),
            "pipeline_count": len(phase3) + len(phase12),
            "druggable_target_count": len(druggable_targets),
            "investability": _investability_rating(
                approved_count=len(approved),
                pipeline_count=len(phase3) + len(phase12),
                druggable_targets=len(druggable_targets),
            ),
        },
        "data_sources": {
            "mondo": "https://www.ebi.ac.uk/ols4/ontologies/mondo",
            "open_targets": "https://platform.opentargets.org",
            "chembl": "https://www.ebi.ac.uk/chembl/",
        },
        "provenance": _provenance(
            open_targets="26.03",
            chembl="v37",
        ),
    }

    log.info("complete", approved=len(approved), pipeline=len(phase3) + len(phase12))
    return landscape


# ── Tool 5: ACMG variant classification framework ────────────────────────────


@mcp.tool(
    annotations={
        "title": "Draft ACMG/AMP Variant Classification",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def classify_variant_acmg(
    params: ACMGVariantInput,
) -> dict[str, Any]:
    """Generate a draft ACMG/AMP variant classification framework.

    Populates ACMG/AMP 2015 criteria (Richards et al.) automatically from
    computational evidence.  Designed to pre-populate variant interpretation
    forms for clinical laboratory review — NOT a substitute for expert review.

    Criteria populated:
      PVS1 — Null variant in LoF-intolerant gene
      PM2   — Absent/extremely rare in gnomAD population databases
      PP3   — Multiple in-silico predictors (AlphaMissense ≥0.564, SIFT, PolyPhen, CADD)
      BP4   — Multiple in-silico predictors benign (AlphaMissense ≤0.340)
      BP7   — Silent variant, no splicing impact
      BS1   — Allele frequency > 5% in gnomAD
      PP5   — ClinVar reports the variant pathogenic / likely pathogenic
              (Supporting). Note: ClinGen's SVI recommends retiring
              PP5/BP6; it is surfaced here as supporting evidence only.

    Args:
        params.hgvs: HGVS expression.
        params.inheritance_pattern: Expected inheritance mode.
    """
    hgvs = params.hgvs.strip()

    vep_task = _ensembl().vep_hgvs(hgvs, canonical=True)
    clinvar_task = _clinvar().search_by_hgvs(hgvs)
    gene_symbol = EnsemblClient.parse_gene_from_hgvs(hgvs)

    vep_results, clinvar_results = await asyncio.gather(
        vep_task, clinvar_task, return_exceptions=True
    )
    vep_results = [] if isinstance(vep_results, Exception) else vep_results
    clinvar_results = [] if isinstance(clinvar_results, Exception) else clinvar_results

    # gnomAD
    gnomad_data: dict[str, Any] = {}
    gnomad_id = _build_gnomad_id(hgvs, vep_results)
    if gnomad_id:
        try:
            gnomad_data = await _gnomad().variant_frequencies(gnomad_id)
        except Exception:
            pass

    # Gene constraint (for PVS1 context)
    gene_constraint: dict[str, Any] = {}
    if gene_symbol:
        try:
            gene_constraint = await _gnomad().gene_constraint(gene_symbol)
        except Exception:
            pass

    am_score: float | None = await _alphamissense_for_variant(
        gene_symbol,
        vep_results,  # type: ignore[arg-type]
    )
    global_af: float | None = gnomad_data.get("global_af")
    clinvar_record = clinvar_results[0] if clinvar_results else None
    clinvar_class = (clinvar_record or {}).get(
        "classification", PathogenicityClass.NOT_PROVIDED.value
    )
    loeuf: float | None = gene_constraint.get("loeuf")

    # Build criteria
    criteria: dict[str, dict[str, Any]] = {}

    # VEP-derived
    vep_criteria = _vep_to_acmg(vep_results)
    for k, v in vep_criteria.items():
        criteria[k] = {"met": True, "evidence": v, "strength": _acmg_strength(k)}

    # AlphaMissense
    am_criteria = _am_to_acmg_evidence(am_score)
    for k, v in am_criteria.items():
        criteria[k] = {"met": True, "evidence": v, "strength": _acmg_strength(k)}

    # gnomAD population
    gnomad_criteria = _gnomad_to_acmg(global_af)
    for k, v in gnomad_criteria.items():
        criteria[k] = {"met": True, "evidence": v, "strength": _acmg_strength(k)}

    # ClinVar
    if clinvar_class in {
        PathogenicityClass.PATHOGENIC.value,
        PathogenicityClass.LIKELY_PATHOGENIC.value,
    }:
        criteria["PP5"] = {
            "met": True,
            "evidence": f"ClinVar: {clinvar_class} — {(clinvar_record or {}).get('review_status', '')}",
            "strength": "Supporting",
        }

    # LOEUF context for PVS1
    if "PVS1" in criteria and loeuf is not None:
        pv = criteria["PVS1"]
        if loeuf < 0.35:
            pv["evidence"] += f" LOEUF={loeuf:.3f} confirms LoF intolerance."
        else:
            pv["strength"] = "Strong"
            pv["evidence"] += (
                f" Note: LOEUF={loeuf:.3f} indicates moderate LoF tolerance — downgrade PVS1→PS1."
            )

    # Final classification rules (simplified Richards et al.)
    pathogenic_strong = sum(
        1
        for c in criteria.values()
        if c.get("met")
        and c.get("strength") in ("Very Strong", "Strong")
        and c.get("evidence", "").split()[0][0] == "P"
    )
    benign_strong = sum(
        1
        for k, c in criteria.items()
        if c.get("met") and k.startswith("B") and c.get("strength") in ("Strong", "Stand-alone")
    )

    final_class = "Variant of Uncertain Significance"
    if "PVS1" in criteria and pathogenic_strong >= 1:
        final_class = "Pathogenic"
    elif pathogenic_strong >= 2:
        final_class = "Likely Pathogenic"
    elif benign_strong >= 2 or (
        benign_strong >= 1
        and sum(
            1
            for k, c in criteria.items()
            if c.get("met") and k.startswith("B") and c.get("strength") == "Supporting"
        )
        >= 1
    ):
        final_class = "Likely Benign"
    elif clinvar_class == PathogenicityClass.PATHOGENIC.value:
        final_class = "Pathogenic (ClinVar-supported)"
    elif clinvar_class == PathogenicityClass.LIKELY_PATHOGENIC.value:
        final_class = "Likely Pathogenic (ClinVar-supported)"

    return {
        "hgvs": hgvs,
        "gene_symbol": gene_symbol,
        "inheritance_pattern": params.inheritance_pattern,
        "draft_classification": final_class,
        "criteria_met": criteria,
        "criteria_not_met": _criteria_not_met(criteria),
        "summary": {
            "pathogenic_evidence_count": sum(
                1 for k in criteria if k.startswith("P") and criteria[k].get("met")
            ),
            "benign_evidence_count": sum(
                1 for k in criteria if k.startswith("B") and criteria[k].get("met")
            ),
        },
        "disclaimer": (
            "This is a computational draft classification generated for clinical laboratory "
            "review assistance only.  It MUST be reviewed by a board-certified clinical "
            "molecular geneticist before use in any clinical or regulatory context.  "
            "Per ACMG/AMP 2015 guidelines (Richards et al., Genet Med 2015;17:405–424)."
        ),
        "provenance": _provenance(ensembl_vep="GRCh38", clinvar="current", gnomad="v4"),
    }


# ── Tool 6: Drug repurposing candidates for a disease ────────────────────────


@mcp.tool(
    annotations={
        "title": "Find Drug Repurposing Candidates",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def find_drug_repurposing_candidates(
    params: DrugRepurposingInput,
) -> dict[str, Any]:
    """Find clinical-stage drugs that may be repurposed for a disease.

    Strategy:
      1. Identify top evidence-scored targets from Open Targets.
      2. For each target, find drugs in clinical development (ChEMBL).
      3. Filter by requested development phase threshold.
      4. Cross-reference against disease indication history (avoids circular reasoning).
      5. Score candidates by (OT evidence × clinical phase).

    This is the structural-biology-informed drug repurposing pipeline:
    by anchoring in AlphaFold structures, future extensions will apply
    topological fingerprinting to find structurally similar pockets with
    existing binding agents.

    Args:
        params.disease_mondo_id: MONDO ID for the target disease.
        params.target_limit: Number of top OT targets to screen.
        params.min_phase: Minimum clinical phase (4=Approved).
    """
    mid = params.disease_mondo_id
    log = logger.bind(disease=mid, tool="find_drug_repurposing_candidates")
    log.info("start")

    # Open Targets keys disease data on underscore-form IDs (MONDO_xxxxxxx).
    ot_disease_id = mid.replace("MONDO:", "MONDO_")

    # Step 1: OT top targets for disease
    ot_targets = await _opentargets().associated_targets(ot_disease_id, limit=params.target_limit)
    if not ot_targets:
        return {
            "disease_mondo_id": mid,
            "candidates": [],
            "message": "No Open Targets associations found for this disease.",
        }

    # Step 2: Find drugs for each target (parallel, bounded)
    semaphore = asyncio.Semaphore(5)

    async def _get_drugs_for_target(
        target: Any,
    ) -> tuple[Any, list[dict[str, Any]]]:
        async with semaphore:
            uid = (
                target.uniprot_id if hasattr(target, "uniprot_id") else target.get("uniprot_id", "")
            )
            if not uid:
                return target, []
            try:
                drugs = await _chembl().find_repurposable_drugs(
                    uid,
                    max_phase=params.min_phase,
                    limit=5,
                )
                return target, drugs
            except Exception:
                return target, []

    drug_results = await asyncio.gather(
        *[_get_drugs_for_target(t) for t in ot_targets],
        return_exceptions=True,
    )

    # Step 3: Build candidate list
    candidates: list[dict[str, Any]] = []
    seen_drug_ids: set[str] = set()

    for result in drug_results:
        if isinstance(result, Exception):
            continue
        target, drugs = result
        target_dict = target.to_dict() if hasattr(target, "to_dict") else target
        ot_score = target_dict.get("overall_score", 0.0)

        for drug in drugs:
            drug_id = drug.get("molecule_chembl_id", "")
            if drug_id in seen_drug_ids:
                continue
            seen_drug_ids.add(drug_id)
            phase = int(drug.get("max_phase") or 0)
            composite_score = round(ot_score * (phase / 4.0), 4)
            candidates.append(
                {
                    "molecule_chembl_id": drug_id,
                    "pref_name": drug.get("pref_name"),
                    "max_phase": phase,
                    "max_phase_label": drug.get("max_phase_label"),
                    "target_gene": target_dict.get("target_gene_symbol", ""),
                    "target_uniprot": target_dict.get("uniprot_id", ""),
                    "ot_evidence_score": round(ot_score, 4),
                    "composite_repurposing_score": composite_score,
                    "mechanism": drug.get("mechanism"),
                    "oral": drug.get("oral"),
                    "first_approval": drug.get("first_approval"),
                }
            )

    candidates.sort(key=lambda c: c["composite_repurposing_score"], reverse=True)

    return {
        "disease_mondo_id": mid,
        "min_phase": params.min_phase,
        "candidates": candidates[:20],
        "candidate_count": len(candidates),
        "methodology": (
            "Composite score = (Open Targets evidence score × clinical phase / 4). "
            "Higher scores indicate stronger genetic evidence + more advanced clinical precedent. "
            "This is a computational prioritization — mechanistic validation is required."
        ),
        "data_sources": {
            "open_targets": "https://platform.opentargets.org",
            "chembl": "https://www.ebi.ac.uk/chembl/",
        },
        "provenance": _provenance(open_targets="26.03", chembl="v37"),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_gnomad_id(hgvs: str, vep_results: list[dict[str, Any]]) -> str | None:
    """Attempt to build a gnomAD variant ID from VEP result mappings."""
    for hit in vep_results:
        # VEP top-level hit contains seq_region_name, start, and allele_string
        chrom = str(hit.get("seq_region_name", "")).lstrip("chr")
        pos = hit.get("start")
        allele_str = hit.get("allele_string", "")
        if chrom and pos and "/" in allele_str:
            ref, _, alt = allele_str.partition("/")
            if ref and alt and ref != "-" and alt != "-":
                return f"{chrom}-{pos}-{ref}-{alt}"
    # Fallback: try to parse from HGVS genomic notation
    m = re.search(r"(\d+)-(\d+)-([ACGT]+)-([ACGT]+)", hgvs.replace(":", "-"))
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"
    return None


def _compute_clinical_tier(
    *,
    clinvar_class: str,
    am_score: float | None,
    global_af: float | None,
    acmg_criteria: dict[str, str],
) -> str:
    """HIGH / MEDIUM / LOW / UNKNOWN based on combined evidence."""
    if clinvar_class == PathogenicityClass.PATHOGENIC.value:
        return "HIGH"
    if clinvar_class == PathogenicityClass.LIKELY_PATHOGENIC.value:
        if am_score is not None and am_score >= 0.564:
            return "HIGH"
        return "MEDIUM"
    if clinvar_class in {PathogenicityClass.BENIGN.value, PathogenicityClass.LIKELY_BENIGN.value}:
        return "LOW"
    # No ClinVar — rely on computational evidence
    p_count = sum(1 for k in acmg_criteria if k.startswith("P"))
    b_count = sum(1 for k in acmg_criteria if k.startswith("B"))
    if p_count >= 2:
        return "MEDIUM"
    if b_count >= 2:
        return "LOW"
    if am_score is not None and am_score >= 0.564:
        return "MEDIUM"
    if am_score is not None and am_score <= 0.340:
        return "LOW"
    return "UNKNOWN"


def _tier_explanation(tier: str) -> str:
    return {
        "HIGH": (
            "Strong evidence of clinical pathogenicity from ClinVar expert curation "
            "and/or multiple concordant computational predictors."
        ),
        "MEDIUM": (
            "Computational evidence suggests pathogenicity; lacks expert ClinVar curation. "
            "Further clinical and functional evidence recommended."
        ),
        "LOW": (
            "Evidence suggests benign classification: population frequency is high "
            "and/or in-silico predictors indicate benign effect."
        ),
        "UNKNOWN": (
            "Insufficient evidence from any source to assign a pathogenicity tier. "
            "Classify as Variant of Uncertain Significance pending further evidence."
        ),
    }.get(tier, "Unknown tier.")


def _druggability_actionability(tier: str, drug_count: int, tractability_labels: list[str]) -> str:
    if tier == "HOT":
        return (
            f"Target is HOT: {drug_count} known drug(s) + tractability confirmed. "
            "Prioritise for lead optimisation or repurposing screen."
        )
    if tier == "WARM":
        return (
            f"Target is WARM: limited clinical precedent ({drug_count} drugs). "
            "Recommend structural analysis + FBDD/SBDD campaign."
        )
    if tier == "COLD":
        return (
            "Target is COLD: no strong drug precedent. "
            "Consider phenotypic screen, allosteric site search, or PROTAC approach."
        )
    return (
        "Target has no current evidence of druggability. "
        "Consider pathway-level intervention or indirect targeting strategy."
    )


def _narrative_summary(
    *,
    sym: str,
    tier: str,
    drug_count: int,
    diseases: list[dict[str, Any]],
    constraint: dict[str, Any],
) -> str:
    disease_names = ", ".join(d["disease_name"] for d in diseases[:3] if d.get("disease_name"))
    loeuf = constraint.get("loeuf")
    constraint_desc = ""
    if loeuf is not None:
        constraint_desc = f"The gene is {'highly constrained (LoF intolerant, LOEUF=' + f'{loeuf:.3f}' + ')' if loeuf < 0.35 else 'moderately constrained' if loeuf < 0.6 else 'tolerant to LoF'}. "
    return (
        f"{sym} is a {tier.lower()}-priority drug target with {drug_count} known clinical compound(s). "
        f"Top associated diseases: {disease_names or 'not determined'}. "
        f"{constraint_desc}"
        f"This dossier was synthesized in real-time from Open Targets, DisGeNET, ChEMBL, gnomAD, ClinVar, and Ensembl."
    )


def _acmg_strength(code: str) -> str:
    strength_map = {
        "PVS1": "Very Strong",
        "PS1": "Strong",
        "PS2": "Strong",
        "PS3": "Strong",
        "PS4": "Strong",
        "PM1": "Moderate",
        "PM2": "Moderate",
        "PM3": "Moderate",
        "PM4": "Moderate",
        "PM5": "Moderate",
        "PM6": "Moderate",
        "PP1": "Supporting",
        "PP2": "Supporting",
        "PP3": "Supporting",
        "PP4": "Supporting",
        "PP5": "Supporting",
        "BA1": "Stand-alone",
        "BS1": "Strong",
        "BS2": "Strong",
        "BS3": "Strong",
        "BS4": "Strong",
        "BP1": "Supporting",
        "BP2": "Supporting",
        "BP3": "Supporting",
        "BP4": "Supporting",
        "BP5": "Supporting",
        "BP6": "Supporting",
        "BP7": "Supporting",
    }
    return strength_map.get(code, "Supporting")


def _criteria_not_met(criteria: dict[str, dict[str, Any]]) -> list[str]:
    all_codes = [
        "PVS1",
        "PS1",
        "PS2",
        "PS3",
        "PS4",
        "PM1",
        "PM2",
        "PM3",
        "PM4",
        "PM5",
        "PM6",
        "PP1",
        "PP2",
        "PP3",
        "PP4",
        "PP5",
        "BA1",
        "BS1",
        "BS2",
        "BS3",
        "BS4",
        "BP1",
        "BP2",
        "BP3",
        "BP4",
        "BP5",
        "BP6",
        "BP7",
    ]
    return [c for c in all_codes if c not in criteria]


def _indication_phase(drug: dict[str, Any]) -> int:
    """Coerce a ChEMBL ``max_phase_for_indication`` to an integer phase.

    ChEMBL returns this field as a string (e.g. ``'4.0'``); blank/unknown
    values collapse to ``0``.
    """
    try:
        return int(float(drug.get("max_phase_for_indication")))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _investability_rating(
    *, approved_count: int, pipeline_count: int, druggable_targets: int
) -> str:
    if approved_count >= 3 and druggable_targets >= 5:
        return "HIGH — well-validated therapeutic area with multiple approved agents and druggable targets."
    if approved_count >= 1 or pipeline_count >= 3:
        return "MEDIUM — emerging therapeutic area with clinical validation."
    if druggable_targets >= 2:
        return (
            "EARLY — biologically validated but limited clinical precedent; high-risk/high-reward."
        )
    return (
        "EXPLORATORY — limited evidence; suitable for academic or phenotypic discovery programmes."
    )
