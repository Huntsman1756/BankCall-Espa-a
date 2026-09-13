"""G1-C core: Arelle-backed DTS loading, structural fingerprints, DTS diff.

BankCall's own layer is deliberately thin:
  * provenance (which official bytes produced which model objects),
  * a canonical structural fingerprint per concept / relationship set,
  * fail-closed classification policy (separate module).

Arelle does all XBRL/DTS processing.  The frozen DTS mirror
(g0_acquisition/dts_mirror) doubles as a taxonomy package so that every
http(s):// URL the DTS references resolves to hash-pinned local bytes while
``webCache.workOffline`` guarantees no network access.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re

from arelle import Cntlr, ModelXbrl, PackageManager, XbrlConst

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIRROR = os.path.join(REPO, "g0_acquisition", "dts_mirror")
PACKAGE_MANIFEST = os.path.join(MIRROR, "META-INF", "taxonomyPackage.xml")

GENERATION_RE = re.compile(
    r"/xbrl/fws/publicos/circ-4-2017/(\d{4})-(\d{2})-01/")
GENERATION_NAMES = {
    "2018-01-01": "publicos_2018_01",
    "2018-12-01": "publicos_2018_12",
    "2023-03-01": "publicos_2023_03",
}

SCHEMA_REF_RE = re.compile(rb'<link:schemaRef[^>]*xlink:href="([^"]+)"')


class _LoadLogCapture(logging.Handler):
    """Capture Arelle log records emitted while a DTS loads."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def load_failures(records):
    """Extract (code, file) pairs for resources Arelle could not load."""
    out = []
    for r in records:
        code = getattr(r, "messageCode", None) or ""
        msg = r.getMessage()
        if "ould not load" in msg or "FileNotLoadable" in code or "fileNotLoadable" in code:
            f = getattr(r, "file", None) or ""
            m = re.search(r"(?:file:|retrieving)\s+(\S+)", msg)
            if not f and m:
                f = m.group(1)
            out.append({"code": code, "file": f, "message": msg[:300]})
    return out


def make_controller(offline=True):
    cntlr = Cntlr.Cntlr(logFileName="logToStdErr", logFormat="%(message)s")
    cntlr.logger.setLevel(logging.CRITICAL)
    PackageManager.init(cntlr)
    PackageManager.addPackage(cntlr, os.path.abspath(PACKAGE_MANIFEST))
    PackageManager.rebuildRemappings(cntlr)
    cntlr.modelManager.validateTransformFileTypes = False
    cntlr.webCache.workOffline = offline
    return cntlr


def load_dts(cntlr, entry_url):
    """Load a DTS through Arelle. Returns (modelXbrl, load_records)."""
    cap = _LoadLogCapture()
    cap.setLevel(logging.DEBUG)
    prev = cntlr.logger.level
    cntlr.logger.setLevel(logging.WARNING)
    cntlr.logger.addHandler(cap)
    try:
        mx = ModelXbrl.load(cntlr.modelManager, entry_url)
    finally:
        cntlr.logger.removeHandler(cap)
        cntlr.logger.setLevel(prev)
    return mx, cap.records


def generation_from_entrypoint(entry_url):
    m = GENERATION_RE.search(entry_url)
    if not m:
        return None
    return GENERATION_NAMES.get("%s-%s-01" % (m.group(1), m.group(2)))


def extract_schemaref(instance_bytes):
    m = SCHEMA_REF_RE.search(instance_bytes)
    return m.group(1).decode("ascii") if m else None


def _clark(q):
    """QName in Clark notation {ns}local -- prefix-independent, so the same
    concept string-identifies identically across DTS generations."""
    if q is None:
        return None
    try:
        return "{%s}%s" % (q.namespaceURI, q.localName)
    except AttributeError:
        return str(q)


def _qn(q):
    return _clark(q)


def _rel_qname(obj):
    """Clark qname for relationship endpoints; str() for non-concept
    resources."""
    if obj is None:
        return None
    return _clark(getattr(obj, "qname", obj))


def _label_fingerprints(mx):
    """concept qname -> list of {role, lang, text} from concept-label arcs."""
    labels = {}
    try:
        rs = mx.relationshipSet(XbrlConst.conceptLabel)
    except Exception:
        return labels
    for rel in rs.modelRelationships:
        if rel.toModelObject is None:
            continue
        lab = rel.toModelObject
        key = _rel_qname(rel.fromModelObject)
        if key is None:
            continue
        labels.setdefault(key, []).append({
            "role": getattr(lab, "role", None),
            "lang": getattr(lab, "xmlLang", None),
            "text": (lab.text or "").strip() if hasattr(lab, "text") else None,
        })
    for v in labels.values():
        v.sort(key=lambda d: (d.get("role") or "", d.get("lang") or "", d.get("text") or ""))
    return labels


