# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""AlphaFold Sovereign Knowledge Graph — local relational provenance store.

This module implements the persistent local knowledge graph that transforms
AlphaFold Sovereign from a stateless API connector into a learning research
intelligence platform.  Every tool result is automatically stored, enabling:

  - **Offline analysis**: query previously fetched data without internet
  - **Cross-session synthesis**: "find all HIGH-tier variants I've ever triaged"
  - **Longitudinal tracking**: monitor how database updates change classifications
  - **Batch analytics**: pandas/polars export for ML feature engineering
  - **Audit compliance**: immutable provenance trail for every inference

Architecture:
  - Primary store: SQLite (zero-dependency, embedded, ACID, WAL mode)
  - Analytical layer: DuckDB if installed (columnar, fast aggregation)
  - Content-addressed JSON blobs: SHA-256 keyed, dedup-safe
  - Full provenance: source, version, timestamp, tool, parameters, hash

Schema (6 entity tables + 4 relationship tables + 1 provenance table):
  proteins      — UniProt entities with structure metadata
  variants      — HGVS variants with clinical classification
  diseases      — MONDO disease records with ICD cross-refs
  drugs         — ChEMBL compounds with development phase
  phenotypes    — HPO terms
  genes         — Gene symbols with Ensembl + Entrez IDs
  protein_disease   — Open Targets + DisGeNET evidence links
  protein_drug      — ChEMBL drug-target links
  variant_disease   — ClinVar + DisGeNET VDA links
  gene_phenotype    — HPO gene-phenotype associations
  tool_invocations  — Every MCP tool call (input + output + timing)
  provenance        — Data-source version snapshot per invocation

Usage:
  >>> from alphafold_sovereign.storage.knowledge_graph import KnowledgeGraph
  >>> async with KnowledgeGraph() as kg:
  ...     await kg.store_variant_report(hgvs="BRCA1:c.181T>G", report={...})
  ...     df = await kg.query_variants(gene="BRCA1", tier="HIGH")
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from platformdirs import user_data_dir

logger = structlog.get_logger(__name__)

# Default DB path — overridden by ALPHAFOLD_KG_PATH env var
_DEFAULT_DB_DIR = Path(user_data_dir("alphafold-sovereign", "TOPOLOGICA"))
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "knowledge_graph.db"

_SCHEMA_VERSION = 3


def _default_db_path() -> Path:
    custom = os.environ.get("ALPHAFOLD_KG_PATH", "")
    return Path(custom) if custom else _DEFAULT_DB_PATH


