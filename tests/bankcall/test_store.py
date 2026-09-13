"""Normalization helpers and store connection guardrails."""

import pytest

from bankcall import store


@pytest.mark.parametrize("raw,expected", [
    ("202606", "202606"),
    ("2026Q2", "202606"),
    ("2026q2", "202606"),
    ("2025Q2", "202506"),
    ("2020", "202012"),   # bare year -> first corpus period of that year
    ("2018", "201803"),
])
def test_norm_period(raw, expected):
    assert store.norm_period(raw) == expected


def test_norm_period_rejects_unknown():
    with pytest.raises(ValueError, match="not in frozen corpus"):
        store.norm_period("1999")


@pytest.mark.parametrize("raw,expected", [
    ("0049", "0049"),
    ("49", "0049"),
    ("ES0049", "0049"),
    ("0049(0002)", "0049"),   # raw SIFDIFU key -> slot code
])
def test_norm_code(raw, expected):
    assert store.norm_code(raw) == expected


def test_connect_fails_closed_without_data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    with pytest.raises(SystemExit, match="bankcall ingest"):
        store.connect()


def test_connect_creates_views(corpus):
    con = store.connect()
    names = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    assert {"facts", "slots", "transfers", "concepts",
            "concept_pairs", "period_generations"} <= names
