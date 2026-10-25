"""Keep the documented public surface aligned with registered source tools."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "src" / "alphafold_sovereign" / "tools"


def test_architecture_tool_inventory_matches_registration() -> None:
    counts = {}
    for path in TOOLS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        counts[path.stem] = sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "tool"
                for decorator in node.decorator_list
            )
            for node in tree.body
        )
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    total = sum(counts.values())
    assert f"{total} tools registered" in architecture
    assert f"({total} tools; thin orchestration)" in architecture
    assert f"3-D variant triage, ICD-10 resolution  ({counts['disease']})" in architecture


def test_variant_evidence_docstring_disclaims_clinical_assessment() -> None:
    tree = ast.parse((TOOLS / "disease.py").read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "triage_variant_3d"
    )
    docstring = ast.get_docstring(function)
    assert docstring is not None
    assert "source-reported variant evidence for research" in docstring
    assert "not a calibrated risk estimate" in docstring
    assert "Comprehensive clinical triage" not in docstring
