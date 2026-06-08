# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Client integration stubs — verify client classes instantiate without network I/O."""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_alphafold_client_import() -> None:
    from alphafold_sovereign.clients.alphafold import AlphaFoldClient

    assert AlphaFoldClient is not None


@pytest.mark.unit
def test_ensembl_client_import() -> None:
    from alphafold_sovereign.clients.ensembl import EnsemblClient

    assert EnsemblClient is not None


@pytest.mark.unit
def test_chembl_client_import() -> None:
    from alphafold_sovereign.clients.chembl import ChEMBLClient

    assert ChEMBLClient is not None


@pytest.mark.unit
def test_disgenet_client_import() -> None:
    from alphafold_sovereign.clients.disgenet import DisGeNETClient

    assert DisGeNETClient is not None


@pytest.mark.unit
def test_gnomad_client_import() -> None:
    from alphafold_sovereign.clients.gnomad import GnomADClient

    assert GnomADClient is not None


@pytest.mark.unit
def test_clinvar_client_import() -> None:
    from alphafold_sovereign.clients.clinvar import ClinVarClient

    assert ClinVarClient is not None
