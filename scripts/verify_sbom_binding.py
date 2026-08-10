#!/usr/bin/env python3
"""Independently verify that a CycloneDX SBOM is bound to one exact wheel.

Checks, from the artifacts alone (no shared state with the generation or
binding step):

  1. the wheel is uniquely identified (an explicit wheel path, or a dist
     directory containing exactly one wheel);
  2. the wheel filename's distribution/version fields agree with the wheel's
     own ``.dist-info/METADATA``;
  3. SBOM root component name  == wheel METADATA ``Name`` (PEP 503 canonical);
  4. SBOM root component version == wheel METADATA ``Version``;
  5. the SBOM root component carries exactly one SHA-256 hash, equal to the
     freshly recomputed SHA-256 of the wheel file.

Any failure exits non-zero with a specific message. This file intentionally
re-implements the helpers found in ``bind_sbom_wheel.py`` instead of
importing them: the verifier must not depend on the code path it verifies.

usage: verify_sbom_binding.py <sbom.cyclonedx.json> <wheel-or-dist-dir>
"""

from __future__ import annotations

import email.parser
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path


def canonical_name(name: str) -> str:
    """PEP 503 normalized project name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def fail(message: str) -> None:
    print(f"SBOM binding verification FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def locate_wheel(target: Path) -> Path:
    if target.is_dir():
        wheels = sorted(target.glob("*.whl"))
        if len(wheels) != 1:
            fail(f"expected exactly one wheel in {target}, found {len(wheels)}")
        return wheels[0]
    if not target.is_file():
        fail(f"wheel not found: {target}")
    return target


def wheel_metadata_identity(wheel_path: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            metadata_members = [
                member
                for member in archive.namelist()
                if member.endswith(".dist-info/METADATA") and member.count("/") == 1
            ]
            if len(metadata_members) != 1:
                fail(
                    f"expected exactly one .dist-info/METADATA in {wheel_path.name}, "
                    f"found {len(metadata_members)}"
                )
            raw = archive.read(metadata_members[0]).decode("utf-8")
    except zipfile.BadZipFile:
        fail(f"{wheel_path.name} is not a readable wheel (bad zip)")
    parsed = email.parser.Parser().parsestr(raw)
    name = parsed.get("Name")
    version = parsed.get("Version")
    if not name or not version:
        fail(f"wheel METADATA is missing Name or Version in {wheel_path.name}")
    return name, version


def wheel_filename_identity(wheel_path: Path) -> tuple[str, str]:
    fields = wheel_path.name.split("-")
    if len(fields) < 5:
        fail(f"not a PEP 427 wheel filename: {wheel_path.name}")
    return fields[0], fields[1]


def recomputed_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 64

    sbom_path = Path(argv[1])
    if not sbom_path.is_file():
        fail(f"SBOM not found: {sbom_path}")
    wheel_path = locate_wheel(Path(argv[2]))

    meta_name, meta_version = wheel_metadata_identity(wheel_path)
    file_name, file_version = wheel_filename_identity(wheel_path)
    if canonical_name(file_name) != canonical_name(meta_name):
        fail(
            f"wheel filename distribution {file_name!r} does not match METADATA name {meta_name!r}"
        )
    if file_version != meta_version.replace("-", "_"):
        fail(
            f"wheel filename version {file_version!r} does not match "
            f"METADATA version {meta_version!r}"
        )

    try:
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        fail(f"SBOM is not valid JSON: {error}")
    if sbom.get("bomFormat") != "CycloneDX":
        fail(f"not a CycloneDX SBOM: bomFormat={sbom.get('bomFormat')!r}")

    component = sbom.get("metadata", {}).get("component")
    if component is None:
        fail("SBOM has no metadata.component root component")

    sbom_name = component.get("name", "")
    sbom_version = component.get("version", "")
    if canonical_name(sbom_name) != canonical_name(meta_name):
        fail(f"root component name {sbom_name!r} does not match wheel METADATA name {meta_name!r}")
    if sbom_version != meta_version:
        fail(
            f"root component version {sbom_version!r} does not match "
            f"wheel METADATA version {meta_version!r}"
        )

    sha256_entries = [
        entry
        for entry in component.get("hashes", [])
        if str(entry.get("alg", "")).upper() == "SHA-256"
    ]
    if len(sha256_entries) != 1:
        fail(f"root component must carry exactly one SHA-256 hash, found {len(sha256_entries)}")
    bound = str(sha256_entries[0].get("content", "")).lower()
    actual = recomputed_sha256(wheel_path)
    if bound != actual:
        fail(
            f"root component SHA-256 {bound or '<empty>'} does not match "
            f"recomputed SHA-256({wheel_path.name}) = {actual}"
        )

    print(
        "SBOM binding verified: "
        f"{sbom_name}=={sbom_version} <-> {wheel_path.name} (sha256 {actual})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
