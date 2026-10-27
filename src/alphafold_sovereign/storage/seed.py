# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Retired illustrative SQLite seed.

Prior releases shipped representative biomedical values without record-level
source evidence. Never insert these values as scientific observations.
This compatibility entrypoint intentionally performs no writes. Existing
SQLite records are preserved; no migration or cleanup is performed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alphafold_sovereign.storage.knowledge_graph import KnowledgeGraph


async def seed_knowledge_graph(kg: KnowledgeGraph) -> None:
    """Do nothing: data must enter SQLite through explicit, sourced writes."""
    return None
