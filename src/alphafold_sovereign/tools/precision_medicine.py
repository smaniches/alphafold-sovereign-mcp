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
import math
import re
from typing import TYPE_CHECKING, Any, Literal, cast

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
from alphafold_sovereign.clients.opentargets import AmbiguousTargetError, OpenTargetsClient
from alphafold_sovereign.clients.pdbe_literature import PDBeLiteratureClient
from alphafold_sovereign.domain.disease import PathogenicityClass
from alphafold_sovereign.domain.druggability import (
    has_small_molecule_tractability,
    resolve_drug_precedent,
    score_target_druggability,
    validated_plddt,
)
from alphafold_sovereign.domain.uniprot import UNIPROT_ACCESSION_PATTERN
from alphafold_sovereign.server.app import mcp

if TYPE_CHECKING:
    from alphafold_sovereign.clients._base import BaseAsyncClient

logger = structlog.get_logger(__name__)


# ── Shared client singletons (initialised on first use) ──────────────────────

_CLIENTS: dict[str, BaseAsyncClient] = {}


def _ensembl() -> EnsemblClient:
    if "ensembl" not in _CLIENTS:
        _CLIENTS["ensembl"] = EnsemblClient()
    return cast("EnsemblClient", _CLIENTS["ensembl"])


def _clinvar() -> ClinVarClient:
    if "clinvar" not in _CLIENTS:
        _CLIENTS["clinvar"] = ClinVarClient()
    return cast("ClinVarClient", _CLIENTS["clinvar"])


def _gnomad() -> GnomADClient:
    if "gnomad" not in _CLIENTS:
        _CLIENTS["gnomad"] = GnomADClient()
    return cast("GnomADClient", _CLIENTS["gnomad"])


def _mondo() -> MONDOClient:
    if "mondo" not in _CLIENTS:
        _CLIENTS["mondo"] = MONDOClient()
    return cast("MONDOClient", _CLIENTS["mondo"])


def _opentargets() -> OpenTargetsClient:
    if "opentargets" not in _CLIENTS:
        _CLIENTS["opentargets"] = OpenTargetsClient()
    return cast("OpenTargetsClient", _CLIENTS["opentargets"])


def _disgenet() -> DisGeNETClient:
    if "disgenet" not in _CLIENTS:
        _CLIENTS["disgenet"] = DisGeNETClient()
    return cast("DisGeNETClient", _CLIENTS["disgenet"])


def _chembl() -> ChEMBLClient:
    if "chembl" not in _CLIENTS:
        _CLIENTS["chembl"] = ChEMBLClient()
    return cast("ChEMBLClient", _CLIENTS["chembl"])


def _alphafold() -> AlphaFoldClient:
    if "alphafold" not in _CLIENTS:
        _CLIENTS["alphafold"] = AlphaFoldClient()
    return cast("AlphaFoldClient", _CLIENTS["alphafold"])


def _pdbe_literature() -> PDBeLiteratureClient:
    if "pdbe_literature" not in _CLIENTS:
        _CLIENTS["pdbe_literature"] = PDBeLiteratureClient()
    return cast("PDBeLiteratureClient", _CLIENTS["pdbe_literature"])


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
            "HGVS expression. Gene-relative 'BRCA1:c.181T>G' is candidate "
            "discovery only; a versioned transcript such as "
            "'NM_007294.4:c.181T>G' permits exact transcript-text matching, "
            "not an independent clinical allele validation."
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
    include_literature_evidence: bool = Field(
        default=False,
        description="Opt in to source-attributed PDBe/IUCr text-mined evidence at an explicit UniProt coordinate.",
    )
    literature_uniprot_id: str | None = Field(
        default=None,
        pattern=UNIPROT_ACCESSION_PATTERN,
        description="UniProt accession of the explicit residue query; not inferred from HGVS.",
    )
    literature_uniprot_residue: int | None = Field(
        default=None,
        ge=1,
        description="One-based UniProt reference residue; not a PDB or model-local index.",
    )


class DruggabilityInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    uniprot_id: str = Field(
        ...,
        description="UniProt accession, e.g. 'P38398' (BRCA1) or 'P04637' (TP53).",
        pattern=UNIPROT_ACCESSION_PATTERN,
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
        pattern=UNIPROT_ACCESSION_PATTERN,
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
        description=(
            "HGVS expression for unassessed evidence review. Gene-relative "
            "terms can find unverified ClinVar candidates; include a versioned "
            "RefSeq transcript for exact transcript-text matching."
        ),
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
        pattern=UNIPROT_ACCESSION_PATTERN,
    )
    uniprot_id_b: str = Field(
        ...,
        description="Second target UniProt ID (e.g. a related kinase for selectivity analysis).",
        pattern=UNIPROT_ACCESSION_PATTERN,
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
    gene_symbol: str | None,
    vep_results: list[dict[str, Any]],
    *,
    source_status: dict[str, str] | None = None,
) -> float | None:
    """Look up a VEP-mapped AlphaMissense score without conflating failure and absence.

    The optional status sink is additive: existing score-only callers continue
    receiving a float or None. An absent score is not evidence of benignity.
    """

    def _mark(state: str) -> None:
        if source_status is not None:
            source_status["alphamissense"] = state

    canonical = next((tc for tc in vep_results if tc.get("canonical")), {})
    protein_variant = _protein_variant_from_vep(canonical)
    if not protein_variant:
        vep_state = None if source_status is None else source_status.get("ensembl_vep")
        if vep_state == "failed":
            _mark("skipped_upstream_failed")
        elif vep_state == "invalid_response":
            _mark("skipped_upstream_invalid")
        elif vep_state == "no_data":
            _mark("skipped_no_vep_data")
        elif not canonical:
            _mark("skipped_no_canonical")
        elif "missense_variant" in (canonical.get("consequence_terms") or []):
            _mark("skipped_incomplete_mapping")
        else:
            _mark("skipped_not_applicable")
        return None

    swissprot = canonical.get("swissprot")
    if swissprot is None or swissprot == "":
        _mark("skipped_no_swissprot")
        return None
    if not isinstance(swissprot, str):
        _mark("invalid_response")
        return None
    uniprot_id = swissprot.split(".")[0]
    if not uniprot_id:
        _mark("invalid_response")
        return None

    try:
        record: object = await _alphafold().alphamissense_score(uniprot_id, protein_variant)
    except Exception as exc:
        logger.warning("alphamissense.failed", gene=gene_symbol, exc=str(exc))
        _mark("failed")
        return None

    if record is None:
        _mark("no_data")
        return None
    if not isinstance(record, dict):
        _mark("invalid_response")
        return None
    raw_score: object = record.get("am_pathogenicity")
    if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
        _mark("invalid_response")
        return None
    score = float(raw_score)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        _mark("invalid_response")
        return None
    _mark("ok")
    return score


def _gnomad_to_acmg(af: float | None) -> dict[str, str]:
    if af is None:
        return {}
    if af > _POPULATION_THRESHOLDS["BS1"]:
        return {"BS1": f"gnomAD AF={af:.4f} > 5% — too common for a rare pathogenic variant"}
    if af < _POPULATION_THRESHOLDS["PM2"]:
        return {"PM2": f"gnomAD AF={af:.6f} < 0.1% — extremely rare in population databases"}
    return {}


def _vep_to_acmg(consequences: list[dict[str, Any]]) -> dict[str, str]:
    """Extract provisional VEP signals, not clinical ACMG criteria."""
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
                "Predicted loss-of-function consequence. Disease-specific LoF mechanism, "
                "relevant transcript, NMD, and variant-specific PVS1 rules are NOT validated."
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
            criteria["BP7"] = (
                "Synonymous consequence reported by VEP; no validated splice-impact "
                "assessment performed. BP7 requires further evidence."
            )
    return criteria


# Re-exported so the tier scoring, the ``tractability_assessment`` display, and
# the actionability text all share one predicate and can never disagree.
_has_small_molecule_tractability = has_small_molecule_tractability


