# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""UniProtKB identifier syntax, not an accession or model existence check.

Source: https://www.uniprot.org/help/accession_numbers
"""

# UniProtKB canonical accessions are 6 or 10 characters.
_UNIPROT_CORE = (
    r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|"
    r"[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})"
)

UNIPROT_ACCESSION_PATTERN = rf"^{_UNIPROT_CORE}$"
# A numbered UniProt isoform (-2 etc.) is not an AlphaFold model fragment (-F2).
UNIPROT_ISOFORM_PATTERN = rf"^{_UNIPROT_CORE}(?:-[1-9][0-9]*)?$"
