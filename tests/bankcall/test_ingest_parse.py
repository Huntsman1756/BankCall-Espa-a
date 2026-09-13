"""parse_instance: XBRL instance -> fact rows.

Regression tests for the ingest findings: `decimals` is XBRL precision
metadata and must NOT scale the reported value; scenario members become
dimensional qualifiers; segment members identify the reporting entity's
aggregation scope — never the other way around.
"""

import json

from bankcall.ingest import parse_instance

XBRL = """<?xml version="1.0" encoding="utf-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
    xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
    xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
    xmlns:cm="http://test/cm-dim"
    xmlns:dim="http://test/dim"
    xmlns:mci="http://test/dom/MCI"
    xmlns:bas="http://test/dom/BAS"
    xmlns:met="http://test/met">
  <xbrli:context id="cES_0049_0002_1">
    <xbrli:entity>
      <xbrli:identifier scheme="http://www.ecb.int/stats/money/mfi">ES0049</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="cm:Agrupacion">cm:AgrupacionIndividual</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period>
      <xbrli:instant>2026-06-30</xbrli:instant>
    </xbrli:period>
    <xbrli:scenario>
      <xbrldi:explicitMember dimension="dim:MCI">mci:x1332</xbrldi:explicitMember>
      <xbrldi:explicitMember dimension="dim:BAS">bas:x6</xbrldi:explicitMember>
    </xbrli:scenario>
  </xbrli:context>
  <xbrli:context id="cES_0049_0002_2">
    <xbrli:entity>
      <xbrli:identifier>ES0049</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2026-01-01</xbrli:startDate>
      <xbrli:endDate>2026-06-30</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>
  <xbrli:context id="ctx_no_pattern">
    <xbrli:entity>
      <xbrli:identifier>ES9999</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period>
      <xbrli:instant>2026-06-30</xbrli:instant>
    </xbrli:period>
  </xbrli:context>
  <xbrli:unit id="uEUR"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
  <met:Importe contextRef="cES_0049_0002_1" unitRef="uEUR" decimals="-6">1000000</met:Importe>
  <met:Nota contextRef="cES_0049_0002_2">No aplica</met:Nota>
  <met:Otro contextRef="ctx_no_pattern" unitRef="uEUR" decimals="0">5</met:Otro>
  <met:Huerfano contextRef="ctx_missing" unitRef="uEUR" decimals="0">7</met:Huerfano>
</xbrli:xbrl>
"""


def _rows(tmp_path):
    p = tmp_path / "2701_202606.xbrl"
    p.write_text(XBRL, encoding="utf-8")
    return parse_instance(p, "202606", "2701", "f" * 64)


def test_decimals_is_precision_not_a_scale(tmp_path):
    row = next(r for r in _rows(tmp_path) if r["metric_local"] == "Importe")
    assert row["value_num"] == 1000000.0
    assert row["decimals"] == "-6"


def test_scenario_members_become_dims_segment_does_not(tmp_path):
    row = next(r for r in _rows(tmp_path) if r["metric_local"] == "Importe")
    assert json.loads(row["dims"]) == {
        "MCI": "{http://test/dom/MCI}x1332",
        "BAS": "{http://test/dom/BAS}x6",
    }
    assert row["agrupacion"] == "AgrupacionIndividual"
    assert row["entity_id"] == "ES0049"
    assert row["bank_code"] == "0049"
    assert row["suffix"] == "0002"
    assert row["instant"] == "2026-06-30"


def test_duration_context_and_non_numeric_fact(tmp_path):
    row = next(r for r in _rows(tmp_path) if r["metric_local"] == "Nota")
    assert row["start"] == "2026-01-01"
    assert row["end"] == "2026-06-30"
    assert row["value_num"] is None
    assert row["value_raw"] == "No aplica"


def test_context_without_slot_pattern_and_orphan_ref(tmp_path):
    rows = _rows(tmp_path)
    assert len(rows) == 3  # orphan contextRef is skipped, units are not facts
    row = next(r for r in rows if r["metric_local"] == "Otro")
    assert row["bank_code"] is None
    assert row["entity_id"] == "ES9999"
    assert row["dims"] == "{}"


def test_metric_is_expanded_qname(tmp_path):
    row = next(r for r in _rows(tmp_path) if r["metric_local"] == "Importe")
    assert row["metric"] == "{http://test/met}Importe"
    assert row["period_id"] == "202606"
    assert row["statement"] == "2701"
    assert row["source_sha256"] == "f" * 64
