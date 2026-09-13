"""BankCall España CLI — v0.1.

Commands over the frozen BdE corpus (run `bankcall ingest` first):

  bankcall entity 0049                     reporting-slot ownership history
  bankcall statement 0049 --period 2026Q2 --statement balance
  bankcall history 0049 loans --from 2020
  bankcall compare 0049 0081 0128 --period 2026Q2
  bankcall changes 0049 --from 2025Q2 --to 2026Q2

Core rule, inherited from G1-BR: a bank code is a reporting slot, not a
legal entity.  `history`/`changes` warn on documented ownership transfers
instead of silently splicing series across them.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from . import store

app = typer.Typer(help="BankCall España — entity-level bank statements "
                       "from Banco de España public XBRL.",
                  no_args_is_help=True)
console = Console()
err = Console(stderr=True)


@app.command()
def ingest() -> None:
    """Build data/*.parquet from the frozen corpus (offline)."""
    from . import ingest as ing
    ing.run_ingest()


# ---------------------------------------------------------------- helpers

def _transfers(con, bank_code: str, lo: str | None = None,
               hi: str | None = None) -> list[tuple]:
    q = ("SELECT from_name, to_name, last_period_predecessor, "
         "       first_period_successor, handoff_date "
         "FROM transfers WHERE bank_code = ?")
    params: list = [bank_code]
    if lo:
        q += " AND first_period_successor >= ?"
        params.append(lo)
    if hi:
        q += " AND last_period_predecessor <= ?"
        params.append(hi)
    return con.execute(q, params).fetchall()


def _warn_transfers(con, bank_code: str, lo: str | None,
                    hi: str | None) -> None:
    for from_name, to_name, lp, fp, hd in _transfers(con, bank_code, lo, hi):
        err.print(
            f"[yellow]warning[/yellow]: slot {bank_code} changed legal "
            f"owner — {from_name} (until {lp}) -> {to_name} (from {fp}), "
            f"official handoff {hd}. Series below is segmented; it is NOT "
            f"one continuous legal entity.")


def _label_map(con) -> dict[str, str]:
    """expanded qname -> best label (ES preferred, EN fallback)."""
    out: dict[str, str] = {}
    for q, es, en in con.execute(
            "SELECT qname, label_es, label_en FROM concepts "
            "ORDER BY generation DESC").fetchall():
        out.setdefault(q, es or en or "")
    return out


def _member_labels(con, qnames: set[str]) -> dict[str, str]:
    if not qnames:
        return {}
    marks = ",".join("?" * len(qnames))
    rows = con.execute(
        f"SELECT DISTINCT qname, label_es, label_en FROM concepts "
        f"WHERE qname IN ({marks})", list(qnames)).fetchall()
    return {q: (es or en or q.rsplit("}", 1)[-1]) for q, es, en in rows}


def _fmt(value, decimals, unit) -> str:
    """decimals is XBRL precision, not a scale: values are already in units."""
    if value is None:
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if unit == "EUR":
        return f"{num:,.0f} EUR"
    return f"{num:,.6g}" + (f" {unit}" if unit else "")


def _resolve(con, term: str) -> list[str]:
    """Resolve a free-text term to matching qnames (metrics AND dimension
    members, labels ES/EN)."""
    # exact localname match: fail closed if the name is namespace-ambiguous
    exact = con.execute(
        "SELECT DISTINCT qname FROM concepts WHERE lower(localname) = ?",
        [term.lower()]).fetchall()
    if exact:
        nss = {r[0].split("}")[0].lstrip("{") for r in exact}
        if len(nss) > 1:
            err.print(f"ambiguous localname '{term}' — exists in "
                      f"{len(nss)} namespaces:")
            for (q,) in exact:
                err.print(f"  {q}")
            err.print("repeat with a fully expanded {ns}local qname")
            raise typer.Exit(1)
        return [r[0] for r in exact]
    rows = con.execute(
        "SELECT DISTINCT qname, label_es, label_en FROM concepts "
        "WHERE lower(label_es) LIKE ? OR lower(label_en) LIKE ? "
        "ORDER BY qname", [f"%{term.lower()}%"] * 2).fetchall()
    if not rows:
        err.print(f"no concept or member matching '{term}'")
        raise typer.Exit(1)
    return [r[0] for r in rows]


def _fact_filter(con, term: str) -> tuple[str, list]:
    """SQL predicate matching facts whose metric OR any dimension member
    resolves to the term."""
    qns = _resolve(con, term)
    marks = ",".join("?" * len(qns))
    pred = f"(metric IN ({marks})"
    for qn in qns:
        pred += " OR dims LIKE ?"
    pred += ")"
    return pred, qns + [f"%{q}%" for q in qns]


def _dims_label(dims_json: str, labels: dict[str, str]) -> str:
    dims = json.loads(dims_json)
    if not dims:
        return "-"
    parts = []
    for d, m in sorted(dims.items()):
        parts.append(f"{d.rsplit('}', 1)[-1]}="
                     f"{labels.get(m, m.rsplit('}', 1)[-1])}")
    return "; ".join(parts)


def _collect_member_qnames(rows: list[tuple], dims_idx: int) -> set[str]:
    out = set()
    for r in rows:
        out.update(json.loads(r[dims_idx]).values())
    return out


# ---------------------------------------------------------------- commands

@app.command()
def entity(code: str) -> None:
    """Reporting-slot ownership history for a bank code."""
    bc = store.norm_code(code)
    con = store.connect()
    rows = con.execute(
        "SELECT DISTINCT period_id, raw_key, official_name, lifecycle_status "
        "FROM slots WHERE bank_code = ? ORDER BY period_id", [bc]).fetchall()
    if not rows:
        err.print(f"no slot observations for code {bc}")
        raise typer.Exit(1)
    t = Table(title=f"Reporting slot {bc} — legal owner per period")
    t.add_column("Period"); t.add_column("Raw key"); t.add_column("Legal entity")
    t.add_column("Status")
    prev = None
    for pid, key, name, status in rows:
        mark = " [yellow]<- transfer[/yellow]" if prev and name != prev else ""
        t.add_row(store.PERIOD_LABELS.get(pid, pid), key,
                  (name or "?") + mark, status or "")
        prev = name
    console.print(t)
    _warn_transfers(con, bc, None, None)


@app.command()
def statement(code: str, period: str = typer.Option(..., "--period", "-p"),
              stmt: str = typer.Option("balance", "--statement", "-s"),
              consolidated: bool = typer.Option(False, "--consolidated", "-c"),
              member: str = typer.Option(None, "--member", "-m",
                help="filter to facts whose dims contain this member label")
             ) -> None:
    """Facts reported by an entity for a statement group in a period.

    Facts are dimensional: the 'line item' is the MCI member, MCY/BAS/APL
    etc. qualify it.  Nothing is aggregated or summed across dimensions.
    """
    bc, pid = store.norm_code(code), store.norm_period(period)
    alias = stmt + ("-cons" if consolidated and not stmt.endswith("-cons")
                    else "")
    stmts = store.STATEMENT_ALIASES.get(alias,
                                        store.STATEMENT_ALIASES.get(stmt,
                                                                    [stmt]))
    con = store.connect()
    labels = _label_map(con)
    member_pred, member_params = "", []
    if member:
        member_pred, member_params = _fact_filter(con, member)
        member_pred = " AND " + member_pred
    for st in stmts:
        rows = con.execute(
            "SELECT metric, dims, value_num, value_raw, unit, decimals "
            "FROM facts WHERE bank_code = ? AND period_id = ? "
            "AND statement = ?" + member_pred + " ORDER BY dims, metric",
            [bc, pid, st, *member_params]).fetchall()
        mem_lbl = _member_labels(con, _collect_member_qnames(rows, 1))
        console.print(f"\n[bold]{st}[/bold] — slot {bc}, "
                      f"{store.PERIOD_LABELS.get(pid, pid)} ({len(rows)} facts)")
        t = Table()
        t.add_column("Metric"); t.add_column("Dimensions (line = MCI member)")
        t.add_column("Value", justify="right"); t.add_column("Unit")
        for metric, dims, num, raw, unit, dec in rows:
            t.add_row(labels.get(metric, metric.rsplit("}", 1)[-1]),
                      _dims_label(dims, mem_lbl),
                      _fmt(num if num is not None else raw, dec, unit),
                      unit or "")
        console.print(t)


@app.command()
def history(code: str, concept: str,
            from_p: str = typer.Option(None, "--from"),
            to_p: str = typer.Option(None, "--to")) -> None:
    """Time series of a concept for a reporting slot.  Each distinct
    dimensional breakdown is its own series — never summed or spliced."""
    bc = store.norm_code(code)
    lo = store.norm_period(from_p) if from_p else None
    hi = store.norm_period(to_p) if to_p else None
    con = store.connect()
    pred, params = _fact_filter(con, concept)
    q = ("SELECT period_id, dims, value_num, value_raw, unit, decimals "
         f"FROM facts WHERE bank_code = ? AND {pred}")
    prm: list = [bc, *params]
    if lo:
        q += " AND period_id >= ?"; prm.append(lo)
    if hi:
        q += " AND period_id <= ?"; prm.append(hi)
    q += " ORDER BY dims, period_id"
    rows = con.execute(q, prm).fetchall()
    if not rows:
        err.print(f"no facts matching '{concept}' for slot {bc}")
        raise typer.Exit(1)
    mem_lbl = _member_labels(con, _collect_member_qnames(rows, 1))
    _warn_transfers(con, bc, lo, hi)
    t = Table(title=f"'{concept}' — slot {bc} (one series per dimension "
                    f"combination)")
    t.add_column("Series (dims)"); t.add_column("Period")
    t.add_column("Value", justify="right"); t.add_column("Legal owner")
    for pid, dims, num, raw, unit, dec in rows:
        owner = con.execute(
            "SELECT official_name FROM slots WHERE bank_code = ? "
            "AND period_id = ? LIMIT 1", [bc, pid]).fetchone()
        t.add_row(_dims_label(dims, mem_lbl),
                  store.PERIOD_LABELS.get(pid, pid),
                  _fmt(num if num is not None else raw, dec, unit),
                  (owner[0].strip() if owner else "?"))
    console.print(t)


@app.command()
def compare(codes: list[str],
            period: str = typer.Option(..., "--period", "-p"),
            concept: str = typer.Option(None, "--concept", "-k")) -> None:
    """Same facts, several reporting slots, one period."""
    pid = store.norm_period(period)
    bcs = [store.norm_code(c) for c in codes]
    con = store.connect()
    pred, params = ("", [])
    if concept:
        pred, params = _fact_filter(con, concept)
        pred = " AND " + pred
    marks = ",".join("?" * len(bcs))
    rows = con.execute(
        "SELECT metric, dims, bank_code, value_num, value_raw, unit, decimals "
        f"FROM facts WHERE period_id = ? AND bank_code IN ({marks}){pred} "
        "ORDER BY metric, dims, bank_code", [pid, *bcs, *params]).fetchall()
    if not rows:
        err.print("no facts for those codes in that period")
        raise typer.Exit(1)
    labels = _label_map(con)
    mem_lbl = _member_labels(con, _collect_member_qnames(rows, 1))
    owners = {}
    for bc in bcs:
        o = con.execute("SELECT official_name FROM slots WHERE bank_code=? "
                        "AND period_id=? LIMIT 1", [bc, pid]).fetchone()
        owners[bc] = o[0].strip() if o else bc
    t = Table(title=f"Compare — {store.PERIOD_LABELS.get(pid, pid)}")
    t.add_column("Metric"); t.add_column("Dims")
    for bc in bcs:
        t.add_column(bc, justify="right")
    t.caption = " | ".join(f"{bc}: {owners[bc]}" for bc in bcs)
    cells: dict[tuple, dict] = {}
    for metric, dims, bc, num, raw, unit, dec in rows:
        cells.setdefault((metric, dims), {})[bc] = _fmt(
            num if num is not None else raw, dec, unit)
    for (metric, dims), by_code in cells.items():
        t.add_row(labels.get(metric, metric.rsplit("}", 1)[-1]),
                  _dims_label(dims, mem_lbl),
                  *[by_code.get(bc, "—") for bc in bcs])
    console.print(t)
    for bc in bcs:
        _warn_transfers(con, bc, pid, pid)


@app.command()
def changes(code: str,
            from_p: str = typer.Option(..., "--from"),
            to_p: str = typer.Option(..., "--to")) -> None:
    """Fact-level diff of a reporting slot between two periods, with
    taxonomy-drift flags from the G1-C concept mapping."""
    bc = store.norm_code(code)
    lo, hi = store.norm_period(from_p), store.norm_period(to_p)
    con = store.connect()
    labels = _label_map(con)
    gens = dict(con.execute(
        "SELECT period_id, generation FROM period_generations").fetchall())
    pair_key = f"{gens.get(lo)}__{gens.get(hi)}"
    drift = dict(con.execute(
        "SELECT from_qname, classification FROM concept_pairs WHERE pair = ?",
        [pair_key]).fetchall())
    drift_local = {q.rsplit("}", 1)[-1]: c for q, c in drift.items()
                   if c != "EXACT_EQUIVALENT"}

    def _flag_cls(metric: str, dims_json: str) -> str | None:
        if metric in drift:
            return drift[metric]
        dims = json.loads(dims_json)
        for cand in [metric.rsplit("}", 1)[-1], *dims.keys(),
                     *(m.rsplit("}", 1)[-1] for m in dims.values())]:
            if cand in drift_local:
                return drift_local[cand]
        return None
    rows = con.execute(
        "SELECT period_id, metric, dims, value_num, value_raw, unit, decimals "
        "FROM facts WHERE bank_code = ? AND period_id IN (?, ?) "
        "ORDER BY metric, dims, period_id", [bc, lo, hi]).fetchall()
    bym: dict[tuple, dict] = {}
    for pid, metric, dims, num, raw, unit, dec in rows:
        bym.setdefault((metric, dims), {})[pid] = (num, raw, unit, dec)
    mem_lbl = _member_labels(con, _collect_member_qnames(rows, 2))
    _warn_transfers(con, bc, lo, hi)
    t = Table(title=f"Changes — slot {bc}, {store.PERIOD_LABELS.get(lo, lo)} "
                    f"-> {store.PERIOD_LABELS.get(hi, hi)}")
    t.add_column("Metric"); t.add_column("Dims")
    t.add_column(store.PERIOD_LABELS.get(lo, lo), justify="right")
    t.add_column(store.PERIOD_LABELS.get(hi, hi), justify="right")
    t.add_column("Delta", justify="right"); t.add_column("Flag")
    for (metric, dims), cells in sorted(bym.items()):
        a, b = cells.get(lo), cells.get(hi)
        va = _fmt(a[0] if a[0] is not None else a[1], a[3], a[2]) if a else "—"
        vb = _fmt(b[0] if b[0] is not None else b[1], b[3], b[2]) if b else "—"
        delta = ""
        if a and b and a[0] is not None and b[0] is not None and a[0] != 0:
            delta = f"{(b[0] - a[0]) / abs(a[0]) * 100:+.1f}%"
        flag = "NEW" if a is None else "REMOVED" if b is None else ""
        cls = _flag_cls(metric, dims)
        if cls:
            flag = (flag + " " if flag else "") + f"[yellow]{cls}[/yellow]"
        t.add_row(labels.get(metric, metric.rsplit("}", 1)[-1]),
                  _dims_label(dims, mem_lbl), va, vb, delta, flag)
    console.print(t)


if __name__ == "__main__":
    app()
