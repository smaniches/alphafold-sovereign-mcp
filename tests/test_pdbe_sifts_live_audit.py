"""Offline contract tests: fabricated records, never biological observations."""
import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "scripts" / "validate_pdbe_sifts_live.py"
spec = importlib.util.spec_from_file_location("sifts_audit", path)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

SIFTS = b'''<entry><entity type="protein" entityId="A"><segment><listResidue>
<residue dbResNum="79" dbResName="TRP">
<crossRefDb dbSource="PDB" dbResNum="495" dbResName="TRP" dbChainId="M"/>
<crossRefDb dbSource="UniProt" dbAccessionId="Q8VH51" dbResNum="495" dbResName="W"/>
</residue></listResidue></segment></entity></entry>'''

CLAIM = {"pdb_id": "5cxt", "chain": "A", "entity_id": 1,
         "label_residue": 79, "author_residue": 495}
LISTING = {"5cxt": [{"entity_id": 1, "chains": [{
    "struct_asym_id": "A", "chain_id": "M", "residues": [
        {"residue_number": 79, "author_residue_number": 495,
         "residue_name": "TRP", "observed_ratio": 1.0}
    ]}]}]}


class Contract(unittest.TestCase):
    def test_exact_match(self):
        mapped = audit.parse_sifts(SIFTS)
        self.assertEqual(audit.check_structure(CLAIM, mapped, LISTING)["status"], "PASS")

    def test_wrong_coordinate_or_chain_fails_closed(self):
        mapped = audit.parse_sifts(SIFTS)
        for bad in ({"chain": "B"}, {"label_residue": 80},
                    {"author_residue": 496}):
            result = audit.check_structure({**CLAIM, **bad}, mapped, LISTING)
            self.assertNotEqual(result["status"], "PASS")

    def test_unobserved_and_insertion_code(self):
        mapped = audit.parse_sifts(SIFTS)
        residue = LISTING["5cxt"][0]["chains"][0]["residues"][0]
        for variant, status in (({"observed_ratio": 0}, "CONFLICT"),
                                ({"author_insertion_code": "A"}, "UNKNOWN")):
            listing = {"5cxt": [{"entity_id": 1, "chains": [
                {**LISTING["5cxt"][0]["chains"][0],
                 "residues": [{**residue, **variant}]}]}]}
            self.assertEqual(audit.check_structure(CLAIM, mapped, listing)["status"], status)

    def test_sequence_identity(self):
        sequence = "A" * 494 + "W" + "A" * 5
        payload = {"primaryAccession": "Q8VH51", "sequence": {"value": sequence, "version": 2}}
        self.assertEqual(audit.check_sequence(payload)["status"], "PASS")
        payload["sequence"]["value"] = "A" * 500
        self.assertEqual(audit.check_sequence(payload)["status"], "CONFLICT")

    def test_publications_not_counted_as_independent_rows(self):
        item = {"uniprotAccession": "Q8VH51", "uniprotResidue": 495,
                "pdbChain": "A", "entityId": 1,
                "pdbResidue": 79, "authorResidueNumber": 495,
                "pubmedId": 27050129}
        response = {"Q8VH51": {"dataType": "ANNOTATIONS", "uniprotResidue": 495,
                    "data": [{"pdbId": "5cxt", "providerList": [{
                        "provider": "IUCr", "residueList": [{
                            "indexType": "PDB", "additionalData": [item] * 203}]}]}]}}
        out = audit.parse_annotations(response)
        self.assertEqual(out["total_rows"], 203)
        self.assertEqual(out["unique_publications"], ["27050129"])
        self.assertEqual(out["unique_structural_claims"], 1)

    def test_unavailable_never_passes(self):
        self.assertEqual(audit.combine("PASS", "UNKNOWN"), "UNKNOWN")
        self.assertEqual(audit.combine("PASS", "CONFLICT"), "CONFLICT")
        self.assertEqual(audit.check_structure(CLAIM, None, LISTING)["status"], "UNKNOWN")
        self.assertEqual(audit.check_sequence(None)["status"], "UNKNOWN")
        self.assertEqual(audit.parse_annotations(None)["status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
