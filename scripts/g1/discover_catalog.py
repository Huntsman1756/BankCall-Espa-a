#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G1-A discovery experiment for the Banco de España public-statements catalog.

This is deliberately not a product client.  It starts at the official SIFDIFU
root, discovers the application's catalog base and URL grammar from the root
HTML/JavaScript, then inventories every period advertised by the source.  The
ten G1 periods are evaluation markers only; they do not limit discovery.

The command performs two complete passes with separate HTTP sessions.  On a
successful run it writes catalog-run1.json, catalog-run2.json, catalog.json
(the canonical run-1 inventory), and g1-evidence.json below evidence/g1/.
No browser, shell execution, cookies, credentials or G0 curl capture is used.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urldefrag, urljoin, urlparse, urlunparse

import requests


SOURCE_ROOT = "https://app.bde.es/sifdifu/es/#/"
EVALUATION_PERIOD_IDS = (
    "201803",
    "201809",
    "201812",
    "202012",
    "202103",
    "202109",
    "202212",
    "202303",
    "202506",
    "202606",
)
USER_AGENT = "BankCall-G1-Discovery/1.0"
REQUEST_TIMEOUT = 60
ARTIFACT_EXPECTED_TYPES = {
    ".xbrl": ("application/octet-stream", "application/xml", "text/xml"),
    ".xls": ("application/vnd.ms-excel", "application/octet-stream"),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    ),
    ".pdf": ("application/pdf",),
}


class DiscoveryError(RuntimeError):
    """Raised when the source cannot be discovered or parsed safely."""


class RootHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang: str | None = None
        self.script_srcs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag.lower() == "html" and attr.get("lang"):
            self.lang = attr["lang"]
        if tag.lower() == "script" and attr.get("src"):
            self.script_srcs.append(attr["src"] or "")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n"
    ).encode("utf-8")


def write_json(path: Path, value: Any) -> str:
    data = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_bytes(data)


def app_directory(url: str) -> str:
    """Return the root application directory without relying on a fixed URL."""
    no_fragment, _ = urldefrag(url)
    parsed = urlparse(no_fragment)
    path = parsed.path if parsed.path.endswith("/") else parsed.path + "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def safe_url(base: str, *parts: str) -> str:
    encoded = [quote(str(part), safe="()_-.") for part in parts]
    return urljoin(base, "/".join(encoded))


def response_meta(response: requests.Response, body: bytes | None = None) -> dict[str, Any]:
    if body is None:
        body = response.content
    return {
        "requested_url": response.request.url if response.request is not None else response.url,
        "final_url": response.url,
        "status": response.status_code,
        "redirects": [
            {"status": item.status_code, "location": item.headers.get("Location")}
            for item in response.history
        ],
        "content_type": response.headers.get("Content-Type"),
        "content_length_header": response.headers.get("Content-Length"),
        "bytes": len(body),
        "sha256": sha256_bytes(body),
    }


def source_record(meta: dict[str, Any], canonical_hash: str | None = None) -> dict[str, Any]:
    result = {
        "source_url": meta["requested_url"],
        "final_url": meta["final_url"],
        "status": meta["status"],
        "redirects": meta["redirects"],
        "content_type": meta["content_type"],
        "content_length_header": meta["content_length_header"],
        "bytes": meta["bytes"],
        "sha256": meta["sha256"],
    }
    if canonical_hash is not None:
        result["canonical_json_sha256"] = canonical_hash
    return result


def flatten_options(items: Iterable[dict[str, Any]], group: str | None = None) -> list[dict[str, Any]]:
    """Flatten Select2 groups while retaining the displayed group label."""
    flattened: list[dict[str, Any]] = []
    for item in items:
        children = item.get("children")
        if isinstance(children, list):
            next_group = item.get("text") or group
            flattened.extend(flatten_options(children, next_group))
            continue
        if "id" not in item:
            continue
        flattened.append(
            {
                "id": str(item["id"]),
                "text": str(item.get("text", "")),
                "group": group,
            }
        )
    return flattened