def _druggability_tier(
    *,
    drug_count: int,
    tractability_labels: list[str],
    loeuf: float | None,
    plddt_mean: float | None,
) -> tuple[str, str, dict[str, Any]]:
    """Return ``(tier, rationale, scoring_breakdown)`` for target druggability.

    Thin adapter over the pure :func:`score_target_druggability` heuristic in
    ``domain/druggability.py``; the ``scoring_breakdown`` dict additionally
    reports data completeness, a confidence grade, and a borderline flag.
    """
    assessment = score_target_druggability(
        drug_count=drug_count,
        tractability_labels=tractability_labels,
        loeuf=loeuf,
        plddt_mean=plddt_mean,
    )
    return assessment.tier, assessment.rationale, assessment.scoring_breakdown()


# ── Tool 1: Full clinical variant report ─────────────────────────────────────


def _report_gene_from_sources(
    hgvs: str, vep_rows: list[dict[str, Any]], clinvar_rows: list[dict[str, Any]]
) -> str | None:
    """Resolve a report gene only from query context or compatible source evidence."""
    gene = EnsemblClient.parse_gene_from_hgvs(hgvs)
    if gene:
        return gene

    symbols: set[str] = set()
    reference = re.match(
        r"^((?:NM|NR|XM|XR)_\d+\.\d+)(?:\(([A-Za-z0-9-]+)\))?:[cnr]\.",
        hgvs,
        flags=re.IGNORECASE,
    )
    queried_transcript = reference.group(1).upper() if reference else ""
    if reference and reference.group(2):
        symbols.add(reference.group(2).upper())

    for row in clinvar_rows:
        symbol = row.get("gene_symbol")
        if row.get("exact_change_match") is True and isinstance(symbol, str) and symbol.strip():
            symbols.add(symbol.strip().upper())

    for row in vep_rows:
        symbol = row.get("gene_symbol")
        if not queried_transcript or not isinstance(symbol, str) or not symbol.strip():
            continue
        hgvsc = row.get("hgvsc")
        transcript_id = row.get("transcript_id")
        refseq_ids = row.get("refseq_transcript_ids")
        matches_hgvsc = (
            isinstance(hgvsc, str) and hgvsc.partition(":")[0].upper() == queried_transcript
        )
        matches_transcript = (
            isinstance(transcript_id, str) and transcript_id.upper() == queried_transcript
        )
        # RefSeq xrefs are aligned transcript references; their accession AND
        # version must agree. Do not infer allelic or sequence equivalence.
        matches_refseq = isinstance(refseq_ids, list) and any(
            isinstance(value, str) and value.upper() == queried_transcript for value in refseq_ids
        )
        if matches_hgvsc or matches_transcript or matches_refseq:
            symbols.add(symbol.strip().upper())

    # An overlapping-gene VEP consequence does not override an exact
    # transcript match. True conflicting evidence for the same queried
    # transcript still requires abstention.
    return next(iter(symbols)) if len(symbols) == 1 else None


async def _resolve_open_targets(uniprot_id: str) -> tuple[dict[str, str], Exception | None]:
    """Resolve a UniProt accession to an Open Targets target, keeping the failure.

    Returns the mapping (empty when Open Targets has no target for the
    accession) and the resolution exception, if any, so callers can report
    an outage or malformed response rather than an intentional skip.
    """
    try:
        return await _opentargets().resolve_target(uniprot_id), None
    except Exception as exc:
        logger.warning("ot.resolve.failed", uniprot_id=uniprot_id, exc=str(exc))
        return {}, exc


def _failure_status(exc: BaseException) -> str:
    """Clients raise ValueError for malformed source content; the rest is a failed request."""
    return "invalid_response" if isinstance(exc, ValueError) else "failed"


async def _unresolved(exc: Exception) -> Any:
    """Stand in for a source call that could not be made because resolution failed."""
    raise exc


class _Skipped:
    """Marker for a source intentionally not queried (no identifier to query with)."""


_SKIPPED = _Skipped()


async def _skipped() -> _Skipped:
    return _SKIPPED


def _ot_source_task(coro_factory: Any, ensembl_id: str, error: Exception | None) -> Any:
    """Open Targets dossier source: inherit a resolution failure, skip an unmapped accession."""
    if error is not None:
        return _unresolved(error)
    if not ensembl_id:
        return _skipped()
    return coro_factory(ensembl_id)


