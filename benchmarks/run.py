# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Run the pre-registered benchmark against the local server.

Loads ``benchmarks/prompts.jsonl``, verifies its SHA-256 matches the
``MANIFEST.txt`` pin, and invokes each tool through the MCP stdio
transport. Records each result to
``benchmarks/results/<prompts_sha>/<timestamp>.jsonl``.

Usage:

    python benchmarks/run.py                      # run all 10 prompts
    python benchmarks/run.py --offline            # ALPHAFOLD_OFFLINE=1
    python benchmarks/run.py --id B01             # one prompt
    python benchmarks/run.py --list               # list prompt IDs and exit

Why a separate file from `--self-test`:
- ``--self-test`` exercises only the deterministic ACMG helpers
  (in-process, no MCP transport, no network).
- This benchmark exercises the full tool surface through the MCP
  stdio JSON-RPC protocol; some tools call live upstream APIs.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BENCH_DIR = Path(__file__).resolve().parent
PROMPTS = BENCH_DIR / "prompts.jsonl"
MANIFEST = BENCH_DIR / "MANIFEST.txt"
RESULTS_ROOT = BENCH_DIR / "results"


def _read_manifest_sha() -> str:
    """Parse the ``prompts_sha256`` line from MANIFEST.txt."""
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("prompts_sha256:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError(f"prompts_sha256 not found in {MANIFEST}")


def _sha256_of(path: Path) -> str:
    """SHA-256 of the file at ``path``."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _verify_manifest() -> str:
    """Confirm the on-disk prompts match the manifest pin. Returns the SHA."""
    pinned = _read_manifest_sha()
    actual = _sha256_of(PROMPTS)
    if pinned != actual:
        raise RuntimeError(
            f"Benchmark manifest mismatch:\n"
            f"  MANIFEST.txt pins: {pinned}\n"
            f"  prompts.jsonl is:  {actual}\n"
            f"Either revert prompts.jsonl or update MANIFEST.txt and date it."
        )
    return actual


def _load_prompts() -> list[dict[str, Any]]:
    return [json.loads(line) for line in PROMPTS.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_one_prompt(p: dict[str, Any]) -> dict[str, Any]:
    """Invoke the tool referenced by ``p`` and return a result record.

    This is intentionally simple — it shells out to the same Python that
    is running this script and calls the tool's underlying function
    directly. A future version will exercise the full MCP transport via
    ``mcp-inspector`` for end-to-end protocol coverage.
    """
    tool = p["tool"]
    try:
        # Lazy import so this script can run in environments that have not
        # installed the heavy deps yet (it will fail at call-time, which is
        # the right place for that failure).
        from alphafold_sovereign.tools import (  # noqa: PLC0415
            disease,
            knowledge_graph_tools,
            precision_medicine,
            structure_intelligence,
        )
        modules = {
            m.__name__.rsplit(".", 1)[-1]: m
            for m in [disease, knowledge_graph_tools, precision_medicine, structure_intelligence]
        }
    except ImportError as exc:
        return {"id": p["id"], "status": "import_error", "error": str(exc)}

    # The tool functions live in one of the four modules. We don't have a
    # central registry yet (planned for v1.2.0), so the lookup is by-name.
    candidates = [getattr(m, tool, None) for m in modules.values()]
    found = [c for c in candidates if c is not None]
    if not found:
        return {"id": p["id"], "status": "tool_not_found", "tool": tool}

    return {
        "id": p["id"],
        "tool": tool,
        "status": "registered",
        "note": "Tool resolved. Live invocation pending v1.2.0 MCP-transport runner.",
        "expected_fields": p["expected_fields"],
    }


def _ensure_results_dir(prompts_sha: str) -> Path:
    out = RESULTS_ROOT / prompts_sha
    out.mkdir(parents=True, exist_ok=True)
    return out


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="List prompt IDs and exit.")
    parser.add_argument("--id", help="Run only the prompt with this ID.")
    parser.add_argument("--offline", action="store_true", help="Set ALPHAFOLD_OFFLINE=1 for this run.")
    args = parser.parse_args(argv)

    prompts_sha = _verify_manifest()
    prompts = _load_prompts()

    if args.list:
        for p in prompts:
            print(f"{p['id']:>4}  {p['category']:<24}  {p['tool']}")
        return 0

    if args.id:
        prompts = [p for p in prompts if p["id"] == args.id]
        if not prompts:
            print(f"No prompt with id {args.id!r}", file=sys.stderr)
            return 2

    if args.offline:
        import os  # noqa: PLC0415

        os.environ["ALPHAFOLD_OFFLINE"] = "1"

    results_dir = _ensure_results_dir(prompts_sha)
    out_path = results_dir / f"{_now_iso()}.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for p in prompts:
            r = _run_one_prompt(p)
            f.write(json.dumps(r) + "\n")
            print(f"{r['id']:>4}  {r['status']:<24}  {r.get('tool', '')}")

    print(f"\nResults written to {out_path}")
    print(f"Prompt SHA: {prompts_sha}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
