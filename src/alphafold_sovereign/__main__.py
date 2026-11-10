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
    """Exercise deterministic variant-evidence helpers on a BRCA1 fixture.

    The self-test asserts, on hand-built fixtures that mirror what the
    upstream APIs return for BRCA1 c.5266dupC, that the pure helpers behave
    as documented: a frameshift consequence yields a PVS1 candidate signal
    (`_vep_to_acmg`); the Ensembl VEP mapping of this reverse-strand variant
    resolves to its forward-strand gnomAD variant ID
    (`_resolve_gnomad_variant`); and allele frequency and AlphaMissense
    scores are reported without any ACMG criterion (`_unassessed_evidence`).
    This proves the install is importable and the evidence handling is
    wired up correctly without requiring any network access.
    """
    # Defer heavy imports until self-test is requested so `--version`
    # stays cheap.
    from alphafold_sovereign.tools.precision_medicine import (  # noqa: PLC0415
        _resolve_gnomad_variant,
        _unassessed_evidence,
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

    # Fixture 2: Ensembl VEP's mapping of BRCA1 c.5266dupC (recorded
    # 2026-11-10 UTC). BRCA1 is on the reverse strand, so the duplicated C is
    # a G in the forward-strand gnomAD variant ID.
    vep_locus = {
        "assembly_name": "GRCh38",
        "seq_region_name": "17",
        "start": 43057064,
        "end": 43057063,
        "strand": -1,
        "allele_string": "-/C",
        "vcf_string": "17-43057063-G-GG",
    }
    variant = _resolve_gnomad_variant("NM_007294.4:c.5266dup", [{"locus": vep_locus}])
    if variant.get("variant_id") != "17-43057063-G-GG":
        failures.append(
            f"_resolve_gnomad_variant(c.5266dup) → expected 17-43057063-G-GG, got {variant!r}"
        )

    # Fixtures 3-5: a rare allele frequency (BRCA1 c.5266dupC ~ 1.4e-5), a
    # common one (>5%) and a high AlphaMissense score are observations. None
    # of them may assign BA1, BS1, PM2, PP3 or BP4.
    for label, allele_frequency, am_score in (
        ("rare allele frequency", 1.42e-5, None),
        ("common allele frequency", 0.10, None),
        ("high AlphaMissense score", None, 0.95),
    ):
        evidence = _unassessed_evidence(
            gnomad_variant=variant,
            gnomad_status="ok",
            gnomad_data={"cohorts": {"exome": {"allele_frequency": allele_frequency}}},
            am_score=am_score,
            am_prediction={},
            am_status=None,
            canonical_tc={},
        )
        statuses = {
            *evidence.get("population_frequency", {}).get("acmg_criteria", {"": ""}).values(),
            *evidence.get("computational_predictions", {}).get("acmg_criteria", {"": ""}).values(),
        }
        if statuses != {"NOT_ASSESSED"}:
            failures.append(
                f"_unassessed_evidence({label}) → expected only NOT_ASSESSED, got {evidence!r}"
            )

    if failures:
        print("SELF-TEST FAIL", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("SELF-TEST PASS - ACMG helpers behave as expected on the BRCA1 c.5266dupC fixture.")
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
