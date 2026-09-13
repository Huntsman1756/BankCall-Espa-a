"""G1-C orchestrator: DTS fingerprints + Arelle native diff + fail-closed
classification + evidence.

Runs over the frozen official DTS mirror (offline).  Produces:
  evidence/g1/concept-mapping.json     - per-concept classification
  evidence/g1/g1-c-evidence.json       - gates, diagnostics, hashes
  evidence/g1/versioning/*.xml         - Arelle versioning reports (large; hashed)

Canonical runs MUST set PYTHONHASHSEED=0: Arelle's versioning engine iterates
hash sets whose order varies with per-process string-hash randomization,
which would make namespaceRename/roleChange evidence maps non-deterministic.

Gate semantics are computed, never hardcoded:
  TAXONOMY_AUTO_RESOLVABLE     every frozen artifact's schemaRef resolved to a
                               generation AND that generation's DTS loads
                               completely (zero load failures) offline.
  CROSS_TAXONOMY_CONCEPT_MAPPING
                               every concept in both generation pairs classified
                               exactly once into the seven categories, with
                               evidence; the Arelle native diff completed.
  NO_SILENT_SEMANTIC_DRIFT     every shared-QName concept fingerprint compared;
                               all material differences surfaced in
                               changed_fields / versioning events.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from taxonomy_dts import (REPO, MIRROR, make_controller, load_dts,
                          load_failures, fingerprint_dts, sha256_json,
                          canonical_json)
from taxonomy_classify import classify_concepts, summarize, CATEGORIES

REGISTRY = os.path.join(REPO, "evidence", "g1", "taxonomy-registry.json")
OUT_MAP = os.path.join(REPO, "evidence", "g1", "concept-mapping.json")
OUT_EVID = os.path.join(REPO, "evidence", "g1", "g1-c-evidence.json")
OUT_FP = os.path.join(REPO, "evidence", "g1", "dts-fingerprints.json")
VERS_DIR = os.path.join(REPO, "evidence", "g1", "versioning")

GENERATION_ORDER = ["publicos_2018_01", "publicos_2018_12", "publicos_2023_03"]
DIFF_PAIRS = [("publicos_2018_01", "publicos_2018_12"),
              ("publicos_2018_12", "publicos_2023_03")]

VER_NS = {
    "vercu": "http://xbrl.org/2013/versioning-concept-use",
    "vercd": "http://xbrl.org/2013/versioning-concept-details",
    "vercb": "http://xbrl.org/2010/versioning-concept-basic",
    "verce": "http://xbrl.org/2010/versioning-concept-extended",
    "ver": "http://xbrl.org/2013/versioning-base",
}


def merge_fingerprints(per_ep):
    """Union of entry-point fingerprints into a generation fingerprint.

    Concepts appearing in several entry points are merged; scalar conflicts are
    recorded (never silently dropped).
    """
    merged = {}
    conflicts = []
    for ep, fp in per_ep.items():
        for qn, c in fp["concepts"].items():
            if qn not in merged:
                merged[qn] = dict(c)
                merged[qn]["entry_points"] = [ep]
                continue
            m = merged[qn]
            m["entry_points"].append(ep)
            for k, v in c.items():
                if k == "entry_points":
                    continue
                if k not in m:
                    m[k] = v
                elif m[k] != v:
                    if k in ("presentation", "calculation", "dimensions") \
                            and isinstance(v, dict):
                        for lr, d in v.items():
                            m[k].setdefault(lr, d)
                    elif k in ("labels", "references") and isinstance(v, list):
                        # entry points attach different label/reference
                        # subsets of the same concept -> union, dedup
                        seen = {canonical_json(x) for x in m[k]}
                        for item in v:
                            if canonical_json(item) not in seen:
                                m[k].append(item)
                                seen.add(canonical_json(item))
                        m[k].sort(key=canonical_json)
                    else:
                        conflicts.append({"qname": qn, "field": k,
                                          "entry_point": ep})
    return merged, conflicts


def parse_versioning_report(path):
    """Extract concept events + namespace/role rename evidence from an
    Arelle versioning report."""
    tree = etree.parse(path)
    events = []
    renames = {}
    counts = {}
    ns_renames = {}
    role_changes = {}
    for el in tree.getroot().iter():
        if not isinstance(el.tag, str):
            continue
        ln = etree.QName(el).localname
        if ln == "namespaceRename":
            fu = tu = None
            for ch in el.iter():
                cln = etree.QName(ch).localname
                if cln == "fromURI":
                    fu = ch.get("value")
                elif cln == "toURI":
                    tu = ch.get("value")
            if fu and tu:
                ns_renames[fu] = tu
                counts[ln] = counts.get(ln, 0) + 1
            continue
        if ln == "roleChange":
            fr = tr = None
            for ch in el.iter():
                cln = etree.QName(ch).localname
                if cln == "fromRoleURI":
                    fr = ch.get("value")
                elif cln == "toRoleURI":
                    tr = ch.get("value")
            if fr and tr:
                role_changes[fr] = tr
                counts[ln] = counts.get(ln, 0) + 1
            continue
        if "versioning" not in el.tag:
            continue
        if not ln.startswith("concept") and "Concept" not in ln:
            continue
        counts[ln] = counts.get(ln, 0) + 1
        fq = tq = None
        for ch in el.iter():
            if not isinstance(ch.tag, str):
                continue
            cln = etree.QName(ch).localname
            if cln == "fromConcept":
                fq = ch.get("name")
            elif cln == "toConcept":
                tq = ch.get("name")
            elif cln == "concept" and fq is None:
                fq = ch.get("name")
        events.append({"event": ln, "from": fq, "to": tq})
        if ln == "conceptRename" and fq and tq:
            renames[fq] = tq
    return {"events": events, "renames": renames, "event_counts": counts,
            "ns_renames": ns_renames, "role_changes": role_changes}


def _close(mx):
    try:
        mx.close()
    except Exception:
        pass


def _report_hash(path):
    """SHA-256 of the versioning report excluding the line-2 generated-at
    timestamp comment Arelle emits."""
    raw = open(path, "rb").read()
    lines = raw.split(b"\n")
    if len(lines) > 1 and b"Generated by Arelle" in lines[1]:
        del lines[1]
    return hashlib.sha256(b"\n".join(lines)).hexdigest()


def _jsonable(o):
    """Arelle containers may carry non-str dict keys (None, QNames);
    normalize recursively for JSON evidence."""
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(x) for x in o]
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    return str(o)


def run(output_suffix=""):
    registry = json.load(open(REGISTRY, encoding="utf-8"))
    generations = registry["generations"]

    gen_fp = {}          # generation -> merged concept fingerprints
    gen_diag = {}        # generation -> diagnostics

    # --- per-generation fingerprints: one controller per generation so Arelle
    #     does not keep prior DTS objects alive
    for gen in GENERATION_ORDER:
        cntlr = make_controller(offline=True)
        eps = generations.get(gen, {}).get("entry_points", [])
        per_ep = {}
        diag_eps = {}
        for ep_url in eps:
            ep_name = ep_url.rsplit("/", 1)[-1]
            mx, recs = load_dts(cntlr, ep_url)
            fails = load_failures(recs)
            fp = fingerprint_dts(mx)
            per_ep[ep_name] = fp
            diag_eps[ep_name] = {
                "entry_point_url": ep_url,
                "docs_loaded": len(mx.urlDocs),
                "concepts": len(mx.qnameConcepts),
                "relationship_sets": len(mx.relationshipSets),
                "load_failures": len(fails),
                "load_failure_files": sorted({f["file"] for f in fails if f["file"]}),
            }
            _close(mx)
        merged, conflicts = merge_fingerprints(per_ep)
        gen_fp[gen] = merged
        gen_diag[gen] = {
            "entry_points": diag_eps,
            "merged_concepts": len(merged),
            "merge_conflicts": conflicts,
        }
        try:
            cntlr.close()
        except Exception:
            pass
        print("%s: %d concepts (%d merge conflicts)" % (gen, len(merged), len(conflicts)), flush=True)

    # --- Arelle native diff per entry point per pair
    os.makedirs(VERS_DIR, exist_ok=True)
    from arelle.ModelVersReport import ModelVersReport
    diffs = {}
    for g_from, g_to in DIFF_PAIRS:
        cntlr = make_controller(offline=True)
        eps_from = {u.rsplit('/', 1)[-1]: u for u in generations[g_from]["entry_points"]}
        eps_to = {u.rsplit('/', 1)[-1]: u for u in generations[g_to]["entry_points"]}
        pair_key = "%s__%s" % (g_from, g_to)
        diffs[pair_key] = {}
        for ep in sorted(set(eps_from) & set(eps_to)):
            mx_f, _rf = load_dts(cntlr, eps_from[ep])
            mx_t, _rt = load_dts(cntlr, eps_to[ep])
            rp = os.path.join(VERS_DIR, "%s_%s_%s.xml" % (ep.replace('.xsd', ''), g_from, g_to))
            try:
                vr = ModelVersReport(mx_t)
                vr.diffDTSes(rp, mx_f, mx_t)
                ok = os.path.exists(rp)
            except Exception as exc:
                ok = False
                diffs[pair_key][ep] = {"status": "DIFF_ERROR", "error": str(exc)[:300]}
                _close(mx_f); _close(mx_t)
                continue
            diffs[pair_key][ep] = {
                "status": "OK" if ok else "NO_OUTPUT",
                "report_path": os.path.relpath(rp, REPO).replace(os.sep, "/"),
                # hash excludes Arelle's generated-at timestamp comment so
                # identical runs produce identical digests
                "report_sha256": _report_hash(rp) if ok else None,
                "ns_renames": dict(getattr(vr, "namespaceRenameFromURI", {})),
                "role_changes": dict(getattr(vr, "roleChangeFromURI", {})),
                "parsed": parse_versioning_report(rp) if ok else None,
            }
            _close(mx_f); _close(mx_t)
            ec = diffs[pair_key][ep].get("parsed", {}).get("event_counts", {})
            print("diff %s %s->%s: %s" % (ep, g_from[-6:], g_to[-6:], dict(list(ec.items())[:6])), flush=True)
        try:
            cntlr.close()
        except Exception:
            pass

    # --- classification per pair (union fingerprints + rename evidence)
    mappings = {}
    for g_from, g_to in DIFF_PAIRS:
        pair_key = "%s__%s" % (g_from, g_to)
        renames = {}
        ns_to_from = {}
        role_to_from = {}
        ns_pairs = set()
        for ep, d in diffs[pair_key].items():
            renames.update(d.get("parsed", {}).get("renames", {}))
            for f, t in d.get("ns_renames", {}).items():
                ns_to_from[t] = f
                ns_pairs.add((f, t))
            for f, t in d.get("role_changes", {}).items():
                role_to_from[t] = f
        mapping = classify_concepts(gen_fp[g_from], gen_fp[g_to], renames,
                                    ns_map=ns_to_from, role_map=role_to_from,
                                    ns_pairs=ns_pairs)
        mappings[pair_key] = {
            "from_generation": g_from,
            "to_generation": g_to,
            "mapping": mapping,
            "summary": summarize(mapping),
        }
        print("%s -> %s: %s" % (g_from, g_to, mappings[pair_key]["summary"]), flush=True)

    # --- fingerprints artifact (per-generation merged, hash-pinned)
    fp_out = {
        "schema": "bankcall-g1c-dts-fingerprints/v1",
        "generations": {
            g: {"concept_count": len(fp), "concepts": fp}
            for g, fp in gen_fp.items()
        },
    }
    with open(OUT_FP, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(fp_out, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    fp_sha = hashlib.sha256(open(OUT_FP, 'rb').read()).hexdigest()

    map_out = {
        "schema": "bankcall-g1c-concept-mapping/v1",
        "method": "BankCall fail-closed classification over structural fingerprints; "
                  "Arelle versioning reports used as evidence only",
        "categories": list(CATEGORIES),
        "pairs": mappings,
    }
    with open(OUT_MAP, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(map_out, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    map_sha = hashlib.sha256(open(OUT_MAP, 'rb').read()).hexdigest()

    # --- gates, computed
    all_resolved = all(
        a.get("taxonomy_generation") and a.get("resolution") == "SCHEMAREF_RESOLVED"
        for a in registry["artifacts"])
    dts_complete = all(
        d["load_failures"] == 0
        for g in gen_diag.values() for d in g["entry_points"].values())
    diffs_ok = all(
        d.get("status") == "OK"
        for v in diffs.values() for d in v.values())
    all_classified = all(
        set(m["mapping"][q]["classification"] for q in m["mapping"]) <= set(CATEGORIES)
        and len(m["mapping"]) > 0
        for m in mappings.values())
    merge_conflicts = sum(len(g["merge_conflicts"]) for g in gen_diag.values())
    gates = {
        "TAXONOMY_AUTO_RESOLVABLE": "PASS" if (all_resolved and dts_complete) else "FAIL",
        "CROSS_TAXONOMY_CONCEPT_MAPPING": "PASS" if (diffs_ok and all_classified) else "FAIL",
        "NO_SILENT_SEMANTIC_DRIFT": "PASS" if (all_classified and diffs_ok
                                              and merge_conflicts == 0) else "FAIL",
    }
    unresolved = sum(v["summary"]["UNKNOWN"] + v["summary"]["NOT_COMPARABLE"]
                     for v in mappings.values())
    evid = {
        "schema": "bankcall-g1c-evidence/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": {"arelle": "2.44.0", "python": sys.version.split()[0]},
        "offline": True,
        "registry_sha256": hashlib.sha256(open(REGISTRY, 'rb').read()).hexdigest(),
        "freeze_manifest": "evidence/g1/dts-freeze-manifest.json",
        "fingerprints_sha256": fp_sha,
        "generation_diagnostics": gen_diag,
        "versioning_diffs": _jsonable(
            {k: {ep: {kk: vv for kk, vv in d.items() if kk != "parsed"}
                 for ep, d in v.items()}
             for k, v in diffs.items()}),
        "mapping_sha256": map_sha,
        "mapping_summary": {k: v["summary"] for k, v in mappings.items()},
        "gates": gates,
        "notes": {
            "unresolved_not_comparable_or_unknown": unresolved,
            "eba_crr": "eba.europa.eu/eu/fr/xbrl/crr/** decommissioned (HTTP 403). "
                       "Resources recovered from (a) the live official EBA "
                       "'Full taxonomy' reporting-framework package (first-party "
                       "bytes under the same URL space) and (b) Wayback-archived "
                       "captures of the exact official URLs where the package "
                       "does not ship them. Per-file origin recorded in the "
                       "freeze manifest.",
            "eba_dict_version_note": "The shared BdE dictionary linkbases are "
                       "a current snapshot referencing all EBA dict versions; "
                       "the mirror therefore carries the latest official EBA "
                       "dictionary publication uniformly across generations. "
                       "Unversioned dict files were selected best-fit per "
                       "required-ID coverage (evidence/g1/eba-dict-bestfit.json); "
                       "exp.xsd retains 3 dangling official references "
                       "(eba_qBA/qCU/qGA) absent from every published EBA "
                       "dictionary -- an upstream source defect, recorded.",
            "qname_space_normalization": "Concept comparison is performed in a "
                       "normalized QName space: to-side namespaces/linkroles "
                       "are translated via positive Arelle namespaceRename/"
                       "roleChange evidence, then the circ-4-2017 generation-"
                       "date path segment is canonicalized to *GEN*. Raw "
                       "QNames are preserved in every mapping entry.",
        },
    }
    with open(OUT_EVID, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(evid, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print("gates:", gates)


if __name__ == "__main__":
    run()
