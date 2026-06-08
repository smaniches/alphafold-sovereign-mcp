# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Curated seed dataset for the local knowledge graph.

Loaded automatically when the graph is empty (see
``KnowledgeGraph.seed_if_empty``) so the local-knowledge-graph tools
(``query_protein_database``, ``query_variant_database``,
``export_research_dataset``, ``find_drug_gene_network``) return
representative results out of the box. Set ``AFSMCP_DISABLE_KG_SEED=1`` to
keep the graph empty.

The seed centres on two well-characterised stories already used in the
worked examples — BCR-ABL / chronic myeloid leukaemia and BRCA1 / breast
cancer. Identifiers are real public accessions; numeric fields (pLDDT,
scores) are representative.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alphafold_sovereign.storage.knowledge_graph import KnowledgeGraph

# (uniprot_id, gene, name, length, mean_plddt, confidence_tier, druggability_tier)
_PROTEINS = [
    ("P00519", "ABL1", "Tyrosine-protein kinase ABL1", 1130, 63.4, "LOW", "WARM"),
    ("P11274", "BCR", "Breakpoint cluster region protein", 1271, 70.2, "HIGH", "WARM"),
    ("P10721", "KIT", "Mast/stem cell growth factor receptor Kit", 976, 72.1, "HIGH", "HOT"),
    ("P38398", "BRCA1", "Breast cancer type 1 susceptibility protein", 1863, 44.6, "LOW", "COLD"),
    ("P04637", "TP53", "Cellular tumor antigen p53", 393, 68.0, "HIGH", "WARM"),
    ("P09874", "PARP1", "Poly [ADP-ribose] polymerase 1", 1014, 72.0, "HIGH", "HOT"),
]

# (mondo_id, name)
_DISEASES = [
    ("MONDO:0011996", "chronic myeloid leukemia"),
    ("MONDO:0007254", "breast cancer"),
]

# (chembl_id, pref_name, mechanism_of_action, first_approval)
_DRUGS = [
    ("CHEMBL941", "IMATINIB", "BCR-ABL tyrosine kinase inhibitor", 2001),
    ("CHEMBL1421", "DASATINIB", "BCR-ABL tyrosine kinase inhibitor", 2006),
    ("CHEMBL255863", "NILOTINIB", "BCR-ABL tyrosine kinase inhibitor", 2007),
    ("CHEMBL1171837", "PONATINIB", "BCR-ABL tyrosine kinase inhibitor", 2012),
    ("CHEMBL288441", "BOSUTINIB", "BCR-ABL tyrosine kinase inhibitor", 2012),
    ("CHEMBL521686", "OLAPARIB", "PARP inhibitor", 2014),
]

# (hgvs, gene, uniprot_id)
_VARIANTS = [
    ("NM_007294.4(BRCA1):c.5266dupC", "BRCA1", "P38398"),
    ("NM_000546.6(TP53):c.743G>A", "TP53", "P04637"),
]

# protein↔drug (uniprot_id, chembl_id, mechanism)
_PROTEIN_DRUG = [
    ("P00519", "CHEMBL941", "BCR-ABL tyrosine kinase inhibitor"),
    ("P00519", "CHEMBL1421", "BCR-ABL tyrosine kinase inhibitor"),
    ("P00519", "CHEMBL255863", "BCR-ABL tyrosine kinase inhibitor"),
    ("P00519", "CHEMBL1171837", "BCR-ABL tyrosine kinase inhibitor"),
    ("P00519", "CHEMBL288441", "BCR-ABL tyrosine kinase inhibitor"),
    ("P10721", "CHEMBL941", "KIT inhibitor (off-target)"),
    # Olaparib targets PARP1 (P09874); its benefit in BRCA-mutant tumours is via
    # synthetic lethality, not BRCA1 binding — so the drug-target edge is to PARP1.
    ("P09874", "CHEMBL521686", "PARP inhibitor"),
]

# protein↔disease (uniprot_id, mondo_id, score)
_PROTEIN_DISEASE = [
    ("P00519", "MONDO:0011996", 0.83),
    ("P11274", "MONDO:0011996", 0.83),
    ("P10721", "MONDO:0011996", 0.71),
    ("P38398", "MONDO:0007254", 0.92),
    ("P04637", "MONDO:0007254", 0.88),
    ("P09874", "MONDO:0007254", 0.55),
]

# variant↔disease (hgvs, mondo_id, score)
_VARIANT_DISEASE = [
    ("NM_007294.4(BRCA1):c.5266dupC", "MONDO:0007254", 1.0),
    ("NM_000546.6(TP53):c.743G>A", "MONDO:0007254", 0.9),
]


async def seed_knowledge_graph(kg: KnowledgeGraph) -> None:
    """Populate an empty knowledge graph with the curated seed dataset.

    Entities are written before the relationships that reference them so the
    foreign-key constraints are satisfied.
    """
    for uid, gene, name, length, plddt, tier, drug_tier in _PROTEINS:
        await kg.store_protein(
            uniprot_id=uid,
            gene_symbol=gene,
            protein_name=name,
            sequence_length=length,
            mean_plddt=plddt,
            confidence_tier=tier,
            druggability_tier=drug_tier,
        )
    for mondo_id, name in _DISEASES:
        await kg.store_disease(mondo_id=mondo_id, name=name, therapeutic_area=True)
    for chembl_id, pref_name, moa, approval in _DRUGS:
        await kg.store_drug(
            chembl_id=chembl_id,
            pref_name=pref_name,
            max_phase=4,
            max_phase_label="Approved",
            mechanism_of_action=moa,
            first_approval=approval,
            oral=True,
        )
    for hgvs, gene, uid in _VARIANTS:
        await kg.store_variant(
            hgvs=hgvs,
            gene_symbol=gene,
            uniprot_id=uid,
            clinvar_class="Pathogenic",
            clinical_tier="HIGH",
        )
    for uid, chembl_id, mechanism in _PROTEIN_DRUG:
        await kg.store_protein_drug(
            uniprot_id=uid, chembl_id=chembl_id, activity_type="mechanism", mechanism=mechanism
        )
    for uid, mondo_id, score in _PROTEIN_DISEASE:
        await kg.store_protein_disease(
            uniprot_id=uid, mondo_id=mondo_id, source="opentargets", score=score
        )
    for hgvs, mondo_id, score in _VARIANT_DISEASE:
        await kg.store_variant_disease(hgvs=hgvs, mondo_id=mondo_id, source="clinvar", score=score)