def _gnomad_result_status(payload: dict[str, Any], availability_field: str) -> str:
    """Respect gnomAD's explicit negative flags even in nonempty responses."""
    if not payload or payload.get(availability_field) is False:
        return "no_data"
    if availability_field == "found" and payload.get("global_af") is None:
        return "no_data"  # Identity is not measured frequency evidence.
    return "ok"


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
    single HGVS variant into one structured research report. It preserves
    source classifications and computational observations separately; it
    does not assign an independent clinical tier or establish ACMG criteria.

    1. **Ensembl VEP** — functional consequence, SIFT/PolyPhen/CADD predictions
    2. **ClinVar** — clinical pathogenicity classifications and review status
    3. **gnomAD v4** — population allele frequencies (gnomAD v4, ~807k individuals)
    4. **AlphaMissense** — deep-learning missense pathogenicity (Cheng et al. 2023)
    5. **Open Targets** — disease-gene evidence scores
    6. **DisGeNET** — curated gene-disease association scores
    7. **ChEMBL** — approved drugs acting on the gene product

    The report includes unassessed ACMG-related computational signals,
    sequence consequences, and gene-level drug context. It does not compute
    variant-specific three-dimensional structural impact.

    Input fields:
        params.hgvs: HGVS expression. Gene-relative expressions discover
            candidate records; clinical source identity requires an exact
            versioned-transcript expression.
        params.include_population_breakdown: Include per-ancestry gnomAD data.
        params.include_drug_context: Include drugs acting on the gene product.
        params.include_literature_evidence: Query PDBe at an explicitly supplied
            UniProt accession and residue. The connection to the HGVS variant
            is NOT independently verified by this operation.
    """
    hgvs = params.hgvs.strip()
    log = logger.bind(hgvs=hgvs, tool="generate_variant_clinical_report")
    log.info("start")

    source_status: dict[str, str] = {}

    # ── Step 1: Parallel evidence gathering ──────────────────────────────────
    vep_task = _ensembl().vep_hgvs(hgvs, canonical=True)
    clinvar_task = _clinvar().search_by_hgvs(hgvs)

    gathered: list[Any] = await asyncio.gather(vep_task, clinvar_task, return_exceptions=True)

    # A malformed or null upstream response is not an empty biological result.
    def _checked_rows(source: str, raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, BaseException):
            log.warning("source.failed", source=source, exc=str(raw))
            source_status[source] = "failed"
            return []
        if not isinstance(raw, list) or not all(isinstance(row, dict) for row in raw):
            source_status[source] = "invalid_response"
            return []
        source_status[source] = "ok" if raw else "no_data"
        return raw

    vep_results = _checked_rows("ensembl_vep", gathered[0])
    clinvar_results = _checked_rows("clinvar", gathered[1])
    gene_symbol = _report_gene_from_sources(hgvs, vep_results, clinvar_results)

    # ── Step 3: gnomAD variant ID construction ───────────────────────────────
    gnomad_data: dict[str, Any] = {}
    gnomad_id = _build_gnomad_id(hgvs, vep_results)
    if gnomad_id:
        try:
            variant_response: object = await _gnomad().variant_frequencies(gnomad_id)
            if isinstance(variant_response, dict):
                gnomad_data = variant_response
                source_status["gnomad"] = _gnomad_result_status(variant_response, "found")
            else:
                source_status["gnomad"] = "invalid_response"
        except Exception as exc:
            log.warning("gnomad.failed", exc=str(exc))
            source_status["gnomad"] = "failed"
    else:
        source_status["gnomad"] = "skipped"

    # ── Step 4: Gene-level constraint ────────────────────────────────────────
    gene_constraint: dict[str, Any] = {}
    source_status["gnomad_constraint"] = "skipped"
    if gene_symbol:
        try:
            constraint_response: object = await _gnomad().gene_constraint(gene_symbol)
            if isinstance(constraint_response, dict):
                gene_constraint = constraint_response
                source_status["gnomad_constraint"] = _gnomad_result_status(
                    constraint_response, "constraint_available"
                )
            else:
                source_status["gnomad_constraint"] = "invalid_response"
        except Exception as exc:
            log.warning("gnomad.constraint.failed", exc=str(exc))
            source_status["gnomad_constraint"] = "failed"

    # ── Step 5: Disease context ───────────────────────────────────────────────
    ot_diseases: list[dict[str, Any]] = []
    disgenet_assocs: list[dict[str, Any]] = []
    if gene_symbol:
        gene_lookup_failed = False
        try:
            gene_info: object = await _ensembl().gene_lookup(gene_symbol)
            if isinstance(gene_info, dict):
                ensembl_id = gene_info.get("ensembl_gene_id") or ""
                if not isinstance(ensembl_id, str):
                    ensembl_id = ""
                    source_status["ensembl_gene_lookup"] = "invalid_response"
                else:
                    source_status["ensembl_gene_lookup"] = "ok" if ensembl_id else "no_data"
            else:
                ensembl_id = ""
                source_status["ensembl_gene_lookup"] = "invalid_response"
        except Exception as exc:
            log.warning("ensembl.gene_lookup.failed", exc=str(exc))
            ensembl_id = ""
            gene_lookup_failed = True
            source_status["ensembl_gene_lookup"] = "failed"

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
        disgenet_assocs = _checked_rows("disgenet", results[0])
        if not ensembl_id:
            source_status["open_targets"] = (
                "skipped_upstream_failed" if gene_lookup_failed else "skipped_no_gene_id"
            )
        else:
            raw_ot: Any = results[1]
            if isinstance(raw_ot, list):
                try:
                    raw_ot = [row.to_dict() if hasattr(row, "to_dict") else row for row in raw_ot]
                except Exception as exc:
                    raw_ot = exc
            ot_diseases = _checked_rows("open_targets", raw_ot)
    else:
        source_status["disgenet"] = "skipped"
        source_status["open_targets"] = "skipped"

    # ── Step 6: Drug context ──────────────────────────────────────────────────
    drug_candidates: list[dict[str, Any]] = []
    if params.include_drug_context and gene_symbol:
        try:
            gene_info_for_drugs: object = await _ensembl().gene_lookup(gene_symbol)
            if not isinstance(gene_info_for_drugs, dict):
                source_status["chembl"] = "invalid_response"
            else:
                uniprot_ids = gene_info_for_drugs.get("uniprot_ids", [])
                if not isinstance(uniprot_ids, list) or not all(
                    isinstance(accession, str) for accession in uniprot_ids
                ):
                    source_status["chembl"] = "invalid_response"
                elif uniprot_ids:
                    drug_response: object = await _chembl().find_repurposable_drugs(
                        uniprot_ids[0], max_phase=2
                    )
                    drug_candidates = _checked_rows("chembl", drug_response)
                else:
                    source_status["chembl"] = "no_data"
        except Exception as exc:
            log.warning("drugs.failed", exc=str(exc))
            source_status["chembl"] = "failed"
    else:
        source_status["chembl"] = "skipped"

    # ── Step 7: Consolidate ClinVar ───────────────────────────────────────────
    # search_by_hgvs stamps verified identity explicitly. An absent flag is
    # not proof: never attribute a record's classification by default.
    clinvar_record: dict[str, Any] | None = None
    if clinvar_results and clinvar_results[0].get("exact_change_match") is True:
        clinvar_record = clinvar_results[0]

    clinvar_class = (clinvar_record or {}).get(
        "classification", PathogenicityClass.NOT_PROVIDED.value
    )

    # ── Step 8: AlphaMissense pathogenicity (AlphaFold DB) ─────────────────────────────
    am_score: float | None = await _alphamissense_for_variant(
        gene_symbol,
        vep_results,
        source_status=source_status,
    )

    # ── Step 9: Draft ACMG criteria ───────────────────────────────────────────
    acmg_criteria: dict[str, str] = {}
    acmg_criteria.update(_am_to_acmg_evidence(am_score))
    acmg_criteria.update(_gnomad_to_acmg(gnomad_data.get("global_af")))
    if isinstance(vep_results, list):  # pragma: no branch
        acmg_criteria.update(_vep_to_acmg(vep_results))

    # ClinVar's independently issued classification is returned in the
    # 'clinvar' section, not double-counted as PP5/BP6 ACMG evidence.

    # No validated variant-specific clinical tier is assigned by this MCP.
    # ClinVar's own classification is preserved with source attribution.
    tier = "NOT_ASSESSED"

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
            "identity_status": "exact_transcript" if clinvar_record is not None else "unverified",
            "unverified_candidates": [
                {"variation_id": row.get("variation_id", ""), "name": row.get("name", "")}
                for row in clinvar_results
                if row.get("candidate_change_match") is True
            ][:3],
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
                "Unreviewed computational signals only; no ACMG/AMP criteria are established "
                "by this report. ClinVar classification is independent source context, not "
                "PP5/BP6 evidence. Gene-disease mechanism and variant-specific clinical "
                "criteria require qualified expert assessment."
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

    # PDBe's publication annotations are a separate evidence family.
    # Never feed them into ACMG classification. The caller must
    # provide a UniProt coordinate; HGVS-to-UniProt joins are not assumed.
    if params.include_literature_evidence:
        accession = params.literature_uniprot_id
        position = params.literature_uniprot_residue
        if accession is None or position is None:
            source_status["pdbe_iucr_literature"] = "missing_coordinates"
            report["literature_residue_evidence"] = {
                "status": "missing_coordinates",
                "note": "Specify both literature_uniprot_id and literature_uniprot_residue.",
            }
        else:
            try:
                evidence = await _pdbe_literature().get_residue_annotations(accession, position)
                report["literature_residue_evidence"] = {
                    **evidence,
                    "hgvs_to_uniprot_mapping": "Not independently verified; caller-supplied coordinate.",
                    "mutation_specificity": "Residue mentions are not necessarily evidence about the requested substitution.",
                }
                source_status["pdbe_iucr_literature"] = evidence["status"]
            except Exception as exc:
                log.warning("pdbe_iucr_literature.failed", exc=str(exc))
                report["literature_residue_evidence"] = {
                    "status": "unavailable",
                    "note": "Upstream failure or invalid mapping; no claim of biological absence.",
                }
                source_status["pdbe_iucr_literature"] = "failed"

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
    if params.include_literature_evidence:
        report["data_sources"]["pdbe_iucr_literature"] = (
            "https://www.ebi.ac.uk/pdbe/api/v2/uniprot/llm_annotations/summary/"
        )
    report["provenance"] = _provenance(
        ensembl_vep="GRCh38",
        clinvar="current",
        gnomad="v4",
        alphamissense="2023",
        pdbe_iucr_literature="source-reported" if params.include_literature_evidence else "",
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
    3. **Structural confidence** — AF2 pLDDT (model-local confidence, not binding evidence)
    4. **Population constraint** — gnomAD LOEUF (gene-level LoF depletion, not toxicity evidence)

    This is an author-defined, uncalibrated research score, not a validated
    predictive model, clinical safety result, or independent biological fact.

    Input fields:
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

    chembl_observed_count: int | None = None
    ot_observed_count: int | None = None
    tractability_labels: list[str] = []
    approved_drugs: list[dict[str, Any]] = []
    # A ValueError is the client's verdict that the ChEMBL response could not
    # be validated (ambiguous or malformed); anything else is a failed request.
    if isinstance(chembl_target, ValueError):
        chembl_status = "invalid_response"
    elif isinstance(chembl_target, BaseException):
        chembl_status = "failed"
    else:
        chembl_status = "no_data"

    if isinstance(chembl_target, dict) and chembl_target.get("chembl_id"):
        target_id = chembl_target["chembl_id"]
        try:
            approved_drugs = await _chembl().approved_drugs(
                target_id,
                include_clinical=params.include_clinical_stage,
                require_complete=True,
            )
            chembl_observed_count = len(approved_drugs)
            chembl_status = "ok"
        except ValueError as exc:
            chembl_status = "invalid_response"
            log.warning("chembl.drugs.invalid", exc=str(exc))
        except Exception as exc:
            chembl_status = "failed"
            log.warning("chembl.drugs.failed", exc=str(exc))

    # Resolve UniProt accession -> Open Targets target (Ensembl ID + symbol).
    # Open Targets keys all target data on Ensembl gene IDs, not UniProt IDs.
    ot_resolved, ot_resolve_error = await _resolve_open_targets(uid)
    ensembl_id = ot_resolved.get("ensembl_id", "")
    gene_symbol = ot_resolved.get("symbol", "")

    # Open Targets tractability (keyed on the resolved Ensembl gene ID). A
    # resolution outage or malformed mapping response is reported as such;
    # "skipped" is reserved for an accession Open Targets does not map.
    ot_tractability: dict[str, Any] = {}
    if ot_resolve_error is not None:
        ot_status = _failure_status(ot_resolve_error)
    elif not ensembl_id:
        ot_status = "skipped"
    else:
        ot_status = "no_data"
    if ensembl_id:
        try:
            ot_tractability = await _opentargets().drug_count_and_tractability(ensembl_id)
            tractability_labels = ot_tractability.get("tractability_labels", [])
            ot_count = ot_tractability.get("drug_count")
            if isinstance(ot_count, int) and not isinstance(ot_count, bool) and ot_count >= 0:
                ot_status = "ok"
                ot_observed_count = ot_count
            elif ot_count is not None:
                ot_status = "invalid_response"
        except ValueError as exc:
            # The client rejects malformed source content with ValueError;
            # that is an invalid response, not a failed request.
            ot_status = "invalid_response"
            log.warning("ot.tractability.invalid", exc=str(exc))
        except Exception as exc:
            ot_status = "failed"
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

    # AlphaFold confidence is an observed [0, 100] measurement or unassessed.
    plddt_mean: float | None = None
    plddt_status = "missing"
    try:
        af_meta: Any = await _alphafold().get_prediction(uid)
        if isinstance(af_meta, dict):
            plddt_mean, plddt_status = validated_plddt(af_meta.get("globalMetricValue"))
        else:
            plddt_status = "invalid_response"
    except Exception as exc:
        plddt_status = "failed"
        log.warning("plddt.failed", exc=str(exc))

    # ChEMBL counts distinct mechanism-linked molecules in the requested
    # stage scope; Open Targets counts drug and clinical-candidate records at
    # every stage. The published successful response promises four tiers and
    # a dict breakdown, so a missing count in the requested scope fails
    # explicitly rather than inventing a zero or a new unversioned shape.
    precedent = resolve_drug_precedent(
        chembl_count=chembl_observed_count,
        open_targets_count=ot_observed_count,
        include_clinical=params.include_clinical_stage,
    )
    if precedent is None:
        raise ValueError(
            "Druggability assessment unavailable: no observed drug count for the "
            f"requested scope ({_precedent_scope(params.include_clinical_stage)}; "
            f"chembl={chembl_status}, open_targets={ot_status}). "
            "No tier was assigned."
        )
    drug_count = precedent.drug_count
    scoring_drug_count = precedent.scoring_count
    tier, rationale, scoring = _druggability_tier(
        drug_count=scoring_drug_count,
        tractability_labels=tractability_labels,
        loeuf=loeuf,
        plddt_mean=plddt_mean,
    )

    report: dict[str, Any] = {
        "uniprot_id": uid,
        "druggability_tier": tier,
        "tier_rationale": rationale,
        "scoring_breakdown": scoring,
        "data_sources_status": {
            "chembl_drug_count": chembl_status,
            "open_targets_drug_count": ot_status,
            "alphafold_plddt": plddt_status,
        },
        "evidence": {
            "drug_count": drug_count,
            "drug_precedent_scoring_count": scoring_drug_count,
            "drug_count_source": precedent.source,
            "drug_precedent_scope": _precedent_scope(params.include_clinical_stage),
            "chembl_mechanism_molecule_count": chembl_observed_count,
            "open_targets_drug_candidate_count": ot_observed_count,
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
            # Same predicate the tier scoring credits, so the display can never
            # contradict the score (e.g. the canonical "Small molecule" label).
            "small_molecule": _has_small_molecule_tractability(tractability_labels),
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
            chembl="v37",
            open_targets="OT-platform-live-release-unverified",
            gnomad="v4",
            alphafold_db="v6",
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
    protein into a single structured record. It composes upstream records
    and author-defined research heuristics, without issuing clinical conclusions.

    Sources fused in parallel:
      - **Open Targets**: disease associations + tractability + drug count
      - **DisGeNET**: curated GDA scores with publication counts
      - **ChEMBL**: approved drugs + MoA + bioactivity
      - **gnomAD**: population constraint (pLI, LOEUF, mis_z)
      - **ClinVar**: pathogenic variants in this gene
      - **Ensembl**: orthologs across 12 species

    Input fields:
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
    ot_resolved, ot_resolve_error = await _resolve_open_targets(uid)
    if isinstance(ot_resolve_error, AmbiguousTargetError):
        # The accession maps to more than one target: identity cannot be
        # established, so multi-source synthesis must not proceed on a guess.
        raise ValueError(
            "Protein dossier target identity could not be established: the "
            "UniProt-to-Ensembl mapping is ambiguous."
        ) from ot_resolve_error
    ensembl_id = ot_resolved.get("ensembl_id", "")
    mapped_symbol = ot_resolved.get("symbol", "")
    if mapped_symbol and mapped_symbol.casefold() != sym.casefold():
        raise ValueError(
            "Protein dossier target identity mismatch: supplied gene_symbol "
            "does not agree with the UniProt-to-Ensembl mapping."
        )
    identity_sources: list[str] = ["open_targets"] if mapped_symbol else []

    # AlphaFold confidence must be a valid measured [0, 100] value. The same
    # record names the accession's gene, a second accession-keyed identity
    # witness that is available even when Open Targets is not.
    dossier_plddt: float | None = None
    dossier_plddt_status = "missing"
    af_gene = ""
    try:
        af_meta: Any = await _alphafold().get_prediction(uid)
        if isinstance(af_meta, dict):
            dossier_plddt, dossier_plddt_status = validated_plddt(af_meta.get("globalMetricValue"))
            raw_gene = af_meta.get("gene")
            af_gene = raw_gene.strip() if isinstance(raw_gene, str) else ""
        else:
            dossier_plddt_status = "invalid_response"
    except Exception as exc:
        dossier_plddt_status = "failed"
        log.warning(
            "alphafold.plddt.failed",
            exc=str(exc),
            uniprot_id=uid,
        )
    if af_gene:
        if af_gene.casefold() != sym.casefold():
            raise ValueError(
                "Protein dossier target identity mismatch: supplied gene_symbol "
                "does not agree with the AlphaFold DB record for the accession."
            )
        identity_sources.append("alphafold_db")
    # True only when an accession-keyed source confirmed the supplied symbol;
    # with no witness available the identity rests on the caller's assertion.
    identity_verified = bool(identity_sources)

    # Parallel evidence gathering
    # When resolution failed, the Open Targets sources inherit that failure
    # instead of being queried with an empty identifier and read as no data.
    tasks: dict[str, Any] = {
        "ot_diseases": _ot_source_task(
            lambda eid: _opentargets().associated_diseases(eid, limit=10),
            ensembl_id,
            ot_resolve_error,
        ),
        "ot_tractability": _ot_source_task(
            _opentargets().drug_count_and_tractability, ensembl_id, ot_resolve_error
        ),
        "disgenet": _disgenet().gene_disease_associations(sym, min_score=0.1, limit=10),
        "gene_constraint": _gnomad().gene_constraint(sym),
        "clinvar_variants": _clinvar().search_gene(sym, limit=5),
        "ensembl_gene": _ensembl().gene_lookup(sym),
    }

    gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)

    # Keep upstream failures distinguishable from valid empty source results.
    def _source_state(value: Any) -> str:
        # Clients raise ValueError for malformed source content; transport
        # and upstream errors are everything else.
        if value is _SKIPPED:
            return "skipped"
        if isinstance(value, ValueError):
            return "invalid_response"
        if isinstance(value, BaseException):
            return "failed"
        if not isinstance(value, (dict, list)):
            return "invalid_response"
        # Ensembl and gnomAD report a successful negative lookup with an
        # explicit availability flag inside a nonempty sentinel dictionary.
        if isinstance(value, dict) and any(
            value.get(flag) is False for flag in ("found", "constraint_available")
        ):
            return "no_data"
        return "ok" if value else "no_data"

    source_status = {key: _source_state(value) for key, value in zip(tasks.keys(), gathered)}
    results: dict[str, Any] = {
        k: (v if isinstance(v, (dict, list)) else None) for k, v in zip(tasks.keys(), gathered)
    }

    # A failed ChEMBL target lookup must not abort the other dossier sources.
    drugs: list[dict[str, Any]] = []
    chembl_drug_status = "no_data"
    chembl_target: dict[str, Any] | None = None
    try:
        target_result: Any = await _chembl().target_by_uniprot(uid)
        if isinstance(target_result, dict):
            chembl_target = target_result
        elif target_result is not None:
            chembl_drug_status = "invalid_response"
    except ValueError as exc:
        chembl_drug_status = "invalid_response"
        log.warning("chembl.target.invalid", uniprot_id=uid, exc=str(exc))
    except Exception as exc:
        chembl_drug_status = "failed"
        log.warning("chembl.target.failed", uniprot_id=uid, exc=str(exc))
    if chembl_target:
        target_id = chembl_target.get("chembl_id", "")
        if target_id:
            try:
                drugs = await _chembl().approved_drugs(
                    target_id, include_clinical=True, require_complete=True
                )
                chembl_drug_status = "ok"
            except ValueError as exc:
                chembl_drug_status = "invalid_response"
                log.warning("chembl.approved_drugs.invalid", exc=str(exc), target_id=target_id)
            except Exception as exc:
                chembl_drug_status = "failed"
                log.warning(
                    "chembl.approved_drugs.failed",
                    exc=str(exc),
                    target_id=target_id,
                )

    # Orthologs (comprehensive depth only)
    orthologs: list[dict[str, Any]] = []
    if params.depth == "comprehensive":
        try:
            orthologs = await _ensembl().orthologs(sym, limit=12)
        except Exception as exc:
            log.warning(
                "ensembl.orthologs.failed",
                exc=str(exc),
                gene=sym,
            )

    # Build dossier
    ot_diseases = results.get("ot_diseases") or []
    ot_scores = [s.to_dict() if hasattr(s, "to_dict") else s for s in ot_diseases]
    ot_tract = results.get("ot_tractability") or {}
    disgenet = results.get("disgenet") or []
    constraint = results.get("gene_constraint") or {}
    clinvar_vars = results.get("clinvar_variants") or []
    ensembl_gene = results.get("ensembl_gene") or {}

    # Missing retrieval is not an observed drug count of zero. The dossier
    # always requests approved plus clinical ChEMBL molecules, so the
    # all-stage Open Targets record count is scope-comparable here.
    ot_count = ot_tract.get("drug_count")
    chembl_observed_count = len(drugs) if chembl_drug_status == "ok" else None
    ot_observed_count = (
        ot_count
        if isinstance(ot_count, int) and not isinstance(ot_count, bool) and ot_count >= 0
        else None
    )
    # The gathered source state says the request succeeded; the count status
    # says whether an observed count came back with it.
    if source_status["ot_tractability"] in {"failed", "invalid_response", "skipped"}:
        ot_count_status = source_status["ot_tractability"]
    elif ot_observed_count is not None:
        ot_count_status = "ok"
    elif ot_count is not None:
        ot_count_status = "invalid_response"
    else:
        ot_count_status = "no_data"
    precedent = resolve_drug_precedent(
        chembl_count=chembl_observed_count,
        open_targets_count=ot_observed_count,
        include_clinical=True,
    )

    # Keep the established successful tier schema; fail on unavailable evidence.
    if precedent is None:
        raise ValueError(
            "Protein dossier druggability unavailable: no observed drug count "
            f"(chembl={chembl_drug_status}, open_targets={ot_count_status}). "
            "No dossier tier was assigned."
        )
    drug_count = precedent.drug_count
    scoring_drug_count = precedent.scoring_count
    tier, rationale, dossier_scoring = _druggability_tier(
        drug_count=scoring_drug_count,
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
            "identity_verified": identity_verified,
            "identity_sources": identity_sources,
            "ensembl_gene_id": ensembl_gene.get("ensembl_gene_id", ""),
            "description": ensembl_gene.get("description", ""),
        },
        "druggability": {
            "tier": tier,
            "rationale": rationale,
            "drug_count": drug_count,
            "drug_precedent_scoring_count": scoring_drug_count,
            "drug_count_source": precedent.source,
            "drug_precedent_scope": _precedent_scope(True),
            "chembl_mechanism_molecule_count": chembl_observed_count,
            "open_targets_drug_candidate_count": ot_observed_count,
            "tractability_labels": ot_tract.get("tractability_labels", []),
            "confidence": dossier_scoring["confidence"] if dossier_scoring else None,
            "borderline": dossier_scoring["borderline"] if dossier_scoring else None,
            "signals": dossier_scoring["signals"] if dossier_scoring else None,
            "score_normalized": dossier_scoring["score_normalized"] if dossier_scoring else None,
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
            drug_count=drug_count,
            diseases=list(disease_map.values()),
            constraint=constraint,
        ),
    }

    if params.depth in ("standard", "comprehensive"):
        dossier["open_targets_detail"] = ot_scores[:5]
        dossier["disgenet_detail"] = disgenet[:5]

    if params.depth == "comprehensive":
        dossier["cross_species_orthologs"] = orthologs

    dossier["data_sources_status"] = {
        **source_status,
        "chembl_drugs": chembl_drug_status,
        "open_targets_drug_count": ot_count_status,
        "alphafold_plddt": dossier_plddt_status,
    }
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
        open_targets="OT-platform-live-release-unverified",
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
    """Map a bounded, source-attributed therapeutic landscape for a disease.

    Returns retrieved approved drugs, pipeline agents, top druggable targets,
    and an exploratory summary for a given MONDO disease.

    Combines Open Targets evidence with ChEMBL drug indications and
    MONDO disease hierarchy to produce a comprehensive landscape report
    used in business development, competitive intelligence, and
    R&D portfolio decisions.

    Input fields:
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
    mondo_status = "failed" if isinstance(mondo_result, BaseException) else "ok"
    if isinstance(mondo_result, BaseException):
        log.warning("mondo.failed", exc=str(mondo_result))
    else:
        disease_name = mondo_result.name or mid
        if mondo_result.efo_ids:
            efo_curie = mondo_result.efo_ids[0]

    # Many MONDO terms carry no direct EFO cross-reference (e.g. the broad
    # "breast cancer" node). Resolve one via Open Targets full-text search so
    # the disease still reaches ChEMBL's EFO-keyed drug indications.
    efo_resolve_error: Exception | None = None
    if not efo_curie and disease_name:
        try:
            efo_curie = await _opentargets().resolve_disease_efo(disease_name)
        except Exception as exc:
            efo_resolve_error = exc
            log.warning("opentargets.disease_search.failed", exc=str(exc))

    # When the MONDO ID yields no Open Targets associations, retry via the
    # EFO cross-reference (OT's native disease ontology).
    if (isinstance(ot_targets, BaseException) or not ot_targets) and efo_curie:
        try:
            ot_targets = await _opentargets().associated_targets(
                efo_curie.replace("EFO:", "EFO_"), limit=20
            )
        except Exception as exc:
            # A failed retry leaves the target list unobserved: an earlier empty
            # MONDO-keyed page must not be reported as a measured zero.
            ot_targets = exc
            log.warning("opentargets.efo_fallback.failed", exc=str(exc))
    elif efo_resolve_error is not None and not ot_targets:
        # The EFO retry could not even be attempted: an empty MONDO-keyed page
        # is unobserved, not a measured zero.
        ot_targets = efo_resolve_error

    if isinstance(ot_targets, ValueError):
        ot_status = "invalid_response"  # the client rejected the source content
    elif isinstance(ot_targets, BaseException):
        ot_status = "failed"
    elif ot_targets:
        ot_status = "ok"
    else:
        ot_status = "no_data"

    top_targets: list[dict[str, Any]] = []
    if not isinstance(ot_targets, BaseException):
        top_targets = [
            cast("dict[str, Any]", t.to_dict() if hasattr(t, "to_dict") else t)
            for t in ot_targets[:10]
        ]

    # ChEMBL drug indications are keyed on EFO / MeSH, not MONDO. Use the EFO
    # cross-reference when available, falling back to the disease name (MeSH).
    chembl_drugs: list[dict[str, Any]] = []
    chembl_status = "skipped"
    try:
        if efo_curie:
            chembl_drugs = await _chembl().drug_indications(efo_id=efo_curie, limit=20)
            chembl_status = "ok" if chembl_drugs else "no_data"
        elif disease_name:
            chembl_drugs = await _chembl().drug_indications(mesh_heading=disease_name, limit=20)
            chembl_status = "ok" if chembl_drugs else "no_data"
    except ValueError as exc:
        # The client rejects a malformed response envelope; that is not an
        # observed empty indication page.
        chembl_status = "invalid_response"
        log.warning("chembl.indications.invalid", exc=str(exc))
    except Exception as exc:
        chembl_status = "failed"
        log.warning("chembl.indications.failed", exc=str(exc))

    # Classify drugs by ChEMBL's documented max_phase_for_ind values: 4
    # approved, 3, 2, 1, 0.5 (early phase 1). A source value of -1 (clinical
    # phase unknown) or a missing/unparseable value cannot be bucketed, so the
    # phase-derived counts below are withheld whenever such a row is present.
    phases = [_indication_phase(d) for d in chembl_drugs]
    approved = [d for d, p in zip(chembl_drugs, phases) if p == 4]
    phase3 = [d for d, p in zip(chembl_drugs, phases) if p == 3]
    phase12 = [d for d, p in zip(chembl_drugs, phases) if p in (0.5, 1, 2)]
    unassigned_phase = sum(1 for p in phases if p not in (0.5, 1, 2, 3, 4))
    phases_assessed = chembl_status in {"ok", "no_data"} and unassigned_phase == 0

    # The drug-indication endpoint returns molecule IDs but not names; backfill
    # preferred names for the entries we surface in one bulk request.
    shown = approved[:10] + phase3[:10] + phase12[:10]
    if shown:
        names = await _chembl().molecule_names([d.get("molecule_chembl_id", "") for d in shown])
        for d in shown:
            if not d.get("pref_name"):
                d["pref_name"] = names.get(d.get("molecule_chembl_id", ""), "")

    # Count the entire retrieved page, not just the displayed top ten.
    target_rows = (
        [cast("dict[str, Any]", t.to_dict() if hasattr(t, "to_dict") else t) for t in ot_targets]
        if isinstance(ot_targets, list)
        else []
    )
    druggable_targets = [t for t in target_rows if t.get("tractable")]
    retrieved_targets = len(ot_targets) if isinstance(ot_targets, list) else None
    # A row whose tractability is unknown (``None``) is not an observed
    # non-tractable target; the tractable count is unassessed in that case.
    tractability_assessed = retrieved_targets is not None and all(
        isinstance(t.get("tractable"), bool) for t in target_rows
    )
    retrieved_indications = len(chembl_drugs) if chembl_status in {"ok", "no_data"} else None
    # A page shorter than the request limit is the complete source result; a
    # full page may be truncated, so its count is a lower bound. The numeric
    # total_* fields keep the retrieved count (the published contract) and the
    # *_page_complete flags say whether that count is a verified total.
    target_page_complete = retrieved_targets < 20 if retrieved_targets is not None else None
    indication_page_complete = (
        retrieved_indications < 20 if retrieved_indications is not None else None
    )
    counts_assessable = bool(
        target_page_complete
        and indication_page_complete
        and tractability_assessed
        and phases_assessed
    )
    investability = (
        _investability_rating(
            approved_count=len(approved),
            pipeline_count=len(phase3) + len(phase12),
            druggable_targets=len(druggable_targets),
        )
        if counts_assessable
        else "NOT_ASSESSED — source lookup failed, was skipped, or pagination is unverified."
    )

    landscape: dict[str, Any] = {
        "disease": {
            "mondo_id": mid,
            "name": disease_name,
        },
        "drug_landscape": {
            "approved_drugs": approved[:10],
            "phase_3_drugs": phase3[:10],
            "phase_1_2_drugs": phase12[:10],
            "total_indication_entries": retrieved_indications,
            "indication_page_complete": indication_page_complete,
            "retrieved_indication_entries": retrieved_indications,
            "unassigned_phase_entries": unassigned_phase
            if retrieved_indications is not None
            else None,
            "page_limit": 20,
        },
        "target_landscape": {
            "top_targets": top_targets[:10],
            "druggable_targets": druggable_targets[:5],
            "total_associated_targets": retrieved_targets,
            "target_page_complete": target_page_complete,
            "retrieved_associated_targets": retrieved_targets,
            "page_limit": 20,
        },
        "competitive_intelligence": {
            "approved_count": len(approved) if phases_assessed else None,
            "pipeline_count": len(phase3) + len(phase12) if phases_assessed else None,
            "druggable_target_count": len(druggable_targets) if tractability_assessed else None,
            "investability": investability,
            "count_scope": "Retrieved source page only, not a verified whole-database count.",
        },
        "data_sources_status": {
            "mondo": mondo_status,
            "open_targets": ot_status,
            "chembl_indications": chembl_status,
        },
        "data_sources": {
            "mondo": "https://www.ebi.ac.uk/ols4/ontologies/mondo",
            "open_targets": "https://platform.opentargets.org",
            "chembl": "https://www.ebi.ac.uk/chembl/",
        },
        "provenance": _provenance(
            open_targets="OT-platform-live-release-unverified",
            chembl="v37",
        ),
    }

    log.info("complete", approved=len(approved), pipeline=len(phase3) + len(phase12))
    return landscape


