import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "g1"
sys.path.insert(0, str(SCRIPT_DIR))

from validate_identity_model import evaluate_model  # noqa: E402


def _observation(
    raw_key: str,
    period_id: str,
    period_end: str,
    candidate_id: str | None,
    basis: str | None = "CODE_OWNERSHIP_HISTORY",
    holders: int = 1,
    status: str = "PROVEN",
    name: str = "ENTITY, S.A.",
) -> dict:
    return {
        "raw_sifdifu_key": raw_key,
        "bank_code": raw_key.split("(")[0],
        "period_id": period_id,
        "period_end": period_end,
        "registry_mapping_status": status,
        "registry_candidate_id": candidate_id,
        "registry_official_name": name if candidate_id else None,
        "mapping_basis": basis,
        "lei_crosscheck": "NOT_APPLICABLE_NO_LABEL_LEI",
        "ownership_classification": [
            {"candidate_id": candidate_id, "holds_code_at_period_end": True}
        ]
        * holders
        if candidate_id
        else [],
    }


def _entities(observations: list[dict], identity_keys: list[dict]) -> dict:
    return {
        "observations": observations,
        "identity_keys": identity_keys,
        "registry_candidates": [],
        "component_semantics": {
            c: {"classification": "X", "business_meaning_proven_by": ["proof"]}
            for c in ("0000", "0001", "0002")
        },
        "key_parser": {"unresolved_component_is_not_normalized": True},
        "checks": {"raw_key_preserved": True},
    }


class IdentityModelGatesTest(unittest.TestCase):
    def test_clean_single_entity_passes_core_gates(self):
        entities = _entities(
            [
                _observation("0049(0002)", "201803", "2018-03-31", "registry:1"),
                _observation("0049(0002)", "201809", "2018-09-30", "registry:1"),
            ],
            [
                {
                    "raw_sifdifu_key": "0049(0002)",
                    "bank_code": "0049",
                    "registry_candidate_ids": ["registry:1"],
                }
            ],
        )
        gates = evaluate_model(entities)["gates"]
        self.assertEqual(gates["ENTITY_MAPPING_UNIQUE_PER_PERIOD"], "PASS")
        self.assertEqual(gates["REPORTING_SLOT_TEMPORAL_OWNERSHIP_PROVEN"], "PASS")
        self.assertEqual(gates["LEGAL_ENTITY_IDENTITY_STABLE"], "PASS")
        self.assertEqual(gates["SCOPE_SEMANTICS_PROVEN"], "PASS")
        self.assertEqual(gates["CODE_TRANSFER_FAIL_CLOSED"], "PASS")

    def test_proven_observation_without_holder_fails_closed_gate(self):
        entities = _entities(
            [_observation("0073(0002)", "201803", "2018-03-31", "registry:1", holders=0)],
            [],
        )
        gates = evaluate_model(entities)["gates"]
        self.assertEqual(gates["ENTITY_MAPPING_UNIQUE_PER_PERIOD"], "FAIL")
        self.assertEqual(gates["CODE_TRANSFER_FAIL_CLOSED"], "FAIL")

    def test_unknown_with_single_holder_flags_missed_evidence(self):
        entities = _entities(
            [
                _observation(
                    "0073(0002)", "201803", "2018-03-31", "registry:1", status="UNKNOWN"
                )
            ],
            [],
        )
        self.assertEqual(evaluate_model(entities)["gates"]["CODE_TRANSFER_FAIL_CLOSED"], "FAIL")

    def test_element_name_instability_fails_legal_entity_gate(self):
        entities = _entities(
            [
                _observation("0049(0002)", "201803", "2018-03-31", "registry:1", name="A, S.A."),
                _observation("0049(0002)", "201809", "2018-09-30", "registry:1", name="B, S.A."),
            ],
            [],
        )
        self.assertEqual(evaluate_model(entities)["gates"]["LEGAL_ENTITY_IDENTITY_STABLE"], "FAIL")

    def test_code_reuse_without_handoff_is_violation(self):
        entities = _entities(
            [
                _observation("0152(0002)", "201803", "2018-03-31", "registry:1"),
                _observation("0152(0002)", "201809", "2018-09-30", "registry:2"),
            ],
            [
                {
                    "raw_sifdifu_key": "0152(0002)",
                    "bank_code": "0152",
                    "registry_candidate_ids": ["registry:1", "registry:2"],
                }
            ],
        )
        result = evaluate_model(entities)
        self.assertEqual(result["gates"]["CODE_REUSE_DETECTED"], "FAIL")
        self.assertTrue(result["checks"]["code_reuse_violations"])

    def test_documented_handoff_passes_code_reuse_gate(self):
        entities = _entities(
            [
                _observation("0152(0002)", "201803", "2018-03-31", "registry:1"),
                _observation("0152(0002)", "202012", "2020-12-31", "registry:2"),
            ],
            [
                {
                    "raw_sifdifu_key": "0152(0002)",
                    "bank_code": "0152",
                    "registry_candidate_ids": ["registry:1", "registry:2"],
                }
            ],
        )
        entities["registry_candidates"] = [
            {
                "bank_code": "0152",
                "candidates": [
                    {
                        "candidate_id": "registry:1",
                        "official_name": "OLD, S.E.",
                        "documents": [],
                        "code_history": [
                            {
                                "codigoBE": "0152",
                                "fechaInicio": "1979-06-28",
                                "fechaFin": "2019-02-01",
                            }
                        ],
                    },
                    {
                        "candidate_id": "registry:2",
                        "official_name": "NEW, S.E.",
                        "documents": [],
                        "code_history": [
                            {"codigoBE": "0152", "fechaInicio": "2019-02-01"}
                        ],
                    },
                ],
            }
        ]
        result = evaluate_model(entities)
        self.assertEqual(result["gates"]["CODE_REUSE_DETECTED"], "PASS")
        event = result["checks"]["code_reuse_events"][0]
        self.assertEqual(event["official_handoff_date"], "2019-02-01")
        self.assertTrue(event["handoff_documented"])


if __name__ == "__main__":
    unittest.main()