def extract_required(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text)
    if not match:
        raise DiscoveryError("could not discover %s from application JavaScript" % label)
    return match.group(1)


def discover_protocol(
    root_response: requests.Response,
    root_body: bytes,
    session: requests.Session,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    parser = RootHTMLParser()
    parser.feed(root_body.decode("utf-8", errors="replace"))
    if not parser.lang:
        raise DiscoveryError("root HTML has no language")
    locale = parser.lang.lower().split("-", 1)[0]
    root_dir = app_directory(root_response.url)
    root_host = urlparse(root_dir).netloc

    script_urls: list[str] = []
    for src in parser.script_srcs:
        url = urljoin(root_dir, src)
        parsed = urlparse(url)
        if parsed.netloc == root_host and parsed.path.startswith(urlparse(root_dir).path):
            if parsed.path.lower().endswith(".js") and url not in script_urls:
                script_urls.append(url)
    if not script_urls:
        raise DiscoveryError("root HTML has no application JavaScript assets")

    fetched: dict[str, tuple[dict[str, Any], str]] = {}
    asset_records: list[dict[str, Any]] = []
    pending = list(script_urls)
    while pending:
        url = pending.pop(0)
        if url in fetched:
            continue
        response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        body = response.content
        meta = response_meta(response, body)
        if response.status_code != 200:
            raise DiscoveryError("application asset failed: %s %s" % (response.status_code, url))
        text = body.decode("utf-8", errors="replace")
        fetched[url] = (meta, text)
        asset_records.append(source_record(meta))

        # Angular/Webpack advertises lazy chunks in runtime.<chunk-hash>.js.
        # Discover those names from the runtime instead of hardcoding a chunk.
        for chunk_id, chunk_hash in re.findall(r"\{(\d+):\"([0-9a-f]+)\"\}\[e\]", text):
            chunk_url = urljoin(root_dir, "%s.%s.js" % (chunk_id, chunk_hash))
            if chunk_url not in fetched and chunk_url not in pending:
                pending.append(chunk_url)

    combined_js = "\n".join(text for _, text in fetched.values())
    base_matches = sorted(
        set(re.findall(r"select2Url\s*:\s*[\"'](https?://[^\"']+/)[\"']", combined_js))
    )
    catalog_bases = [url for url in base_matches if url.endswith("/documentosAsociaciones/")]
    if len(catalog_bases) != 1:
        raise DiscoveryError("could not uniquely discover the public-statements catalog base")
    catalog_base = catalog_bases[0]

    periods_prefix = extract_required(
        r"[\"']([^\"']*select2-periodos-)[\"']\+this\.localeId\+[\"']\.json",
        combined_js,
        "period endpoint",
    ).strip("/")
    states_prefix = extract_required(
        r"[\"']([^\"']*select2-estados-)[\"']\+this\.localeId\+[\"']\.json",
        combined_js,
        "state endpoint",
    ).strip("/")
    entities_prefix = extract_required(
        r"[\"']([^\"']*select2-entidades-)[\"']\+this\.localeId\+[\"']\.json",
        combined_js,
        "entity endpoint",
    ).strip("/")
    config_prefix = extract_required(
        r"[\"']([^\"']*config-)[\"']\+this\.localeId\+[\"']\.json",
        combined_js,
        "configuration endpoint",
    ).strip("/")
    periods_segment = extract_required(
        r"[\"']([^\"']+)/[\"']\+this\.option1\+[\"']/select2-estados-",
        combined_js,
        "period path segment",
    )
    artifact_fragment = (
        '"%s/"+this.option1+"/"+this.option2+"/"+this.option2+"_"+this.option1'
        % periods_segment
    )
    if artifact_fragment not in combined_js:
        raise DiscoveryError("could not discover the bulk artifact path construction")
    extensions = sorted(
        {"." + ext.lower() for ext in re.findall(r"resources\+\s*[\"']\.([A-Za-z0-9]+)[\"']", combined_js)}
    )
    if not extensions:
        raise DiscoveryError("could not discover downloadable artifact extensions")

    if any(prefix.startswith("/") for prefix in (periods_prefix, states_prefix, entities_prefix, config_prefix)):
        raise DiscoveryError("discovered endpoint prefix still starts with slash")

    protocol = {
        "locale": locale,
        "catalog_base": catalog_base,
        "templates": {
            "periods": periods_prefix + locale + ".json",
            "states": periods_segment + "/{period}/" + states_prefix + locale + ".json",
            "entities": periods_segment + "/{period}/{statement}/" + entities_prefix + locale + ".json",
            "config": periods_segment + "/{period}/{statement}/" + config_prefix + locale + ".json",
            "bulk_artifact_stem": periods_segment + "/{period}/{statement}/{statement}_{period}",
        },
        "artifact_extensions": extensions,
        "discovery_basis": {
            "root_final_url": root_response.url,
            "root_script_srcs": parser.script_srcs,
            "application_assets": sorted(asset_records, key=lambda item: item["source_url"]),
            "runtime_lazy_chunks_discovered": sorted(
                item["source_url"]
                for item in asset_records
                if re.search(r"/\d+\.[0-9a-f]+\.js$", item["source_url"])
            ),
        },
    }
    return protocol, asset_records


def get_json(
    session: requests.Session,
    url: str,
) -> tuple[dict[str, Any], Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    body = response.content
    meta = response_meta(response, body)
    if response.status_code != 200:
        raise DiscoveryError("catalog endpoint failed: %s %s" % (response.status_code, url))
    try:
        value = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError("catalog endpoint is not valid JSON: %s" % url) from exc
    return meta, value


def probe_artifact(session: requests.Session, url: str) -> dict[str, Any]:
    response = session.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    method = "HEAD"
    if response.status_code in (405, 501):
        response.close()
        response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True)
        method = "GET_HEADER_ONLY"
    content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
    extension = "." + url.rsplit(".", 1)[-1].lower()
    expected_types = ARTIFACT_EXPECTED_TYPES.get(extension, ())
    type_matches = content_type in expected_types
    available = 200 <= response.status_code < 300 and type_matches
    return {
        "url": url,
        "method": method,
        "status": response.status_code,
        "final_url": response.url,
        "redirects": [
            {"status": item.status_code, "location": item.headers.get("Location")}
            for item in response.history
        ],
        "content_type": response.headers.get("Content-Type"),
        "content_length_header": response.headers.get("Content-Length"),
        "extension": extension,
        "expected_content_types": list(expected_types),
        "content_type_matches": type_matches,
        "availability": "AVAILABLE" if available else "NOT_AVAILABLE",
        "payload_validation": "DEFERRED_G1_C",
    }


def discover_once(run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    session = requests.Session()
    session.verify = True
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"})

    root_response = session.get(SOURCE_ROOT, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    root_body = root_response.content
    if root_response.status_code != 200:
        raise DiscoveryError("source root failed: %s" % root_response.status_code)
    protocol, _ = discover_protocol(root_response, root_body, session)
    base = protocol["catalog_base"]
    templates = protocol["templates"]
    locale = protocol["locale"]

    periods_url = safe_url(base, templates["periods"])
    periods_meta, periods_payload = get_json(session, periods_url)
    period_items = flatten_options(periods_payload.get("results", [])) if isinstance(periods_payload, dict) else []
    if not period_items:
        raise DiscoveryError("period catalog is empty")
    period_ids = {item["id"] for item in period_items}
    if len(period_ids) != len(period_items):
        raise DiscoveryError("period catalog contains duplicate IDs")

    periods: list[dict[str, Any]] = []
    for period in sorted(period_items, key=lambda item: item["id"]):
        period_id = period["id"]
        states_url = safe_url(
            base,
            periods_segment_from_template(templates["states"]),
            period_id,
            templates["states"].split("/{period}/", 1)[1],
        )
        states_meta, states_payload = get_json(session, states_url)
        state_items = flatten_options(states_payload.get("results", [])) if isinstance(states_payload, dict) else []
        if not state_items:
            raise DiscoveryError("state catalog is empty for period %s" % period_id)
        if len({item["id"] for item in state_items}) != len(state_items):
            raise DiscoveryError("state catalog contains duplicate IDs for period %s" % period_id)

        state_records: list[dict[str, Any]] = []
        for state in sorted(state_items, key=lambda item: item["id"]):
            statement_id = state["id"]
            entities_suffix = templates["entities"].split("/{statement}/", 1)[1]
            config_suffix = templates["config"].split("/{statement}/", 1)[1]
            entities_url = safe_url(base, periods_segment_from_template(templates["entities"]), period_id, statement_id, entities_suffix)
            config_url = safe_url(base, periods_segment_from_template(templates["config"]), period_id, statement_id, config_suffix)
            entities_meta, entities_payload = get_json(session, entities_url)
            config_meta, config_payload = get_json(session, config_url)
            entity_items = flatten_options(entities_payload.get("results", [])) if isinstance(entities_payload, dict) else []
            if len({item["id"] for item in entity_items}) != len(entity_items):
                raise DiscoveryError("entity catalog contains duplicate IDs for %s/%s" % (period_id, statement_id))

            artifact_stem = safe_url(
                base,
                periods_segment_from_template(templates["bulk_artifact_stem"]),
                period_id,
                statement_id,
                "%s_%s" % (statement_id, period_id),
            )
            artifacts = [
                probe_artifact(session, artifact_stem + extension)
                for extension in protocol["artifact_extensions"]
            ]
            state_records.append(
                {
                    "id": statement_id,
                    "text": state["text"],
                    "group": state.get("group"),
                    "source": source_record(states_meta),
                    "entities_source": source_record(
                        entities_meta,
                        sha256_bytes(canonical_json_bytes(entities_payload)),
                    ),
                    "config_source": source_record(
                        config_meta,
                        sha256_bytes(canonical_json_bytes(config_payload)),
                    ),
                    "config_summary": {
                        "title": config_payload.get("titulo") if isinstance(config_payload, dict) else None,
                        "header": config_payload.get("encabezamiento") if isinstance(config_payload, dict) else None,
                        "groups": len(config_payload.get("grupos", [])) if isinstance(config_payload, dict) and isinstance(config_payload.get("grupos"), list) else None,
                        "columns": len(config_payload.get("columnas", [])) if isinstance(config_payload, dict) and isinstance(config_payload.get("columnas"), list) else None,
                        "rows": len(config_payload.get("filas", [])) if isinstance(config_payload, dict) and isinstance(config_payload.get("filas"), list) else None,
                    },
                    "entities": sorted(entity_items, key=lambda item: item["id"]),
                    "artifacts": artifacts,
                }
            )

        periods.append(
            {
                "id": period_id,
                "text": period["text"],
                "source": source_record(periods_meta),
                "states": state_records,
            }
        )

    catalog = {
        "schema": "bankcall.g1.discovery.catalog.v1",
        "scope": "G1-A_DISCOVERY_ONLY",
        "source_root": SOURCE_ROOT,
        "protocol": protocol,
        "period_catalog_source": source_record(
            periods_meta,
            sha256_bytes(canonical_json_bytes(periods_payload)),
        ),
        "period_count": len(periods),
        "evaluation_period_ids": list(EVALUATION_PERIOD_IDS),
        "evaluation_periods_found": sorted(set(EVALUATION_PERIOD_IDS) & period_ids),
        "periods": periods,
    }
    counts = inventory_counts(catalog)
    run_meta = {
        "run_id": run_id,
        "started_utc": None,
        "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tls_verification": session.verify,
        "user_agent": USER_AGENT,
        "status": "PASS",
        "counts": counts,
    }
    return catalog, run_meta


def periods_segment_from_template(template: str) -> str:
    return template.split("/", 1)[0]


def inventory_counts(catalog: dict[str, Any]) -> dict[str, Any]:
    states = [state for period in catalog.get("periods", []) for state in period.get("states", [])]
    entities = [entity for state in states for entity in state.get("entities", [])]
    artifacts = [artifact for state in states for artifact in state.get("artifacts", [])]
    available = [artifact for artifact in artifacts if artifact.get("availability") == "AVAILABLE"]
    return {
        "periods": len(catalog.get("periods", [])),
        "states": len(states),
        "entity_records": len(entities),
        "artifact_candidates": len(artifacts),
        "available_artifacts": len(available),
        "available_by_extension": {
            extension: sum(
                1 for artifact in available if artifact.get("extension") == extension
            )
            for extension in sorted({str(artifact.get("extension")) for artifact in artifacts})
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[2] / "evidence" / "g1"),
        help="output directory (default: evidence/g1)",
    )
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, Any]] = []
    catalogs: list[dict[str, Any] | None] = []
    for run_id in ("run1", "run2"):
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            catalog, run_meta = discover_once(run_id)
            run_meta["started_utc"] = started
            run_meta["catalog_sha256"] = sha256_bytes(canonical_json_bytes(catalog))
            runs.append(run_meta)
            catalogs.append(catalog)
            write_json(out / ("catalog-%s.json" % run_id), catalog)
        except Exception as exc:  # evidence records failure; no stale success is emitted
            runs.append(
                {
                    "run_id": run_id,
                    "started_utc": started,
                    "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "tls_verification": True,
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                }
            )
            catalogs.append(None)
            break

    both_passed = len(catalogs) == 2 and all(catalog is not None for catalog in catalogs)
    determinism = "NOT_TESTED"
    if both_passed:
        first_hash = runs[0]["catalog_sha256"]
        second_hash = runs[1]["catalog_sha256"]
        determinism = "IDENTICAL" if first_hash == second_hash else "UNEXPLAINED_DIFF"
        if determinism == "IDENTICAL":
            write_json(out / "catalog.json", catalogs[0])

    evidence = {
        "experiment": "BANKCALL_ES_G1_A_DISCOVERY",
        "scope": "G1-A only; G1-B/G1-C/G1-D not executed",
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_root": SOURCE_ROOT,
        "evaluation_period_ids": list(EVALUATION_PERIOD_IDS),
        "runs": runs,
        "determinism": {
            "classification": determinism,
            "catalog_run1_sha256": runs[0].get("catalog_sha256") if runs else None,
            "catalog_run2_sha256": runs[1].get("catalog_sha256") if len(runs) > 1 else None,
        },
        "inventory": inventory_counts(catalogs[0]) if both_passed else None,
        "gates": {
            "DISCOVERY_DETERMINISTIC": "PASS" if determinism == "IDENTICAL" else "FAIL",
            "ENTITY_KEY_DECOMPOSED": "NOT_TESTED",
            "ENTITY_MAPPING_PROVEN": "NOT_TESTED",
            "ENTITY_LIFECYCLE_HANDLED": "NOT_TESTED",
            "TAXONOMY_AUTO_RESOLVABLE": "NOT_TESTED",
            "CROSS_TAXONOMY_CONCEPT_MAPPING": "NOT_TESTED",
            "NO_SILENT_SEMANTIC_DRIFT": "NOT_TESTED",
            "PROVENANCE_COMPLETE": "NOT_TESTED",
            "TEN_PERIOD_CORPUS_PASS": "NOT_TESTED",
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "requests": requests.__version__,
            "tls_verification": True,
            "script_sha256": sha256_bytes(Path(__file__).read_bytes()),
        },
    }
    write_json(out / "g1-evidence.json", evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if both_passed and determinism == "IDENTICAL" else 1


if __name__ == "__main__":
    sys.exit(main())
