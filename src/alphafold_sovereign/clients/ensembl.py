# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Ensembl REST async client.

Provides:
- HGVS notation lookup → genomic coordinates, transcript consequences
- Variant Effect Predictor (VEP) — functional effect prediction
- Gene ID lookup (gene symbol → Ensembl gene ID → UniProt)
- Cross-species ortholog lookup (for pandemic-preparedness / biothreat analysis)

Reference:
  Cunningham F et al. Ensembl 2022.  Nucleic Acids Res.
  2022;50(D1):D988–D995.
  https://rest.ensembl.org
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig

logger = structlog.get_logger(__name__)

_ENSEMBL_CONFIG = UpstreamConfig(
    base_url="https://rest.ensembl.org",
    calls_per_second=15.0,  # Ensembl permits ~15 req/s
    max_retries=3,
    timeout=30.0,
    headers={"Content-Type": "application/json", "Accept": "application/json"},
)

_HGVS_GENE_RE = re.compile(
    r"^(?P<gene>[A-Z][A-Z0-9_-]{1,})"  # BRCA1, TP53, etc.
    r":(?:c\.|p\.|g\.|m\.|n\.|r\.)",  # HGVS type prefix
    re.IGNORECASE,
)

_REFSEQ_RE = re.compile(
    r"^(?P<acc>NM_\d+(?:\.\d+)?|NP_\d+(?:\.\d+)?|NC_\d+(?:\.\d+)?)"
    r"(?::(?P<hgvs>.+))?$"
)


def _first_uniprot(value: Any) -> str:
    """Normalise a VEP ``swissprot`` cross-reference to one accession.

    Ensembl VEP returns the SwissProt cross-reference as a list, e.g.
    ``['P38398.280']`` (the trailing ``.280`` is the UniProt sequence
    version). This collapses the list to its first element and leaves the
    version suffix intact for the caller to strip if required. Returns an
    empty string when no accession is present.
    """
    if isinstance(value, list) and value:
        value = value[0]
    return value if isinstance(value, str) else ""


