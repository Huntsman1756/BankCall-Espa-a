"""G1-C classification tests: fail-closed semantics over synthetic fingerprints."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "g1"))
from taxonomy_classify import classify_concepts, summarize, CATEGORIES


def fp(qname, **over):
    base = {
        "qname": qname,
        "namespace": qname.split(":")[0],
        "localname": qname.split(":")[1],
        "type": "xbrli:monetaryItemType",
        "substitutionGroup": "xbrli:item",
        "abstract": False,
        "nillable": True,
        "periodType": "instant",
        "balance": "debit",
        "labels": [{"role": "http://www.xbrl.org/2003/role/label",
                    "lang": "es", "text": "Concepto"}],
        "references": [],
    }
    base.update(over)
    return base


class TestClassify(unittest.TestCase):
    def test_exact_equivalent(self):
        a = {"ns:A": fp("ns:A")}
        b = {"ns:A": fp("ns:A")}
        out = classify_concepts(a, b)
        self.assertEqual(out["ns:A"]["classification"], "EXACT_EQUIVALENT")

    def test_structurally_changed_type(self):
        a = {"ns:A": fp("ns:A")}
        b = {"ns:A": fp("ns:A", type="xbrli:stringItemType")}
        out = classify_concepts(a, b)
        self.assertEqual(out["ns:A"]["classification"], "STRUCTURALLY_CHANGED")
        self.assertIn("type", out["ns:A"]["changed_fields"])

    def test_structurally_changed_balance(self):
        a = {"ns:A": fp("ns:A")}
        b = {"ns:A": fp("ns:A", balance="credit")}
        out = classify_concepts(a, b)
        self.assertEqual(out["ns:A"]["classification"], "STRUCTURALLY_CHANGED")

    def test_label_change_is_not_silent(self):
        a = {"ns:A": fp("ns:A")}
        b = {"ns:A": fp("ns:A", labels=[{"role": "http://www.xbrl.org/2003/role/label",
                                       "lang": "es", "text": "Otro texto"}])}
        out = classify_concepts(a, b)
        self.assertEqual(out["ns:A"]["classification"], "STRUCTURALLY_CHANGED")
        self.assertIn("labels", out["ns:A"]["changed_fields"])

    def test_new_and_removed(self):
        a = {"ns:A": fp("ns:A")}
        b = {"ns:B": fp("ns:B", labels=[{"role": "r", "lang": "es", "text": "Diferente"}],
                      type="xbrli:stringItemType")}
        out = classify_concepts(a, b)
        self.assertEqual(out["ns:A"]["classification"], "REMOVED")
        self.assertEqual(out["ns:B"]["classification"], "NEW")

    def test_renamed_identical_structure_positive(self):
        old = fp("ns:Antiguo")
        new = fp("ns:Nuevo")          # identical fingerprint modulo identity
        out = classify_concepts({"ns:Antiguo": old}, {"ns:Nuevo": new})
        self.assertEqual(out["ns:Antiguo"]["classification"], "RENAMED_EQUIVALENT")
        self.assertEqual(out["ns:Antiguo"]["to_qname"], "ns:Nuevo")

    def test_ambiguous_candidate_fails_closed(self):
        old = fp("ns:Antiguo")
        n1 = fp("ns:N1")
        n2 = fp("ns:N2")              # two identical candidates
        out = classify_concepts({"ns:Antiguo": old}, {"ns:N1": n1, "ns:N2": n2})
        self.assertEqual(out["ns:Antiguo"]["classification"], "NOT_COMPARABLE")
        self.assertEqual(sorted(out["ns:Antiguo"]["candidates"]), ["ns:N1", "ns:N2"])
        self.assertEqual(out["ns:N1"]["classification"], "NOT_COMPARABLE")
        self.assertEqual(out["ns:N2"]["classification"], "NOT_COMPARABLE")

    def test_similar_label_is_not_rename_evidence(self):
        # same label text but different structure -> never RENAMED
        old = fp("ns:Viejo", type="xbrli:monetaryItemType", periodType="instant")
        new = fp("ns:Nuevo", type="xbrli:stringItemType", periodType="duration")
        out = classify_concepts({"ns:Viejo": old}, {"ns:Nuevo": new})
        self.assertEqual(out["ns:Viejo"]["classification"], "REMOVED")
        self.assertEqual(out["ns:Nuevo"]["classification"], "NEW")

    def test_versioning_rename_evidence(self):
        old = fp("ns:Viejo")
        new = fp("ns:Nuevo")
        out = classify_concepts({"ns:Viejo": old}, {"ns:Nuevo": new},
                                renames={"ns:Viejo": "ns:Nuevo"})
        self.assertEqual(out["ns:Viejo"]["classification"], "RENAMED_EQUIVALENT")

    def test_namespace_rename_via_arelle_evidence(self):
        ns1 = ("http://www.bde.es/xbrl/fws/publicos/circ-4-2017/"
               "2018-01-01/mod/ps_in1")
        ns2 = ("http://www.bde.es/xbrl/fws/publicos/circ-4-2017/"
               "2018-12-01/mod/ps_in1")
        q1, q2 = "{%s}Total" % ns1, "{%s}Total" % ns2
        out = classify_concepts({q1: fp(q1)}, {q2: fp(q2)},
                                ns_map={ns2: ns1},
                                ns_pairs={(ns1, ns2)})
        self.assertEqual(out[q1]["classification"], "RENAMED_EQUIVALENT")
        self.assertEqual(out[q1]["evidence"], "arelle_namespace_rename")
        self.assertEqual(out[q1]["from_qname"], q1)
        self.assertEqual(out[q1]["to_qname"], q2)

    def test_generation_stamp_without_arelle_evidence(self):
        # same equivalence but no namespaceRename event -> declared
        # normalization is the recorded evidence, not silence
        ns1 = ("http://www.bde.es/xbrl/fws/publicos/circ-4-2017/"
               "2018-01-01/mod/pi_in1")
        ns2 = ("http://www.bde.es/xbrl/fws/publicos/circ-4-2017/"
               "2018-12-01/mod/pi_in1")
        q1, q2 = "{%s}Total" % ns1, "{%s}Total" % ns2
        out = classify_concepts({q1: fp(q1)}, {q2: fp(q2)})
        self.assertEqual(out[q1]["classification"], "RENAMED_EQUIVALENT")
        self.assertEqual(out[q1]["evidence"],
                         "declared_generation_stamp_normalization")

    def test_genstamp_rename_with_structural_change(self):
        ns1 = ("http://www.bde.es/xbrl/fws/publicos/circ-4-2017/"
               "2018-01-01/mod/pi_in1")
        ns2 = ("http://www.bde.es/xbrl/fws/publicos/circ-4-2017/"
               "2018-12-01/mod/pi_in1")
        q1, q2 = "{%s}Total" % ns1, "{%s}Total" % ns2
        out = classify_concepts({q1: fp(q1)},
                                {q2: fp(q2, type="xbrli:stringItemType")})
        self.assertEqual(out[q1]["classification"], "STRUCTURALLY_CHANGED")
        self.assertIn("type", out[q1]["changed_fields"])

    def test_no_unknown_promoted(self):
        out = classify_concepts({"ns:A": fp("ns:A")}, {})
        for v in out.values():
            self.assertIn(v["classification"], CATEGORIES)

    def test_summary_counts(self):
        a = {"ns:A": fp("ns:A"), "ns:B": fp("ns:B")}
        b = {"ns:A": fp("ns:A"), "ns:C": fp("ns:C", type="xbrli:stringItemType")}
        s = summarize(classify_concepts(a, b))
        self.assertEqual(s["EXACT_EQUIVALENT"], 1)
        self.assertEqual(s["REMOVED"], 1)
        self.assertEqual(s["NEW"], 1)


if __name__ == "__main__":
    unittest.main()
