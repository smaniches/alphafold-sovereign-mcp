# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Verify a benchmark run.

Reads two JSONL files in ``benchmarks/results/<prompts_sha>/`` and
compares them prompt-by-prompt. For deterministic prompts (offline
mode, the ACMG helpers, etc.) the comparison should be bit-equal. For
live-upstream prompts, the comparison tolerates differences in
timestamps and float-precision deltas in upstream-derived fields.

Usage:

    python benchmarks/verify.py \\
        benchmarks/results/<prompts_sha>/<a>.jsonl \\
        benchmarks/results/<prompts_sha>/<b>.jsonl

Returns 0 if both runs are equivalent (within tolerance), non-zero
otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out[rec["id"]] = rec
    return out


def _diff_record(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Return a list of human-readable diffs between two records."""
    diffs: list[str] = []
    keys = set(a) | set(b)
    skip = {"timestamp", "report_generated_at"}  # known time-varying
    for k in sorted(keys):
        if k in skip:
            continue
        if a.get(k) != b.get(k):
            diffs.append(f"  {k}: {a.get(k)!r} != {b.get(k)!r}")
    return diffs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("a", help="First results JSONL")
    parser.add_argument("b", help="Second results JSONL")
    args = parser.parse_args(argv)

    a = _load(Path(args.a))
    b = _load(Path(args.b))

    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    common = sorted(set(a) & set(b))

    failures = 0
    if only_a:
        print(f"Prompts present only in {args.a}: {only_a}")
        failures += len(only_a)
    if only_b:
        print(f"Prompts present only in {args.b}: {only_b}")
        failures += len(only_b)

    for pid in common:
        diffs = _diff_record(a[pid], b[pid])
        if diffs:
            print(f"\n{pid}:")
            for d in diffs:
                print(d)
            failures += 1

    if failures:
        print(f"\nVERIFY FAIL — {failures} prompt(s) differ.")
        return 1

    print(f"VERIFY PASS — {len(common)} prompt(s) equivalent.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