# ── Tool 5: ACMG variant classification framework ────────────────────────────


def _is_pathogenic_strong_key(key: str, criterion: dict[str, Any]) -> bool:
    """True for a met, Strong-tier pathogenic criterion (PS1–PS4).

    Classification is keyed on the ACMG criterion code, never on the free-text
    evidence string — so an empty or unusually-worded evidence value can neither
    change the count nor crash the tool. PVS1 is the separate Very Strong gate
    and is excluded by key: even when the LOEUF rule downgrades its strength to
    "Strong", a lone PVS1 must not count itself into a Pathogenic call.
    """
    return (
        bool(criterion.get("met"))
        and key.startswith("P")
        and key != "PVS1"
        and criterion.get("strength") == "Strong"
    )


def _is_benign_strong_key(key: str, criterion: dict[str, Any]) -> bool:
    """True for a met, Strong or Stand-alone benign criterion (BA1, BS1–BS4).

    Symmetric with :func:`_is_pathogenic_strong_key`: keyed on the criterion
    code, independent of the evidence text.
    """
    return (
        bool(criterion.get("met"))
        and key.startswith("B")
        and criterion.get("strength") in ("Strong", "Stand-alone")
    )


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

    Reports computational observations that may inform an expert's later
    disease-specific ACMG/AMP review. This tool does NOT establish ACMG
    criteria or assign a pathogenicity class: generic consequence, model
    scores, and population frequencies are insufficient without clinical
    disease mechanism, inheritance, and criterion-specific validation.

    Criteria populated:
      PVS1 — Candidate loss-of-function consequence; mechanism not established
      PM2   — Absent/extremely rare in gnomAD population databases
      PP3   — Multiple in-silico predictors (AlphaMissense ≥0.564, SIFT, PolyPhen, CADD)
      BP4   — In-silico benign evidence (AlphaMissense ≤0.340)
      BP7   — Silent variant, no splicing impact
      BS1   — Allele frequency > 5% in gnomAD
      ClinVar is returned as independent source context, not as PP5/BP6 evidence.

    Input fields:
        params.hgvs: HGVS expression.
        params.inheritance_pattern: Expected inheritance mode.
    """
    hgvs = params.hgvs.strip()

    vep_task = _ensembl().vep_hgvs(hgvs, canonical=True)
    clinvar_task = _clinvar().search_by_hgvs(hgvs)
    gathered: list[Any] = await asyncio.gather(vep_task, clinvar_task, return_exceptions=True)
    vep_raw, clinvar_raw = gathered[0], gathered[1]
    source_status: dict[str, str] = {}

    def _checked_rows(name: str, raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, BaseException):
            source_status[name] = "failed"
            return []
        if not isinstance(raw, list) or not all(isinstance(row, dict) for row in raw):
            source_status[name] = "invalid_response"
            return []
        source_status[name] = "ok" if raw else "no_data"
        return raw

    vep_results = _checked_rows("ensembl_vep", vep_raw)
    clinvar_results = _checked_rows("clinvar", clinvar_raw)
    gene_symbol = _report_gene_from_sources(hgvs, vep_results, clinvar_results)
    if clinvar_results and not any(r.get("exact_change_match") is True for r in clinvar_results):
        source_status["clinvar"] = (
            "candidate_only"
            if any(r.get("candidate_change_match") is True for r in clinvar_results)
            else "no_verified_match"
        )

    # gnomAD
    gnomad_data: dict[str, Any] = {}
    gnomad_id = _build_gnomad_id(hgvs, vep_results)
    source_status["gnomad_variant"] = "skipped"
    if gnomad_id:
        try:
            variant_response: object = await _gnomad().variant_frequencies(gnomad_id)
            if isinstance(variant_response, dict):
                gnomad_data = variant_response
                source_status["gnomad_variant"] = _gnomad_result_status(variant_response, "found")
            else:
                source_status["gnomad_variant"] = "invalid_response"
        except Exception as exc:
            source_status["gnomad_variant"] = "failed"
            logger.warning(
                "gnomad.variant_frequencies.failed",
                exc=str(exc),
                gnomad_id=gnomad_id,
            )

    # Gene constraint (for PVS1 context)
    gene_constraint: dict[str, Any] = {}
    source_status["gnomad_constraint"] = "skipped"
    if gene_symbol:
        try:
            constraint_response: object = await _gnomad().gene_constraint(gene_symbol)
            if isinstance(constraint_response, dict):
                gene_constraint = constraint_response
                source_status["gnomad_constraint"] = _gnomad_result_status(
                    constraint_response, "constraint_available"
                )
            else:
                source_status["gnomad_constraint"] = "invalid_response"
        except Exception as exc:
            source_status["gnomad_constraint"] = "failed"
            logger.warning(
                "gnomad.gene_constraint.failed",
                exc=str(exc),
                gene=gene_symbol,
            )

    am_score: float | None = await _alphamissense_for_variant(
        gene_symbol,
        vep_results,
        source_status=source_status,
    )
    global_af: float | None = gnomad_data.get("global_af")
    # See generate_variant_clinical_report: a non-exact top hit must not be
    # reported as the queried variant's own ClinVar classification.
    clinvar_record = (
        clinvar_results[0]
        if clinvar_results and clinvar_results[0].get("exact_change_match") is True
        else None
    )
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

    # ClinVar classification is an external assertion, not an ACMG
    # criterion. Preserve it below with its review status and source ID.

    # Gene-level constraint does not validate a gene-disease loss-of-function
    # mechanism. Record it as context without changing any ACMG strength.
    if "PVS1" in criteria and loeuf is not None:
        criteria["PVS1"]["evidence"] += (
            f" LOEUF={loeuf:.3f} is gene-level constraint; not sufficient "
            "for disease-specific PVS1 assessment."
        )

    # No P/LP/VUS/B/LB classification is issued without gene-disease-specific
    # evidence and accredited professional review. A VUS is itself a clinical
    # classification; absent evidence must not silently become a VUS.
    candidate_signals = {
        code: {
            "computational_observation": data["evidence"],
            "suggested_criterion_for_review": code,
            "clinical_criterion_status": "not_assessed",
        }
        for code, data in criteria.items()
    }

    return {
        "hgvs": hgvs,
        "gene_symbol": gene_symbol,
        "inheritance_pattern": params.inheritance_pattern,
        "draft_classification": "Not assessed",
        "clinical_classification_performed": False,
        "clinvar_reference": {
            "found": clinvar_record is not None,
            "classification": clinvar_class,
            "review_status": (clinvar_record or {}).get("review_status", ""),
            "variation_id": (clinvar_record or {}).get("variation_id", ""),
            "identity_status": "exact_transcript" if clinvar_record is not None else "unverified",
            "unverified_candidates": [
                {"variation_id": row.get("variation_id", ""), "name": row.get("name", "")}
                for row in clinvar_results
                if row.get("candidate_change_match") is True
            ][:3],
            "interpretation": (
                "External source classification, only when versioned-transcript text "
                "matches; unverified candidates are not counted as ACMG evidence."
            ),
        },
        "criteria_met": {},
        "criteria_not_met": [],
        "candidate_criteria": candidate_signals,
        "summary": {
            "pathogenic_evidence_count": 0,
            "benign_evidence_count": 0,
            "unreviewed_computational_signals": len(candidate_signals),
        },
        "data_sources_status": source_status,
        "disclaimer": (
            "This tool does not classify a variant or establish ACMG/AMP criteria. "
            "All computed signals are unreviewed and disease mechanism evidence is absent. "
            "Independent ClinVar records are context, never PP5/BP6 evidence. "
            "A qualified clinical molecular geneticist must assess all applicable criteria."
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
    """Rank existing clinical-stage drugs as repurposing candidates for a disease.

    Surfaces approved or trial-stage drugs whose target carries genetic/association
    evidence for the disease — i.e. drug-repurposing hypotheses. For the full
    approved-plus-pipeline drug picture of a disease (not only repurposing
    candidates), use ``map_disease_drug_landscape`` instead.

    How it works: take the top ``target_limit`` Open Targets evidence-scored targets
    for the disease; for each, fetch its ChEMBL drugs at or above ``min_phase``; drop
    duplicate molecules; rank by
    ``composite_repurposing_score = OT evidence score × (max ChEMBL phase / 4)``.
    Ranking uses clinical and association evidence only — no protein structure.

    Returns a JSON record whose ``candidates`` list holds up to 20 drugs (each with
    ChEMBL ID, name, max phase, target gene/UniProt, OT evidence score, composite
    score, and mechanism), plus the candidate count and the methodology string.
    Returns an empty ``candidates`` list with a ``message`` when the disease has no
    Open Targets associations. The composite score is a prioritisation aid, not an
    efficacy prediction — validate mechanistically before acting on it.

    Input fields:
        params.disease_mondo_id: MONDO disease ID to repurpose against, e.g.
            'MONDO:0007254' (breast carcinoma).
        params.target_limit: How many top OT-evidence targets to screen (1–50).
        params.min_phase: Minimum ChEMBL clinical phase to include
            (1 = Phase I, 2 = Phase II, 3 = Phase III, 4 = Approved).
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
            "candidate_count": 0,
            "data_sources_status": {"open_targets": "no_data", "chembl": "skipped"},
            "evidence_completeness": {
                "targets_considered": 0,
                "chembl_lookups_assessed": 0,
                "chembl_lookups_failed": 0,
                "targets_without_uniprot": 0,
                "partial": False,
            },
        }

    # Step 2: Find drugs for each target (parallel, bounded)
    semaphore = asyncio.Semaphore(5)

    async def _get_drugs_for_target(
        target: Any,
    ) -> tuple[Any, list[dict[str, Any]], str]:
        async with semaphore:
            uid = (
                target.uniprot_id if hasattr(target, "uniprot_id") else target.get("uniprot_id", "")
            )
            if not uid:
                return target, [], "skipped"
            try:
                drugs = await _chembl().find_repurposable_drugs(
                    uid,
                    max_phase=params.min_phase,
                    limit=5,
                )
                return target, drugs, "ok" if drugs else "no_data"
            except ValueError as exc:
                # The client rejects ambiguous targets, unverifiable pagination
                # and malformed molecule content with ValueError.
                log.warning("chembl.repurposing.invalid", uniprot_id=uid, exc=str(exc))
                return target, [], "invalid_response"
            except Exception as exc:
                log.warning("chembl.repurposing.failed", uniprot_id=uid, exc=str(exc))
                return target, [], "failed"

    drug_results = await asyncio.gather(
        *[_get_drugs_for_target(t) for t in ot_targets],
        return_exceptions=True,
    )

    # Step 3: Build candidate list
    candidates: list[dict[str, Any]] = []
    seen_drug_ids: set[str] = set()
    lookup_statuses: list[str] = []
    invalid_drug_records = 0

    for result in drug_results:
        if isinstance(result, BaseException):
            lookup_statuses.append("failed")
            continue
        target, drugs, lookup_status = result
        lookup_statuses.append(lookup_status)
        target_dict = target.to_dict() if hasattr(target, "to_dict") else target
        ot_score = target_dict.get("overall_score", 0.0)

        for candidate_record in drugs:
            drug: Any = candidate_record
            if not isinstance(drug, dict):
                invalid_drug_records += 1
                continue
            drug_id = drug.get("molecule_chembl_id")
            if not isinstance(drug_id, str) or not drug_id:
                invalid_drug_records += 1
                continue
            if drug_id in seen_drug_ids:
                continue
            raw_phase = drug.get("max_phase")
            if raw_phase is None or isinstance(raw_phase, bool):
                invalid_drug_records += 1
                continue
            try:
                measured_phase = float(raw_phase)
            except (TypeError, ValueError, OverflowError):
                invalid_drug_records += 1
                continue
            if (
                not math.isfinite(measured_phase)
                or not params.min_phase <= measured_phase <= 4
                or drug.get("max_phase_known", True) is not True
            ):
                invalid_drug_records += 1
                continue
            seen_drug_ids.add(drug_id)
            phase = int(measured_phase) if measured_phase.is_integer() else measured_phase
            composite_score = round(ot_score * (measured_phase / 4.0), 4)
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
    failed_lookups = lookup_statuses.count("failed")
    invalid_lookups = lookup_statuses.count("invalid_response")
    assessed_lookups = lookup_statuses.count("ok") + lookup_statuses.count("no_data")
    skipped_lookups = lookup_statuses.count("skipped")
    if (failed_lookups or invalid_lookups) and assessed_lookups:
        chembl_status = "partial"
    elif failed_lookups:
        chembl_status = "failed"
    elif invalid_lookups:
        chembl_status = "invalid_response"
    elif assessed_lookups:
        chembl_status = "ok" if "ok" in lookup_statuses else "no_data"
    else:
        chembl_status = "skipped"
    if invalid_drug_records and chembl_status == "ok":
        chembl_status = "partial"

    report = {
        "disease_mondo_id": mid,
        "min_phase": params.min_phase,
        "candidates": candidates[:20],
        "candidate_count": len(candidates),
        "data_sources_status": {"open_targets": "ok", "chembl": chembl_status},
        "evidence_completeness": {
            "targets_considered": len(ot_targets),
            "chembl_lookups_assessed": assessed_lookups,
            "chembl_lookups_failed": failed_lookups,
            "chembl_lookups_invalid": invalid_lookups,
            "targets_without_uniprot": skipped_lookups,
            "invalid_or_unassessed_drug_records": invalid_drug_records,
            "partial": bool(
                failed_lookups or invalid_lookups or skipped_lookups or invalid_drug_records
            ),
        },
        "methodology": (
            "Composite score = (Open Targets evidence score × clinical phase / 4). "
            "Higher scores indicate stronger genetic evidence + more advanced clinical precedent. "
            "This is a computational prioritization — mechanistic validation is required."
        ),
        "data_sources": {
            "open_targets": "https://platform.opentargets.org",
            "chembl": "https://www.ebi.ac.uk/chembl/",
        },
        "provenance": _provenance(open_targets="OT-platform-live-release-unverified", chembl="v37"),
    }
    warnings: list[str] = []
    if failed_lookups:
        warnings.append(
            f"ChEMBL retrieval failed for {failed_lookups} target(s). "
            "The candidate list is incomplete; absence of candidates is not evidence of no drugs."
        )
    if invalid_lookups:
        warnings.append(
            f"ChEMBL returned content that could not be validated for {invalid_lookups} "
            "target(s). The candidate list is incomplete; absence of candidates is not "
            "evidence of no drugs."
        )
    if invalid_drug_records:
        warnings.append(
            f"{invalid_drug_records} candidate record(s) lacked verified molecule identity "
            "or valid observed clinical phase and were not scored."
        )
    if warnings:
        report["message"] = " ".join(warnings)
    return report


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_gnomad_id(hgvs: str, vep_results: list[dict[str, Any]]) -> str | None:
    """Attempt to build a gnomAD variant ID from VEP result mappings."""
    for hit in vep_results:
        # VEP top-level hit contains seq_region_name, start, and allele_string
        chrom_raw = hit.get("seq_region_name")
        pos = hit.get("start")
        allele_str = hit.get("allele_string")
        if not isinstance(chrom_raw, str) or not isinstance(allele_str, str):
            continue
        chrom = chrom_raw.removeprefix("chr")
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
    """Legacy compatibility helper: clinical severity is never inferred here."""
    return "NOT_ASSESSED"


