import sys
import unittest
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "g1"
sys.path.insert(0, str(SCRIPT_DIR))

from identity_lifecycle import (  # noqa: E402
    IdentityLifecycleError,
    build_observations,
    candidate_lifecycle_status,
    name_comparison,
    parse_catalog_label,
    parse_sifdifu_key,
    registry_status_for_period,
)


class IdentityLifecycleHelpersTest(unittest.TestCase):
    def test_unresolved_period_mapping_marks_key_ambiguous(self):
        periods = [
            {
                "id": "202012",
                "states": [
                    {
                        "id": "2701",
                        "text": "Balance individual público. Activo",
                        "entities": [
                            {"id": "0073(0002)", "text": "0073 - OPEN BANK, S.A."}
                        ],
                    }
                ],
            }
        ]
        active_candidates = {
            "0073": [
                {
                    "candidate_id": "registry:one",
                    "official_name": "OPEN BANK, S.A.",
                    "codigoBE": "0073",
                    "detail_source_id": "registry-detail:one",
                    "roles": [{"fechaAltaRol": "1988-08-19"}],
                    "successors": [],
                },
                {
                    "candidate_id": "registry:two",
                    "official_name": "OPEN BANK, S.A.",
                    "codigoBE": "0073",
                    "detail_source_id": "registry-detail:two",
                    "roles": [{"fechaAltaRol": "1988-08-19"}],
                    "successors": [],
                },
            ]
        }

        observations, identity_keys, all_codes = build_observations(
            periods, active_candidates
        )

        self.assertEqual(all_codes, {"0073"})
        self.assertEqual(observations[0]["registry_mapping_status"], "UNKNOWN")
        self.assertEqual(identity_keys[0]["unresolved_observation_count"], 1)
        self.assertEqual(
            identity_keys[0]["candidate_ids_considered"],
            ["registry:one", "registry:two"],
        )
        self.assertEqual(
            identity_keys[0]["temporal_stability"], "CHANGED_OR_AMBIGUOUS"
        )

    def test_key_parser_preserves_both_components(self):
        self.assertEqual(
            parse_sifdifu_key("0049(0002)"),
            {
                "raw_sifdifu_key": "0049(0002)",
                "bank_code": "0049",
                "component_or_suffix": "0002",
            },
        )

    def test_key_parser_rejects_malformed_key(self):
        with self.assertRaises(IdentityLifecycleError):
            parse_sifdifu_key("0049(2)")

    def test_catalog_label_extracts_lei_and_reporting_role(self):
        result = parse_catalog_label(
            "0049(0000)",
            "0049 - BANCO SANTANDER, S.A. - 5493006QMFDDMYWIAM13 (Grupo) ",
        )
        self.assertEqual(result["bank_code"], "0049")
        self.assertEqual(result["component_or_suffix"], "0000")
        self.assertEqual(result["catalog_name"], "BANCO SANTANDER, S.A.")
        self.assertEqual(result["catalog_lei"], "5493006QMFDDMYWIAM13")
        self.assertEqual(result["reporting_role_qualifier"], "GRUPO")

    def test_registry_status_distinguishes_active_and_inactive(self):
        active = {
            "candidate_id": "registry:1",
            "roles": [{"fechaAltaRol": "2011-01-01", "fechaBajaRol": None}],
        }
        inactive = {
            "candidate_id": "registry:2",
            "roles": [{"fechaAltaRol": "2011-01-01", "fechaBajaRol": "2021-03-26"}],
        }
        self.assertEqual(candidate_lifecycle_status(active, date(2020, 12, 31)), "active")
        self.assertEqual(candidate_lifecycle_status(inactive, date(2021, 9, 30)), "inactive")
        status, candidate, _ = registry_status_for_period([active, inactive], date(2021, 9, 30))
        self.assertEqual(status, "active")
        self.assertEqual(candidate["candidate_id"], "registry:1")

    def test_name_comparison_does_not_claim_unknown_equivalence(self):
        self.assertEqual(
            name_comparison("BANKIA, S.A.", "BANKIA, S.A "),
            "EXACT_NORMALIZED",
        )
        self.assertEqual(
            name_comparison("OLD ENTITY", "UNRELATED ENTITY"),
            "DIFFERENT_OFFICIAL_LABEL",
        )


if __name__ == "__main__":
    unittest.main()
