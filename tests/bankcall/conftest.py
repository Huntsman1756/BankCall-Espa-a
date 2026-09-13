"""Shared fixtures: a synthetic parquet corpus for bankcall product tests.

The real corpus is generated locally (`bankcall ingest`) and gitignored, so
these tests build a minimal equivalent in tmp_path and point store.DATA at it.
The fixture encodes every documented v0.1 behaviour:

- two dimension combos for the same metric (facts are never summed)
- a reporting slot (0073) with a documented legal-owner transfer
- a duplicate slot observation (dedup)
- an ambiguous localname present in two namespaces (fail closed)
- cross-generation concept mappings (taxonomy drift flags)
"""

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from bankcall import store

NS_MET = "http://test/met"
NS_OLD = "http://test/met-old"
D_MCI = "http://test/dom/MCI"
D_BAS = "http://test/dom/BAS"
D_MCY = "http://test/dom/MCY"
D_APL = "http://test/dom/APL"


def m(local: str) -> str:
    return f"{{{NS_MET}}}{local}"


DIMS_A = {"MCI": f"{{{D_MCI}}}x1332", "BAS": f"{{{D_BAS}}}x6",
          "MCY": f"{{{D_MCY}}}x329"}
DIMS_B = {"MCI": f"{{{D_MCI}}}x1332", "BAS": f"{{{D_BAS}}}x6",
          "MCY": f"{{{D_MCY}}}x999"}


def fact(period, code, metric, dims, value_num, value_raw=None, unit="EUR",
         decimals="-6", statement="2701", instant=None, start=None, end=None):
    return {
        "period_id": period, "statement": statement,
        "entity_id": f"ES{code}", "bank_code": code, "suffix": "0002",
        "agrupacion": "AgrupacionIndividual",
        "instant": instant or ("2025-06-30" if period == "202506"
                               else "2026-06-30"),
        "start": start, "end": end,
        "metric": metric, "metric_local": metric.rsplit("}", 1)[-1],
        "value_raw": value_raw if value_raw is not None else str(value_num),
        "value_num": value_num, "unit": unit, "decimals": decimals,
        "dims": json.dumps(dims, sort_keys=True),
        "source_file": f"{statement}_{period}.xbrl",
        "source_sha256": "0" * 64,
    }


FACTS = [
    # same metric, two dimension combos — must stay two series, never summed
    fact("202506", "0049", m("ImporteEnLibros"), DIMS_A, 1000000),
    fact("202506", "0049", m("ImporteEnLibros"), DIMS_B, 500000),
    fact("202506", "0049", m("Anticipos"), {}, 100),
    fact("202606", "0049", m("ImporteEnLibros"), DIMS_A, 1200000),
    fact("202606", "0049", m("ImporteEnLibros"), DIMS_B, 500000),
    fact("202606", "0049", m("Nuevo"),
         {"MCI": f"{{{D_MCI}}}x1332", "APL": f"{{{D_APL}}}x77"}, 42),
    fact("202606", "0049", m("DriftedMetric"), {}, 9,
         start="2026-01-01", end="2026-06-30", instant=None),
    fact("202606", "0049", m("Anticipos"),
         {"MCI": f"{{{D_MCI}}}OldMember"}, 5),
    fact("202606", "0049", m("NotaTexto"), {}, None,
         value_raw="No aplica", unit=None, decimals=None),
    # slot 0073: documented ownership transfer between the two periods
    fact("202506", "0073", m("ImporteEnLibros"), {}, 10),
    fact("202606", "0073", m("ImporteEnLibros"), {}, 11),
    fact("202606", "0081", m("ImporteEnLibros"), DIMS_A, 600),
]


def slot(period, key, name, status="active"):
    code, suffix = key.split("(", 1)
    return {
        "period_id": period,
        "period_end": "2025-06-30" if period == "202506" else "2026-06-30",
        "raw_key": key, "bank_code": code, "suffix": suffix.rstrip(")"),
        "statement_id": "2701", "legal_entity_ref": f"reg:{name}",
        "official_name": name, "catalog_name": name.title(),
        "lifecycle_status": status, "mapping_status": "PROVEN",
        "mapping_basis": "CODE_OWNERSHIP_HISTORY",
    }


