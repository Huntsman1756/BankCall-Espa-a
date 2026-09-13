#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G1-BR corrected temporal-identity-model validation for BankCall España.

G1-B v1.0 falsified the assumption that a raw SIFDIFU key identifies one
legal entity over time: 8 of 288 keys change the underlying registry element
(ADR-001).  This validator is a pure function of the frozen
``entities.json`` — it performs no network access — and checks that the
corrected model holds on the observed data:

- every observation maps to exactly one registry element per period, proven
  by the official code-assignment history;
- every slot transfer is detected, is a single switch, and has matching
  handoff dates in the official history;
- ambiguous ownership stays UNKNOWN (fail closed);
- the legal entity behind a registry element is itself stable;
- the parsed key scope semantics remain proven.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from discover_catalog import canonical_json_bytes, sha256_bytes


OWNERSHIP_BASES = {
    "CODE_OWNERSHIP_HISTORY",
    "CODE_OWNERSHIP_HISTORY_LEI_DISAMBIGUATED",
}


class IdentityModelError(RuntimeError):
    """Raised when the frozen entities output is structurally unusable."""


def parse_date(value: Any) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def holder_count(observation: dict[str, Any]) -> int:
    return sum(
        1
        for item in observation.get("ownership_classification", [])
        if item.get("holds_code_at_period_end") is True
    )


def period_candidate_sequence(
    observations: list[dict[str, Any]], raw_key: str
) -> list[tuple[str, set[str]]]:
    by_period: dict[str, set[str]] = {}
    for observation in observations:
        if observation["raw_sifdifu_key"] == raw_key:
            by_period.setdefault(observation["period_id"], set()).add(
                observation["registry_candidate_id"] or "NONE"
            )
    return [(period, by_period[period]) for period in sorted(by_period)]


def interval_covering(
    candidate: dict[str, Any], bank_code: str, period_end: dt.date
) -> dict[str, Any] | None:
    for entry in candidate.get("code_history") or []:
        if str(entry.get("codigoBE") or "") != bank_code:
            continue
        start = parse_date(entry.get("fechaInicio"))
        end = parse_date(entry.get("fechaFin"))
        if (start is None or start <= period_end) and (end is None or period_end <= end):
            return entry
    return None