def _tier_explanation(tier: str) -> str:
    """Describe the boundary between retrieved data and clinical judgment."""
    return (
        "No clinical tier assessed by Topologica. Source-reported ClinVar "
        "classifications and computational observations remain separate; "
        "clinical interpretation requires disease-specific evidence and review."
    )


def _precedent_scope(include_clinical: bool) -> str:
    """Name the development-stage scope requested for the ChEMBL drug count."""
    return "approved_and_clinical" if include_clinical else "approved_only"


def _druggability_actionability(
    tier: str, drug_count: int | None, tractability_labels: list[str]
) -> str:
    if tier == "HOT":
        if _has_small_molecule_tractability(tractability_labels):
            basis = f"{drug_count} known drug(s) + small-molecule tractability label(s)"
        else:
            basis = f"{drug_count} known drug(s) on drug precedent alone (no small-molecule tractability label)"
        return f"Research heuristic HOT: {basis}. Independently verify target engagement and indication."
    if tier == "WARM":
        return (
            f"Research heuristic WARM: {drug_count} reported compound(s). "
            "No independent clinical or binding validation is implied."
        )
    if tier == "COLD":
        return (
            "Research heuristic COLD: limited retrieved drug precedent. "
            "This is not evidence of absent therapeutic potential."
        )
    return (
        "NOT_DRUGGABLE is an uncalibrated heuristic label, not a conclusion "
        "that the target cannot be drugged; check source coverage."
    )


