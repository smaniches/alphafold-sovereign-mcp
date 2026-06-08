# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Disease ontology and clinical intelligence MCP tools.

12 tools spanning:
- MONDO disease lookup and hierarchy traversal
- HPO phenotype-to-disease and gene-to-phenotype
- Common disease protein target profiling (all major ICD chapters)
- Open Targets disease-target evidence scoring
- Variant 3-D triage (HGVS → ClinVar + gnomAD constraint + disease context)
- Phenotype-to-structure pipeline
- Cross-disease structural comparison
- Orphan disease structural atlas

All tools are read-only, idempotent, and append a provenance footer
with server version, request timestamp, and data-source identifiers.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from alphafold_sovereign import __version__
from alphafold_sovereign.clients.clinvar import ClinVarClient
from alphafold_sovereign.clients.ensembl import EnsemblClient
from alphafold_sovereign.clients.gnomad import GnomADClient
from alphafold_sovereign.clients.hpo import HPOClient
from alphafold_sovereign.clients.mondo import MONDOClient
from alphafold_sovereign.clients.opentargets import OpenTargetsClient
from alphafold_sovereign.domain.disease import (
    PathogenicityClass,
    TargetEvidenceScore,
)
from alphafold_sovereign.server.app import mcp

logger = structlog.get_logger(__name__)

_SERVER_VERSION = __version__

# ---------------------------------------------------------------------------
# Common disease MONDO IDs — curated, validated against MONDO 2025-01 release
# ---------------------------------------------------------------------------
COMMON_DISEASE_ROOTS: dict[str, dict[str, str]] = {
    "cardiovascular": {
        "coronary_artery_disease": "MONDO:0004995",
        "heart_failure": "MONDO:0005009",
        "atrial_fibrillation": "MONDO:0004981",
        "stroke": "MONDO:0005098",
        "hypertension": "MONDO:0001134",
        "peripheral_artery_disease": "MONDO:0006652",
    },
    "oncology": {
        "breast_carcinoma": "MONDO:0007254",
        "lung_carcinoma": "MONDO:0008903",
        "colorectal_carcinoma": "MONDO:0005575",
        "prostate_carcinoma": "MONDO:0006256",
        "pancreatic_carcinoma": "MONDO:0006265",
        "ovarian_carcinoma": "MONDO:0006046",
        "leukemia": "MONDO:0005059",
        "lymphoma": "MONDO:0005570",
        "hepatocellular_carcinoma": "MONDO:0007256",
        "melanoma": "MONDO:0005105",
    },
    "neurodegeneration": {
        "alzheimer_disease": "MONDO:0004975",
        "parkinson_disease": "MONDO:0005180",
        "amyotrophic_lateral_sclerosis": "MONDO:0004976",
        "multiple_sclerosis": "MONDO:0005301",
        "huntington_disease": "MONDO:0007739",
    },
    "metabolic": {
        "type_2_diabetes": "MONDO:0005148",
        "type_1_diabetes": "MONDO:0005147",
        "obesity": "MONDO:0011122",
        "nonalcoholic_fatty_liver": "MONDO:0007035",
        "metabolic_syndrome": "MONDO:0007255",
    },
    "autoimmune": {
        "rheumatoid_arthritis": "MONDO:0008383",
        "systemic_lupus_erythematosus": "MONDO:0007263",
        "inflammatory_bowel_disease": "MONDO:0005265",
        "multiple_sclerosis": "MONDO:0005301",
        "psoriasis": "MONDO:0005083",
    },
    "respiratory": {
        "chronic_obstructive_pulmonary_disease": "MONDO:0005002",
        "asthma": "MONDO:0004979",
        "idiopathic_pulmonary_fibrosis": "MONDO:0008345",
        "cystic_fibrosis": "MONDO:0009061",
    },
    "infectious": {
        "tuberculosis": "MONDO:0018076",
        "hiv_infection": "MONDO:0005109",
        "malaria": "MONDO:0005136",
        "covid_19": "MONDO:0100096",
        "hepatitis_b": "MONDO:0009842",
        "hepatitis_c": "MONDO:0005234",
    },
    "psychiatric": {
        "major_depressive_disorder": "MONDO:0002050",
        "schizophrenia": "MONDO:0005090",
        "bipolar_disorder": "MONDO:0004985",
        "anxiety_disorder": "MONDO:0005246",
    },
    "rare": {
        "cystic_fibrosis": "MONDO:0009061",
        "huntington_disease": "MONDO:0007739",
        "sickle_cell_disease": "MONDO:0011382",
        "phenylketonuria": "MONDO:0009861",
        "gaucher_disease": "MONDO:0010159",
    },
}


# ---------------------------------------------------------------------------
# Pydantic input models
# ---------------------------------------------------------------------------


class MONDOLookupInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    mondo_id: str = Field(
        ...,
        description="MONDO disease identifier, e.g. 'MONDO:0004995'.",
        min_length=1,
        max_length=20,
    )
    include_hierarchy: bool = Field(
        default=True,
        description="Include immediate parent and child MONDO terms.",
    )


class MONDOSearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(
        ...,
        description="Disease name or keyword, e.g. 'breast cancer', 'type 2 diabetes'.",
        min_length=2,
        max_length=200,
    )
    limit: int = Field(default=10, ge=1, le=50, description="Maximum results.")


class HPOTermInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    hpo_id: str = Field(
        ...,
        description="HPO term identifier, e.g. 'HP:0001250' (Seizure).",
        min_length=1,
        max_length=15,
    )
    include_diseases: bool = Field(
        default=True,
        description="Include diseases annotated with this phenotype.",
    )
    disease_limit: int = Field(default=20, ge=1, le=100)


class GenePhenotypeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    gene_symbol: str = Field(
        ...,
        description="HGNC gene symbol, e.g. 'BRCA1', 'TP53'.",
        min_length=1,
        max_length=50,
    )
    include_constraint: bool = Field(
        default=True,
        description="Include gnomAD constraint scores for the gene.",
    )


class DiseaseTargetsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    disease_id: str = Field(
        ...,
        description=(
            "MONDO or EFO disease ID, e.g. 'MONDO:0007254' (breast carcinoma). "
            "Accepts MONDO, EFO, or Orphanet IDs — Open Targets maps them all."
        ),
        min_length=1,
        max_length=30,
    )
    limit: int = Field(default=20, ge=1, le=100)
    min_score: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Minimum overall evidence score (0–1).",
    )
    include_tractable_only: bool = Field(
        default=False,
        description="If true, return only tractable (druggable) targets.",
    )


class TargetDiseaseInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    uniprot_id: str = Field(
        ...,
        description="UniProt accession for the protein target, e.g. 'P12345'.",
        min_length=1,
        max_length=20,
    )
    ensembl_id: str = Field(
        default="",
        description=(
            "Ensembl gene ID (optional; used to bypass UniProt→Ensembl lookup). "
            "e.g. 'ENSG00000012048'."
        ),
        max_length=20,
    )
    limit: int = Field(default=20, ge=1, le=100)


class CommonDiseaseInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    category: str = Field(
        ...,
        description=(
            "Disease category. One of: "
            "cardiovascular, oncology, neurodegeneration, metabolic, "
            "autoimmune, respiratory, infectious, psychiatric, rare."
        ),
    )
    disease_name: str = Field(
        default="",
        description=(
            "Specific disease within the category. "
            "Leave blank to profile all diseases in the category."
        ),
        max_length=100,
    )
    target_limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum top targets to return per disease.",
    )


class VariantTriageInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    hgvs: str = Field(
        ...,
        description=(
            "HGVS variant expression. Supports coding DNA notation "
            "e.g. 'BRCA1:c.181T>G', 'TP53:c.817C>T', "
            "or genomic e.g. 'chr17:g.43094692G>A'."
        ),
        min_length=5,
        max_length=200,
    )
    include_structure: bool = Field(
        default=True,
        description=(
            "Add a pointer note toward structural-confidence analysis. "
            "The full AlphaFold pLDDT/PAE join is a Wave-3 roadmap item "
            "(not wired into this tool yet)."
        ),
    )
    include_gnomad: bool = Field(
        default=True,
        description=(
            "Fetch gnomAD gene-CONSTRAINT scores (LOEUF / pLI) only. "
            "Per-variant allele frequencies are not wired into this tool."
        ),
    )
    include_disease_context: bool = Field(
        default=True,
        description=(
            "Add a placeholder disease-context note. The MONDO / Open "
            "Targets traversal is a Wave-3 roadmap item (stub)."
        ),
    )


class PhenotypeToStructureInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    hpo_id: str = Field(
        ...,
        description="HPO phenotype term ID, e.g. 'HP:0001250' (Seizure).",
        min_length=1,
        max_length=15,
    )
    disease_limit: int = Field(default=5, ge=1, le=20)
    targets_per_disease: int = Field(default=5, ge=1, le=20)


class OrphanDiseaseInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    orphanet_id: str = Field(
        ...,
        description="Orphanet disease ID, e.g. '79318' (Gaucher disease).",
        min_length=1,
        max_length=15,
    )


class DiseaseSimilarityInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    mondo_id_a: str = Field(..., description="First MONDO disease ID.", min_length=1, max_length=20)
    mondo_id_b: str = Field(
        ..., description="Second MONDO disease ID.", min_length=1, max_length=20
    )
    target_limit: int = Field(default=10, ge=1, le=50)


# ---------------------------------------------------------------------------
# Provenance footer
# ---------------------------------------------------------------------------


def _provenance(**sources: str) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    src_str = " | ".join(f"{k}={v}" for k, v in sources.items() if v)
    return f"\n\n---\n*AlphaFold Sovereign MCP v{_SERVER_VERSION} · {ts} · {src_str}*"


