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
    code_ownership_at,
    name_comparison,
    parse_catalog_label,
    parse_sifdifu_key,
    registry_observation_mapping,
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

    def _candidate(
        self,
        element_id: int,
        lei: str | None = None,
        history: list[dict] | None = None,
        role_end: str | None = None,
    ) -> dict:
        role = {"nombreRol": "Banco", "fechaAltaRol": "1990-01-01"}
        if role_end:
            role["fechaBajaRol"] = role_end
        return {
            "candidate_id": "registry:%s" % element_id,
            "idelemento": element_id,
            "codigoBE": "0073",
            "official_name": "OPEN BANK, S.A.",
            "documents": (
                [{"tipoDocumento": "LEI", "numeroDocumento": lei}] if lei else []
            ),
            "roles": [role],
            "successors": [],
            "code_history": history,
        }

    def test_code_ownership_interval_ends_are_inclusive(self):
        candidate = self._candidate(
            1, history=[{"codigoBE": "0073", "fechaInicio": "2000-01-01", "fechaFin": "2020-12-31"}]
        )
        self.assertIs(code_ownership_at(candidate, "0073", date(2020, 12, 31)), True)
        self.assertIs(code_ownership_at(candidate, "0073", date(2021, 1, 1)), False)
        self.assertIs(code_ownership_at(candidate, "0049", date(2010, 6, 30)), False)
        no_history = self._candidate(2)
        self.assertIsNone(code_ownership_at(no_history, "0073", date(2010, 6, 30)))

    def test_history_resolves_overlapping_active_candidates(self):
        old_holder = self._candidate(
            33119,
            lei="95980020140006024944",
            history=[{"codigoBE": "0073", "fechaInicio": "1899-06-30", "fechaFin": "2026-05-04"}],
            role_end="2026-05-04",
        )
        new_holder = self._candidate(
            33408,
            lei="5493000LM0MZ4JPMGM90",
            history=[{"codigoBE": "0073", "fechaInicio": "2026-05-04"}],
        )
        status, candidate, *_ = registry_observation_mapping(
            [old_holder, new_holder], "0073", date(2021, 3, 31)
        )
        self.assertEqual(status, "PROVEN")
        self.assertEqual(candidate["candidate_id"], "registry:33119")
        status, candidate, *_ = registry_observation_mapping(
            [old_holder, new_holder], "0073", date(2026, 6, 30)
        )
        self.assertEqual(candidate["candidate_id"], "registry:33408")

    def test_label_lei_disambiguates_transfer_boundary_day(self):
        old_holder = self._candidate(
            1,
            lei="95980020140006024944",
            history=[{"codigoBE": "0073", "fechaInicio": "1899-06-30", "fechaFin": "2026-05-04"}],
        )
        new_holder = self._candidate(
            2,
            lei="5493000LM0MZ4JPMGM90",
            history=[{"codigoBE": "0073", "fechaInicio": "2026-05-04"}],
        )
        status, candidate, _, _, basis, *_ = registry_observation_mapping(
            [old_holder, new_holder], "0073", date(2026, 5, 4), "5493000LM0MZ4JPMGM90"
        )
        self.assertEqual(status, "PROVEN")
        self.assertEqual(basis, "CODE_OWNERSHIP_HISTORY_LEI_DISAMBIGUATED")
        self.assertEqual(candidate["candidate_id"], "registry:2")
        status, candidate, *_ = registry_observation_mapping(
            [old_holder, new_holder], "0073", date(2026, 5, 4)
        )
        self.assertEqual(status, "UNKNOWN")

    def test_conflicting_label_lei_stays_unknown(self):
        holder = self._candidate(
            1,
            lei="5493000LM0MZ4JPMGM90",
            history=[{"codigoBE": "0073", "fechaInicio": "2000-01-01"}],
        )
        status, candidate, _, _, _, crosscheck, _ = registry_observation_mapping(
            [holder], "0073", date(2021, 3, 31), "95980020140006024944"
        )
        self.assertEqual(status, "UNKNOWN")
        self.assertEqual(crosscheck, "MISMATCH")

    def test_no_code_holder_with_complete_history_is_unknown(self):
        expired = self._candidate(
            1, history=[{"codigoBE": "0073", "fechaInicio": "1900-01-01", "fechaFin": "2010-01-01"}]
        )
        status, candidate, *_ = registry_observation_mapping(
            [expired], "0073", date(2021, 3, 31)
        )
        self.assertEqual(status, "UNKNOWN")
        self.assertIsNone(candidate)

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