class EnsemblClient(BaseAsyncClient):
    """
    Async REST client for Ensembl Variant Effect Predictor and gene data.

    Species defaults to ``human`` (GRCh38 / hg38).
    """

    upstream_name = "ensembl"
    config = _ENSEMBL_CONFIG

    def __init__(self, *, species: str = "human", **kwargs: Any) -> None:
        self.species = species
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # HGVS → VEP consequences
    # ------------------------------------------------------------------

    async def vep_hgvs(
        self,
        hgvs: str,
        *,
        canonical: bool = True,
    ) -> list[dict[str, Any]]:
        """Run VEP on an HGVS notation string.

        Args:
            hgvs: HGVS expression, e.g. ``'NM_007294.3:c.181T>G'``
                or gene-relative ``'BRCA1:c.181T>G'``.
            canonical: Return only canonical transcript consequence.

        Returns:
            List of consequence dicts, each with keys:
            ``transcript_id``, ``gene_id``, ``gene_symbol``,
            ``biotype``, ``impact``, ``consequence_terms``,
            ``protein_id``, ``protein_start``, ``amino_acids``, ``codons``,
            ``polyphen_score``, ``sift_score``, ``cadd_phred``,
            ``sift_prediction``, ``polyphen_prediction``, ``swissprot``.
        """
        params: dict[str, Any] = {
            "canonical": int(canonical),
            "numbers": 1,
            "protein": 1,
            "uniprot": 1,
            "xref_refseq": 1,
            "Genoverse": 0,
        }
        try:
            data = await self._get(
                f"/vep/{self.species}/hgvs/{hgvs}",
                params=params,
            )
        except Exception as exc:
            logger.warning("ensembl.vep.error", hgvs=hgvs, exc=str(exc))
            return []

        results: list[dict[str, Any]] = []
        any_data: Any = data
        for hit in any_data if isinstance(any_data, list) else []:
            for tc in hit.get("transcript_consequences", []):
                results.append(self._parse_tc(tc))
        return results

    # ------------------------------------------------------------------
    # Gene symbol → Ensembl gene ID + UniProt
    # ------------------------------------------------------------------

    async def gene_lookup(self, gene_symbol: str) -> dict[str, Any]:
        """Resolve a gene symbol to Ensembl gene ID and associated UniProt IDs.

        Args:
            gene_symbol: HGNC gene symbol, e.g. ``'BRCA1'``.

        Returns:
            Dict with ``ensembl_gene_id``, ``display_name``, ``description``,
            ``biotype``, ``strand``, ``chromosome``, ``start``, ``end``,
            ``uniprot_ids`` (list of UniProt accessions).
        """
        try:
            data = await self._get(
                f"/lookup/symbol/{self.species}/{gene_symbol}",
                params={"expand": 1, "xrefs": 1},
            )
        except Exception as exc:
            logger.warning("ensembl.gene_lookup.error", gene=gene_symbol, exc=str(exc))
            return {"gene_symbol": gene_symbol, "found": False}

        uniprot_ids = self._extract_xref_ids(data.get("Xref", []) or [], "Uniprot")
        return {
            "gene_symbol": gene_symbol,
            "found": True,
            "ensembl_gene_id": data.get("id", ""),
            "display_name": data.get("display_name", gene_symbol),
            "description": (data.get("description") or "").split("[Source:")[0].strip(),
            "biotype": data.get("biotype", ""),
            "strand": data.get("strand"),
            "chromosome": data.get("seq_region_name", ""),
            "start": data.get("start"),
            "end": data.get("end"),
            "uniprot_ids": uniprot_ids,
        }

    # ------------------------------------------------------------------
    # HGVS → gene symbol (quick parse for pipeline use)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_gene_from_hgvs(hgvs: str) -> str | None:
        """Extract gene symbol from a gene-relative HGVS expression.

        Returns ``None`` for RefSeq-based expressions (``NM_…``).

        Examples::

            >>> EnsemblClient.parse_gene_from_hgvs("BRCA1:c.181T>G")
            'BRCA1'
            >>> EnsemblClient.parse_gene_from_hgvs("NM_007294.3:c.181T>G")
            None
        """
        m = _HGVS_GENE_RE.match(hgvs.strip())
        return m.group("gene").upper() if m else None

    # ------------------------------------------------------------------
    # Variant rsID lookup
    # ------------------------------------------------------------------

    async def variant_info(self, rsid: str) -> dict[str, Any]:
        """Fetch variant information for a dbSNP rsID.

        Args:
            rsid: dbSNP rsID, e.g. ``'rs1799977'``.

        Returns:
            Dict with ``rsid``, ``minor_allele``, ``maf``, ``mappings``
            (list of genomic location dicts).
        """
        try:
            data = await self._get(
                f"/variation/{self.species}/{rsid}",
                params={"genotypes": 0, "phenotypes": 0, "pops": 0},
            )
        except Exception as exc:
            logger.warning("ensembl.variant.error", rsid=rsid, exc=str(exc))
            return {"rsid": rsid, "found": False}

        return {
            "rsid": rsid,
            "found": True,
            "name": data.get("name", rsid),
            "minor_allele": data.get("minor_allele"),
            "maf": data.get("MAF"),
            "evidence": data.get("evidence", []),
            "mappings": [
                {
                    "chromosome": m.get("seq_region_name", ""),
                    "start": m.get("start"),
                    "end": m.get("end"),
                    "ref": m.get("allele_string", "").split("/")[0],
                    "allele_string": m.get("allele_string", ""),
                }
                for m in (data.get("mappings") or [])
            ],
        }

    # ------------------------------------------------------------------
    # Cross-species orthologs (for biothreat / pandemic-prep)
    # ------------------------------------------------------------------

    async def orthologs(
        self,
        gene_symbol: str,
        target_species: list[str] | None = None,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find orthologs of a human gene in other species.

        Useful for cross-species structural comparison in pandemic preparedness
        and host-pathogen interaction research.

        Args:
            gene_symbol: Human HGNC gene symbol.
            target_species: List of Ensembl species names to filter to,
                e.g. ``['mus_musculus', 'sus_scrofa', 'gallus_gallus']``.
                ``None`` returns all species.
            limit: Maximum orthologs.

        Returns:
            List of ortholog dicts with keys:
            ``species``, ``gene_id``, ``gene_name``, ``type``
            (``'ortholog_one2one'``, ``'ortholog_one2many'``, etc.),
            ``subtype``, ``dn_ds``, ``identity``.
        """
        lookup = await self.gene_lookup(gene_symbol)
        if not lookup.get("found"):
            return []
        ensembl_id = lookup["ensembl_gene_id"]

        try:
            data = await self._get(
                f"/homology/id/{ensembl_id}",
                params={"type": "orthologues", "aligned": 0, "sequence": "none"},
            )
        except Exception as exc:
            logger.warning("ensembl.orthologs.error", gene=gene_symbol, exc=str(exc))
            return []

        results: list[dict[str, Any]] = []
        for group in data.get("data", []):
            for hom in group.get("homologies", []):
                target = hom.get("target", {})
                species = target.get("species", "")
                if target_species and species not in target_species:
                    continue
                results.append(
                    {
                        "species": species,
                        "gene_id": target.get("id", ""),
                        "gene_name": target.get("display_label", ""),
                        "type": hom.get("type", ""),
                        "subtype": hom.get("subtype", ""),
                        "dn_ds": hom.get("dn_ds"),
                        "identity": float(target.get("perc_id", 0.0) or 0.0),
                    }
                )
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
        return results

    # ------------------------------------------------------------------
    # Transcript → protein ID mapping
    # ------------------------------------------------------------------

    async def transcript_protein(self, transcript_id: str) -> dict[str, Any]:
        """Resolve an Ensembl transcript ID to its canonical protein.

        Args:
            transcript_id: Ensembl transcript ID, e.g. ``'ENST00000357654'``.

        Returns:
            Dict with ``protein_id``, ``uniprot_id``, ``length``.
        """
        try:
            data = await self._get(
                f"/lookup/id/{transcript_id}",
                params={"expand": 1, "xrefs": 1},
            )
        except Exception as exc:
            logger.warning("ensembl.transcript.error", tid=transcript_id, exc=str(exc))
            return {"transcript_id": transcript_id, "found": False}

        protein_id = data.get("Translation", {}).get("id", "")
        uniprot_ids = self._extract_xref_ids(data.get("Xref", []) or [], "Uniprot")
        return {
            "transcript_id": transcript_id,
            "found": True,
            "protein_id": protein_id,
            "uniprot_id": uniprot_ids[0] if uniprot_ids else "",
            "length": data.get("Translation", {}).get("length"),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_xref_ids(xrefs: list[dict[str, Any]], db_prefix: str) -> list[str]:
        return [
            x.get("primary_id", "")
            for x in xrefs
            if x.get("dbname", "").lower().startswith(db_prefix.lower()) and x.get("primary_id")
        ]

    @staticmethod
    def _parse_tc(tc: dict[str, Any]) -> dict[str, Any]:
        extras = tc.get("extra", {}) or {}
        return {
            "transcript_id": tc.get("transcript_id", ""),
            "gene_id": tc.get("gene_id", ""),
            "gene_symbol": tc.get("gene_symbol", ""),
            "biotype": tc.get("biotype", ""),
            "canonical": bool(tc.get("canonical")),
            "impact": tc.get("impact", ""),
            "consequence_terms": tc.get("consequence_terms", []),
            "protein_id": tc.get("protein_id", ""),
            "swissprot": _first_uniprot(tc.get("swissprot")),
            "protein_start": tc.get("protein_start"),
            "amino_acids": tc.get("amino_acids", ""),
            "codons": tc.get("codons", ""),
            "hgvsp": tc.get("hgvsp", ""),
            "hgvsc": tc.get("hgvsc", ""),
            "exon": tc.get("exon", ""),
            "intron": tc.get("intron", ""),
            "sift_score": tc.get("sift_score"),
            "sift_prediction": tc.get("sift_prediction", ""),
            "polyphen_score": tc.get("polyphen_score"),
            "polyphen_prediction": tc.get("polyphen_prediction", ""),
            "cadd_phred": extras.get("CADD_PHRED"),
            "cadd_raw": extras.get("CADD_raw"),
            "spliceai_ds_max": extras.get("SpliceAI_pred_DS_max"),
        }
