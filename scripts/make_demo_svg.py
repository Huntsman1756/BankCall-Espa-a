"""Regenerate docs/assets/*.svg terminal captures for the README.

Runs the real `bankcall` commands against the local data/ corpus (run
`bankcall ingest` first) and renders the captured output with rich.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
from pathlib import Path

from rich.console import Console
from rich.text import Text

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "assets"
WIDTH = 180  # wide enough that drift flags (e.g. STRUCTURALLY_CHANGED)
             # render on a single line

# (cli args, anchor regex or None, lines of context around the anchor)
DEMOS = {
    "compare": (["compare", "0049", "0081", "0128",
                 "--period", "2026Q2", "--concept", "patrimonio neto"],
                r"85,083,626", 4),
    "entity": (["entity", "0073"], None, 0),
    "changes": (["changes", "0049", "--from", "2018Q1", "--to", "2018Q4"],
                r"STRUCTURALLY_CHANGED", 6),
}


def run(args: list[str]) -> list[str]:
    env = {**os.environ, "COLUMNS": str(WIDTH), "PYTHONIOENCODING": "utf-8",
           "PYTHONUTF8": "1"}
    proc = subprocess.run(
        ["bankcall", *args], cwd=REPO, env=env,
        capture_output=True, text=True, encoding="utf-8")
    lines = proc.stdout.rstrip().splitlines()
    if proc.stderr.strip():  # surface warnings like a real terminal would
        lines += ["", *proc.stderr.rstrip().splitlines()]
    return lines


def excerpt(lines: list[str], anchor: str | None, span: int) -> list[str]:
    """Table header (title + column rule) plus the rows around the anchor."""
    if anchor is None:
        return lines
    idx = next(i for i, ln in enumerate(lines) if re.search(anchor, ln))
    head = lines[:4]
    # walk back to the start of the anchor's table row: a new row begins
    # where the first cell is non-empty (rich draws no row separators)
    start = idx
    while start > 4 and not lines[start].split("│")[1].strip():
        start -= 1
    body = lines[start:idx + span]
    return head + ["   ...", *body, "   ..."]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (args, anchor, span) in DEMOS.items():
        lines = run(args)
        body = "\n".join(excerpt(lines, anchor, span))
        con = Console(record=True, width=WIDTH, file=io.StringIO())
        con.print(Text(f"$ bankcall {' '.join(args)}", style="bold"))
        con.print(Text(body))
        svg = OUT / f"{name}.svg"
        con.save_svg(str(svg), title=f"bankcall {name}")
        print(f"{svg.relative_to(REPO)}  ({len(body.splitlines())} lines)")


if __name__ == "__main__":
    main()