SLOTS = [
    slot("202506", "0049(0002)", "BANCO SANTANDER, S.A."),
    slot("202506", "0049(0002)", "BANCO SANTANDER, S.A."),  # duplicate
    slot("202606", "0049(0002)", "BANCO SANTANDER, S.A."),
    slot("202506", "0073(0002)", "OLD BANK, S.A."),
    slot("202606", "0073(0002)", "NEW BANK, S.A."),
    slot("202506", "0081(0002)", "BANCO DE SABADELL, S.A."),
    slot("202606", "0081(0002)", "BANCO DE SABADELL, S.A."),
]

TRANSFERS = [{
    "bank_code": "0073", "suffix": "0002", "raw_key": "0073(0002)",
    "from_entity": "reg:OLD BANK, S.A.", "from_name": "OLD BANK, S.A.",
    "to_entity": "reg:NEW BANK, S.A.", "to_name": "NEW BANK, S.A.",
    "last_period_predecessor": "202506", "first_period_successor": "202606",
    "handoff_date": "2026-05-04",
}]


def concept(qname, label_es=None, label_en=None, gen="gen2"):
    return {
        "generation": gen, "qname": qname,
        "localname": qname.rsplit("}", 1)[-1],
        "namespace": qname.split("}")[0].lstrip("{"),
        "type": "xbrli:monetaryItemType", "balance": "debit",
        "period_type": "instant", "abstract": False,
        "label_es": label_es, "label_en": label_en,
    }


CONCEPTS = [
    concept(m("ImporteEnLibros"), "Importe en libros"),
    concept(m("Anticipos"), "Anticipos"),
    concept(m("Nuevo"), "Nuevo concepto"),
    concept(m("DriftedMetric"), "Métrica con deriva"),
    concept(m("NotaTexto"), "Nota textual"),
    # same localname in two namespaces -> resolution must fail closed
    concept(f"{{{NS_OLD}}}Ambiguo", "Ambiguous (old ns)"),
    concept(m("Ambiguo"), "Ambiguous (new ns)"),
    # dimension members
    concept(f"{{{D_MCI}}}x1332", "Caja y depósitos"),
    concept(f"{{{D_BAS}}}x6", "Patrimonio neto"),
    concept(f"{{{D_MCY}}}x329", "Todo el patrimonio neto"),
    concept(f"{{{D_MCY}}}x999", label_en="Other scope"),
    # note: {D_APL}x77 intentionally absent -> localname fallback
]

CONCEPT_PAIRS = [
    {"pair": "gen1__gen2", "from_qname": m("DriftedMetric"),
     "to_qname": m("DriftedMetricV2"), "classification": "STRUCTURALLY_CHANGED"},
    {"pair": "gen1__gen2", "from_qname": f"{{{D_MCI}}}OldMember",
     "to_qname": f"{{{D_MCI}}}NewMember", "classification": "RENAMED_EQUIVALENT"},
    {"pair": "gen1__gen2", "from_qname": m("Gone"),
     "to_qname": None, "classification": "REMOVED"},
]

PERIOD_GENERATIONS = [
    {"period_id": "202506", "generation": "gen1"},
    {"period_id": "202606", "generation": "gen2"},
]


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    tables = {
        "facts": FACTS,
        "slots": SLOTS,
        "transfers": TRANSFERS,
        "concepts": CONCEPTS,
        "concept_pairs": CONCEPT_PAIRS,
        "period_generations": PERIOD_GENERATIONS,
    }
    for name, rows in tables.items():
        pq.write_table(pa.Table.from_pylist(rows),
                       tmp_path / f"{name}.parquet")
    monkeypatch.setattr(store, "DATA", tmp_path)
    return tmp_path
