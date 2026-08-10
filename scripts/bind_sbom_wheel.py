#!/usr/bin/env python3
"""Bind the SHA-256 digest of the exact built wheel into a CycloneDX SBOM.

Reads the wheel's ``METADATA`` (PEP 566) name and version, requires the SBOM
root component (``metadata.component``) to already carry the same identity
(the SBOM tool seeds it from ``pyproject.toml``), and then binds the wheel's
SHA-256 into the root component append-or-confirm, never repair: with no
existing SHA-256 the digest is added; an existing equal SHA-256 is accepted
and preserved; an existing conflicting SHA-256, or multiple SHA-256 entries,
is a fail-closed error that leaves the SBOM byte-for-byte unchanged.
Unrelated non-SHA-256 hash entries are preserved. A name or version mismatch
between the SBOM root and the wheel is likewise a fail-closed error: binding
must never paper over a drift between source metadata and built artifact.

Verification is intentionally NOT this script's job:
``scripts/verify_sbom_binding.py`` is a separate, self-contained
implementation so that a bug here cannot silently verify its own output.

usage: bind_sbom_wheel.py <sbom.cyclonedx.json> <wheel>
"""

from __future__ import annotations

import email.parser
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

WHEEL_FILENAME_PROPERTY = "smaniches:release:bound-wheel-filename"


def canonical_name(name: str) -> str:
    """PEP 503 normalized project name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def wheel_identity(wheel_path: Path) -> tuple[str, str]:
    """Return (name, version) from the wheel's single .dist-info/METADATA."""
    with zipfile.ZipFile(wheel_path) as archive:
        metadata_members = [
            member
            for member in archive.namelist()
            if member.endswith(".dist-info/METADATA") and member.count("/") == 1
        ]
        if len(metadata_members) != 1:
            raise SystemExit(
                f"expected exactly one .dist-info/METADATA in {wheel_path.name}, "
                f"found {len(metadata_members)}"
            )
        raw = archive.read(metadata_members[0]).decode("utf-8")
    parsed = email.parser.Parser().parsestr(raw)
    name = parsed.get("Name")
    version = parsed.get("Version")
    if not name or not version:
        raise SystemExit(f"wheel METADATA is missing Name or Version in {wheel_path.name}")
    return name, version


def sha256_of(path: Path) -> str:
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
    wheel_path = Path(argv[2])

    wheel_name, wheel_version = wheel_identity(wheel_path)
    wheel_digest = sha256_of(wheel_path)

    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    component = sbom.get("metadata", {}).get("component")
    if component is None:
        print(
            "SBOM has no metadata.component root; generate it with "
            "cyclonedx-py ... --pyproject pyproject.toml",
            file=sys.stderr,
        )
        return 65

    sbom_name = component.get("name", "")
    sbom_version = component.get("version", "")
    if canonical_name(sbom_name) != canonical_name(wheel_name):
        print(
            f"refusing to bind: SBOM root name {sbom_name!r} does not match "
            f"wheel METADATA name {wheel_name!r}",
            file=sys.stderr,
        )
        return 66
    if sbom_version != wheel_version:
        print(
            f"refusing to bind: SBOM root version {sbom_version!r} does not match "
            f"wheel METADATA version {wheel_version!r}",
            file=sys.stderr,
        )
        return 67

    # Digest binding is append-or-confirm, never repair:
    #   - no existing SHA-256          -> bind the exact wheel digest
    #   - one equal SHA-256            -> accept and preserve it
    #   - one conflicting SHA-256      -> fail closed, SBOM left unchanged
    #   - multiple SHA-256 entries     -> fail closed, SBOM left unchanged
    # Unrelated non-SHA-256 hash entries are always preserved.
    hashes = component.get("hashes", [])
    sha256_entries = [entry for entry in hashes if str(entry.get("alg", "")).upper() == "SHA-256"]
    if len(sha256_entries) > 1:
        print(
            f"refusing to bind: root component already carries "
            f"{len(sha256_entries)} SHA-256 hashes; expected at most one",
            file=sys.stderr,
        )
        return 68
    if len(sha256_entries) == 1:
        existing = str(sha256_entries[0].get("content", "")).lower()
        if existing != wheel_digest:
            print(
                f"refusing to bind: root component already carries SHA-256 "
                f"{existing or '<empty>'}, which conflicts with "
                f"SHA-256({wheel_path.name}) = {wheel_digest}",
                file=sys.stderr,
            )
            return 69
        # Equal digest: accept and preserve the existing entry verbatim.
    else:
        component["hashes"] = [*hashes, {"alg": "SHA-256", "content": wheel_digest}]
    properties = [
        prop
        for prop in component.get("properties", [])
        if prop.get("name") != WHEEL_FILENAME_PROPERTY
    ]
    properties.append({"name": WHEEL_FILENAME_PROPERTY, "value": wheel_path.name})
    component["properties"] = properties

    sbom_path.write_text(json.dumps(sbom, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"bound SHA-256({wheel_path.name}) = {wheel_digest} into {sbom_path.name} root component")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
