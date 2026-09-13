"""G1-C.1 - Taxonomy resolution from each XBRL instance's own schemaRef.

For every .xbrl artifact in the frozen ten-period corpus:
  * download the instance payload once (frozen under g0_acquisition/xbrl_instances),
  * extract the schemaRef from the instance itself,
  * resolve the taxonomy generation from the entry-point URL,
  * record URL / final URL / bytes / SHA-256 / retrieval timestamp / TLS status.

No period -> taxonomy lookup table is used; the instance's schemaRef is the
source of truth.
"""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import sys
import time
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from taxonomy_dts import GENERATION_NAMES, extract_schemaref, generation_from_entrypoint

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CATALOG = os.path.join(REPO, "evidence", "g1", "catalog.json")
INSTANCES_DIR = os.path.join(REPO, "g0_acquisition", "xbrl_instances")
OUT = os.path.join(REPO, "evidence", "g1", "taxonomy-registry.json")

GENERATION_URLBASE = {
    "publicos_2018_01": "https://www.bde.es/es/fr/xbrl/fws/publicos/circ-4-2017/2018-01-01/",
    "publicos_2018_12": "https://www.bde.es/es/fr/xbrl/fws/publicos/circ-4-2017/2018-12-01/",
    "publicos_2023_03": "https://www.bde.es/es/fr/xbrl/fws/publicos/circ-4-2017/2023-03-01/",
}


def fetch_instance(session, url, dest):
    r = session.get(url, timeout=120, verify=True)
    body = r.content
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(body)
    return {
        "source_url": url,
        "final_url": r.url,
        "status": r.status_code,
        "redirects": [h.status_code for h in r.history],
        "content_type": r.headers.get("Content-Type"),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "tls_verified": r.url.startswith("https"),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main():
    catalog = json.load(open(CATALOG, encoding="utf-8"))
    frozen = list(catalog["evaluation_period_ids"])

    artifacts = []
    for p in catalog["periods"]:
        if p["id"] not in frozen:
            continue
        for st in p["states"]:
            for a in st["artifacts"]:
                if a["extension"] == ".xbrl":
                    artifacts.append({
                        "period": p["id"],
                        "statement": st["id"],
                        "statement_group": st.get("group"),
                        "url": a["url"],
                    })

    session = requests.Session()
    records = []
    for i, art in enumerate(artifacts):
        dest = os.path.join(INSTANCES_DIR, art["period"], "%s_%s.xbrl" % (art["statement"], art["period"]))
        prov = fetch_instance(session, art["url"], dest)
        body = open(dest, "rb").read()
        sref = extract_schemaref(body)
        gen = generation_from_entrypoint(sref) if sref else None
        records.append({
            **art,
            "instance": prov,
            "local_payload": os.path.relpath(dest, REPO).replace(os.sep, "/"),
            "schemaRef": sref,
            "entry_point": sref,
            "taxonomy_generation": gen,
            "resolution": "SCHEMAREF_RESOLVED" if gen else ("SCHEMAREF_UNMAPPED" if sref else "SCHEMAREF_MISSING"),
        })
        print("[%d/%d] %s %s -> %s" % (i + 1, len(artifacts), art["period"], art["statement"], gen), flush=True)

    generations = {}
    for r in records:
        g = generations.setdefault(r["taxonomy_generation"], {
            "url_base": GENERATION_URLBASE.get(r["taxonomy_generation"]),
            "entry_points": set(), "statements": set(), "periods": set(), "artifact_count": 0})
        g["entry_points"].add(r["entry_point"])
        g["statements"].add(r["statement"])
        g["periods"].add(r["period"])
        g["artifact_count"] += 1
    gen_out = {g: {**v, "entry_points": sorted(v["entry_points"]),
                   "statements": sorted(v["statements"]),
                   "periods": sorted(v["periods"])}
               for g, v in sorted(generations.items(), key=lambda kv: str(kv[0]))}

    out = {
        "schema": "bankcall-g1c-taxonomy-registry/v1",
        "resolution_source": "instance schemaRef (no period->taxonomy table)",
        "artifact_count": len(records),
        "periods": frozen,
        "generations": gen_out,
        "artifacts": records,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print("generations:", {g: v["artifact_count"] for g, v in gen_out.items()})


if __name__ == "__main__":
    sys.exit(main())