def _sha256(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


class KnowledgeGraph:
    """
    Async local knowledge graph for AlphaFold Sovereign.

    Thread-safe SQLite backend with WAL mode.  Use as an async context manager::

        async with KnowledgeGraph() as kg:
            await kg.store_protein(uniprot_id="P38398", ...)

    Or with a custom path::

        async with KnowledgeGraph(db_path="/data/research.db") as kg:
            ...
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def __aenter__(self) -> KnowledgeGraph:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def connect(self) -> None:
        loop = asyncio.get_event_loop()
        self._conn = await loop.run_in_executor(None, self._open_db)
        logger.info("kg.connected", path=str(self._db_path))

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("kg.closed")

    def _open_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        self._run_migrations(conn)
        return conn

    # ── Schema migrations ──────────────────────────────────────────────────────

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        row = conn.execute("SELECT MAX(version) FROM _schema_version").fetchone()
        current = row[0] or 0

        if current < 1:
            self._apply_migration_1(conn)
            conn.execute(
                "INSERT INTO _schema_version VALUES (1, ?)",
                [datetime.datetime.now(datetime.timezone.utc).isoformat()],
            )
        if current < 2:
            self._apply_migration_2(conn)
            conn.execute(
                "INSERT INTO _schema_version VALUES (2, ?)",
                [datetime.datetime.now(datetime.timezone.utc).isoformat()],
            )
        if current < 3:
            self._apply_migration_3(conn)
            conn.execute(
                "INSERT INTO _schema_version VALUES (3, ?)",
                [datetime.datetime.now(datetime.timezone.utc).isoformat()],
            )
        conn.commit()

    def _apply_migration_1(self, conn: sqlite3.Connection) -> None:
        """Initial schema: core entity tables."""
        conn.executescript(
            """
            -- ── Entity tables ──────────────────────────────────────────────

            CREATE TABLE IF NOT EXISTS proteins (
                uniprot_id          TEXT PRIMARY KEY,
                gene_symbol         TEXT,
                ensembl_gene_id     TEXT,
                protein_name        TEXT,
                organism            TEXT DEFAULT 'Homo sapiens',
                sequence_length     INTEGER,
                mean_plddt          REAL,
                confidence_tier     TEXT,
                idr_fraction        REAL,
                druggability_tier   TEXT,
                tda_fingerprint     TEXT,           -- JSON array (64-dim)
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                data_hash           TEXT            -- SHA-256 of canonical form
            );

            CREATE INDEX IF NOT EXISTS idx_proteins_gene ON proteins(gene_symbol);
            CREATE INDEX IF NOT EXISTS idx_proteins_druggability ON proteins(druggability_tier);

            -- ── Variants ──────────────────────────────────────────────────

            CREATE TABLE IF NOT EXISTS variants (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                hgvs                TEXT NOT NULL UNIQUE,
                gene_symbol         TEXT,
                uniprot_id          TEXT REFERENCES proteins(uniprot_id),
                clinvar_id          TEXT,
                clinvar_class       TEXT,
                clinvar_acmg_code   TEXT,
                gnomad_af           REAL,
                gnomad_ac           INTEGER,
                gnomad_an           INTEGER,
                homozygote_count    INTEGER,
                alphamissense_score REAL,
                vep_consequence     TEXT,
                vep_impact          TEXT,
                sift_prediction     TEXT,
                polyphen_prediction TEXT,
                cadd_phred          REAL,
                clinical_tier       TEXT,           -- HIGH/MEDIUM/LOW/UNKNOWN
                acmg_criteria       TEXT,           -- JSON
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                data_hash           TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_variants_gene ON variants(gene_symbol);
            CREATE INDEX IF NOT EXISTS idx_variants_tier ON variants(clinical_tier);
            CREATE INDEX IF NOT EXISTS idx_variants_class ON variants(clinvar_class);

            -- ── Diseases ──────────────────────────────────────────────────

            CREATE TABLE IF NOT EXISTS diseases (
                mondo_id            TEXT PRIMARY KEY,
                name                TEXT NOT NULL,
                definition          TEXT,
                icd10_codes         TEXT,           -- JSON array
                icd11_codes         TEXT,           -- JSON array
                omim_ids            TEXT,           -- JSON array
                orphanet_ids        TEXT,           -- JSON array
                synonyms            TEXT,           -- JSON array
                therapeutic_area    INTEGER DEFAULT 0,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_diseases_name ON diseases(name);

            -- ── Drugs ─────────────────────────────────────────────────────

            CREATE TABLE IF NOT EXISTS drugs (
                chembl_id           TEXT PRIMARY KEY,
                pref_name           TEXT,
                max_phase           INTEGER,
                max_phase_label     TEXT,
                first_approval      INTEGER,
                molecule_type       TEXT,
                oral                INTEGER DEFAULT 0,
                parenteral          INTEGER DEFAULT 0,
                black_box_warning   INTEGER DEFAULT 0,
                mechanism_of_action TEXT,
                usan_stem           TEXT,
                mw_freebase         REAL,
                alogp               REAL,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_drugs_phase ON drugs(max_phase);

            -- ── Genes ─────────────────────────────────────────────────────

            CREATE TABLE IF NOT EXISTS genes (
                gene_symbol         TEXT PRIMARY KEY,
                ensembl_gene_id     TEXT,
                entrez_id           TEXT,
                hgnc_id             TEXT,
                biotype             TEXT,
                chromosome          TEXT,
                pli                 REAL,
                loeuf               REAL,
                mis_z               REAL,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );

            -- ── Phenotypes (HPO) ───────────────────────────────────────────

            CREATE TABLE IF NOT EXISTS phenotypes (
                hpo_id              TEXT PRIMARY KEY,
                label               TEXT NOT NULL,
                description         TEXT,
                namespace           TEXT DEFAULT 'HP',
                created_at          TEXT NOT NULL
            );

            -- ── Relationship tables ─────────────────────────────────────────

            CREATE TABLE IF NOT EXISTS protein_disease (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                uniprot_id      TEXT REFERENCES proteins(uniprot_id),
                mondo_id        TEXT REFERENCES diseases(mondo_id),
                source          TEXT NOT NULL,      -- 'opentargets' | 'disgenet'
                score           REAL,
                genetic_assoc   REAL,
                known_drug      REAL,
                n_pmids         INTEGER,
                created_at      TEXT NOT NULL,
                UNIQUE(uniprot_id, mondo_id, source)
            );

            CREATE INDEX IF NOT EXISTS idx_pd_uniprot ON protein_disease(uniprot_id);
            CREATE INDEX IF NOT EXISTS idx_pd_mondo ON protein_disease(mondo_id);

            CREATE TABLE IF NOT EXISTS protein_drug (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                uniprot_id      TEXT REFERENCES proteins(uniprot_id),
                chembl_id       TEXT REFERENCES drugs(chembl_id),
                target_chembl_id TEXT,
                activity_type   TEXT,
                value_nm        REAL,
                mechanism       TEXT,
                created_at      TEXT NOT NULL,
                UNIQUE(uniprot_id, chembl_id, activity_type)
            );

            CREATE TABLE IF NOT EXISTS variant_disease (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                hgvs            TEXT REFERENCES variants(hgvs),
                mondo_id        TEXT REFERENCES diseases(mondo_id),
                source          TEXT NOT NULL,      -- 'clinvar' | 'disgenet'
                score           REAL,
                p_value         REAL,
                created_at      TEXT NOT NULL,
                UNIQUE(hgvs, mondo_id, source)
            );

            CREATE TABLE IF NOT EXISTS gene_phenotype (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                gene_symbol     TEXT REFERENCES genes(gene_symbol),
                hpo_id          TEXT REFERENCES phenotypes(hpo_id),
                frequency       TEXT,
                onset           TEXT,
                evidence_codes  TEXT,               -- JSON array
                created_at      TEXT NOT NULL,
                UNIQUE(gene_symbol, hpo_id)
            );
            """
        )

    def _apply_migration_2(self, conn: sqlite3.Connection) -> None:
        """Add tool invocation audit trail."""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tool_invocations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name       TEXT NOT NULL,
                params_hash     TEXT NOT NULL,       -- SHA-256 of input params
                params_json     TEXT NOT NULL,
                result_hash     TEXT,                -- SHA-256 of output
                result_json     TEXT,                -- truncated if > 1MB
                duration_ms     INTEGER,
                error           TEXT,
                session_id      TEXT,
                request_id      TEXT,
                called_at       TEXT NOT NULL,
                completed_at    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_inv_tool ON tool_invocations(tool_name);
            CREATE INDEX IF NOT EXISTS idx_inv_called ON tool_invocations(called_at);

            CREATE TABLE IF NOT EXISTS provenance (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                invocation_id   INTEGER REFERENCES tool_invocations(id),
                source_name     TEXT NOT NULL,       -- 'clinvar' | 'gnomad' | etc.
                source_version  TEXT,
                fetch_url       TEXT,
                fetch_timestamp TEXT NOT NULL,
                data_hash       TEXT                 -- SHA-256 of fetched payload
            );
            """
        )

    def _apply_migration_3(self, conn: sqlite3.Connection) -> None:
        """Add analytical views and full-text search."""
        conn.executescript(
            """
            -- Denormalised view for variant analytics
            CREATE VIEW IF NOT EXISTS variant_summary AS
            SELECT
                v.hgvs,
                v.gene_symbol,
                v.clinical_tier,
                v.clinvar_class,
                v.clinvar_acmg_code,
                v.gnomad_af,
                v.alphamissense_score,
                v.vep_consequence,
                v.vep_impact,
                v.cadd_phred,
                p.mean_plddt,
                p.druggability_tier,
                g.loeuf,
                g.pli,
                v.created_at
            FROM variants v
            LEFT JOIN proteins p ON v.uniprot_id = p.uniprot_id
            LEFT JOIN genes g ON v.gene_symbol = g.gene_symbol;

            -- Drug landscape view
            CREATE VIEW IF NOT EXISTS drug_landscape AS
            SELECT
                d.chembl_id,
                d.pref_name,
                d.max_phase,
                d.max_phase_label,
                d.mechanism_of_action,
                d.oral,
                d.first_approval,
                p.gene_symbol,
                p.uniprot_id,
                dis.name AS disease_name,
                dis.mondo_id
            FROM drugs d
            JOIN protein_drug pd ON pd.chembl_id = d.chembl_id
            JOIN proteins p ON pd.uniprot_id = p.uniprot_id
            LEFT JOIN protein_disease pdi ON pdi.uniprot_id = p.uniprot_id
            LEFT JOIN diseases dis ON pdi.mondo_id = dis.mondo_id;
            """
        )

    # ── Core write operations ─────────────────────────────────────────────────

    async def store_protein(
        self,
        *,
        uniprot_id: str,
        gene_symbol: str = "",
        ensembl_gene_id: str = "",
        protein_name: str = "",
        sequence_length: int | None = None,
        mean_plddt: float | None = None,
        confidence_tier: str = "",
        idr_fraction: float | None = None,
        druggability_tier: str = "",
        tda_fingerprint: list[float] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Upsert a protein record. Returns the uniprot_id."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        canonical: dict[str, Any] = {
            "uniprot_id": uniprot_id,
            "gene_symbol": gene_symbol,
            "mean_plddt": mean_plddt,
            "druggability_tier": druggability_tier,
        }
        data_hash = _sha256(canonical)

        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._upsert_protein,
                uniprot_id,
                gene_symbol,
                ensembl_gene_id,
                protein_name,
                sequence_length,
                mean_plddt,
                confidence_tier,
                idr_fraction,
                druggability_tier,
                json.dumps(tda_fingerprint) if tda_fingerprint else None,
                now,
                data_hash,
            )
        return uniprot_id

    def _upsert_protein(
        self,
        uniprot_id: str,
        gene_symbol: str,
        ensembl_gene_id: str,
        protein_name: str,
        sequence_length: int | None,
        mean_plddt: float | None,
        confidence_tier: str,
        idr_fraction: float | None,
        druggability_tier: str,
        tda_json: str | None,
        now: str,
        data_hash: str,
    ) -> None:
        assert self._conn is not None
        self._conn.execute(
            """
            INSERT INTO proteins
                (uniprot_id, gene_symbol, ensembl_gene_id, protein_name,
                 sequence_length, mean_plddt, confidence_tier, idr_fraction,
                 druggability_tier, tda_fingerprint, created_at, updated_at, data_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uniprot_id) DO UPDATE SET
                gene_symbol = excluded.gene_symbol,
                ensembl_gene_id = excluded.ensembl_gene_id,
                mean_plddt = COALESCE(excluded.mean_plddt, proteins.mean_plddt),
                confidence_tier = COALESCE(NULLIF(excluded.confidence_tier,''), proteins.confidence_tier),
                idr_fraction = COALESCE(excluded.idr_fraction, proteins.idr_fraction),
                druggability_tier = COALESCE(NULLIF(excluded.druggability_tier,''), proteins.druggability_tier),
                tda_fingerprint = COALESCE(excluded.tda_fingerprint, proteins.tda_fingerprint),
                updated_at = excluded.updated_at,
                data_hash = excluded.data_hash
            """,
            [
                uniprot_id,
                gene_symbol,
                ensembl_gene_id,
                protein_name,
                sequence_length,
                mean_plddt,
                confidence_tier,
                idr_fraction,
                druggability_tier,
                tda_json,
                now,
                now,
                data_hash,
            ],
        )
        self._conn.commit()

    async def store_variant(
        self,
        *,
        hgvs: str,
        gene_symbol: str = "",
        uniprot_id: str = "",
        clinvar_id: str = "",
        clinvar_class: str = "",
        gnomad_af: float | None = None,
        gnomad_ac: int | None = None,
        gnomad_an: int | None = None,
        homozygote_count: int | None = None,
        alphamissense_score: float | None = None,
        vep_consequence: str = "",
        vep_impact: str = "",
        sift_prediction: str = "",
        polyphen_prediction: str = "",
        cadd_phred: float | None = None,
        clinical_tier: str = "UNKNOWN",
        acmg_criteria: dict[str, Any] | None = None,
    ) -> str:
        """Upsert a variant record. Returns the hgvs identifier."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        canonical: dict[str, Any] = {
            "hgvs": hgvs,
            "clinvar_class": clinvar_class,
            "gnomad_af": gnomad_af,
            "alphamissense_score": alphamissense_score,
            "clinical_tier": clinical_tier,
        }
        data_hash = _sha256(canonical)
        acmg_json = json.dumps(acmg_criteria) if acmg_criteria else None

        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._upsert_variant,
                hgvs,
                gene_symbol,
                uniprot_id or None,
                clinvar_id,
                clinvar_class,
                gnomad_af,
                gnomad_ac,
                gnomad_an,
                homozygote_count,
                alphamissense_score,
                vep_consequence,
                vep_impact,
                sift_prediction,
                polyphen_prediction,
                cadd_phred,
                clinical_tier,
                acmg_json,
                now,
                data_hash,
            )
        return hgvs

    def _upsert_variant(
        self,
        hgvs: str,
        gene_symbol: str,
        uniprot_id: str | None,
        clinvar_id: str,
        clinvar_class: str,
        gnomad_af: float | None,
        gnomad_ac: int | None,
        gnomad_an: int | None,
        homozygote_count: int | None,
        alphamissense_score: float | None,
        vep_consequence: str,
        vep_impact: str,
        sift_prediction: str,
        polyphen_prediction: str,
        cadd_phred: float | None,
        clinical_tier: str,
        acmg_json: str | None,
        now: str,
        data_hash: str,
    ) -> None:
        assert self._conn is not None
        clinvar_acmg_code = ""
        if clinvar_class:
            from alphafold_sovereign.domain.disease import PathogenicityClass

            _acmg_map = {
                PathogenicityClass.PATHOGENIC.value: "P",
                PathogenicityClass.LIKELY_PATHOGENIC.value: "LP",
                PathogenicityClass.UNCERTAIN.value: "VUS",
                PathogenicityClass.LIKELY_BENIGN.value: "LB",
                PathogenicityClass.BENIGN.value: "B",
            }
            clinvar_acmg_code = _acmg_map.get(clinvar_class, "NP")

        self._conn.execute(
            """
            INSERT INTO variants
                (hgvs, gene_symbol, uniprot_id, clinvar_id, clinvar_class,
                 clinvar_acmg_code, gnomad_af, gnomad_ac, gnomad_an,
                 homozygote_count, alphamissense_score,
                 vep_consequence, vep_impact, sift_prediction, polyphen_prediction,
                 cadd_phred, clinical_tier, acmg_criteria, created_at, updated_at, data_hash)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(hgvs) DO UPDATE SET
                clinvar_class = COALESCE(NULLIF(excluded.clinvar_class,''), variants.clinvar_class),
                clinvar_acmg_code = COALESCE(NULLIF(excluded.clinvar_acmg_code,''), variants.clinvar_acmg_code),
                gnomad_af = COALESCE(excluded.gnomad_af, variants.gnomad_af),
                alphamissense_score = COALESCE(excluded.alphamissense_score, variants.alphamissense_score),
                clinical_tier = excluded.clinical_tier,
                acmg_criteria = COALESCE(excluded.acmg_criteria, variants.acmg_criteria),
                updated_at = excluded.updated_at,
                data_hash = excluded.data_hash
            """,
            [
                hgvs,
                gene_symbol,
                uniprot_id,
                clinvar_id,
                clinvar_class,
                clinvar_acmg_code,
                gnomad_af,
                gnomad_ac,
                gnomad_an,
                homozygote_count,
                alphamissense_score,
                vep_consequence,
                vep_impact,
                sift_prediction,
                polyphen_prediction,
                cadd_phred,
                clinical_tier,
                acmg_json,
                now,
                now,
                data_hash,
            ],
        )
        self._conn.commit()

    async def store_disease(
        self,
        *,
        mondo_id: str,
        name: str,
        definition: str = "",
        icd10_codes: list[str] | None = None,
        icd11_codes: list[str] | None = None,
        omim_ids: list[str] | None = None,
        orphanet_ids: list[str] | None = None,
        synonyms: list[str] | None = None,
        therapeutic_area: bool = False,
    ) -> str:
        """Upsert a disease record. Returns the mondo_id."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._upsert_disease,
                mondo_id,
                name,
                definition,
                json.dumps(icd10_codes or []),
                json.dumps(icd11_codes or []),
                json.dumps(omim_ids or []),
                json.dumps(orphanet_ids or []),
                json.dumps(synonyms or []),
                int(therapeutic_area),
                now,
            )
        return mondo_id

    def _upsert_disease(
        self,
        mondo_id: str,
        name: str,
        definition: str,
        icd10_json: str,
        icd11_json: str,
        omim_json: str,
        orphanet_json: str,
        synonyms_json: str,
        therapeutic_area: int,
        now: str,
    ) -> None:
        assert self._conn is not None
        self._conn.execute(
            """
            INSERT INTO diseases
                (mondo_id, name, definition, icd10_codes, icd11_codes, omim_ids,
                 orphanet_ids, synonyms, therapeutic_area, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(mondo_id) DO UPDATE SET
                name = excluded.name,
                definition = COALESCE(NULLIF(excluded.definition,''), diseases.definition),
                icd10_codes = excluded.icd10_codes,
                updated_at = excluded.updated_at
            """,
            [
                mondo_id,
                name,
                definition,
                icd10_json,
                icd11_json,
                omim_json,
                orphanet_json,
                synonyms_json,
                therapeutic_area,
                now,
                now,
            ],
        )
        self._conn.commit()

    async def store_drug(
        self,
        *,
        chembl_id: str,
        pref_name: str = "",
        max_phase: int = 0,
        max_phase_label: str = "",
        first_approval: int | None = None,
        molecule_type: str = "",
        oral: bool = False,
        parenteral: bool = False,
        black_box_warning: bool = False,
        mechanism_of_action: str = "",
        usan_stem: str = "",
        mw_freebase: float | None = None,
        alogp: float | None = None,
    ) -> str:
        """Upsert a drug record. Returns the chembl_id."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._upsert_drug,
                chembl_id,
                pref_name,
                max_phase,
                max_phase_label,
                first_approval,
                molecule_type,
                int(oral),
                int(parenteral),
                int(black_box_warning),
                mechanism_of_action,
                usan_stem,
                mw_freebase,
                alogp,
                now,
            )
        return chembl_id

    def _upsert_drug(
        self,
        chembl_id: str,
        pref_name: str,
        max_phase: int,
        max_phase_label: str,
        first_approval: int | None,
        molecule_type: str,
        oral: int,
        parenteral: int,
        bbw: int,
        moa: str,
        usan_stem: str,
        mw: float | None,
        alogp: float | None,
        now: str,
    ) -> None:
        assert self._conn is not None
        self._conn.execute(
            """
            INSERT INTO drugs
                (chembl_id, pref_name, max_phase, max_phase_label, first_approval,
                 molecule_type, oral, parenteral, black_box_warning,
                 mechanism_of_action, usan_stem, mw_freebase, alogp,
                 created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(chembl_id) DO UPDATE SET
                max_phase = MAX(excluded.max_phase, drugs.max_phase),
                pref_name = COALESCE(NULLIF(excluded.pref_name,''), drugs.pref_name),
                updated_at = excluded.updated_at
            """,
            [
                chembl_id,
                pref_name,
                max_phase,
                max_phase_label,
                first_approval,
                molecule_type,
                oral,
                parenteral,
                bbw,
                moa,
                usan_stem,
                mw,
                alogp,
                now,
                now,
            ],
        )
        self._conn.commit()

    async def log_tool_invocation(
        self,
        *,
        tool_name: str,
        params: dict[str, Any],
        result: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
        session_id: str = "",
        request_id: str = "",
    ) -> int:
        """Log a tool invocation for audit trail. Returns the invocation row ID."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        params_hash = _sha256(params)
        params_json = json.dumps(params, default=str)
        result_hash: str | None = None
        result_json: str | None = None
        if result is not None:
            result_hash = _sha256(result)
            result_json = json.dumps(result, default=str)

        async with self._lock:
            loop = asyncio.get_event_loop()
            row_id = await loop.run_in_executor(
                None,
                self._insert_invocation,
                tool_name,
                params_hash,
                params_json,
                result_hash,
                result_json,
                duration_ms,
                error,
                session_id,
                request_id,
                now,
            )
        return row_id

    def _insert_invocation(
        self,
        tool_name: str,
        params_hash: str,
        params_json: str,
        result_hash: str | None,
        result_json: str | None,
        duration_ms: int | None,
        error: str | None,
        session_id: str,
        request_id: str,
        now: str,
    ) -> int:
        assert self._conn is not None
        cursor = self._conn.execute(
            """
            INSERT INTO tool_invocations
                (tool_name, params_hash, params_json, result_hash, result_json,
                 duration_ms, error, session_id, request_id, called_at, completed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                tool_name,
                params_hash,
                params_json,
                result_hash,
                result_json,
                duration_ms,
                error,
                session_id,
                request_id,
                now,
                now,
            ],
        )
        self._conn.commit()
        return cursor.lastrowid or 0

    # ── Query API ─────────────────────────────────────────────────────────────

    async def query_variants(
        self,
        *,
        gene: str | None = None,
        tier: str | None = None,
        clinvar_class: str | None = None,
        min_am_score: float | None = None,
        max_gnomad_af: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query stored variants with filters.

        Args:
            gene: Filter by gene symbol (case-insensitive).
            tier: Clinical tier filter: 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'.
            clinvar_class: ClinVar classification string.
            min_am_score: Minimum AlphaMissense score.
            max_gnomad_af: Maximum gnomAD allele frequency.
            limit: Max rows.

        Returns:
            List of variant summary dicts from the ``variant_summary`` view.
        """
        clauses: list[str] = []
        values: list[Any] = []

        if gene:
            clauses.append("gene_symbol = ?")
            values.append(gene.upper())
        if tier:
            clauses.append("clinical_tier = ?")
            values.append(tier.upper())
        if clinvar_class:
            clauses.append("clinvar_class = ?")
            values.append(clinvar_class)
        if min_am_score is not None:
            clauses.append("alphamissense_score >= ?")
            values.append(min_am_score)
        if max_gnomad_af is not None:
            clauses.append("(gnomad_af IS NULL OR gnomad_af <= ?)")
            values.append(max_gnomad_af)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT * FROM variant_summary {where} ORDER BY alphamissense_score DESC LIMIT {limit}"
        )

        async with self._lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._fetchall, sql, values)

    async def query_proteins(
        self,
        *,
        druggability_tier: str | None = None,
        min_plddt: float | None = None,
        organism: str = "Homo sapiens",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query stored proteins by druggability and confidence."""
        clauses = ["organism = ?"]
        values: list[Any] = [organism]
        if druggability_tier:
            clauses.append("druggability_tier = ?")
            values.append(druggability_tier.upper())
        if min_plddt is not None:
            clauses.append("mean_plddt >= ?")
            values.append(min_plddt)
        where = f"WHERE {' AND '.join(clauses)}"
        sql = f"SELECT * FROM proteins {where} ORDER BY mean_plddt DESC LIMIT {limit}"
        async with self._lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._fetchall, sql, values)

    async def query_drug_landscape(
        self,
        *,
        mondo_id: str | None = None,
        min_phase: int = 4,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query stored drugs by disease and development phase."""
        clauses = ["max_phase >= ?"]
        values: list[Any] = [min_phase]
        if mondo_id:
            clauses.append("mondo_id = ?")
            values.append(mondo_id)
        where = f"WHERE {' AND '.join(clauses)}"
        sql = f"SELECT * FROM drug_landscape {where} ORDER BY max_phase DESC LIMIT {limit}"
        async with self._lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._fetchall, sql, values)

    async def get_statistics(self) -> dict[str, Any]:
        """Return database statistics — size, entity counts, last activity."""
        async with self._lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._gather_stats)

    def _gather_stats(self) -> dict[str, Any]:
        assert self._conn is not None
        tables = [
            "proteins",
            "variants",
            "diseases",
            "drugs",
            "genes",
            "phenotypes",
            "protein_disease",
            "protein_drug",
            "variant_disease",
            "gene_phenotype",
            "tool_invocations",
        ]
        counts: dict[str, int] = {}
        for t in tables:
            row = self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
            counts[t] = row[0] if row else 0

        last_inv = self._conn.execute(
            "SELECT called_at FROM tool_invocations ORDER BY called_at DESC LIMIT 1"
        ).fetchone()

        db_size = os.path.getsize(str(self._db_path)) if self._db_path.exists() else 0

        return {
            "entity_counts": counts,
            "database_size_bytes": db_size,
            "database_size_mb": round(db_size / 1_048_576, 3),
            "database_path": str(self._db_path),
            "schema_version": _SCHEMA_VERSION,
            "last_tool_invocation": last_inv[0] if last_inv else None,
        }

    async def export_to_dict(
        self,
        tables: list[str] | None = None,
        *,
        limit: int = 10_000,
    ) -> dict[str, list[dict[str, Any]]]:
        """Export tables as JSON-serialisable dicts for pandas/ML pipelines.

        Args:
            tables: Specific tables to export (None = all entity tables).
            limit: Max rows per table.

        Returns:
            Dict mapping table name → list of row dicts.
        """
        default_tables = [
            "proteins",
            "variants",
            "diseases",
            "drugs",
            "protein_disease",
            "protein_drug",
        ]
        selected = tables or default_tables
        result: dict[str, list[dict[str, Any]]] = {}
        for t in selected:
            async with self._lock:
                loop = asyncio.get_event_loop()
                result[t] = await loop.run_in_executor(
                    None,
                    self._fetchall,
                    f"SELECT * FROM {t} LIMIT {limit}",
                    [],
                )
        return result

    def _fetchall(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        assert self._conn is not None
        cursor = self._conn.execute(sql, params)
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


# ── Module-level singleton ────────────────────────────────────────────────────

_KG_SINGLETON: KnowledgeGraph | None = None
_KG_LOCK = asyncio.Lock()


@asynccontextmanager
async def get_knowledge_graph(
    db_path: str | Path | None = None,
) -> AsyncIterator[KnowledgeGraph]:
    """Acquire the module-level KnowledgeGraph singleton.

    Reuses a single connection across tool calls for efficiency.
    Creates a new connection if not yet initialised or if a custom path
    is provided.

    Usage::

        async with get_knowledge_graph() as kg:
            await kg.store_variant(hgvs="BRCA1:c.181T>G", ...)
    """
    global _KG_SINGLETON
    async with _KG_LOCK:
        if _KG_SINGLETON is None or (db_path and str(db_path) != str(_KG_SINGLETON._db_path)):
            if _KG_SINGLETON is not None:
                await _KG_SINGLETON.close()
            _KG_SINGLETON = KnowledgeGraph(db_path)
            await _KG_SINGLETON.connect()
    yield _KG_SINGLETON
