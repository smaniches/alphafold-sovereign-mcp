# Target evidence retrieval

`assess_target_druggability` can retrieve ChEMBL drug records, Open Targets
tractability annotations, gene-level constraint, and AlphaFold DB predicted
structure-confidence information for a UniProt accession.

Example input: `uniprot_id="P00533"`.

The returned source fields are distinguishable from the tool's local
`druggability_tier` calculation. Such a tier is a transparent but
**uncalibrated research heuristic**, not experimental proof that a protein is
tractable, safe, or suitable for a particular therapy.

AlphaFold pLDDT reports model-prediction confidence; it is not a laboratory
measurement of target druggability or ligand-binding behavior.

Inspect `scoring_breakdown`, source identifiers, confidence, and failures
before using these observations downstream. No fixed numerical result is
asserted here because the source databases change.
