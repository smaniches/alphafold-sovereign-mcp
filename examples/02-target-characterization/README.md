# Target evidence retrieval

Tool: `assess_target_druggability` with a caller-supplied, source-checked UniProt accession.

This tool retrieves and attributes ChEMBL, Open Targets, gnomAD and
AlphaFold DB information. AlphaFold pLDDT is confidence in a predicted
structure, not experimental evidence of a binding pocket or drug efficacy.

Any `druggability_tier` is a local, uncalibrated heuristic. Inspect
the original source fields and scoring breakdown. No particular tier,
drug count, drug indication, or activity claim is fixed in this README.

Older 2026-06-08 illustrative output has been removed from the active
example because it is not an up-to-date or independently validated
scientific narrative.
