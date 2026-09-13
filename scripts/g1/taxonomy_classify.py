"""G1-C.4 - BankCall fail-closed cross-taxonomy classification.

BankCall owns the seven frozen categories; Arelle's versioning report is only
*evidence*.  No equivalence is ever inferred from label similarity alone.

Categories (frozen, G1-CONTRACT v1.0):
  EXACT_EQUIVALENT      same QName, identical semantic fingerprint
  RENAMED_EQUIVALENT    different QName + positive structural evidence
                        (identical fingerprint modulo qname, or an explicit
                        versioning-report rename/use-correspondence event)
  STRUCTURALLY_CHANGED  same QName, material fingerprint difference
                        (type, periodType, balance, dimensions, topology,
                        labels, references, ...)
  NEW                   only in later taxonomy, no removed-side candidate
  REMOVED               only in earlier taxonomy, no new-side candidate
  NOT_COMPARABLE        a candidate relationship exists but equivalence is not
                        demonstrated, or evidence is contradictory
  UNKNOWN               evidence insufficient even to reach the above

QName space note: BdE embeds the generation date in `mod/*` namespaces and in
many linkrole URIs (``circ-4-2017/YYYY-MM-01``).  Cross-generation comparison
therefore first translates the *to* fingerprint into the *from* QName space
using only positive evidence -- Arelle ``namespaceRename``/``roleChange``
events -- and then applies a declared generation-stamp canonicalization of the
dated path segment.  Both steps are recorded in the evidence artifact; raw
QNames are always preserved in the mapping output.
"""
from __future__ import annotations

import json
import re

CATEGORIES = (
    "EXACT_EQUIVALENT", "RENAMED_EQUIVALENT", "STRUCTURALLY_CHANGED",
    "NEW", "REMOVED", "NOT_COMPARABLE", "UNKNOWN",
)

# Fingerprint fields compared for EXACT vs STRUCTURALLY_CHANGED.
STRUCTURAL_FIELDS = (
    "type", "substitutionGroup", "abstract", "nillable", "periodType",
    "balance", "labels", "references", "presentation", "calculation",
    "dimensions",
)

# Declared canonicalization: the BdE generation date path segment inside
# circ-4-2017 URIs is the taxonomy-generation axis, not concept identity.
GEN_STAMP_RE = re.compile(r"(circ-4-2017/)\d{4}-\d{2}-01")
GEN_STAMP_TOKEN = "*GEN*"


def _norm_str(s, ns_map, role_map):
    """Translate a to-side string into from-side QName/role space.

    Order: exact namespace/role replacement (positive Arelle evidence), then
    ``{to_ns}`` substring replacement inside Clark QNames, then the declared
    generation-stamp canonicalization.
    """
    s = ns_map.get(s, role_map.get(s, s))
    for to_uri, from_uri in ns_map.items():
        needle = "{%s}" % to_uri
        if needle in s:
            s = s.replace(needle, "{%s}" % from_uri)
    return GEN_STAMP_RE.sub(r"\1" + GEN_STAMP_TOKEN, s)


def _norm_obj(o, ns_map, role_map):
    if isinstance(o, str):
        return _norm_str(o, ns_map, role_map)
    if isinstance(o, list):
        return [_norm_obj(x, ns_map, role_map) for x in o]
    if isinstance(o, dict):
        return {_norm_str(k, ns_map, role_map): _norm_obj(v, ns_map, role_map)
                for k, v in o.items()}
    return o


def _prune_empty(o):
    """Drop empty containers produced by setdefault bookkeeping (a `[]` where
    the other side has no key is a fingerprint artifact, not drift; the same
    endpoint information is carried by the reverse `parents`/`dimensionedBy`
    lists)."""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            pv = _prune_empty(v)
            if pv not in ({}, [], None):
                out[k] = pv
        return out
    if isinstance(o, list):
        return [_prune_empty(x) for x in o]
    return o


def normalize_fp(fp, ns_map=None, role_map=None):
    """Normalize a concept fingerprint into comparable QName space.

    Returns (normalized_fp, raw_qnames) where raw_qnames maps each normalized
    key back to the original QName string for audit output.
    """
    ns_map = ns_map or {}
    role_map = role_map or {}
    out = {}
    raw = {}
    for q, c in fp.items():
        nq = _norm_str(q, ns_map, role_map)
        out[nq] = _prune_empty(_norm_obj(c, ns_map, role_map))
        raw[nq] = q
    return out, raw


def _sans_qname(fp):
    return {k: v for k, v in fp.items()
            if k not in ("qname", "namespace", "localname", "entry_points")}


def _structural_key(fp):
    """Fingerprint modulo identity: structural content only (for rename
    candidate detection).  Labels included — a true rename keeps them."""
    return json.dumps(_sans_qname(fp), sort_keys=True, ensure_ascii=False)


def _changed_fields(a, b):
    return [f for f in STRUCTURAL_FIELDS if a.get(f) != b.get(f)]


