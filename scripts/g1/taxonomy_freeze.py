"""G1-C.2 - Freeze official BdE DTS resources into a local provenance manifest.

Reads the frozen mirror tree produced from the official BdE taxonomy packs
(g0_acquisition/dts_mirror) and emits a manifest with SHA-256 per resource so
that every DTS document Arelle loads is traceable to an official byte string.

Mirror sources:
  * Banco de España official packs (es-bde, es-bde-aux, eu-eurofiling).
  * EBA official taxonomy packages (live first-party publication):
    Reporting Framework 4.3 "Full taxonomy" plus dictionary packages
    2.7/3.0/3.1/3.2 - needed because eba.europa.eu/eu/fr/xbrl/crr/** is
    decommissioned (HTTP 403) and the BdE DTS legitimately references it.
  * Wayback-archived captures of the exact official EBA URLs for resources
    not shipped in any official package (see eba-crr-recovery.json).
  * xbrl.org PWD table-linkbase specification schema (immutable spec).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIRROR = os.path.join(REPO, "g0_acquisition", "dts_mirror")
PACKS = {
    "es-bde": "g0_acquisition/es-bde.zip",
    "es-bde-aux": "g0_acquisition/es-bde-aux.zip",
    "eu-eurofiling": "g0_acquisition/eu-eurofiling.zip",
    "eba-txp-2.7.0.1": "g0_acquisition/eba-taxonomy-packages-2.7.0.1.bin",
    "eba-txp-3.0": "g0_acquisition/eba-txp-3.0.zip",
    "eba-txp-3.1": "g0_acquisition/eba-txp-3.1.zip",
    "eba-txp-3.2": "g0_acquisition/eba-txp-3.2.zip",
    "eba-full-taxonomy-4.3": "g0_acquisition/eba-full-taxonomy-4.3.zip",
    "eba-dict-2.7.0.0": "g0_acquisition/eba-dict-2.7.0.0.zip",
    "eba-dict-3.0": "g0_acquisition/eba-dict-3.0.zip",
    "eba-dict-3.1": "g0_acquisition/eba-dict-3.1.zip",
    "eba-dict-3.2": "g0_acquisition/eba-dict-3.2.zip",
}
PACK_SOURCES = {
    "es-bde": "https://www.bde.es/es/fr/documentacion/taxonomias/es-bde/es-bde.zip",
    "es-bde-aux": "https://www.bde.es/es/fr/documentacion/taxonomias/es-bde-aux/es-bde-aux.zip",
    "eu-eurofiling": "https://www.bde.es/es/fr/documentacion/taxonomias/eu-eurofiling/eu-eurofiling.zip",
    "eba-txp-2.7.0.1": "https://www.eba.europa.eu/sites/default/files/2023-11/"
                       "1091d42c-4e51-4c43-bc02-86897db722ea/"
                       "Taxonomy%20Packages.2.7.0.1",
    "eba-txp-3.0": "https://www.eba.europa.eu/sites/default/files/2023-11/"
                   "36f10c02-f33b-439f-8b3e-d7076b7bd3c6/"
                   "Taxonomy%20Package%203.0.1.Errata3.zip",
    "eba-txp-3.1": "https://www.eba.europa.eu/sites/default/files/2023-11/"
                   "f3eaedf0-2713-4fb1-b136-99e5a9025158/Taxonomy%20Package.zip",
    "eba-txp-3.2": "https://www.eba.europa.eu/sites/default/files/2023-11/"
                   "3df42118-31da-4fd5-9678-7fa05f9cec64/"
                   "Taxonomy%20Package%20V3.2.phase3_.zip",
    "eba-full-taxonomy-4.3": "https://ebprstaewspublic01.blob.core.windows.net/"
                             "public/tools-prod/documents/Big_Files/files/"
                             "Reporting%20framework%204.3/Full%20taxonomy.zip",
    "eba-dict-2.7.0.0": "extracted from eba-taxonomy-packages-2.7.0.1",
    "eba-dict-3.0": "extracted from eba-txp-3.0",
    "eba-dict-3.1": "extracted from eba-txp-3.1",
    "eba-dict-3.2": "extracted from eba-txp-3.2",
}
RECOVERY = os.path.join(REPO, "evidence", "g1", "eba-crr-recovery.json")
BESTFIT = os.path.join(REPO, "evidence", "g1", "eba-dict-bestfit.json")
OUT = os.path.join(REPO, "evidence", "g1", "dts-freeze-manifest.json")

# Files sourced from a specific official package outside the recovery/best-fit
# evidence files (explicit per-file provenance).
EXTRA_ORIGINS = {
    "www.eba.europa.eu/eu/fr/xbrl/crr/dict/dom/ba/mem-lab-codes.xml":
        "EBA_OFFICIAL_TAXONOMY_PACKAGE:eba-dict-3.2",
    "www.eba.europa.eu/eu/fr/xbrl/crr/dict/dom/cu/mem-lab-codes.xml":
        "EBA_OFFICIAL_TAXONOMY_PACKAGE:eba-dict-3.2",
    "www.eurofiling.info/eu/fr/xbrl/ext/model.xsd":
        "LIVE_OFFICIAL:eurofiling.info",
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resource_origin(rel):
    if rel in EXTRA_ORIGINS:
        return EXTRA_ORIGINS[rel]
    if rel.startswith("www.eba.europa.eu/"):
        # bulk of the transitive crr closure was copied from the live official
        # EBA Reporting Framework 4.3 "Full taxonomy" package; recovery and
        # best-fit evidence override per file below
        return "EBA_OFFICIAL_TAXONOMY_PACKAGE:eba-full-taxonomy-4.3"
    if rel.startswith("www.xbrl.org/"):
        return "XBRL_ORG_SPECIFICATION"
    if rel.startswith("www.eurofiling.info/"):
        return "BDE_OFFICIAL_PACK:eu-eurofiling"
    return "BDE_OFFICIAL_PACK:es-bde"


def main():
    packs = {}
    for name, rel in PACKS.items():
        p = os.path.join(REPO, rel)
        packs[name] = {
            "source_url": PACK_SOURCES[name],
            "local_path": rel,
            "bytes": os.path.getsize(p),
            "sha256": sha256_file(p),
        }

    recovery_by_path = {}
    if os.path.exists(RECOVERY):
        rec = json.load(open(RECOVERY, encoding="utf-8"))
        for r in rec.get("resources", []):
            recovery_by_path[r["mirror_path"]] = r

    bestfit_by_path = {}
    if os.path.exists(BESTFIT):
        bf = json.load(open(BESTFIT, encoding="utf-8"))
        for t in bf.get("targets", []):
            if t.get("chosen_source") and t["chosen_source"] != "mirror-current":
                bestfit_by_path[t["mirror_path"]] = t

    resources = []
    for root, _dirs, files in os.walk(MIRROR):
        for fn in sorted(files):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, MIRROR).replace(os.sep, "/")
            if rel.startswith("META-INF/"):
                continue
            host, _, path = rel.partition("/")
            entry = {
                "mirror_path": rel,
                "canonical_url": "http://%s/%s" % (host, path),
                "canonical_url_https": "https://%s/%s" % (host, path),
                "bytes": os.path.getsize(full),
                "sha256": sha256_file(full),
                "origin": resource_origin(rel),
            }
            r = recovery_by_path.get(rel)
            if r:
                entry["origin"] = r["origin"]
                for k in ("archive_url", "archive_timestamp", "archive_digest",
                          "archive_http_status", "package"):
                    if r.get(k) is not None:
                        entry[k] = r[k]
            bt = bestfit_by_path.get(rel)
            if bt:
                entry["origin"] = "EBA_OFFICIAL_TAXONOMY_PACKAGE:%s" % bt["chosen_source"]
                entry["bestfit_coverage"] = bt.get("coverage")
                if bt.get("missing_ids"):
                    entry["dangling_official_ids"] = bt["missing_ids"]
            resources.append(entry)
    resources.sort(key=lambda r: r["mirror_path"])

    manifest = {
        "schema": "bankcall-g1c-dts-freeze-manifest/v1",
        "purpose": "Frozen official DTS resources for G1-C; every resource hash-pinned",
        "packs": packs,
        "mirror_root": "g0_acquisition/dts_mirror",
        "eba_recovery_evidence": "evidence/g1/eba-crr-recovery.json",
        "resource_count": len(resources),
        "resources": resources,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print("resources:", len(resources))
    for n, p in packs.items():
        print(n, p["sha256"][:16], p["bytes"])


if __name__ == "__main__":
    sys.exit(main())
