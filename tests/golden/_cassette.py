# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Record/replay machinery for the end-to-end golden examples.

The golden examples run a full pipeline tool against **real upstream responses
captured once from the live public APIs** and replayed deterministically, so
the same run reproduces byte-for-byte in CI with no network access. Recording
happens at the ``BaseAsyncClient._request`` boundary, which returns only the
final successful response after the client's internal retry loop — so a
cassette holds one clean request/response per upstream call, free of transient
429/503 noise. Replay re-registers those responses as ``respx`` routes at the
same transport layer.

This module is the single source of truth shared by the recorder
(``scripts/record_golden_examples.py``) and the golden test
(``tests/golden/test_golden_examples.py``): the example registry, the tool
dispatch, the response reconstruction, and the volatile-field normalisation
that keeps ``expected.json`` stable across releases.
"""

from __future__ import annotations

import base64
import json
import pathlib
import re
from typing import Any

import httpx

from alphafold_sovereign.tools.precision_medicine import (
    VariantClinicalReportInput,
    generate_variant_clinical_report,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "examples" / "golden"

# The golden set: the flagship variant clinical-report pipeline (which fans out
# across Ensembl VEP, ClinVar, gnomAD, Open Targets, DisGeNET, ChEMBL and the
# AlphaFold/AlphaMissense join) run against three canonical, well-characterised
# variants spanning the interpretive space: a germline loss-of-function founder
# allele, a somatic structural hotspot, and a somatic activating driver.
EXAMPLES: list[dict[str, Any]] = [
    {
        "slug": "01-brca1-c5266dup",
        "tool": "generate_variant_clinical_report",
        "input": {"hgvs": "BRCA1:c.5266dupC"},
    },
    {
        "slug": "02-tp53-r175h",
        "tool": "generate_variant_clinical_report",
        "input": {"hgvs": "TP53:p.Arg175His"},
    },
    {
        "slug": "03-egfr-l858r",
        "tool": "generate_variant_clinical_report",
        "input": {"hgvs": "EGFR:p.Leu858Arg"},
    },
]


async def run_tool(tool: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """Invoke a pipeline tool by name with its Pydantic input model."""
    dispatch = {
        "generate_variant_clinical_report": (
            generate_variant_clinical_report,
            VariantClinicalReportInput,
        ),
    }
    fn, model = dispatch[tool]
    return await fn(model(**tool_input))


# --- provenance normalisation ------------------------------------------------

# The only volatile fields in a report are the package version and the UTC
# timestamp embedded in the provenance footer; everything else derives from the
# frozen upstream responses. Redacting just these two keeps the diff meaningful
# (every scientific field must match exactly) while surviving version bumps.
_PROVENANCE_RE = re.compile(r"AlphaFold Sovereign MCP v[^ ·]+ · [0-9T:\-Z]+ ·")
_PROVENANCE_REDACTED = "AlphaFold Sovereign MCP v<VERSION> · <TIMESTAMP> ·"


def normalize_output(obj: Any) -> Any:
    """Redact the provenance version + timestamp anywhere in a result.

    Walks the structure and rewrites string values in place rather than
    round-tripping through JSON, so the middle-dot separator in the provenance
    footer is matched literally (``json.dumps`` would escape it to ``\\u00b7``).
    """
    if isinstance(obj, str):
        return _PROVENANCE_RE.sub(_PROVENANCE_REDACTED, obj)
    if isinstance(obj, dict):
        return {key: normalize_output(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [normalize_output(item) for item in obj]
    return obj


# --- cassette load + replay --------------------------------------------------


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def reconstruct_response(interaction: dict[str, Any]) -> httpx.Response:
    """Rebuild the recorded httpx response from its stored body encoding."""
    status = interaction["status"]
    if "response_json" in interaction:
        return httpx.Response(status, json=interaction["response_json"])
    if "response_text" in interaction:
        return httpx.Response(status, content=interaction["response_text"].encode("utf-8"))
    return httpx.Response(status, content=base64.b64decode(interaction["response_base64"]))


def install_routes(router: Any, cassette: dict[str, Any]) -> None:
    """Register every recorded interaction as a respx route.

    GET routes match on the full recorded URL (query included); POST routes
    additionally match on the request JSON body so the several GraphQL calls
    that share one endpoint (gnomAD, Open Targets) each resolve to their own
    recorded response.
    """
    for interaction in cassette["interactions"]:
        response = reconstruct_response(interaction)
        method = interaction["method"].upper()
        url = interaction["url"]
        if method == "GET":
            router.get(url).mock(return_value=response)
        elif method == "POST" and "request_json" in interaction:
            router.post(url, json=interaction["request_json"]).mock(return_value=response)
        else:
            router.route(method=method, url=url).mock(return_value=response)