def _narrative_summary(
    *,
    sym: str,
    tier: str,
    drug_count: int | None,
    diseases: list[dict[str, Any]],
    constraint: dict[str, Any],
) -> str:
    disease_names = ", ".join(d["disease_name"] for d in diseases[:3] if d.get("disease_name"))
    loeuf = constraint.get("loeuf")
    constraint_desc = ""
    if loeuf is not None:
        constraint_desc = (
            f"Gene-level LOEUF={loeuf:.3f}; this is not a clinical phenotype or safety inference. "
        )
    count_description = (
        f"{drug_count} source-reported drug or clinical-candidate record(s)"
        if drug_count is not None
        else "an unavailable drug-precedent count"
    )
    return (
        f"{sym} has a local {tier.lower()} target-priority heuristic and "
        f"{count_description}. "
        f"Top associated diseases: {disease_names or 'not determined'}. "
        f"{constraint_desc}"
        "This is an unvalidated research synthesis; inspect each source status "
        "and record identity before relying on the reported evidence."
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
        "BP7",
    ]
    return [c for c in all_codes if c not in criteria]


_INDICATION_PHASES = frozenset({-1.0, 0.5, 1.0, 2.0, 3.0, 4.0})
"""Observed ChEMBL ``max_phase_for_ind`` values (ChEMBL 37, probed 2026-10-28).

``-1`` is ChEMBL's marker for a clinical phase it cannot assign; ``0.5`` is
early phase 1. ChEMBL serves the field as a decimal string (``'4.0'``).
"""


def _indication_phase(drug: dict[str, Any]) -> float | None:
    """Return the source-reported ``max_phase_for_indication`` or ``None``.

    ``None`` means the phase is missing or unparseable; a reported ``-1`` is
    returned as is so callers can distinguish ChEMBL's "clinical phase
    unknown" from an absent value. Neither is ever read as phase 0.
    """
    raw = drug.get("max_phase_for_indication")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        phase = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return phase if phase in _INDICATION_PHASES else None


def _investability_rating(
    *, approved_count: int, pipeline_count: int, druggable_targets: int
) -> str:
    if approved_count >= 3 and druggable_targets >= 5:
        return "HIGH — heuristic source-count category, not clinical validation."
    if approved_count >= 1 or pipeline_count >= 3:
        return "MEDIUM — heuristic source-count category, not clinical validation."
    if druggable_targets >= 2:
        return "EARLY — heuristic source-count category; no independent biological validation."
    return "EXPLORATORY — limited retrieved evidence; absent records are not evidence of absence."
