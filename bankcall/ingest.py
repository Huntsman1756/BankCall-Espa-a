"""Ingest the frozen BdE XBRL corpus into local Parquet tables.

Reads only frozen artifacts — never the network:

  g0_acquisition/xbrl_instances/<period>/<statement>_<period>.xbrl
  evidence/g1/taxonomy-registry.json      (per-file sha256 provenance)
  evidence/g1/entities.json             (slot -> legal entity observations)
  evidence/g1/g1-br-evidence.json       (documented slot transfers)
  evidence/g1/dts-fingerprints.json     (concept metadata per generation)
  evidence/g1/concept-mapping.json      (cross-generation classifications)

Writes data/*.parquet:
  facts.parquet        one row per reported fact, entity/period denormalized
  slots.parquet        (bank_code, suffix, period) -> legal entity element
  transfers.parquet    documented reporting-slot ownership transfers
  concepts.parquet     concept metadata (labels ES/EN, type, balance)
  concept_pairs.parquet  non-EXACT_EQUIVALENT cross-generation mappings
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

REPO = Path(__file__).resolve().parent.parent
INSTANCES = REPO / "g0_acquisition" / "xbrl_instances"
EVIDENCE = REPO / "evidence" / "g1"
DATA = REPO / "data"

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"

CTX_ID_RE = re.compile(r"^cES_(\d{4})_(\d{4})_")


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_instance(path: Path, period_id: str, statement: str,
                   file_sha256: str) -> list[dict]:
    """Parse one BdE XBRL instance into fact rows."""
    tree = etree.parse(str(path))
    root = tree.getroot()
    nsmap = root.nsmap

    def expand(prefixed: str) -> str:
        """'es_dim:MCI' -> '{http://.../dim}MCI' using the instance nsmap."""
        if ":" not in prefixed:
            return prefixed
        p, local = prefixed.split(":", 1)
        ns = nsmap.get(p)
        return f"{{{ns}}}{local}" if ns else prefixed

    contexts: dict[str, dict] = {}
    for ctx in root.iter(f"{{{XBRLI}}}context"):
        cid = ctx.get("id")
        ident = ctx.findtext(f"{{{XBRLI}}}entity/{{{XBRLI}}}identifier")
        seg_members = [
            (expand(m.get("dimension") or ""),
             expand((m.text or "").strip()))
            for m in ctx.iter(f"{{{XBRLDI}}}explicitMember")
            if _localname(m.getparent().tag) == "segment"
        ]
        scn_members = [
            (expand(m.get("dimension") or ""),
             expand((m.text or "").strip()))
            for m in ctx.iter(f"{{{XBRLDI}}}explicitMember")
            if _localname(m.getparent().tag) == "scenario"
        ]
        instant = ctx.findtext(f"{{{XBRLI}}}period/{{{XBRLI}}}instant")
        start = ctx.findtext(f"{{{XBRLI}}}period/{{{XBRLI}}}startDate")
        end = ctx.findtext(f"{{{XBRLI}}}period/{{{XBRLI}}}endDate")
        m = CTX_ID_RE.match(cid or "")
        contexts[cid] = {
            "entity_id": (ident or "").strip() if ident else None,
            "bank_code": m.group(1) if m else None,
            "suffix": m.group(2) if m else None,
            "agrupacion": next((_localname(v) for d, v in seg_members
                                if d.endswith("Agrupacion")), None),
            "instant": instant,
            "start": start,
            "end": end,
            "dims": {_localname(d): v for d, v in scn_members},
        }

    rows = []
    for el in root.iter():
        cref = el.get("contextRef")
        if cref is None or _localname(el.tag) in ("context", "unit"):
            continue
        c = contexts.get(cref)
        if c is None:
            continue
        raw = (el.text or "").strip()
        try:
            num = float(raw)
        except ValueError:
            num = None
        qname = etree.QName(el)
        rows.append({
            "period_id": period_id,
            "statement": statement,
            "entity_id": c["entity_id"],
            "bank_code": c["bank_code"],
            "suffix": c["suffix"],
            "agrupacion": c["agrupacion"],
            "instant": c["instant"],
            "start": c["start"],
            "end": c["end"],
            "metric": f"{{{qname.namespace}}}{qname.localname}",
            "metric_local": qname.localname,
            "value_raw": raw,
            "value_num": num,
            "unit": el.get("unitRef"),
            "decimals": el.get("decimals"),
            "dims": json.dumps(c["dims"], sort_keys=True),
            "source_file": path.name,
            "source_sha256": file_sha256,
        })
    return rows


def build_facts() -> int:
    registry = json.loads(
        (EVIDENCE / "taxonomy-registry.json").read_text(encoding="utf-8"))
    sha_by_payload = {a["local_payload"]: a["instance"]["sha256"]
                      for a in registry["artifacts"]}

    rows: list[dict] = []
    files = sorted(INSTANCES.glob("*/*.xbrl"))
    for i, path in enumerate(files, 1):
        period_id = path.parent.name
        statement = path.name.split("_", 1)[0]
        rel = path.relative_to(REPO).as_posix()
        sha = sha_by_payload.get(rel) or hashlib.sha256(
            path.read_bytes()).hexdigest()
        rows.extend(parse_instance(path, period_id, statement, sha))
        if i % 20 == 0 or i == len(files):
            print(f"  {i}/{len(files)} instances, {len(rows)} facts",
                  flush=True)

    table = pa.Table.from_pylist(rows)
    pq.write_table(table, DATA / "facts.parquet", compression="zstd")

    gens = sorted({(a["period"], a["taxonomy_generation"])
                   for a in registry["artifacts"]})
    pq.write_table(
        pa.Table.from_pylist(
            [{"period_id": p, "generation": g} for p, g in gens]),
        DATA / "period_generations.parquet", compression="zstd")
    return len(rows)


def build_identity() -> int:
    entities = json.loads(
        (EVIDENCE / "entities.json").read_text(encoding="utf-8"))
    rows = [{
        "period_id": o["period_id"],
        "period_end": o.get("period_end"),
        "raw_key": o["raw_sifdifu_key"],
        "bank_code": o["bank_code"],
        "suffix": o["component_or_suffix"],
        "statement_id": o.get("statement_id"),
        "legal_entity_ref": o.get("registry_candidate_id"),
        "official_name": (o.get("registry_official_name") or "").strip(),
        "catalog_name": (o.get("catalog_name") or "").strip(),
        "lifecycle_status": o.get("registry_lifecycle_status"),
        "mapping_status": o.get("registry_mapping_status"),
        "mapping_basis": o.get("mapping_basis"),
    } for o in entities["observations"]]
    pq.write_table(pa.Table.from_pylist(rows),
                   DATA / "slots.parquet", compression="zstd")

    g1br = json.loads(
        (EVIDENCE / "g1-br-evidence.json").read_text(encoding="utf-8"))
    trs = [{
        "bank_code": e["raw_sifdifu_key"].split("(", 1)[0],
        "suffix": e["raw_sifdifu_key"].split("(", 1)[1].rstrip(")"),
        "raw_key": e["raw_sifdifu_key"],
        "from_entity": e["from_candidate_id"],
        "from_name": (e["from_official_name"] or "").strip(),
        "to_entity": e["to_candidate_id"],
        "to_name": (e["to_official_name"] or "").strip(),
        "last_period_predecessor": e["last_period_predecessor"],
        "first_period_successor": e["first_period_successor"],
        "handoff_date": e["official_handoff_date"],
    } for e in g1br["checks"]["code_reuse_events"]]
    pq.write_table(pa.Table.from_pylist(trs),
                   DATA / "transfers.parquet", compression="zstd")
    return len(rows)


def build_concepts() -> int:
    fp = json.loads(
        (EVIDENCE / "dts-fingerprints.json").read_text(encoding="utf-8"))
    rows = []
    for gen, g in fp["generations"].items():
        for qn, c in g["concepts"].items():
            labels = c.get("labels") or []
            rows.append({
                "generation": gen,
                "qname": qn,
                "localname": c.get("localname"),
                "namespace": c.get("namespace"),
                "type": (c.get("type") or ""),
                "balance": c.get("balance"),
                "period_type": c.get("periodType"),
                "abstract": c.get("abstract"),
                "label_es": next((l["text"] for l in labels
                                  if l.get("lang") == "es"
                                  and l.get("role", "").endswith("/label")),
                                 None),
                "label_en": next((l["text"] for l in labels
                                  if l.get("lang") == "en"
                                  and l.get("role", "").endswith("/label")),
                                 None),
            })
    pq.write_table(pa.Table.from_pylist(rows),
                   DATA / "concepts.parquet", compression="zstd")

    mapping = json.loads(
        (EVIDENCE / "concept-mapping.json").read_text(encoding="utf-8"))
    pairs = [{
        "pair": pk,
        "from_qname": m.get("from_qname") or qn,
        "to_qname": m.get("to_qname"),
        "classification": m["classification"],
    } for pk, pair in mapping["pairs"].items()
        for qn, m in pair["mapping"].items()
        if m["classification"] != "EXACT_EQUIVALENT"]
    pq.write_table(pa.Table.from_pylist(pairs),
                   DATA / "concept_pairs.parquet", compression="zstd")
    return len(rows)


def run_ingest() -> None:
    DATA.mkdir(exist_ok=True)
    print("facts:")
    n = build_facts()
    print(f"  facts.parquet: {n} rows")
    print("identity:")
    n = build_identity()
    print(f"  slots.parquet: {n} rows")
    print("concepts:")
    n = build_concepts()
    print(f"  concepts.parquet: {n} rows")
