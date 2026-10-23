#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only disease ID audit against a hash-pinned MONDO OBO release."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def catalog(path: Path) -> dict[str, dict[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "COMMON_DISEASE_ROOTS":
                return ast.literal_eval(node.value)
    raise ValueError("Missing COMMON_DISEASE_ROOTS")


def ontology(path: Path) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    term: dict[str, object] = {}
    inside = False
    with path.open(encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                if inside and "id" in term:
                    records[str(term["id"])] = term
                term = {"synonyms": [], "obsolete": False}
                inside = line == "[Term]"
                continue
            if not inside:
                continue
            if line.startswith("id: "):
                term["id"] = line[4:]
            elif line.startswith("name: "):
                term["name"] = line[6:]
            elif line == "is_obsolete: true":
                term["obsolete"] = True
            elif line.startswith("synonym: "):
                match = re.match(
                    r'^synonym: "((?:[^"\\]|\\.)*)"\s+(EXACT|BROAD|NARROW|RELATED)\b',
                    line,
                )
                if match:
                    term["synonyms"].append((match.group(1), match.group(2)))
    if inside and "id" in term:
        records[str(term["id"])] = term
    return records


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold().replace("_", " ")).strip()


def exact_label_suggestions(
    name: str, records: dict[str, dict[str, object]]
) -> list[dict[str, str]]:
    """Find candidate current ontology IDs; never auto-select a disease."""
    requested = normalize(name)
    matched: list[dict[str, str]] = []
    for identifier, term in records.items():
        if term["obsolete"]:
            continue
        label = str(term.get("name", ""))
        aliases = {
            normalize(str(synonym))
            for synonym, kind in term["synonyms"]
            if kind == "EXACT"
        }
        if requested == normalize(label) or requested in aliases:
            matched.append({"mondo_id": identifier, "preferred_label": label})
    return sorted(matched, key=lambda row: row["mondo_id"])[:12]


def inspect(source: Path, obo: Path) -> dict[str, object]:
    records = ontology(obo)
    rows = []
    for category, values in catalog(source).items():
        for name, identifier in values.items():
            term = records.get(identifier)
            status = "NOT_FOUND" if term is None else "OBSOLETE" if term["obsolete"] else ""
            if term and not status:
                label = normalize(str(term.get("name", "")))
                requested = normalize(name)
                exact = {normalize(str(s)) for s, kind in term["synonyms"] if kind == "EXACT"}
                if requested == label:
                    status = "PREFERRED_LABEL"
                elif requested in exact:
                    status = "EXACT_SYNONYM"
                else:
                    status = "REVIEW_IDENTITY_OR_SCOPE"
            rows.append({
                "category": category, "requested_name": name,
                "mondo_id": identifier,
                "preferred_label": term.get("name") if term else None,
                "status": status,
                "exact_label_alternatives": (
                    exact_label_suggestions(name, records)
                    if status not in {"PREFERRED_LABEL", "EXACT_SYNONYM"}
                    else []
                ),
            })
    requires_review = sum(
        row["status"] not in {"PREFERRED_LABEL", "EXACT_SYNONYM"} for row in rows
    )
    return {
        "source_sha256": sha256(source), "ontology_sha256": sha256(obo),
        "records_checked": len(rows), "requires_review": requires_review,
        "note": "Lexical comparison is not independent biological validation.",
        "entries": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--obo", required=True, type=Path)
    parser.add_argument("--expected-hash", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if sha256(args.obo) != args.expected_hash.lower():
        parser.error("Frozen MONDO ontology SHA256 mismatch")
    result = inspect(args.source, args.obo)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Records checked:", result["records_checked"])
    print("Requires scientific review:", result["requires_review"])
    for row in result["entries"]:
        print(row["status"], row["mondo_id"], row["requested_name"], row["preferred_label"])
        if row["exact_label_alternatives"]:
            print("  EXACT_LABEL_CANDIDATES", row["exact_label_alternatives"])


if __name__ == "__main__":
    main()