def _reference_fingerprints(mx):
    refs = {}
    try:
        rs = mx.relationshipSet(XbrlConst.conceptReference)
    except Exception:
        return refs
    for rel in rs.modelRelationships:
        if rel.toModelObject is None or rel.fromModelObject is None:
            continue
        res = rel.toModelObject
        key = _rel_qname(rel.fromModelObject)
        parts = []
        try:
            for p in res.iterchildren():
                parts.append({"part": p.localName, "text": (p.text or "").strip()})
        except Exception:
            pass
        refs.setdefault(key, []).append({
            "role": getattr(res, "role", None),
            "parts": sorted(parts, key=lambda d: (d["part"], d["text"])),
        })
    for v in refs.values():
        v.sort(key=lambda d: json.dumps(d, sort_keys=True))
    return refs


def _network_fingerprints(mx, arcrole):
    """concept -> {role -> {parents, children}} for a relationship arcrole."""
    nets = {}
    linkroles = sorted({k[1] for k in mx.baseSets if k and k[0] == arcrole and k[1]})
    for lr in linkroles:
        try:
            rs = mx.relationshipSet(arcrole, lr)
        except Exception:
            continue
        for rel in rs.modelRelationships:
            fq = _rel_qname(rel.fromModelObject)
            tq = _rel_qname(rel.toModelObject)
            if fq is None or tq is None:
                continue
            entry = nets.setdefault(fq, {}).setdefault(lr, {"children": [], "calc_children": []})
            rec = {"qname": tq}
            if getattr(rel, "weight", None) is not None:
                rec["weight"] = rel.weight
            if getattr(rel, "order", None) is not None:
                rec["order"] = rel.order
            key = "calc_children" if "weight" in rec else "children"
            entry.setdefault(key, []).append(rec)
            pent = nets.setdefault(tq, {}).setdefault(lr, {})
            pent.setdefault("parents", []).append({"qname": fq})
    for concept in nets.values():
        for lr, d in concept.items():
            for k in d:
                d[k] = sorted(d[k], key=lambda r: (r.get("order", 0), r["qname"]))
    return nets


def fingerprint_dts(mx):
    """BankCall canonical structural fingerprint of a loaded DTS."""
    labels = _label_fingerprints(mx)
    refs = _reference_fingerprints(mx)
    pres = _network_fingerprints(mx, XbrlConst.parentChild)
    calc = _network_fingerprints(mx, XbrlConst.summationItem)
    dim_arcs = (
        XbrlConst.all, XbrlConst.notAll, XbrlConst.hypercubeDimension,
        XbrlConst.dimensionDomain, XbrlConst.domainMember,
        XbrlConst.dimensionDefault,
    )
    dims = {}
    for ar in dim_arcs:
        for fq, by_lr in _network_fingerprints(mx, ar).items():
            for lr, d in by_lr.items():
                tgt = dims.setdefault(fq, {})
                tgt.setdefault(ar, {})[lr] = [c["qname"] for c in d.get("children", []) + d.get("calc_children", [])]
                for p in d.get("parents", []):
                    dims.setdefault(p["qname"], {}).setdefault("dimensionedBy", {}) \
                        .setdefault(lr, []).append(fq)

    concepts = {}
    for qn, c in sorted(mx.qnameConcepts.items(), key=lambda kv: _clark(kv[0])):
        if not getattr(c, "isItem", False) and not getattr(c, "isTuple", False) \
                and not getattr(c, "isDimensionItem", False) \
                and not getattr(c, "isHypercubeItem", False):
            pass  # keep everything; classification decides relevance
        cqn = _clark(qn)
        entry = {
            "qname": cqn,
            "namespace": c.qname.namespaceURI,
            "localname": c.qname.localName,
            "type": _qn(getattr(c, "typeQname", None)),
            "substitutionGroup": _qn(getattr(c, "substitutionGroupQname", None)),
            "abstract": bool(getattr(c, "isAbstract", False)),
            "nillable": bool(getattr(c, "isNillable", False)),
            "periodType": getattr(c, "periodType", None),
            "balance": getattr(c, "balance", None),
            "labels": labels.get(cqn, []),
            "references": refs.get(cqn, []),
        }
        if cqn in pres:
            entry["presentation"] = pres[cqn]
        if cqn in calc:
            entry["calculation"] = calc[cqn]
        if cqn in dims:
            entry["dimensions"] = dims[cqn]
        concepts[cqn] = entry

    return {
        "schema": "bankcall-g1c-dts-fingerprint/v1",
        "concept_count": len(concepts),
        "concepts": concepts,
        "linkrole_count": len({k[1] for k in mx.baseSets if k and k[1]}),
    }


def canonical_json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(obj):
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
