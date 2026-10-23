#!/usr/bin/env python3
"""Generate and verify an SPDX 2.3 inventory of the installed release wheel.

The exact wheel-bound CycloneDX document is the common inventory source.
An independent installed-environment inventory is required at release time.
"""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def identity(component: dict) -> tuple[str, str]:
    name, version = component.get("name"), component.get("version")
    require(isinstance(name, str) and bool(name), "component lacks name")
    require(isinstance(version, str) and bool(version), "component lacks version")
    return normalized(name), version


def inventory(cdx: dict) -> tuple[dict[str, dict], str, set[tuple[str, str]]]:
    require(cdx.get("bomFormat") == "CycloneDX", "invalid CycloneDX format")
    root = cdx.get("metadata", {}).get("component")
    require(isinstance(root, dict), "CycloneDX root missing")
    components = cdx.get("components")
    require(isinstance(components, list) and bool(components), "empty inventory")
    refs: dict[str, dict] = {}
    identities: set[tuple[str, str]] = set()
    for component in [root, *components]:
        require(isinstance(component, dict), "invalid component")
        key, ref = identity(component), component.get("bom-ref")
        require(isinstance(ref, str) and bool(ref), "missing bom-ref")
        require(ref not in refs, f"duplicate bom-ref: {ref}")
        require(key not in identities, f"duplicate package identity: {key}")
        refs[ref] = component
        identities.add(key)
    return refs, root["bom-ref"], identities


def dependency_edges(cdx: dict, refs: dict[str, dict], root_ref: str) -> set[tuple[str, str]]:
    nodes = cdx.get("dependencies")
    require(isinstance(nodes, list) and bool(nodes), "missing dependency graph")
    seen: set[str] = set()
    edges: set[tuple[str, str]] = set()
    for node in nodes:
        require(isinstance(node, dict), "invalid dependency node")
        parent = node.get("ref")
        require(parent in refs and parent not in seen, "invalid dependency parent")
        seen.add(parent)
        children = node.get("dependsOn", [])
        require(isinstance(children, list), "dependsOn must be a list")
        require(len(children) == len(set(children)), "duplicate dependency edge")
        for child in children:
            require(child in refs and child != parent, "invalid dependency child")
            edges.add((parent, child))
    require(bool(edges), "empty dependency relationships")
    require(any(parent == root_ref for parent, _ in edges), "root has no dependencies")
    return edges


def wheel_identity(target: Path) -> tuple[tuple[str, str], str]:
    wheels = sorted(target.glob("*.whl")) if target.is_dir() else [target]
    require(len(wheels) == 1 and wheels[0].is_file(), "expected one wheel")
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        members = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA") and name.count("/") == 1
        ]
        require(len(members) == 1, "invalid wheel METADATA")
        metadata = email.parser.Parser().parsestr(archive.read(members[0]).decode("utf-8"))
    require(metadata.get("Name") and metadata.get("Version"), "invalid wheel identity")
    name_version = normalized(metadata["Name"]), metadata["Version"]
    parts = wheel.name.split("-")
    require(len(parts) >= 5, "invalid wheel filename")
    require(
        normalized(parts[0]) == name_version[0] and parts[1] == name_version[1].replace("-", "_"),
        "wheel filename / metadata mismatch",
    )
    digest = hashlib.sha256()
    with wheel.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return name_version, digest.hexdigest()


def installed_packages(environment: Path) -> set[tuple[str, str]]:
    python = environment / "bin" / "python"
    require(python.is_file(), f"missing environment interpreter: {python}")
    code = (
        "import importlib.metadata as m,json; "
        "print(json.dumps([(d.metadata['Name'],d.version) "
        "for d in m.distributions()]))"
    )
    run = subprocess.run([str(python), "-c", code], check=True, capture_output=True, text=True)
    pairs = json.loads(run.stdout)
    records = {(normalized(name), version) for name, version in pairs}
    require(len(records) == len(pairs), "duplicate installed distributions")
    return records


def root_digest(root: dict) -> str:
    matches = [h.get("content") for h in root.get("hashes", []) if h.get("alg") == "SHA-256"]
    require(len(matches) == 1, "root needs exactly one SHA-256")
    digest = matches[0]
    require(
        isinstance(digest, str) and re.fullmatch(r"[a-fA-F0-9]{64}", digest) is not None,
        "invalid wheel SHA-256",
    )
    return digest.lower()


