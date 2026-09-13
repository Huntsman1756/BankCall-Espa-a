"""G1-C remediation (final): resolve every EBA URL the frozen BdE DTS
references, with per-file provenance.

Sources, in preference order:
  1. Wayback-archived capture of the *exact* official URL already present in
     the mirror (fetched by fetch_eba_crr_wayback.py).  Provenance is completed
     with a fresh CDX metadata lookup (capture timestamp/digest).
  2. Live official EBA "Full taxonomy" reporting-framework 4.3 package
     (first-party bytes published under the same URL space; the authoritative
     current publication of that URL).
  3. Fresh Wayback download (bounded) for anything left.
  4. no_capture — recorded, never silently skipped.

The live eba.europa.eu/eu/fr/xbrl/crr/** tree itself returns HTTP 403
(decommissioned); nothing is fetched from it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
from urllib.parse import quote

import requests

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIRROR = os.path.join(REPO, "g0_acquisition", "dts_mirror")
STAGING = os.path.join(REPO, "g0_acquisition", "eba_pack_4.3_staging",
                       "Full_taxonomy")
PACK_DESC = {
    "package": "EBA Reporting Framework 4.3 - Full taxonomy",
    "package_url": "https://ebprstaewspublic01.blob.core.windows.net/public/"
                   "tools-prod/documents/Big_Files/files/Reporting%20framework"
                   "%204.3/Full%20taxonomy.zip",
    "package_page": "https://eba.europa.eu/risk-and-data-analysis/reporting/"
                    "reporting-frameworks/reporting-framework-43",
    "note": "first-party EBA publication; files ship under the official "
            "www.eba.europa.eu URL space",
}
SCAN_ROOTS = [
    os.path.join(MIRROR, "www.bde.es", "es", "fr", "xbrl", p)
    for p in ("fws/publicos/circ-4-2017", "dict", "main", "eu-main", "esrs")
] + [os.path.join(MIRROR, "www.eba.europa.eu")]  # transitive refs
OUT = os.path.join(REPO, "evidence", "g1", "eba-crr-recovery.json")

URL_RE = re.compile(
    rb'(?:xlink:href|schemaLocation)="(https?://www\.eba\.europa\.eu/[^"#]+)')


def needed_urls():
    urls = set()
    for root in SCAN_ROOTS:
        if not os.path.isdir(root):
            continue
        for r, _d, files in os.walk(root):
            for fn in files:
                try:
                    data = open(os.path.join(r, fn), "rb").read()
                except OSError:
                    continue
                urls.update(m.decode("ascii") for m in URL_RE.findall(data))
    return sorted(urls)


def cdx_lookup(session, url, retries=2):
    """Best available 200-capture metadata for *url* (bare-host fallback)."""
    for u in (url, "http://" + url[len("http://www."):]
              if url.startswith("http://www.") else url):
        q = ("https://web.archive.org/cdx/search/cdx?url=%s&output=json"
             "&filter=statuscode:200&collapse=digest&limit=5"
             % quote(u, safe=""))
        for attempt in range(retries):
            try:
                r = session.get(q, timeout=45)
                if r.status_code == 200 and r.text.strip():
                    try:
                        rows = r.json()
                    except ValueError:
                        rows = []
                    if len(rows) >= 2:
                        hdr, row = rows[0], rows[1]
                        ts = row[hdr.index("timestamp")]
                        dig = row[hdr.index("digest")]
                        return ("https://web.archive.org/web/%sid_/%s"
                                % (ts, u), ts, dig)
            except requests.RequestException:
                pass
            time.sleep(2 * (attempt + 1))
    return None


def main():
    urls = needed_urls()
    print("needed eba urls:", len(urls), flush=True)
    session = requests.Session()
    session.verify = True
    session.headers["User-Agent"] = "BankCall-G1C (official taxonomy recovery)"

    records, missing = [], []
    for i, url in enumerate(urls):
        rel = url.split("://", 1)[1]
        dest = os.path.join(MIRROR, *rel.split("/"))
        staged = os.path.join(STAGING, *rel.split("/"))

        if os.path.exists(dest):
            body = open(dest, "rb").read()
            cap = cdx_lookup(session, url)
            rec = {
                "original_url": url,
                "origin": "WAYBACK_ARCHIVED_OFFICIAL_COPY",
                "mirror_path": rel,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
            if cap:
                rec.update({"archive_url": cap[0], "archive_timestamp": cap[1],
                            "archive_digest": cap[2], "archive_http_status": 200})
            else:
                rec["provenance_note"] = ("bytes present in mirror from an "
                                          "earlier Wayback run; capture "
                                          "metadata unavailable")
            records.append(rec)
            continue

        if os.path.exists(staged):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(staged, dest)
            body = open(dest, "rb").read()
            records.append({
                "original_url": url,
                "origin": "EBA_OFFICIAL_TAXONOMY_PACKAGE",
                "package": PACK_DESC,
                "mirror_path": rel,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            })
            continue

        cap = cdx_lookup(session, url)
        if cap:
            try:
                r = session.get(cap[0], timeout=120)
                if r.status_code == 200:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as fh:
                        fh.write(r.content)
                    records.append({
                        "original_url": url,
                        "origin": "WAYBACK_ARCHIVED_OFFICIAL_COPY",
                        "archive_url": cap[0], "archive_timestamp": cap[1],
                        "archive_digest": cap[2],
                        "archive_http_status": r.status_code,
                        "mirror_path": rel, "bytes": len(r.content),
                        "sha256": hashlib.sha256(r.content).hexdigest(),
                    })
                    continue
            except requests.RequestException:
                pass
        missing.append(url)
        print("  UNRESOLVED", url, flush=True)

    records.sort(key=lambda r: r["original_url"])
    by_origin = {}
    for r in records:
        by_origin[r["origin"]] = by_origin.get(r["origin"], 0) + 1
    out = {
        "schema": "bankcall-g1c-eba-crr-recovery/v1",
        "purpose": "Resolve every EBA URL referenced by the frozen BdE DTS "
                   "with per-file provenance",
        "official_host_status": "eba.europa.eu/eu/fr/xbrl/crr/** returns "
                                "HTTP 403 (verified); non-crr paths still serve",
        "resources": records,
        "unresolved": missing,
        "counts": {"needed": len(urls), "resolved": len(records),
                   "unresolved": len(missing), "by_origin": by_origin},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print("resolved:", len(records), by_origin, "unresolved:", len(missing))


if __name__ == "__main__":
    sys.exit(main())
