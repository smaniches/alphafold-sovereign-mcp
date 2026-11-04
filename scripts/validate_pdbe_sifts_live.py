#!/usr/bin/env python3
"""Read-only, evidence-bound audit. UNKNOWN is never promoted to PASS."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ACCESSION = "Q8VH51"
POSITION = 495
AMINO_ACID = "W"
PDB = "5cxt"
HOSTS = {"rest.uniprot.org", "www.ebi.ac.uk", "ftp.ebi.ac.uk"}
AA3 = {"TRP": "W"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def combine(*statuses):
    if "CONFLICT" in statuses:
        return "CONFLICT"
    if not statuses or any(s != "PASS" for s in statuses):
        return "UNKNOWN"
    return "PASS"


def retrieve(label, url, provenance):
    item = {"url": url, "retrieved_utc": now(), "status": "UNKNOWN"}
    provenance[label] = item
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS or parts.username:
        item["error"] = "disallowed_url"
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Sovereign-MCP-readonly-evidence-audit/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            redirected = urlsplit(response.geturl())
            if redirected.scheme != "https" or redirected.hostname not in HOSTS:
                item["error"] = "disallowed_redirect"
                return None
            content = response.read(16_000_001)
            item["http_status"] = response.status
            if len(content) > 16_000_000:
                item["error"] = "oversized"
                return None
        item.update(status="RETRIEVED", sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))
        return content
    except Exception as error:
        item["error"] = type(error).__name__ + ": " + str(error)[:150]
        return None


def get_json(label, url, provenance):
    data = retrieve(label, url, provenance)
    if data is None:
        return None
    try:
        return json.loads(data)
    except (ValueError, UnicodeError):
        provenance[label]["status"] = "UNKNOWN"
        provenance[label]["error"] = "invalid_json"
        return None


def check_sequence(data):
    if not isinstance(data, dict):
        return {"status": "UNKNOWN", "reason": "missing_uniprot_record"}
    if data.get("primaryAccession") != ACCESSION:
        return {"status": "CONFLICT", "reason": "wrong_accession"}
    sequence_data = data.get("sequence")
    if not isinstance(sequence_data, dict) or not isinstance(sequence_data.get("value"), str):
        return {"status": "UNKNOWN", "reason": "missing_sequence"}
    sequence = sequence_data["value"]
    if len(sequence) < POSITION:
        return {"status": "CONFLICT", "reason": "sequence_too_short"}
    residue = sequence[POSITION - 1]
    return {
        "status": "PASS" if residue == AMINO_ACID else "CONFLICT",
        "residue": residue,
        "sequence_version": sequence_data.get("version"),
        "sequence_length": len(sequence),
        "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
    }


def parse_annotations(data):
    result = {"status": "UNKNOWN", "rows": [], "excluded_mismatches": 0}
    if not isinstance(data, dict):
        result["reason"] = "unavailable_annotation_source"
        return result
    if not data:
        result["reason"] = "empty_source_not_biological_absence"
        return result
    root = data.get(ACCESSION)
    if not isinstance(root, dict) or root.get("dataType") != "ANNOTATIONS":
        result["reason"] = "invalid_annotation_root"
        return result
    if "uniprotResidue" in root and str(root["uniprotResidue"]) != str(POSITION):
        result["status"] = "CONFLICT"
        result["reason"] = "wrong_root_residue"
        return result
    try:
        for group in root["data"]:
            pdb = group["pdbId"].lower()
            if not re.fullmatch(r"[0-9][a-z0-9]{3}", pdb):
                raise ValueError("bad_pdb")
            for provider in group["providerList"]:
                for site in provider["residueList"]:
                    if site["indexType"] != "PDB":
                        raise ValueError("non_pdb_index")
                    for ann in site["additionalData"]:
                        if ann.get("uniprotAccession") != ACCESSION or str(ann.get("uniprotResidue")) != str(POSITION):
                            result["excluded_mismatches"] += 1
                            continue
                        if not (isinstance(ann.get("pdbChain"), str) and
                                all(type(ann.get(k)) is int and ann[k] > 0
                                    for k in ("entityId", "pdbResidue", "authorResidueNumber"))):
                            raise ValueError("bad_annotation_identity")
                        result["rows"].append({
                            "pdb_id": pdb, "chain": ann["pdbChain"],
                            "entity_id": ann["entityId"],
                            "label_residue": ann["pdbResidue"],
                            "author_residue": ann["authorResidueNumber"],
                            "pmid": str(ann.get("pubmedId") or ""),
                            "doi": ann.get("doi"),
                        })
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        result["rows"] = []
        result["reason"] = "malformed_annotation_schema:" + str(exc)[:60]
        return result
    result["total_rows"] = len(result["rows"])
    result["unique_publications"] = sorted({r["pmid"] for r in result["rows"] if r["pmid"]})
    result["unique_pdb_entries"] = sorted({r["pdb_id"] for r in result["rows"]})
    result["unique_structural_claims"] = len({(r["pdb_id"], r["chain"], r["entity_id"],
                                                r["label_residue"], r["author_residue"])
                                               for r in result["rows"]})
    if result["rows"]:
        result["status"] = "PASS"  # source annotation schema and identity only
    else:
        result["reason"] = "no_matching_source_annotations"
    return result


def local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_sifts(data):
    if data is None:
        return None
    try:
        body = gzip.decompress(data) if data[:2] == b"\\x1f\\x8b" else data
        root = ET.fromstring(body)
    except (OSError, ValueError, ET.ParseError):
        return None
    mapped = []
    for entity in root.iter():
        if local(entity.tag) != "entity" or entity.get("type") != "protein":
            continue
        for residue in entity.iter():
            if local(residue.tag) != "residue":
                continue
            cross = [c.attrib for c in residue if local(c.tag) == "crossRefDb"]
            matched = [c for c in cross if c.get("dbSource") == "UniProt" and
                       c.get("dbAccessionId") == ACCESSION and c.get("dbResNum") == str(POSITION)]
            if not matched:
                continue
            unobserved = any(local(c.tag) == "residueDetail" and
                             "notobserved" in "".join((c.text or "").lower().split()).replace("_", "")
                             for c in residue)
            for pdb in (c for c in cross if c.get("dbSource") == "PDB"):
                mapped.append({
                    "chain": entity.get("entityId"),
                    "label_residue": residue.get("dbResNum"),
                    "author_chain": pdb.get("dbChainId"),
                    "author_residue": pdb.get("dbResNum"),
                    "uniprot_aa": matched[0].get("dbResName"),
                    "pdb_aa": pdb.get("dbResName"),
                    "unobserved": unobserved,
                })
    return mapped


def check_structure(claim, sifts, listing):
    """Require exact chain, entity, label/author numbering and observed PDB identity."""
    if sifts is None or not isinstance(listing, dict):
        return {"status": "UNKNOWN", "reason": "missing_sifts_or_pdb"}
    candidates = [m for m in sifts if m["chain"] == claim["chain"] and
                  m["label_residue"] == str(claim["label_residue"])]
    if not candidates:
        return {"status": "UNKNOWN", "reason": "no_independent_sifts_correspondence"}
    if len(candidates) != 1:
        return {"status": "UNKNOWN", "reason": "ambiguous_sifts_correspondence"}
    m = candidates[0]
    if m["author_residue"] != str(claim["author_residue"]):
        return {"status": "CONFLICT", "reason": "author_number_disagrees"}
    if m["unobserved"]:
        return {"status": "CONFLICT", "reason": "sifts_unobserved"}
    if m["uniprot_aa"] != AMINO_ACID or AA3.get(m["pdb_aa"]) != AMINO_ACID:
        return {"status": "CONFLICT", "reason": "sifts_amino_acid_disagrees"}
    molecules = listing.get(claim["pdb_id"])
    if not isinstance(molecules, list):
        return {"status": "UNKNOWN", "reason": "pdb_entry_unavailable"}
    for mol in molecules:
        if mol.get("entity_id") != claim["entity_id"]:
            continue
        for chain in mol.get("chains", []):
            if chain.get("struct_asym_id") != claim["chain"]:
                continue
            if chain.get("chain_id") != m["author_chain"]:
                return {"status": "CONFLICT", "reason": "author_chain_disagrees"}
            for res in chain.get("residues", []):
                if res.get("residue_number") != claim["label_residue"]:
                    continue
                if res.get("author_residue_number") != claim["author_residue"]:
                    return {"status": "CONFLICT", "reason": "pdb_author_number_disagrees"}
                if res.get("author_insertion_code") not in (None, "", " "):
                    return {"status": "UNKNOWN", "reason": "insertion_code_not_attributed"}
                if AA3.get(res.get("residue_name")) != AMINO_ACID:
                    return {"status": "CONFLICT", "reason": "pdb_residue_name_disagrees"}
                ratio = res.get("observed_ratio")
                if not isinstance(ratio, (float, int)):
                    return {"status": "UNKNOWN", "reason": "missing_observed_ratio"}
                if ratio <= 0:
                    return {"status": "CONFLICT", "reason": "pdb_residue_unobserved"}
                return {"status": "PASS", "observed_ratio": ratio}
    return {"status": "UNKNOWN", "reason": "no_exact_pdb_listing_match"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = {}
    sequence = check_sequence(get_json("uniprot",
        f"https://rest.uniprot.org/uniprotkb/{ACCESSION}.json", sources))
    annotation = parse_annotations(get_json("annotations",
        f"https://www.ebi.ac.uk/pdbe/api/v2/uniprot/llm_annotations/summary/{ACCESSION}/{POSITION}", sources))
    unique = {(r["pdb_id"], r["chain"], r["entity_id"], r["label_residue"], r["author_residue"]): r
              for r in annotation["rows"]}
    claims = []
    for pdb_id in sorted({PDB, *(k[0] for k in unique)})[:10]:
        sifts = None
        for i, path in enumerate((f"xml/{pdb_id}.xml.gz",
                                  f"splitxml/{pdb_id[1:3]}/{pdb_id}.xml.gz")):
            sifts = parse_sifts(retrieve(f"sifts_{pdb_id}_{i}",
                f"https://ftp.ebi.ac.uk/pub/databases/msd/sifts/{path}", sources))
            if sifts is not None:
                break
        listing = get_json(f"pdb_listing_{pdb_id}",
            f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/residue_listing/{pdb_id}", sources)
        for claim in unique.values():
            if claim["pdb_id"] == pdb_id:
                claims.append({"claim": claim, **check_structure(claim, sifts, listing)})
    structure = {"status": combine(*(c["status"] for c in claims)), "claims": claims}
    report = {
        "audit": "readonly-v1", "retrieved_utc": now(),
        "reference": {"uniprot": ACCESSION, "position": POSITION, "aa": AMINO_ACID},
        "sources": sources, "sequence_check": sequence,
        "annotation_check": {k: v for k, v in annotation.items() if k != "rows"},
        "structure_check": structure,
        "overall": combine(sequence["status"], annotation["status"], structure["status"]) if len({PDB, *(k[0] for k in unique)}) <= 10 else "UNKNOWN",
        "not_validated": ["HGVS transcript/isoform identity", "primary-paper statement review",
                          "published MCP interface live output", "clinical significance"],
        "terms": "Consult upstream provider attribution/reuse conditions; raw evidence is not redistributed",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"overall": report["overall"],
                      "sequence": sequence["status"],
                      "annotations": annotation["status"],
                      "structure": structure["status"],
                      "sources": {k: v["status"] for k, v in sources.items()}}, indent=2))
    return 1 if report["overall"] == "CONFLICT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