def spdx_document(cdx: dict) -> dict:
    refs, root_ref, _ = inventory(cdx)
    edges = dependency_edges(cdx, refs, root_ref)
    root = refs[root_ref]
    digest = root_digest(root)
    ordered = [root_ref, *sorted(ref for ref in refs if ref != root_ref)]
    ids = {ref: f"SPDXRef-Package-{i:04d}" for i, ref in enumerate(ordered)}
    packages = []
    for ref in ordered:
        c = refs[ref]
        pkg = {
            "SPDXID": ids[ref],
            "name": c["name"],
            "versionInfo": c["version"],
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "copyrightText": "NOASSERTION",
        }
        if c.get("purl"):
            pkg["externalRefs"] = [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": c["purl"],
                }
            ]
        if ref == root_ref:
            pkg["checksums"] = [
                {
                    "algorithm": "SHA256",
                    "checksumValue": digest,
                }
            ]
        packages.append(pkg)
    relations = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": ids[root_ref],
        }
    ]
    relations.extend(
        {
            "spdxElementId": ids[parent],
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": ids[child],
        }
        for parent, child in sorted(edges)
    )
    timestamp = cdx.get("metadata", {}).get("timestamp", "1970-01-01T00:00:00Z")
    require(isinstance(timestamp, str) and bool(timestamp), "invalid timestamp")
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{root['name']} {root['version']} installed-wheel SBOM",
        "documentNamespace": (
            f"https://github.com/smaniches/alphafold-sovereign-mcp/spdx/{root['version']}/{digest}"
        ),
        "creationInfo": {
            "created": timestamp,
            "creators": ["Tool: release_spdx.py"],
        },
        "documentDescribes": [ids[root_ref]],
        "packages": packages,
        "relationships": relations,
    }


def verify(cdx: dict, spdx: dict, wheel: Path, environment: Path | None = None) -> None:
    refs, root_ref, identities = inventory(cdx)
    edges = dependency_edges(cdx, refs, root_ref)
    wheel_package, sha = wheel_identity(wheel)
    require(identity(refs[root_ref]) == wheel_package, "root/wheel identity mismatch")
    require(root_digest(refs[root_ref]) == sha, "CycloneDX wheel digest mismatch")
    require(
        spdx.get("spdxVersion") == "SPDX-2.3"
        and spdx.get("SPDXID") == "SPDXRef-DOCUMENT"
        and spdx.get("dataLicense") == "CC0-1.0",
        "invalid SPDX document header",
    )
    require(
        isinstance(spdx.get("creationInfo", {}).get("creators"), list)
        and bool(spdx["creationInfo"]["creators"]),
        "missing SPDX creator",
    )
    require(
        isinstance(spdx.get("documentNamespace"), str) and bool(spdx["documentNamespace"]),
        "missing SPDX namespace",
    )
    packages = spdx.get("packages")
    require(isinstance(packages, list) and bool(packages), "empty SPDX")
    by_id: dict[str, tuple[str, str]] = {}
    by_identity: dict[tuple[str, str], dict] = {}
    for pkg in packages:
        require(isinstance(pkg, dict), "invalid SPDX package")
        identifier = pkg.get("SPDXID")
        require(
            isinstance(identifier, str)
            and identifier.startswith("SPDXRef-Package-")
            and identifier not in by_id,
            "duplicate/invalid SPDX ID",
        )
        key = identity(
            {
                "name": pkg.get("name"),
                "version": pkg.get("versionInfo"),
            }
        )
        require(key not in by_identity, "duplicate SPDX package")
        require(
            pkg.get("filesAnalyzed") is False and pkg.get("downloadLocation") == "NOASSERTION",
            "invalid SPDX package properties",
        )
        by_id[identifier] = key
        by_identity[key] = pkg
    require(
        set(by_identity) == identities,
        f"SPDX inventory differs: {identities ^ set(by_identity)}",
    )
    root = by_identity[wheel_package]
    root_id = root["SPDXID"]
    require(spdx.get("documentDescribes") == [root_id], "wrong SPDX root")
    require(
        root.get("checksums")
        == [
            {
                "algorithm": "SHA256",
                "checksumValue": sha,
            }
        ],
        "SPDX root wheel hash mismatch",
    )
    relations = spdx.get("relationships")
    require(isinstance(relations, list), "SPDX missing relationships")
    seen_edges = set()
    descriptions = 0
    for rel in relations:
        require(isinstance(rel, dict), "invalid SPDX relationship")
        kind = rel.get("relationshipType")
        source, target = rel.get("spdxElementId"), rel.get("relatedSpdxElement")
        if kind == "DESCRIBES":
            require(
                source == "SPDXRef-DOCUMENT" and target == root_id,
                "incorrect document description",
            )
            descriptions += 1
        else:
            require(
                kind == "DEPENDS_ON" and source in by_id and target in by_id,
                "invalid SPDX dependency relationship",
            )
            edge = by_id[source], by_id[target]
            require(edge not in seen_edges, "duplicate SPDX edge")
            seen_edges.add(edge)
    require(descriptions == 1, "missing/duplicate SPDX root description")
    wanted = {(identity(refs[a]), identity(refs[b])) for a, b in edges}
    require(seen_edges == wanted, "SPDX dependency graph differs")
    if environment is not None:
        installed = installed_packages(environment)
        require(
            installed == identities,
            f"installed environment differs: {installed ^ identities}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["generate", "verify"])
    parser.add_argument("cyclonedx", type=Path)
    parser.add_argument("spdx", type=Path)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--environment", type=Path)
    args = parser.parse_args()
    try:
        cdx = json.loads(args.cyclonedx.read_text(encoding="utf-8"))
        if args.action == "generate":
            result = spdx_document(cdx)
            args.spdx.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        spdx = json.loads(args.spdx.read_text(encoding="utf-8"))
        verify(cdx, spdx, args.wheel, args.environment)
    except (
        ValueError,
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ) as error:
        print(f"SPDX release verification FAILED: {error}", file=sys.stderr)
        return 1
    print(f"SPDX verification PASS: {len(spdx['packages'])} packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
