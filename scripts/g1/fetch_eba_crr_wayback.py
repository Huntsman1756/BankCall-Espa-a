"""G1-C remediation: recover dead official EBA CRR dictionary files from the
Wayback Machine.

The official host eba.europa.eu/eu/fr/xbrl/crr/** is decommissioned (HTTP 403
on every resource) and is not shipped in any official taxonomy pack.  The
Banco de España publicos DTS legitimately references it (dimension defaults
and domain members in def linkbases).

Policy (user-approved): fetch Wayback captures of the *exact official URLs*
and record explicit provenance:
  origin            = WAYBACK_ARCHIVED_OFFICIAL_COPY
  original_url      = http://www.eba.europa.eu/...  (the URL the DTS references)
  archive_url       = https://web.archive.org/web/<ts>id_/<original>
  archive_timestamp = Wayback capture timestamp
  archive_digest    = Wayback-recorded content digest (SHA-1, base32) when present
  sha256            = SHA-256 of retrieved bytes (BankCall canonical hash)

Writes the bytes into the frozen mirror at g0_acquisition/dts_mirror/
www.eba.europa.eu/... so the TXP catalog resolves them offline.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import quote

import requests

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIRROR = os.path.join(REPO, "g0_acquisition", "dts_mirror")
SCAN_ROOTS = [
    os.path.join(MIRROR, "www.bde.es", "es", "fr", "xbrl", "fws", "publicos", "circ-4-2017"),
    os.path.join(MIRROR, "www.bde.es", "es", "fr", "xbrl", "dict"),
    os.path.join(MIRROR, "www.bde.es", "es", "fr", "xbrl", "main"),
    os.path.join(MIRROR, "www.bde.es", "es", "fr", "xbrl", "eu-main"),
    os.path.join(MIRROR, "www.bde.es", "es", "fr", "esrs"),
    os.path.join(MIRROR, "www.eba.europa.eu"),
]
OUT = os.path.join(REPO, "evidence", "g1", "eba-crr-wayback.json")

URL_RE = re.compile(rb'(?:xlink:href|schemaLocation)="(https?://www\.eba\.europa\.eu/[^"#]+)')


def needed_urls():
    urls = set()
    for root in SCAN_ROOTS:
        if not os.path.isdir(root):
            continue
        for r, _d, files in os.walk(root):
            for fn in files:
                p = os.path.join(r, fn)
                try:
                    data = open(p, "rb").read()
                except OSError:
                    continue
                for m in URL_RE.findall(data):
                    urls.add(m.decode("ascii"))
    return sorted(urls)


def _cdx(session, url, extra, yr="2013", to="2023"):
    q = ("https://web.archive.org/cdx/search/cdx?url=%s&output=json"
         "&filter=statuscode:200&collapse=digest&from=%s&to=%s&limit=5%s"
         % (quote(url, safe=""), yr, to, extra))
    for attempt in range(4):
        try:
            r = session.get(q, timeout=60)
            if r.status_code == 200 and r.text.strip():
                try:
                    return r.json()
                except ValueError:
                    pass
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    return []


def wayback_capture(session, url):
    """Return (capture_url, timestamp, digest) for the best available capture."""
    rows = _cdx(session, url, "&filter=mimetype:text/xml")
    if len(rows) < 2:
        rows = _cdx(session, url, "")
    if len(rows) < 2 and url.startswith("http://www."):
        # some captures are stored under the bare host
        alt = "http://" + url[len("http://www."):]
        rows = _cdx(session, alt, "")
        if len(rows) >= 2:
            url = alt
    if len(rows) < 2:
        return None
    hdr = rows[0]
    ts_i, dig_i = hdr.index("timestamp"), hdr.index("digest")
    row = rows[1]
    ts, digest = row[ts_i], row[dig_i]
    cap_url = "https://web.archive.org/web/%sid_/%s" % (ts, url)
    return cap_url, ts, digest


def main():
    urls = needed_urls()
    print("needed eba urls:", len(urls))
    session = requests.Session()
    session.verify = True
    session.headers["User-Agent"] = "BankCall-G1C-research (archived official copy retrieval)"

    records, missing = [], []
    done = set()
    if os.path.exists(OUT):
        prev = json.load(open(OUT, encoding="utf-8"))
        done = {r["original_url"] for r in prev.get("resources", [])}
        records = prev.get("resources", [])
        print("resuming; already fetched:", len(done))
    for i, url in enumerate(urls):
        rel = url.split("://", 1)[1]
        dest = os.path.join(MIRROR, *rel.split("/"))
        if url in done:
            continue
        if os.path.exists(dest):
            # downloaded by an earlier interrupted run; provenance fields
            # beyond the byte hash are not recoverable
            body = open(dest, "rb").read()
            records.append({
                "original_url": url,
                "origin": "WAYBACK_ARCHIVED_OFFICIAL_COPY",
                "archive_url": None,
                "archive_timestamp": None,
                "archive_digest": None,
                "archive_http_status": None,
                "provenance_note": "bytes present in mirror from an interrupted "
                                   "earlier run; capture metadata unavailable",
                "mirror_path": rel,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            })
            continue
        cap = wayback_capture(session, url)
        if cap is None:
            missing.append(url)
            print("  NOCAPTURE", url, flush=True)
            continue
        cap_url, ts, digest = cap
        body = None
        for attempt in range(3):
            try:
                r = session.get(cap_url, timeout=120)
                if r.status_code == 200:
                    body = r.content
                    break
            except requests.RequestException:
                pass
            time.sleep(3 * (attempt + 1))
        if body is None:
            missing.append(url)
            print("  FETCHFAIL", url, flush=True)
            continue
        rel = url.split("://", 1)[1]
        dest = os.path.join(MIRROR, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(body)
        records.append({
            "original_url": url,
            "origin": "WAYBACK_ARCHIVED_OFFICIAL_COPY",
            "archive_url": cap_url,
            "archive_timestamp": ts,
            "archive_digest": digest,
            "archive_http_status": r.status_code,
            "mirror_path": rel,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })
        print("[%d/%d] %s <- %s" % (i + 1, len(urls), url.rsplit('/', 1)[-1], ts), flush=True)
        time.sleep(0.25)

    records.sort(key=lambda r: r["original_url"])
    out = {
        "schema": "bankcall-g1c-eba-crr-wayback/v1",
        "purpose": "Recover decommissioned official EBA CRR dictionary resources",
        "official_host_status": "eba.europa.eu/eu/fr/xbrl/crr/** returns HTTP 403 (verified)",
        "resources": records,
        "no_capture": missing,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print("fetched:", len(records), "no_capture:", len(missing))


if __name__ == "__main__":
    sys.exit(main())
