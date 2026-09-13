"""G1-C remediation: pick, per unversioned EBA dictionary file, the official
package bytes that satisfy every referenced fragment id.

Problem discovered empirically: eba.europa.eu's *unversioned* dictionary
schemas (dict/dom/<dom>/mem.xsd, dict/met/met.xsd, dict/dim/dim.xsd, ...)
evolve across reporting frameworks — members are added and *removed*.
Versioned linkbases (dict/dom/<dom>/<ver>/hier-def.xml) always reference
``../mem.xsd#<id>``, i.e. the unversioned file, so one mirror copy must
contain the union of every member ever referenced.  No single published
package guarantees that; this script measures coverage and installs the
best-fit official bytes per file, recording the choice and any residual
missing ids (fail-closed) in evidence.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import zipfile
from urllib.parse import urljoin

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIRROR = os.path.join(REPO, "g0_acquisition", "dts_mirror")
STAGING = os.path.join(REPO, "g0_acquisition", "eba_pack_4.3_staging",
                       "Full_taxonomy")
OUT = os.path.join(REPO, "evidence", "g1", "eba-dict-bestfit.json")

DICT_ZIPS = {
    "eba-dict-2.7.0.0": ("g0_acquisition/eba-dict-2.7.0.0.zip",
                         "EBA_CRD_IV_XBRL_2.7_Dictionary_2.7.0.0/"),
    "eba-dict-3.0.1.0": ("g0_acquisition/eba-dict-3.0.zip",
                         "EBA_CRD_IV_XBRL_3.0_Dictionary_3.0.1.0.Errata3/"),
    "eba-dict-3.1.1.0": ("g0_acquisition/eba-dict-3.1.zip",
                         "EBA_CRD_IV_XBRL_3.1_Dictionary_3.1.1.0/"),
    "eba-dict-3.2.2.0": ("g0_acquisition/eba-dict-3.2.zip",
                         "EBA_CRD_IV_XBRL_3.2_Dictionary_3.2.2.0/"),
}

HREF_RE = re.compile(rb'xlink:href="([^"#]+)#([A-Za-z_][A-Za-z0-9_.-]*)"')
ID_RE = re.compile(r'id="([A-Za-z_][A-Za-z0-9_.-]*)"')


def collect_requirements():
    """target unversioned mirror-rel path -> set of required fragment ids."""
    reqs = {}
    roots = [os.path.join(MIRROR, "www.eba.europa.eu", "eu", "fr", "xbrl")]
    for root in roots:
        for r, _d, files in os.walk(root):
            for fn in files:
                p = os.path.join(r, fn)
                try:
                    data = open(p, "rb").read()
                except OSError:
                    continue
                base_url = "http://" + os.path.relpath(p, MIRROR) \
                    .replace(os.sep, "/")
                for m in HREF_RE.finditer(data):
                    href, frag = m.group(1).decode(), m.group(2).decode()
                    tgt = urljoin(base_url, href)
                    if not tgt.startswith("http://www.eba.europa.eu/"):
                        continue
                    rel = tgt.split("://", 1)[1]
                    reqs.setdefault(rel, set()).add(frag)
    return reqs


def candidates_for(rel):
    """package-version -> bytes for mirror-relative *eba* path."""
    cands = {}
    for tag, (zp, prefix) in DICT_ZIPS.items():
        zp = os.path.join(REPO, zp)
        if not os.path.exists(zp):
            continue
        z = zipfile.ZipFile(zp)
        inner = prefix + rel
        if inner in z.namelist():
            cands[tag] = z.read(inner)
    staged = os.path.join(STAGING, *rel.split("/"))
    if os.path.exists(staged):
        cands["eba-full-taxonomy-4.3"] = open(staged, "rb").read()
    current = os.path.join(MIRROR, *rel.split("/"))
    if os.path.exists(current):
        cands["mirror-current"] = open(current, "rb").read()
    return cands


def main():
    reqs = collect_requirements()
    print("unversioned-ish targets with required ids:", len(reqs), flush=True)
    report, changed = [], 0
    for rel in sorted(reqs):
        ids = reqs[rel]
        if not ids:
            continue
        cands = candidates_for(rel)
        if not cands:
            report.append({"mirror_path": rel, "required_ids": len(ids),
                           "status": "NO_CANDIDATE"})
            continue
        best, best_cov, best_missing = None, -1, None
        coverage = {}
        for tag, body in cands.items():
            defined = set(ID_RE.findall(body.decode("utf-8", "replace")))
            cov = len(ids & defined)
            coverage[tag] = cov
            if cov > best_cov or (cov == best_cov and best is not None
                                  and tag > best):  # tie -> newest label
                best, best_cov = tag, cov
                best_missing = sorted(ids - defined)
        dst = os.path.join(MIRROR, *rel.split("/"))
        cur = open(dst, "rb").read() if os.path.exists(dst) else None
        if cands[best] != cur:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(cands[best])
            changed += 1
        report.append({
            "mirror_path": rel,
            "required_ids": len(ids),
            "chosen_source": best,
            "coverage": coverage,
            "covered": best_cov,
            "missing_ids": best_missing,
            "sha256": hashlib.sha256(cands[best]).hexdigest(),
            "status": "OK" if not best_missing else "PARTIAL",
        })
    out = {
        "schema": "bankcall-g1c-eba-dict-bestfit/v1",
        "purpose": "Per-file selection of official EBA dictionary bytes that "
                   "satisfy all versioned linkbase fragment references",
        "targets": report,
        "files_replaced": changed,
        "incomplete": [r for r in report if r["status"] != "OK"],
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    ok = sum(1 for r in report if r["status"] == "OK")
    print("targets:", len(report), "fully covered:", ok,
            "partial/none:", len(report) - ok, "files replaced:", changed)


if __name__ == "__main__":
    sys.exit(main())