def classify_concepts(from_fp, to_fp, renames=None, ns_map=None,
                      role_map=None, ns_pairs=None):
    """Classify every concept of two generation fingerprints.

    from_fp / to_fp: {qname_str: fingerprint_dict} (Clark-notation qnames as
    produced by fingerprint_dts).
    renames: iterable of (from_qname, to_qname) positive-evidence pairs
    extracted from an Arelle versioning report (conceptRename events).
    ns_map: to-namespace -> from-namespace, from Arelle namespaceRename
    events (positive evidence only).
    role_map: to-linkrole -> from-linkrole, from Arelle roleChange events.
    ns_pairs: set of (from_ns, to_ns) for evidence labelling.
    Never built from label similarity.
    """
    renames = dict(renames or {})
    ns_pairs = ns_pairs or set()
    n_from, raw_from = normalize_fp(from_fp)
    n_to, raw_to = normalize_fp(to_fp, ns_map, role_map)
    out = {}

    def _rename_evidence(fq, tq):
        fns = fq[1:].split("}")[0] if fq.startswith("{") else ""
        tns = tq[1:].split("}")[0] if tq.startswith("{") else ""
        if (fns, tns) in ns_pairs:
            return "arelle_namespace_rename"
        if fns != tns:
            return "declared_generation_stamp_normalization"
        return "identical_structural_fingerprint_modulo_qname"

    from_q = set(n_from)
    to_q = set(n_to)
    shared = from_q & to_q
    only_from = from_q - to_q
    only_to = to_q - from_q

    for q in sorted(shared):
        a, b = n_from[q], n_to[q]
        fq, tq = raw_from[q], raw_to[q]
        diffs = _changed_fields(a, b)
        base = {"from_qname": fq, "to_qname": tq}
        if fq == tq:
            out[fq] = dict(base, classification=(
                "EXACT_EQUIVALENT" if not diffs else "STRUCTURALLY_CHANGED"))
            if diffs:
                out[fq]["changed_fields"] = diffs
                out[fq]["evidence"] = "fingerprint_diff"
        elif not diffs:
            out[fq] = dict(base, classification="RENAMED_EQUIVALENT",
                           evidence=_rename_evidence(fq, tq))
        else:
            out[fq] = dict(base, classification="STRUCTURALLY_CHANGED",
                           changed_fields=diffs,
                           evidence="fingerprint_diff+%s" % _rename_evidence(fq, tq))

    # rename candidates among the unshared: identical structural fingerprint
    # modulo identity.  Positive evidence only — no fuzzy matching.
    key_to_new = {}
    for q in sorted(only_to):
        key_to_new.setdefault(_structural_key(n_to[q]), []).append(q)
    key_to_old = {}
    for q in sorted(only_from):
        key_to_old.setdefault(_structural_key(n_from[q]), []).append(q)

    renamed = set()     # normalized to_qnames consumed by a rename
    for q in sorted(only_from):
        fq = raw_from[q]
        cand = key_to_new.get(_structural_key(n_from[q]), [])
        if cand:
            if len(cand) == 1:
                t = cand[0]
                ev = _rename_evidence(fq, raw_to[t])
                if renames.get(fq) == raw_to[t]:
                    ev += "+arelle_versioning_rename"
                out[fq] = {"classification": "RENAMED_EQUIVALENT",
                           "from_qname": fq, "to_qname": raw_to[t],
                           "evidence": ev}
                renamed.add(t)
            else:
                # ambiguous candidates -> fail closed
                out[fq] = {"classification": "NOT_COMPARABLE",
                           "from_qname": fq,
                           "candidates": [raw_to[c] for c in cand],
                           "evidence": "ambiguous_structural_match"}
        elif fq in renames:
            t = renames[fq]
            tn = _norm_str(t, ns_map or {}, role_map or {})
            if tn in only_to and tn not in renamed:
                out[fq] = {"classification": "RENAMED_EQUIVALENT",
                           "from_qname": fq, "to_qname": t,
                           "evidence": "arelle_versioning_rename"}
                renamed.add(tn)
            else:
                out[fq] = {"classification": "NOT_COMPARABLE",
                           "from_qname": fq,
                           "evidence": "rename_target_absent_or_consumed"}
        else:
            out[fq] = {"classification": "REMOVED", "from_qname": fq}

    for q in sorted(only_to):
        if q in renamed:
            continue
        cand = key_to_old.get(_structural_key(n_to[q]), [])
        if cand:
            out[raw_to[q]] = {"classification": "NOT_COMPARABLE",
                              "to_qname": raw_to[q],
                              "candidates": [raw_from[c] for c in cand],
                              "evidence": "unmatched_structural_candidate"}
        else:
            out[raw_to[q]] = {"classification": "NEW", "to_qname": raw_to[q]}

    return out


def summarize(mapping):
    counts = {c: 0 for c in CATEGORIES}
    for v in mapping.values():
        counts[v["classification"]] += 1
    return counts
