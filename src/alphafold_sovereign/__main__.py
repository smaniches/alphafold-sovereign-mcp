# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Entry point for ``python -m alphafold_sovereign`` and the console script.

Without flags, launches the MCP server over stdio (suitable for Claude
Desktop and other stdio-based MCP clients).

With ``--version`` prints the package version and exits.

With ``--self-test`` runs a deterministic offline self-test that
exercises the ACMG helper functions on a known BRCA1 variant fixture
and returns exit code 0 on PASS, non-zero on FAIL. No network calls.
"""

from __future__ import annotations

import argparse
import sys


def _run_self_test() -> int:
    """Exercise deterministic ACMG helper functions on a BRCA1 fixture.

    The self-test asserts that the three pure functions (`_vep_to_acmg`,
    `_gnomad_to_acmg`, `_am_to_acmg_evidence`) emit the expected ACMG
    criteria on a hand-built fixture that mirrors what the upstream
    APIs would return for BRCA1 c.5266dupC. This proves the install is
    importable and the ACMG mapping is wired up correctly without
    requiring any network access.
    """
    # Defer heavy imports until self-test is requested so `--version`
    # stays cheap.
    from alphafold_sovereign.tools.precision_medicine import (  # noqa: PLC0415
        _am_to_acmg_evidence,
        _gnomad_to_acmg,
        _vep_to_acmg,
    )

    failures: list[str] = []

    # Fixture 1: a canonical frameshift variant should produce PVS1.
    vep_frameshift = [
        {
            "canonical": True,
            "consequence_terms": ["frameshift_variant"],
            "impact": "HIGH",
        }
    ]
    out = _vep_to_acmg(vep_frameshift)
    if "PVS1" not in out:
        failures.append(f"_vep_to_acmg(frameshift) → expected PVS1 key, got {out!r}")

    # Fixture 2: extremely rare gnomAD AF (BRCA1 c.5266dupC ~ 1.4e-5) → PM2.
    out2 = _gnomad_to_acmg(1.42e-5)
    if "PM2" not in out2:
        failures.append(f"_gnomad_to_acmg(1.42e-5) → expected PM2 key, got {out2!r}")

    # Fixture 3: high AlphaMissense score (likely_pathogenic) → PP3.
    out3 = _am_to_acmg_evidence(0.95)
    if "PP3" not in out3:
        failures.append(f"_am_to_acmg_evidence(0.95) → expected PP3 key, got {out3!r}")

    # Fixture 4: low AlphaMissense score (likely_benign) → BP4.
    out4 = _am_to_acmg_evidence(0.05)
    if "BP4" not in out4:
        failures.append(f"_am_to_acmg_evidence(0.05) → expected BP4 key, got {out4!r}")

    # Fixture 5: common gnomAD AF (>5%) → BS1.
    out5 = _gnomad_to_acmg(0.10)
    if "BS1" not in out5:
        failures.append(f"_gnomad_to_acmg(0.10) → expected BS1 key, got {out5!r}")

    if failures:
        print("SELF-TEST FAIL", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("SELF-TEST PASS — ACMG helpers behave as expected on the BRCA1 c.5266dupC fixture.")
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="alphafold-sovereign-mcp",
        description="MCP server wrapping AlphaFold DB and 8 other biomedical data sources.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the package version and exit.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run a deterministic offline self-test of the ACMG helper "
            "functions and exit. No network calls."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    if args.version:
        from alphafold_sovereign import __version__  # noqa: PLC0415

        print(__version__)
        return 0

    if args.self_test:
        return _run_self_test()

    # Default: boot the stdio MCP server.
    from alphafold_sovereign.server.stdio import run_stdio  # noqa: PLC0415

    run_stdio()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