# ---------------------------------------------------------------------------
# Tool 1: MONDO disease lookup
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "MONDO Disease Lookup",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def lookup_disease(params: MONDOLookupInput) -> str:
    """Retrieve a disease record from the MONDO unified disease ontology.

    Returns the canonical MONDO entry with:
    - Disease name, definition, synonyms
    - ICD-10 / ICD-11 codes (for clinical coding / EHR integration)
    - OMIM, Orphanet, MeSH, DOID cross-references
    - Immediate parent and child terms in the MONDO hierarchy

    Example: ``lookup_disease(mondo_id='MONDO:0004995')``
    returns the record for coronary artery disease.
    """
    try:
        async with MONDOClient() as client:
            record = await client.lookup(params.mondo_id)
            parents: list[Any] = []
            children: list[Any] = []
            if params.include_hierarchy:  # pragma: no branch
                parents, children = await asyncio.gather(
                    client.ancestors(params.mondo_id, limit=5),
                    client.children(params.mondo_id),
                )

        result: dict[str, Any] = {
            "status": "success",
            "disease": record.to_dict(),
        }
        if params.include_hierarchy:
            result["hierarchy"] = {
                "parents": [{"id": t.id, "label": t.label} for t in parents[:5]],
                "children": [{"id": t.id, "label": t.label} for t in children[:10]],
            }

        output = json.dumps(result, indent=2)
        return output + _provenance(mondo="OLS4")

    except KeyError:
        return json.dumps(
            {
                "status": "not_found",
                "mondo_id": params.mondo_id,
                "message": "No MONDO record found for this ID.",
            }
        )
    except Exception as exc:
        logger.error("lookup_disease_failed", mondo_id=params.mondo_id, error=str(exc))
        return json.dumps({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# Tool 2: MONDO disease search
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Search Diseases (MONDO)",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def search_diseases(params: MONDOSearchInput) -> str:
    """Search for diseases by name or keyword using the MONDO ontology.

    Returns a ranked list of matching diseases with MONDO IDs and
    cross-references.  Useful for resolving a clinical term to a
    canonical identifier before querying targets or phenotypes.

    Example: ``search_diseases(query='breast cancer', limit=5)``
    """
    try:
        async with MONDOClient() as client:
            results = await client.search(params.query, limit=params.limit)
        if not results:
            return json.dumps(
                {
                    "status": "no_results",
                    "query": params.query,
                    "message": "No matching diseases found.",
                }
            )
        return json.dumps(
            {
                "status": "success",
                "query": params.query,
                "count": len(results),
                "results": [r.to_dict() for r in results],
            },
            indent=2,
        ) + _provenance(mondo="OLS4")
    except Exception as exc:
        logger.error("search_diseases_failed", query=params.query, error=str(exc))
        return json.dumps({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# Tool 3: HPO phenotype lookup
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "HPO Phenotype Lookup",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def lookup_phenotype(params: HPOTermInput) -> str:
    """Retrieve an HPO phenotype term with associated disease annotations.

    Returns:
    - Phenotype label, definition, synonyms
    - Diseases annotated with this phenotype (from HPO + OMIM + Orphanet)
    - Parent phenotype terms

    Example: ``lookup_phenotype(hpo_id='HP:0001250')``
    returns the Seizure phenotype with ~400 associated diseases.
    """
    try:
        async with HPOClient() as client:
            term = await client.lookup(params.hpo_id)
            diseases = []
            parents = []
            if params.include_diseases:  # pragma: no branch
                diseases, parents = await asyncio.gather(
                    client.diseases_for_phenotype(
                        params.hpo_id,
                        limit=params.disease_limit,
                    ),
                    client.ancestors(params.hpo_id),
                )

        result: dict[str, Any] = {
            "status": "success",
            "phenotype": term.to_dict(),
        }
        if params.include_diseases:
            result["associated_diseases"] = [d.to_dict() for d in diseases]
            result["parent_terms"] = [{"id": p.id, "label": p.label} for p in parents[:5]]

        return json.dumps(result, indent=2) + _provenance(hpo="JAX-HPO")

    except Exception as exc:
        logger.error("lookup_phenotype_failed", hpo_id=params.hpo_id, error=str(exc))
        return json.dumps({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# Tool 4: Gene phenotype profile
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Gene Phenotype Profile",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_gene_phenotype_profile(params: GenePhenotypeInput) -> str:
    """Return all HPO phenotypes associated with a gene, plus gnomAD constraint.

    Useful for understanding the clinical consequences of variants in a gene
    before requesting structural context.

    Returns:
    - HPO phenotypes linked to the gene (from HPO association database)
    - gnomAD LOEUF / pLI constraint scores
    - Interpretation of constraint (haploinsufficient / tolerant / moderate)

    Example: ``get_gene_phenotype_profile(gene_symbol='SCN1A')``
    """
    try:
        async with (
            EnsemblClient() as ensembl_client,
            HPOClient() as hpo_client,
            GnomADClient() as gnomad_client,
        ):
            # HPO's network-annotation endpoint is keyed on NCBI Gene IDs, so
            # resolve the HGNC symbol to its Entrez ID via Ensembl first.
            ncbi_gene_id = await ensembl_client.ncbi_gene_id(params.gene_symbol)

            coros: list[Any] = []
            if ncbi_gene_id:
                coros.append(
                    hpo_client.phenotypes_for_gene_id(
                        f"NCBIGene:{ncbi_gene_id}", gene_symbol=params.gene_symbol
                    )
                )
            if params.include_constraint:
                coros.append(gnomad_client.gene_constraint(params.gene_symbol))  # type: ignore[arg-type]
            results = await asyncio.gather(*coros, return_exceptions=True)

        phenotypes_result = results[0] if ncbi_gene_id else None
        constraint_result = results[-1] if params.include_constraint else {}

        phenotypes: list[dict[str, Any]] = []
        if phenotypes_result is not None and not isinstance(phenotypes_result, Exception):
            phenotypes = [p.to_dict() for p in phenotypes_result]

        constraint: dict[str, Any] = {}
        if not isinstance(constraint_result, Exception) and constraint_result:
            constraint = constraint_result  # type: ignore[assignment]

        return json.dumps(
            {
                "status": "success",
                "gene_symbol": params.gene_symbol,
                "phenotype_count": len(phenotypes),
                "phenotypes": phenotypes,
                "gnomad_constraint": constraint,
            },
            indent=2,
        ) + _provenance(hpo="JAX-HPO", gnomad="gnomAD-r4")

    except Exception as exc:
        logger.error("gene_phenotype_failed", gene=params.gene_symbol, error=str(exc))
        return json.dumps({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# Tool 5: Disease → protein targets (Open Targets)
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Disease Target Evidence",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_disease_targets(params: DiseaseTargetsInput) -> str:
    """Return top protein targets for a disease with Open Targets evidence scores.

    Evidence score breakdown (0–1 per data type):
    - ``genetic_association``: GWAS + rare-variant signals
    - ``somatic_mutation``: Cancer somatic variant evidence
    - ``known_drug``: Approved or clinical-stage drugs
    - ``affected_pathway``: Pathway membership (Reactome, SIGNOR)
    - ``literature``: Text-mining evidence (Europe PMC)
    - ``animal_model``: Knockout / model organism phenotypes
    - ``rna_expression``: Differential expression evidence

    Example: ``get_disease_targets(disease_id='MONDO:0007254', limit=15)``
    returns top 15 targets for breast carcinoma.
    """
    try:
        async with OpenTargetsClient() as ot:
            targets = await ot.associated_targets(
                params.disease_id,
                limit=params.limit,
            )

        filtered = [
            t
            for t in targets
            if t.overall_score >= params.min_score
            and (not params.include_tractable_only or t.tractable)
        ]

        return json.dumps(
            {
                "status": "success",
                "disease_id": params.disease_id,
                "total_returned": len(filtered),
                "targets": [t.to_dict() for t in filtered],
            },
            indent=2,
        ) + _provenance(open_targets="OT-platform-24.06")

    except Exception as exc:
        logger.error("get_disease_targets_failed", disease=params.disease_id, error=str(exc))
        return json.dumps({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# Tool 6: Protein target → diseases (Open Targets)
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Target Disease Associations",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_target_diseases(params: TargetDiseaseInput) -> str:
    """Return all diseases associated with a protein target via Open Targets.

    Accepts a UniProt accession and returns the full disease landscape
    for that target — essential for target-validation and indication-expansion.

    Example: ``get_target_diseases(uniprot_id='P04637')``
    returns all diseases associated with TP53 / p53.
    """
    try:
        ensembl_id = params.ensembl_id
        if not ensembl_id:
            ensembl_id = await _uniprot_to_ensembl(params.uniprot_id)

        async with OpenTargetsClient() as ot:
            disease_scores = await ot.associated_diseases(
                ensembl_id,
                limit=params.limit,
            )

        return json.dumps(
            {
                "status": "success",
                "uniprot_id": params.uniprot_id,
                "ensembl_id": ensembl_id,
                "total_returned": len(disease_scores),
                "diseases": [s.to_dict() for s in disease_scores],
            },
            indent=2,
        ) + _provenance(open_targets="OT-platform-24.06")

    except Exception as exc:
        logger.error("get_target_diseases_failed", uniprot=params.uniprot_id, error=str(exc))
        return json.dumps({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# Tool 7: Common disease target profiling
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Common Disease Target Profile",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def get_common_disease_targets(params: CommonDiseaseInput) -> str:
    """Profile protein targets for major common diseases across ICD chapters.

    Covers 9 disease categories with curated MONDO IDs and Open Targets
    evidence scores.  Designed for target-identification in drug discovery
    and for understanding the structural landscape of disease-relevant proteins.

    Categories: cardiovascular, oncology, neurodegeneration, metabolic,
    autoimmune, respiratory, infectious, psychiatric, rare.

    Example: ``get_common_disease_targets(category='neurodegeneration')``
    returns top targets for AD, PD, ALS, MS, and Huntington disease.
    """
    cat = params.category.lower().strip()
    if cat not in COMMON_DISEASE_ROOTS:
        return json.dumps(
            {
                "status": "error",
                "error": f"Unknown category '{cat}'. Valid: {sorted(COMMON_DISEASE_ROOTS.keys())}",
            }
        )

    disease_map = COMMON_DISEASE_ROOTS[cat]
    if params.disease_name:
        # Filter to the specified disease within the category
        hit = {
            k: v
            for k, v in disease_map.items()
            if params.disease_name.lower().replace(" ", "_") in k
        }
        if not hit:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"Disease '{params.disease_name}' not found in {cat}. "
                    f"Available: {list(disease_map.keys())}",
                }
            )
        disease_map = hit

    async with OpenTargetsClient() as ot:
        tasks = {
            name: ot.associated_targets(mondo_id, limit=params.target_limit)
            for name, mondo_id in disease_map.items()
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    profile: dict[str, Any] = {}
    for (disease_name, mondo_id), result in zip(disease_map.items(), results):
        if isinstance(result, Exception):
            profile[disease_name] = {"error": str(result), "mondo_id": mondo_id}
        else:
            profile[disease_name] = {
                "mondo_id": mondo_id,
                "top_targets": [t.to_dict() for t in result],  # type: ignore[union-attr]
            }

    return json.dumps(
        {
            "status": "success",
            "category": cat,
            "diseases_profiled": len(profile),
            "profile": profile,
        },
        indent=2,
    ) + _provenance(open_targets="OT-platform-24.06")


# ---------------------------------------------------------------------------
# Tool 8: Variant 3-D triage
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Variant 3-D Structural Triage",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def triage_variant_3d(params: VariantTriageInput) -> str:
    """Comprehensive clinical triage for a missense variant.

    Fuses the upstream signals this tool currently wires into a single
    prioritised report:

    1. **Pathogenicity** — ClinVar interpretation + review status. The
       ``alphamissense_score`` / ``alphamissense_interpretation`` fields
       are always ``null`` / "Not available" here: AlphaMissense is not
       wired into this tool. For an AlphaMissense pathogenicity score use
       ``generate_variant_clinical_report``.
    2. **Population genetics** — gnomAD LOEUF / pLI gene-constraint
       scores. Per-variant allele frequencies and the per-ancestry
       breakdown are not wired into this tool.
    3. **Disease associations** — a placeholder note pointing at
       ``get_target_diseases()``; the Open Targets / MONDO traversal is
       a roadmap (Wave-3) item.
    4. **Structural context** — a text note pointing at
       ``analyze_structural_confidence`` (resolve the gene to a UniProt
       accession first); the AlphaFold pLDDT / PAE join into this report
       is a roadmap (Wave-3) item.

    Returns a ``pathogenicity_tier``: HIGH / MEDIUM / LOW / UNKNOWN
    (derived from ClinVar; the AlphaMissense input is always absent here).

    Example: ``triage_variant_3d(hgvs='BRCA1:c.181T>G')``
    """
    hgvs = params.hgvs.strip()
    sources: list[str] = ["ClinVar"]

    try:
        # -- Step 1: Parse gene + coding change from HGVS ---------------
        gene_symbol, _ = _parse_hgvs_gene(hgvs)
        if not gene_symbol:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"Could not extract gene symbol from HGVS '{hgvs}'. "
                    "Expected format: 'GENE:c.NNNx>y' e.g. 'BRCA1:c.181T>G'.",
                }
            )

        # -- Step 2: Parallel data fetch --------------------------------
        clinvar_coro = _fetch_clinvar(hgvs, gene_symbol)
        gnomad_coro = _fetch_gnomad(hgvs, gene_symbol) if params.include_gnomad else None
        disease_coro = (
            _fetch_disease_context(gene_symbol) if params.include_disease_context else None
        )

        # Map each coroutine to its source key so results stay
        # unambiguously matched regardless of which include_* flags are
        # set (positional indexing breaks when gnomAD is off but disease
        # context is on). Insertion order keeps gather order
        # clinvar -> gnomad -> disease.
        coro_map: dict[str, Any] = {"clinvar": clinvar_coro}
        if gnomad_coro:
            coro_map["gnomad"] = gnomad_coro
            sources.append("gnomAD")
        if disease_coro:
            # Disease context is a local pointer note, not an upstream query
            # (the Open Targets / MONDO traversal is a Wave-3 roadmap item),
            # so it is deliberately not added to sources_queried or to the
            # provenance footer.
            coro_map["disease"] = disease_coro

        gathered = await asyncio.gather(*coro_map.values(), return_exceptions=True)
        results = dict(zip(coro_map.keys(), gathered))

        def _ok(value: Any) -> dict[str, Any]:
            return value if isinstance(value, dict) else {}

        clinvar_data: dict[str, Any] = _ok(results.get("clinvar"))
        gnomad_data: dict[str, Any] = _ok(results.get("gnomad"))
        disease_data: dict[str, Any] = _ok(results.get("disease"))

        # -- Step 3: Pathogenicity tier ---------------------------------
        clinvar_cls_raw = clinvar_data.get("classification", "Not provided")
        clinvar_cls = _parse_clinvar_class(clinvar_cls_raw)
        am_score: float | None = gnomad_data.get("alphamissense_score")
        tier = _compute_tier(clinvar_cls, am_score)

        report: dict[str, Any] = {
            "status": "success",
            "hgvs": hgvs,
            "gene_symbol": gene_symbol,
            "pathogenicity_tier": tier,
            "pathogenicity": {
                "alphamissense_score": am_score,
                "alphamissense_interpretation": _am_label(am_score),
                "clinvar_classification": clinvar_cls_raw,
                "clinvar_review_status": clinvar_data.get("review_status", ""),
                "clinvar_variation_id": clinvar_data.get("variation_id", ""),
                "clinvar_conditions": clinvar_data.get("conditions", []),
            },
            "population_genetics": gnomad_data,
            "disease_context": disease_data,
            "sources_queried": sources,
        }

        # Structural context note (full integration in Wave 3 when the
        # existing alphafold_mcp tools are migrated to the new module layout)
        if params.include_structure:
            report["structure_note"] = (
                f"AlphaFold structural confidence for {gene_symbol}: resolve "
                f"{gene_symbol} to a UniProt accession, then call "
                "analyze_structural_confidence(uniprot_id='<UNIPROT>'). "
                "Automatic structural integration into this report is a "
                "Wave-3 roadmap item."
            )

        # Stamp only the upstreams actually queried for this call: ClinVar
        # always, gnomAD when requested. Open Targets / MONDO are not
        # queried (disease context is a stub), so they are not stamped.
        prov: dict[str, str] = {"clinvar": "NCBI-ClinVar"}
        if params.include_gnomad:
            prov["gnomad"] = "gnomAD-r4"
        return json.dumps(report, indent=2) + _provenance(**prov)

    except Exception as exc:
        logger.error("triage_variant_3d_failed", hgvs=hgvs, error=str(exc))
        return json.dumps({"status": "error", "hgvs": hgvs, "error": str(exc)})


# ---------------------------------------------------------------------------
# Tool 9: Phenotype → protein structures
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Phenotype to Protein Structures",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def phenotype_to_structures(params: PhenotypeToStructureInput) -> str:
    """Map a clinical phenotype to the protein structures of its disease targets.

    Pipeline:
    1. Resolve HPO term → associated diseases
    2. For each disease → top protein targets (Open Targets)
    3. For each target → UniProt ID (for AlphaFold retrieval)

    Use the returned UniProt IDs with ``analyze_structural_confidence``
    to retrieve AlphaFold structural confidence (pLDDT/PAE).

    Example: ``phenotype_to_structures(hpo_id='HP:0002621')``
    maps Atherosclerosis → disease targets → UniProt IDs.
    """
    try:
        async with HPOClient() as hpo, OpenTargetsClient() as ot:
            diseases = await hpo.diseases_for_phenotype(
                params.hpo_id,
                limit=params.disease_limit,
            )

            # Resolve each disease to a MONDO ID for Open Targets. The HPO
            # annotation already carries a cross-referenced MONDO ID; fall back
            # to an OMIM→MONDO lookup only when it does not.
            mondo_tasks = [
                _identity(d.mondo_id) if d.mondo_id else _omim_to_mondo(d.disease_id)
                for d in diseases
            ]
            mondo_ids = await asyncio.gather(*mondo_tasks, return_exceptions=True)

            target_tasks = []
            valid_diseases = []
            for disease, mondo_id in zip(diseases, mondo_ids):
                if isinstance(mondo_id, Exception) or not mondo_id:
                    continue
                target_tasks.append(
                    ot.associated_targets(
                        str(mondo_id),
                        limit=params.targets_per_disease,
                    )
                )
                valid_diseases.append(disease)

            target_results = await asyncio.gather(*target_tasks, return_exceptions=True)

        output: list[dict[str, Any]] = []
        for disease, targets in zip(valid_diseases, target_results):
            if isinstance(targets, Exception):
                continue
            output.append(
                {
                    "disease_id": disease.disease_id,
                    "disease_name": disease.disease_name,
                    "targets": [
                        {
                            "uniprot_id": t.uniprot_id,
                            "gene_symbol": t.target_gene_symbol,
                            "evidence_score": round(t.overall_score, 4),
                            "known_drugs": t.drug_count,
                        }
                        for t in targets  # type: ignore[union-attr]
                        if t.uniprot_id
                    ],
                }
            )

        return json.dumps(
            {
                "status": "success",
                "hpo_id": params.hpo_id,
                "diseases_found": len(output),
                "result": output,
                "next_step": (
                    "Use analyze_structural_confidence(uniprot_id=...) for "
                    "AlphaFold structural confidence (pLDDT/PAE)."
                ),
            },
            indent=2,
        ) + _provenance(hpo="JAX-HPO", open_targets="OT-24.06")

    except Exception as exc:
        logger.error("phenotype_to_structures_failed", hpo_id=params.hpo_id, error=str(exc))
        return json.dumps({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# Tool 10: Orphan disease atlas
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Orphan Disease Structural Atlas",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_orphan_disease_atlas(params: OrphanDiseaseInput) -> str:
    """Map an Orphanet rare disease to its MONDO record, HPO phenotypes, and protein targets.

    Rare / orphan diseases are often under-studied because their small
    patient populations make large trials impractical.  This tool aggregates
    the available structural and clinical intelligence into one report to
    accelerate research.

    Returns:
    - MONDO record with ICD-10 coding
    - HPO phenotype profile of the disease
    - Open Targets protein target evidence scores
    - UniProt IDs for AlphaFold structural retrieval

    Example: ``get_orphan_disease_atlas(orphanet_id='79318')``
    returns the Gaucher disease atlas.
    """
    try:
        # Resolve Orphanet → MONDO
        async with MONDOClient() as mondo_client:
            search_results = await mondo_client.from_orphanet(params.orphanet_id)

        if not search_results:
            return json.dumps(
                {
                    "status": "not_found",
                    "orphanet_id": params.orphanet_id,
                    "message": f"No MONDO record found for Orphanet:{params.orphanet_id}.",
                }
            )

        mondo_id = search_results[0].mondo_id

        # Parallel: MONDO record + HPO diseases + OT targets
        async with MONDOClient() as mc, HPOClient() as hpo, OpenTargetsClient() as ot:
            record, hpo_diseases, ot_targets = await asyncio.gather(
                mc.lookup(mondo_id),
                hpo.phenotypes_for_disease(f"OMIM:{params.orphanet_id}"),
                ot.associated_targets(mondo_id, limit=10),
                return_exceptions=True,
            )

        result: dict[str, Any] = {
            "status": "success",
            "orphanet_id": params.orphanet_id,
            "mondo_id": mondo_id,
        }

        if not isinstance(record, Exception):
            result["disease"] = record.to_dict()  # type: ignore[union-attr]
        if not isinstance(hpo_diseases, Exception):
            result["phenotypes"] = [p.to_dict() for p in hpo_diseases[:20]]  # type: ignore[union-attr]
        if not isinstance(ot_targets, Exception):
            result["protein_targets"] = [t.to_dict() for t in ot_targets]  # type: ignore[union-attr]

        return json.dumps(result, indent=2) + _provenance(
            mondo="OLS4", hpo="JAX-HPO", open_targets="OT-24.06"
        )

    except Exception as exc:
        logger.error("orphan_disease_atlas_failed", orphanet=params.orphanet_id, error=str(exc))
        return json.dumps({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# Tool 11: Disease structural similarity
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Cross-Disease Structural Target Overlap",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def compare_disease_target_overlap(params: DiseaseSimilarityInput) -> str:
    """Compare the protein target landscapes of two diseases.

    Identifies shared and unique targets between two diseases —
    a key analysis for drug repurposing, identifying shared mechanisms,
    and understanding comorbidity.

    Returns:
    - Shared targets (present in both disease target sets)
    - Unique to Disease A / Disease B
    - Jaccard similarity score of target sets

    Example: ``compare_disease_target_overlap(
        mondo_id_a='MONDO:0004975',  # Alzheimer disease
        mondo_id_b='MONDO:0005180',  # Parkinson disease
    )``
    """
    try:
        async with OpenTargetsClient() as ot:
            targets_a, targets_b = await asyncio.gather(
                ot.associated_targets(params.mondo_id_a, limit=params.target_limit),
                ot.associated_targets(params.mondo_id_b, limit=params.target_limit),
            )

        set_a = {t.target_ensembl_id: t for t in targets_a}
        set_b = {t.target_ensembl_id: t for t in targets_b}

        shared_ids = set(set_a) & set(set_b)
        only_a_ids = set(set_a) - set(set_b)
        only_b_ids = set(set_b) - set(set_a)
        union_size = len(set(set_a) | set(set_b))
        jaccard = len(shared_ids) / union_size if union_size > 0 else 0.0

        def _fmt(
            t: TargetEvidenceScore, other: dict[str, TargetEvidenceScore] | None = None
        ) -> dict[str, Any]:
            d = {
                "ensembl_id": t.target_ensembl_id,
                "gene_symbol": t.target_gene_symbol,
                "uniprot_id": t.uniprot_id,
                "score_a": round(set_a.get(t.target_ensembl_id, t).overall_score, 4),
                "score_b": round(set_b.get(t.target_ensembl_id, t).overall_score, 4),
            }
            return d

        shared = [
            _fmt(set_a[eid])
            for eid in sorted(
                shared_ids,
                key=lambda e: -(set_a[e].overall_score + set_b[e].overall_score),
            )
        ]

        return json.dumps(
            {
                "status": "success",
                "disease_a": params.mondo_id_a,
                "disease_b": params.mondo_id_b,
                "jaccard_similarity": round(jaccard, 4),
                "shared_target_count": len(shared_ids),
                "unique_to_a_count": len(only_a_ids),
                "unique_to_b_count": len(only_b_ids),
                "shared_targets": shared,
                "unique_to_a": [
                    {
                        "ensembl_id": e,
                        "gene_symbol": set_a[e].target_gene_symbol,
                        "uniprot_id": set_a[e].uniprot_id,
                        "score": round(set_a[e].overall_score, 4),
                    }
                    for e in sorted(only_a_ids, key=lambda e: -set_a[e].overall_score)
                ],
                "unique_to_b": [
                    {
                        "ensembl_id": e,
                        "gene_symbol": set_b[e].target_gene_symbol,
                        "uniprot_id": set_b[e].uniprot_id,
                        "score": round(set_b[e].overall_score, 4),
                    }
                    for e in sorted(only_b_ids, key=lambda e: -set_b[e].overall_score)
                ],
                "repurposing_note": (
                    "Shared targets with known drugs are strong candidates for "
                    "repurposing. Use get_disease_targets(include_tractable_only=True) "
                    "to filter to druggable targets."
                ),
            },
            indent=2,
        ) + _provenance(open_targets="OT-24.06")

    except Exception as exc:
        logger.error("compare_diseases_failed", error=str(exc))
        return json.dumps({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# Tool 12: ICD-10 to MONDO resolution
# ---------------------------------------------------------------------------


class ICD10ToMONDOInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    icd10_code: str = Field(
        ...,
        description="ICD-10 code, e.g. 'I21.0' (STEMI), 'C50.9' (breast cancer).",
        min_length=2,
        max_length=10,
    )


@mcp.tool(
    annotations={
        "title": "ICD-10 to MONDO Resolver",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def resolve_icd10_to_mondo(params: ICD10ToMONDOInput) -> str:
    """Resolve an ICD-10 clinical code to MONDO disease ontology terms.

    Enables integration between clinical / EHR data (which uses ICD-10)
    and the research-grade MONDO ontology used by Open Targets, HPO, and
    this MCP.

    Example: ``resolve_icd10_to_mondo(icd10_code='I21.0')``
    maps ST-elevation MI (ICD-10) to MONDO coronary disease terms.
    """
    try:
        async with MONDOClient() as client:
            results = await client.from_icd10(params.icd10_code)

        if not results:
            return json.dumps(
                {
                    "status": "not_found",
                    "icd10_code": params.icd10_code,
                    "message": "No MONDO terms found for this ICD-10 code.",
                }
            )

        return json.dumps(
            {
                "status": "success",
                "icd10_code": params.icd10_code,
                "mondo_terms": [r.to_dict() for r in results[:10]],
                "note": (
                    "Use the MONDO ID with get_disease_targets() or "
                    "lookup_disease() for downstream analysis."
                ),
            },
            indent=2,
        ) + _provenance(mondo="OLS4")

    except Exception as exc:
        logger.error("resolve_icd10_failed", icd10=params.icd10_code, error=str(exc))
        return json.dumps({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_hgvs_gene(hgvs: str) -> tuple[str, str]:
    """Extract gene symbol and c. notation from an HGVS expression.

    Handles the three common notations:

    - Gene-relative:           ``BRCA1:c.181T>G``           → ``('BRCA1', 'c.181T>G')``
    - RefSeq with gene parens: ``NM_007294.4(BRCA1):c.5266dupC``
      (the canonical ClinVar form) → ``('BRCA1', 'c.5266dupC')``
    - RefSeq without gene:      ``NM_007294.3:c.181T>G``     → ``('', 'c.181T>G')``
    """
    import re

    hgvs = hgvs.strip()

    # RefSeq/Ensembl transcript carrying the gene in parentheses, e.g.
    # 'NM_007294.4(BRCA1):c.5266dupC' — the standard ClinVar HGVS form.
    paren = re.match(r"^[A-Za-z][A-Za-z0-9_.\-]*\(([A-Za-z0-9\-]+)\):(.+)$", hgvs)
    if paren:
        return (paren.group(1).upper(), paren.group(2))

    # 'BRCA1:c.181T>G' or transcript-only 'NM_007294.3:c.181T>G'
    match = re.match(r"^([A-Za-z][A-Za-z0-9_\-\.]*):(.+)$", hgvs)
    if match:
        raw_gene = match.group(1)
        # A bare RefSeq/Ensembl transcript or genomic accession, or a bare
        # chromosome name (genomic HGVS like 'NC_000017.11:g.…' / 'chr17:g.…'),
        # is not a gene symbol.
        is_accession = raw_gene.startswith(
            ("NM_", "NR_", "NP_", "XM_", "XR_", "ENST", "ENSP", "NC_", "NG_", "NT_", "NW_", "NZ_")
        )
        is_chromosome = re.match(r"^chr([0-9]+|[XYM]|MT)$", raw_gene, re.IGNORECASE) is not None
        if is_accession or is_chromosome:
            return ("", match.group(2))
        return (raw_gene, match.group(2))
    return ("", "")


async def _fetch_clinvar(hgvs: str, gene_symbol: str) -> dict[str, Any]:
    async with ClinVarClient() as cv:
        results = await cv.search_by_hgvs(hgvs)
        if not results and gene_symbol:
            results = await cv.search_gene(gene_symbol, limit=1)
        return results[0] if results else {}


async def _fetch_gnomad(hgvs: str, gene_symbol: str) -> dict[str, Any]:
    """Fetch gnomAD data — constraint scores always, freq if ID available."""
    async with GnomADClient() as gn:
        constraint = await gn.gene_constraint(gene_symbol)
        return constraint


async def _fetch_disease_context(gene_symbol: str) -> dict[str, Any]:
    """Fetch top diseases for a gene via Open Targets."""
    # Build a placeholder ensembl ID; full resolution in Wave 3
    # via the Ensembl client (not yet written in this wave).
    return {"note": f"Full disease context for {gene_symbol} via get_target_diseases()."}


async def _identity(value: str) -> str:
    """Async pass-through, so a known value can join an ``asyncio.gather``."""
    return value


async def _omim_to_mondo(disease_id: str) -> str | None:
    """Convert an OMIM/Orphanet disease ID to a MONDO ID via OLS4 search."""
    if not disease_id:
        return None
    try:
        async with MONDOClient() as mc:
            results = await mc.search(disease_id, limit=1)
            return results[0].mondo_id if results else None
    except Exception:
        return None


_OT_SINGLETON: OpenTargetsClient | None = None


def _get_ot_client() -> OpenTargetsClient:
    global _OT_SINGLETON  # noqa: PLW0603
    if _OT_SINGLETON is None:
        _OT_SINGLETON = OpenTargetsClient()
    return _OT_SINGLETON


async def _uniprot_to_ensembl(uniprot_id: str) -> str:
    """Resolve UniProt accession to Ensembl gene ID via Open Targets search.

    Routes through OpenTargetsClient so the request shares the client's
    rate limiter, retry policy, circuit breaker, and air-gap enforcement.
    Uses a module-level singleton to avoid per-call connection overhead.
    """
    try:
        resolved = await _get_ot_client().resolve_target(uniprot_id)
        return resolved.get("ensembl_id", "")
    except Exception:
        return ""


def _parse_clinvar_class(raw: str) -> PathogenicityClass:
    from alphafold_sovereign.clients.clinvar import _parse_classification

    return _parse_classification(raw)


def _am_label(score: float | None) -> str:
    if score is None:
        return "Not available"
    if score >= 0.564:
        return f"Likely pathogenic (AM={score:.3f})"
    if score <= 0.34:
        return f"Likely benign (AM={score:.3f})"
    return f"Uncertain (AM={score:.3f})"


def _compute_tier(cls: PathogenicityClass, am_score: float | None) -> str:
    if cls in (PathogenicityClass.PATHOGENIC, PathogenicityClass.LIKELY_PATHOGENIC):
        return "HIGH"
    if cls == PathogenicityClass.BENIGN:
        return "LOW"
    if am_score is not None and am_score >= 0.564:
        return "HIGH"
    if am_score is not None and am_score <= 0.34:
        return "LOW"
    if cls == PathogenicityClass.UNCERTAIN:
        return "MEDIUM"
    return "UNKNOWN"
