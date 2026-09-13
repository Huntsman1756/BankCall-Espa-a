"""End-to-end CLI tests over the synthetic corpus (tests/bankcall/conftest.py).

Covers the v0.1 contract points that came out of the G1 findings: no implicit
aggregation across dimensions, slot dedup, ownership-transfer segmentation,
fail-closed ambiguous localnames, member label resolution, and taxonomy-drift
propagation in `changes`.
"""

import pytest
import typer
from typer.testing import CliRunner

from bankcall import store
from bankcall.cli import _fmt, _resolve, app

from conftest import m

runner = CliRunner()
WIDE = {"COLUMNS": "300"}  # keep rich tables unwrapped for assertions


# ------------------------------------------------------------------ helpers

def test_fmt_decimals_never_scales():
    # decimals="-6" is XBRL precision metadata: the reported value is final
    assert _fmt(1000000, "-6", "EUR") == "1,000,000 EUR"
    assert _fmt(None, "-6", "EUR") == "-"
    assert _fmt("No aplica", None, None) == "No aplica"
    assert _fmt(5, "0", "shares") == "5 shares"


def test_resolve_by_label_and_localname(corpus):
    con = store.connect()
    assert _resolve(con, "importe") == [m("ImporteEnLibros")]
    assert _resolve(con, "ImporteEnLibros") == [m("ImporteEnLibros")]


def test_resolve_no_match_fails_closed(corpus):
    con = store.connect()
    with pytest.raises(typer.Exit):
        _resolve(con, "zz-no-such-concept")


# ------------------------------------------------------------------ entity

def test_entity_dedup_slot_observations(corpus):
    r = runner.invoke(app, ["entity", "0049"])
    assert r.exit_code == 0
    assert "BANCO SANTANDER" in r.output
    # the duplicate 202506 observation must not produce a second row
    assert r.output.count("2025Q2") == 1
    assert r.output.count("2026Q2") == 1


def test_entity_marks_ownership_transfer(corpus):
    r = runner.invoke(app, ["entity", "0073"])
    assert r.exit_code == 0
    assert "OLD BANK" in r.output and "NEW BANK" in r.output
    assert "<- transfer" in r.output
    assert "changed legal owner" in r.stderr


def test_entity_unknown_code_fails(corpus):
    r = runner.invoke(app, ["entity", "9999"])
    assert r.exit_code == 1
    assert "no slot observations" in r.stderr


# ----------------------------------------------------------------- history

def test_history_one_series_per_dimension_combo(corpus):
    r = runner.invoke(app, ["history", "0049", "importe"], env=WIDE)
    assert r.exit_code == 0
    # both dimension combos are their own series — never summed
    assert "1,000,000" in r.output
    assert "500,000" in r.output
    assert "1,500,000" not in r.output
    assert "Todo el patrimonio neto" in r.output
    assert "Other scope" in r.output  # EN label fallback


def test_history_transfer_segments_series(corpus):
    r = runner.invoke(app, ["history", "0073", "importe"])
    assert r.exit_code == 0
    assert "changed legal owner" in r.stderr
    assert "OLD BANK, S.A." in r.output
    assert "NEW BANK, S.A." in r.output


def test_history_filters_by_member_label(corpus):
    r = runner.invoke(app, ["history", "0049", "todo el patrimonio"],
                      env=WIDE)
    assert r.exit_code == 0
    # member x329 appears only in DIMS_A facts
    assert "1,000,000" in r.output
    assert "1,200,000" in r.output
    assert "500,000" not in r.output


def test_history_ambiguous_localname_fails_closed(corpus):
    r = runner.invoke(app, ["history", "0049", "Ambiguo"])
    assert r.exit_code == 1
    assert "ambiguous localname" in r.stderr
    assert "2 namespaces" in r.stderr


def test_history_no_facts_fails(corpus):
    # slot 0073 only reports ImporteEnLibros in the fixture
    r = runner.invoke(app, ["history", "0073", "anticipos"])
    assert r.exit_code == 1
    assert "no facts matching" in r.stderr


# ---------------------------------------------------------------- statement

def test_statement_resolves_member_labels(corpus):
    r = runner.invoke(app, ["statement", "0049", "--period", "2026Q2",
                            "--statement", "balance"], env=WIDE)
    assert r.exit_code == 0
    assert "Caja y depósitos" in r.output        # MCI member label (ES)
    assert "Patrimonio neto" in r.output         # BAS member label
    assert "x77" in r.output                     # unlabeled member -> localname
    assert "Nuevo concepto" in r.output          # metric label


def test_statement_decimals_not_applied_as_scale(corpus):
    r = runner.invoke(app, ["statement", "0049", "--period", "2025Q2",
                            "--statement", "balance"], env=WIDE)
    assert r.exit_code == 0
    assert "1,000,000" in r.output               # not scaled to 1.0


def test_statement_text_fact_shows_raw_value(corpus):
    r = runner.invoke(app, ["statement", "0049", "--period", "2026Q2",
                            "--statement", "balance"], env=WIDE)
    assert "No aplica" in r.output


# ----------------------------------------------------------------- compare

def test_compare_same_dims_side_by_side_no_sum(corpus):
    r = runner.invoke(app, ["compare", "0049", "0081", "--period", "2026Q2"],
                      env=WIDE)
    assert r.exit_code == 0
    assert "1,200,000" in r.output
    assert "500,000" in r.output
    assert "600" in r.output
    assert "1,700,000" not in r.output           # no implicit aggregation
    assert "BANCO SANTANDER" in r.output         # owner caption
    assert "BANCO DE SABADELL" in r.output


def test_compare_no_facts_fails(corpus):
    r = runner.invoke(app, ["compare", "0081", "--period", "2025Q2"])
    assert r.exit_code == 1


# ----------------------------------------------------------------- changes

def test_changes_flags_new_removed_and_delta(corpus):
    r = runner.invoke(app, ["changes", "0049", "--from", "2025Q2",
                            "--to", "2026Q2"], env=WIDE)
    assert r.exit_code == 0
    assert "NEW" in r.output                     # Nuevo concept
    assert "REMOVED" in r.output                 # Anticipos with empty dims
    assert "+20.0%" in r.output                  # 1,000,000 -> 1,200,000


def test_changes_propagates_taxonomy_drift(corpus):
    r = runner.invoke(app, ["changes", "0049", "--from", "2025Q2",
                            "--to", "2026Q2"], env=WIDE)
    assert r.exit_code == 0
    # metric qname directly in the gen1__gen2 concept mapping
    assert "STRUCTURALLY_CHANGED" in r.output
    # drift reached through a dimension member's localname
    assert "RENAMED_EQUIVALENT" in r.output


def test_changes_warns_on_transfer(corpus):
    r = runner.invoke(app, ["changes", "0073", "--from", "2025Q2",
                            "--to", "2026Q2"])
    assert r.exit_code == 0
    assert "changed legal owner" in r.stderr