def detect_code_reuse(
    entities: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (documented transition events, violation messages)."""
    candidates = {
        candidate["candidate_id"]: candidate
        for group in entities["registry_candidates"]
        for candidate in group["candidates"]
    }
    observations = entities["observations"]
    events: list[dict[str, Any]] = []
    violations: list[str] = []
    for key in entities["identity_keys"]:
        raw_key = key["raw_sifdifu_key"]
        sequence = period_candidate_sequence(observations, raw_key)
        candidates_seen = sorted({c for _, ids in sequence for c in ids})
        if len(candidates_seen) <= 1:
            continue
        for (prev_period, prev_ids), (next_period, next_ids) in zip(sequence, sequence[1:]):
            if prev_ids == next_ids:
                continue
            if len(prev_ids) != 1 or len(next_ids) != 1:
                violations.append("%s: ambiguous candidate set at %s/%s" % (raw_key, prev_period, next_period))
                continue
            prev_id, next_id = next(iter(prev_ids)), next(iter(next_ids))
            prev_cand, next_cand = candidates.get(prev_id), candidates.get(next_id)
            handoff_ok = False
            handoff_date = None
            if prev_cand and next_cand:
                prev_end = parse_date(
                    next(o["period_end"] for o in observations
                         if o["raw_sifdifu_key"] == raw_key and o["period_id"] == prev_period)
                )
                next_end = parse_date(
                    next(o["period_end"] for o in observations
                         if o["raw_sifdifu_key"] == raw_key and o["period_id"] == next_period)
                )
                prev_interval = interval_covering(prev_cand, key["bank_code"], prev_end)
                next_interval = interval_covering(next_cand, key["bank_code"], next_end)
                if prev_interval and next_interval:
                    prev_fin = parse_date(prev_interval.get("fechaFin"))
                    next_ini = parse_date(next_interval.get("fechaInicio"))
                    if prev_fin is not None and prev_fin == next_ini:
                        handoff_ok = True
                        handoff_date = prev_fin.isoformat()
            if not handoff_ok:
                violations.append(
                    "%s: undocumented handoff %s -> %s between %s and %s"
                    % (raw_key, prev_id, next_id, prev_period, next_period)
                )
            events.append(
                {
                    "raw_sifdifu_key": raw_key,
                    "from_candidate_id": prev_id,
                    "to_candidate_id": next_id,
                    "from_official_name": prev_cand.get("official_name") if prev_cand else None,
                    "to_official_name": next_cand.get("official_name") if next_cand else None,
                    "last_period_predecessor": prev_period,
                    "first_period_successor": next_period,
                    "official_handoff_date": handoff_date,
                    "handoff_documented": handoff_ok,
                }
            )
        # flip-flop check: each candidate's observed periods must be contiguous
        for candidate_id in candidates_seen:
            positions = [
                index
                for index, (_, ids) in enumerate(sequence)
                if candidate_id in ids
            ]
            if positions != list(range(positions[0], positions[0] + len(positions))):
                violations.append("%s: non-contiguous assignment of %s" % (raw_key, candidate_id))
    events.sort(key=lambda item: (item["raw_sifdifu_key"], item["official_handoff_date"] or ""))
    return events, violations


def evaluate_model(entities: dict[str, Any]) -> dict[str, Any]:
    observations = entities["observations"]
    checks: dict[str, Any] = {}
    gates: dict[str, str] = {}

    not_unique = [
        o["raw_sifdifu_key"]
        for o in observations
        if o["registry_mapping_status"] != "PROVEN" or holder_count(o) != 1
    ]
    checks["observation_count"] = len(observations)
    checks["non_unique_mapping_count"] = len(not_unique)
    checks["non_unique_mapping_examples"] = sorted(set(not_unique))[:20]
    gates["ENTITY_MAPPING_UNIQUE_PER_PERIOD"] = "PASS" if not not_unique else "FAIL"

    not_ownership = [
        o["raw_sifdifu_key"]
        for o in observations
        if o["registry_mapping_status"] == "PROVEN"
        and o.get("mapping_basis") not in OWNERSHIP_BASES
    ]
    checks["non_ownership_proven_count"] = len(not_ownership)
    checks["mapping_basis_counts"] = dict(
        sorted(
            Counter(o.get("mapping_basis") or "UNRESOLVED" for o in observations).items()
        )
    )
    gates["REPORTING_SLOT_TEMPORAL_OWNERSHIP_PROVEN"] = "PASS" if not not_ownership else "FAIL"

    events, reuse_violations = detect_code_reuse(entities)
    checks["code_reuse_events"] = events
    checks["code_reuse_event_count"] = len(events)
    checks["code_reuse_violations"] = reuse_violations
    gates["CODE_REUSE_DETECTED"] = "PASS" if events and not reuse_violations else "FAIL"

    fail_closed_violations = [
        o["raw_sifdifu_key"]
        for o in observations
        if (
            o["registry_mapping_status"] == "PROVEN"
            and holder_count(o) != 1
            and o.get("mapping_basis") != "CODE_OWNERSHIP_HISTORY_LEI_DISAMBIGUATED"
        )
        or (
            o["registry_mapping_status"] == "UNKNOWN"
            and holder_count(o) == 1
        )
    ]
    checks["fail_closed_violations"] = sorted(set(fail_closed_violations))[:20]
    checks["fail_closed_violation_count"] = len(fail_closed_violations)
    gates["CODE_TRANSFER_FAIL_CLOSED"] = "PASS" if not fail_closed_violations else "FAIL"

    names_by_candidate: dict[str, set[str]] = {}
    for o in observations:
        if o["registry_candidate_id"]:
            names_by_candidate.setdefault(o["registry_candidate_id"], set()).add(
                o["registry_official_name"]
            )
    unstable_names = {k: sorted(v) for k, v in names_by_candidate.items() if len(v) > 1}
    lei_mismatches = [o for o in observations if o.get("lei_crosscheck") == "MISMATCH"]
    multi_lei = [
        c["candidate_id"]
        for group in entities["registry_candidates"]
        for c in group["candidates"]
        if sum(
            1
            for d in c.get("documents", [])
            if isinstance(d, dict) and d.get("tipoDocumento") == "LEI"
        )
        > 1
    ]
    checks["observed_registry_elements"] = len(names_by_candidate)
    checks["elements_with_unstable_name"] = unstable_names
    checks["lei_mismatch_count"] = len(lei_mismatches)
    checks["elements_with_multiple_lei_documents"] = multi_lei
    gates["LEGAL_ENTITY_IDENTITY_STABLE"] = (
        "PASS" if not unstable_names and not lei_mismatches and not multi_lei else "FAIL"
    )

    semantics = entities.get("component_semantics", {})
    scope_ok = all(
        component in semantics
        and semantics[component].get("business_meaning_proven_by")
        and semantics[component].get("classification")
        for component in ("0000", "0001", "0002")
    )
    key_parser = entities.get("key_parser", {})
    checks["scope_semantics"] = sorted(semantics)
    checks["raw_key_preserved"] = entities.get("checks", {}).get("raw_key_preserved")
    checks["unresolved_component_not_normalized"] = key_parser.get(
        "unresolved_component_is_not_normalized"
    )
    gates["SCOPE_SEMANTICS_PROVEN"] = (
        "PASS"
        if scope_ok
        and checks["raw_key_preserved"] is True
        and checks["unresolved_component_not_normalized"] is True
        else "FAIL"
    )
    return {"gates": gates, "checks": checks}


def render_report(evidence: dict[str, Any]) -> str:
    gates = evidence["gates"]
    checks = evidence["checks"]
    lines = [
        "# BankCall España — G1-BR Corrected Temporal Identity Model",
        "",
        "Validates ADR-001 against the frozen `entities.json` produced by G1-B",
        "v1.0 (`g1-b-identity-lifecycle-v1.0`). Pure offline check; no source",
        "fetches. G1-B v1.0 keeps its two FAIL gates as the falsification",
        "record; this report evaluates the corrected model.",
        "",
        "## Gate result",
        "",
        "| Gate | Result |",
        "| --- | --- |",
    ]
    lines.extend("| `%s` | **%s** |" % (name, gates[name]) for name in sorted(gates))
    lines.extend(
        [
            "",
            "- Observations: **%s**; non-unique mappings: **%s**."
            % (checks["observation_count"], checks["non_unique_mapping_count"]),
            "- Mapping basis: %s."
            % ", ".join(
                "`%s`=%s" % (name, count)
                for name, count in checks["mapping_basis_counts"].items()
            ),
            "- Registry elements observed: **%s**; unstable element names: **%s**; LEI mismatches: **%s**."
            % (
                checks["observed_registry_elements"],
                len(checks["elements_with_unstable_name"]),
                checks["lei_mismatch_count"],
            ),
            "",
            "## Documented slot transfers",
            "",
            "| Raw key | From | To | Handoff date | Documented |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for event in checks["code_reuse_events"]:
        lines.append(
            "| `%s` | %s | %s | `%s` | `%s` |"
            % (
                event["raw_sifdifu_key"],
                "%s (%s)" % (event["from_official_name"], event["from_candidate_id"]),
                "%s (%s)" % (event["to_official_name"], event["to_candidate_id"]),
                event["official_handoff_date"],
                event["handoff_documented"],
            )
        )
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "```text",
            "python scripts/g1/validate_identity_model.py",
            "```",
            "",
            "Input: `entities.json` (frozen G1-B v1.0 output). Evidence: `g1-br-evidence.json`.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    base = Path(__file__).resolve().parents[2] / "evidence" / "g1"
    parser.add_argument("--entities", default=str(base / "entities.json"))
    parser.add_argument("--out", default=str(base))
    args = parser.parse_args()
    entities_path = Path(args.entities).resolve()
    out = Path(args.out).resolve()
    raw = entities_path.read_bytes()
    try:
        entities = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("entities.json is not valid UTF-8 JSON: %s" % exc)

    result1 = evaluate_model(entities)
    result2 = evaluate_model(entities)
    identical = canonical_json_bytes(result1) == canonical_json_bytes(result2)
    gates = result1["gates"]
    evidence = {
        "schema": "bankcall.g1.temporal_identity_model.evidence.v1",
        "experiment": "BANKCALL_ES_G1_BR_TEMPORAL_IDENTITY_MODEL",
        "model_decision": "methodology/ADR-001-temporal-reporting-slots.md",
        "scope": "offline validation of the corrected identity model over frozen G1-B v1.0 output",
        "input": {
            "path": str(entities_path),
            "raw_sha256": sha256_bytes(raw),
            "g1_b_freeze_tag": "g1-b-identity-lifecycle-v1.0",
        },
        "determinism": {
            "classification": "IDENTICAL" if identical else "UNEXPLAINED_DIFF",
            "note": "pure function of frozen entities.json; evaluated twice",
        },
        "gates": gates,
        "checks": result1["checks"],
        "result": (
            "PASS"
            if identical and all(value == "PASS" for value in gates.values())
            else "FAIL_CLOSED"
        ),
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    (out / "g1-br-evidence.json").write_bytes(canonical_json_bytes(evidence))
    (out / "G1-BR-REPORT.md").write_text(render_report(evidence), encoding="utf-8")
    print(json.dumps({"result": evidence["result"], "gates": gates}, indent=2))
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
