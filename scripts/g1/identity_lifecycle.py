#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G1-B identity and lifecycle experiment for BankCall España.

This is an experimental evidence producer, not a product client.  It starts
from the frozen G1-A catalog, preserves every raw SIFDIFU entity key, proves
the key components against official XBRL contexts, and reconciles the first
component with the official Banco de España entity register.  The register is
used only as an authority for identity/lifecycle fields; it does not replace
the SIFDIFU catalog or discover its period/statement URLs.

Two clean HTTP sessions are run.  Logical output deliberately excludes
retrieval timestamps; those timestamps remain in g1-b-evidence.json.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import json
import platform
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from defusedxml import ElementTree as DefusedET

from discover_catalog import canonical_json_bytes, sha256_bytes


REGISTRY_APP_ROOT = "https://app.bde.es/rbe_spa/"
REGISTRY_CONFIG_PATH = "assets/data/app.config.json"
REGISTRY_USER_AGENT = "BankCall-G1-Identity-Lifecycle/1.0"
REQUEST_TIMEOUT = 120
SIFDIFU_KEY_RE = re.compile(r"^(?P<bank_code>\d{4})\((?P<component>\d{4})\)$")
XBRL_CONTEXT_KEY_RE = re.compile(r"^cES_(?P<bank_code>\d{4})_(?P<component>\d{4})_")
LEI_RE = re.compile(r"[A-Z0-9]{20}")
ALLOWED_LIFECYCLE_STATUSES = {"active", "inactive", "absent-from-period", "unknown"}
FOCUS_CODES = ("2038", "2048")


class IdentityLifecycleError(RuntimeError):
    """Raised when an identity/lifecycle assertion cannot be proven."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def parse_period_end(period_id: str) -> dt.date:
    if not re.fullmatch(r"\d{6}", period_id):
        raise IdentityLifecycleError("invalid period ID: %s" % period_id)
    year, month = int(period_id[:4]), int(period_id[4:])
    if month not in range(1, 13):
        raise IdentityLifecycleError("invalid period month: %s" % period_id)
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def parse_sifdifu_key(raw_key: str) -> dict[str, str]:
    match = SIFDIFU_KEY_RE.fullmatch(str(raw_key))
    if not match:
        raise IdentityLifecycleError("malformed SIFDIFU key: %r" % raw_key)
    return {
        "raw_sifdifu_key": str(raw_key),
        "bank_code": match.group("bank_code"),
        "component_or_suffix": match.group("component"),
    }


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value))
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return " ".join(value.casefold().split())


def qname_local(value: str) -> str:
    """Return the local part of an expanded or prefix-qualified QName."""
    return str(value).rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def parse_catalog_label(raw_key: str, raw_label: str) -> dict[str, Any]:
    parsed = parse_sifdifu_key(raw_key)
    label = str(raw_label)
    prefix = parsed["bank_code"] + " - "
    if not label.startswith(prefix):
        raise IdentityLifecycleError(
            "catalog label/code mismatch: %s / %s" % (raw_key, raw_label)
        )
    remainder = label[len(prefix) :].strip()
    role_qualifier: str | None = None
    qualifier_match = re.search(r"\s*\((Grupo|Subgrupo)\)\s*$", remainder, re.I)
    if qualifier_match:
        role_qualifier = qualifier_match.group(1).upper()
        remainder = remainder[: qualifier_match.start()].rstrip()
    lei_match = LEI_RE.search(remainder)
    lei = lei_match.group(0) if lei_match else None
    if lei_match:
        remainder = re.sub(r"\s+-\s+" + re.escape(lei) + r"\s*$", "", remainder).rstrip()
    return {
        **parsed,
        "raw_catalog_label": label,
        "catalog_name": remainder,
        "catalog_lei": lei,
        "reporting_role_qualifier": role_qualifier,
    }


def name_comparison(catalog_name: str, official_name: str) -> str:
    left = re.sub(r"[^a-z0-9]+", "", normalize_text(catalog_name))
    right = re.sub(r"[^a-z0-9]+", "", normalize_text(official_name))
    if left == right:
        return "EXACT_NORMALIZED"
    if left and right and (left in right or right in left):
        return "QUALIFIER_OR_MINOR_VARIANT"
    return "DIFFERENT_OFFICIAL_LABEL"


def catalog_source_id(period_id: str, statement_id: str) -> str:
    return "sifdifu-entities:%s:%s" % (period_id, statement_id)


def catalog_periods(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    evaluation_ids = list(catalog.get("evaluation_period_ids", []))
    if len(evaluation_ids) != 10 or len(set(evaluation_ids)) != 10:
        raise IdentityLifecycleError("catalog does not contain the frozen ten-period corpus")
    by_id = {str(period.get("id")): period for period in catalog.get("periods", [])}
    if set(evaluation_ids) - set(by_id):
        raise IdentityLifecycleError("evaluation period is missing from catalog")
    return [by_id[period_id] for period_id in evaluation_ids]


def source_from_catalog(period_id: str, state: dict[str, Any]) -> dict[str, Any]:
    source = dict(state.get("entities_source") or {})
    required = {"source_url", "final_url", "status", "content_type", "bytes", "sha256"}
    if not required.issubset(source):
        raise IdentityLifecycleError(
            "entity source provenance is incomplete for %s/%s" % (period_id, state.get("id"))
        )
    return {
        "source_id": catalog_source_id(period_id, str(state["id"])),
        "source_role": "SIFDIFU_ENTITY_CATALOG",
        **{key: source.get(key) for key in sorted(source)},
    }


def statement_kind(text: str) -> str:
    normalized = normalize_text(text)
    if "sucursal" in normalized:
        return "branch_or_eee"
    if "balance" in normalized and "individual" in normalized:
        return "individual_balance"
    if "balance" in normalized and "consolid" in normalized:
        return "consolidated_balance"
    return "other"


def choose_state(period: dict[str, Any], kind: str) -> dict[str, Any] | None:
    states = [state for state in period.get("states", []) if statement_kind(state.get("text", "")) == kind]
    return sorted(states, key=lambda state: str(state.get("id")))[0] if states else None


def http_source_record(
    source_id: str,
    response: requests.Response,
    body: bytes,
    retrieved_utc: str,
    source_role: str,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_role": source_role,
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
        "retrieved_utc": retrieved_utc,
        "tls_verification": True,
    }


def add_source(
    sources: list[dict[str, Any]],
    source_id: str,
    response: requests.Response,
    body: bytes,
    source_role: str,
) -> dict[str, Any]:
    record = http_source_record(source_id, response, body, utc_now(), source_role)
    sources.append(record)
    return record


def get_json_value(
    session: requests.Session,
    url: str,
    source_id: str,
    source_role: str,
    sources: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    body = response.content
    source = add_source(sources, source_id, response, body, source_role)
    if response.status_code != 200:
        raise IdentityLifecycleError(
            "official JSON endpoint failed: %s %s" % (response.status_code, source["requested_url"])
        )
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IdentityLifecycleError("official endpoint is not JSON: %s" % source["requested_url"]) from exc
    return payload, source


def get_json(
    session: requests.Session,
    url: str,
    source_id: str,
    source_role: str,
    sources: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = get_json_value(
        session, url, source_id, source_role, sources, params=params
    )
    if not isinstance(payload, dict):
        raise IdentityLifecycleError("official JSON root is not an object: %s" % source["requested_url"])
    return payload, source


def registry_bootstrap(
    session: requests.Session,
    sources: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    config_url = urljoin(REGISTRY_APP_ROOT, REGISTRY_CONFIG_PATH)
    config, source = get_json(
        session,
        config_url,
        "registry-config",
        "OFFICIAL_BDE_REGISTRY_CONFIGURATION",
        sources,
    )
    try:
        base_url = str(config["api"]["rbe_api"]["baseUrl"]).rstrip("/")
    except (KeyError, TypeError) as exc:
        raise IdentityLifecycleError("official registry configuration has no API base URL") from exc
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or parsed.netloc not in {"app.bde.es", "www.bde.es"}:
        raise IdentityLifecycleError("registry API base URL is not an official HTTPS BdE host")
    return base_url, source


def registry_search(
    session: requests.Session,
    base_url: str,
    bank_code: str,
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    page = 1
    page_size = 100
    while True:
        payload, _ = get_json(
            session,
            base_url + "/elementos",
            "registry-search:%s:page:%s" % (bank_code, page),
            "OFFICIAL_BDE_REGISTRY_SEARCH",
            sources,
            params={
                "q": bank_code,
                "sort": "nombre",
                "lang": "ES",
                "sort_order": "ASC",
                "page": page,
                "page_size": page_size,
            },
        )
        items = payload.get("elementos")
        if not isinstance(items, list):
            raise IdentityLifecycleError("registry search has no elementos list for %s" % bank_code)
        all_items.extend(item for item in items if isinstance(item, dict))
        total = int(payload.get("numResultados", len(all_items)))
        if len(all_items) >= total or not items:
            return all_items
        page += 1


def registry_detail(
    session: requests.Session,
    base_url: str,
    element_id: int,
    sources: list[dict[str, Any]],
    cache: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    if element_id in cache:
        return cache[element_id]
    payload, _ = get_json(
        session,
        base_url + "/elementos/%s" % element_id,
        "registry-detail:%s" % element_id,
        "OFFICIAL_BDE_REGISTRY_ENTITY_DETAIL",
        sources,
        params={"lang": "ES"},
    )
    cache[element_id] = payload
    return payload


def registry_code_history(
    session: requests.Session,
    base_url: str,
    element_id: int,
    sources: list[dict[str, Any]],
    cache: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if element_id in cache:
        return cache[element_id]
    payload, _ = get_json_value(
        session,
        base_url + "/elementos/historia-codigosbde/%s" % element_id,
        "registry-history-codes:%s" % element_id,
        "OFFICIAL_BDE_REGISTRY_CODE_HISTORY",
        sources,
        params={"lang": "ES"},
    )
    if not isinstance(payload, list):
        raise IdentityLifecycleError("registry code history is not a list for %s" % element_id)
    cache[element_id] = [item for item in payload if isinstance(item, dict)]
    return cache[element_id]


def registry_code_history_or_none(
    session: requests.Session,
    base_url: str,
    element_id: int,
    sources: list[dict[str, Any]],
    cache: dict[int, list[dict[str, Any]] | None],
) -> list[dict[str, Any]] | None:
    """Fetch the official code-assignment history for an element.

    A failed or non-list response is recorded in sources and returned as
    None (history unavailable); ownership then falls back to role activity.
    """
    if element_id in cache:
        return cache[element_id]
    try:
        cache[element_id] = registry_code_history(session, base_url, element_id, sources, cache)  # type: ignore[arg-type]
    except IdentityLifecycleError:
        cache[element_id] = None
    return cache[element_id]


def clean_role(role: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("nombreRol", "fechaAltaRol", "fechaBajaRol", "motivoBaja", "deEntidadIDElemento"):
        if key in role:
            result[key] = role.get(key)
    successors = role.get("sucesorasRol")
    if isinstance(successors, list):
        result["sucesorasRol"] = [
            {
                key: item.get(key)
                for key in ("idelemento", "nombre", "codigoBE", "fechaSucesion")
                if key in item
            }
            for item in successors
            if isinstance(item, dict)
        ]
    return result


def candidate_from_detail(
    bank_code: str,
    item: dict[str, Any],
    detail: dict[str, Any],
    search_source_id: str,
    detail_source_id: str,
    code_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    element_id = int(detail.get("idelemento", item.get("idelemento")))
    current_code = str(detail.get("codigoBE") or item.get("codigoBE") or "")
    roles = [clean_role(role) for role in detail.get("roles", []) if isinstance(role, dict)]
    successors = [
        successor
        for role in roles
        for successor in role.get("sucesorasRol", [])
        if isinstance(successor, dict)
    ]
    return {
        "candidate_id": "registry:%s" % element_id,
        "idelemento": element_id,
        "requested_bank_code": bank_code,
        "codigoBE": current_code,
        "official_name": str(detail.get("nombre") or item.get("nombre") or ""),
        "documents": [
            {
                key: document.get(key)
                for key in ("tipoDocumento", "numeroDocumento", "esPrincipal")
                if key in document
            }
            for document in detail.get("documentos", [])
            if isinstance(document, dict)
        ],
        "roles": roles,
        "successors": successors,
        "search_source_id": search_source_id,
        "detail_source_id": detail_source_id,
        "code_history": code_history,
    }


def load_registry_candidates(
    session: requests.Session,
    base_url: str,
    bank_codes: Iterable[str],
    sources: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    detail_cache: dict[int, dict[str, Any]] = {}
    history_cache: dict[int, list[dict[str, Any]] | None] = {}
    output: dict[str, list[dict[str, Any]]] = {}
    for bank_code in sorted(set(bank_codes)):
        search_items = registry_search(session, base_url, bank_code, sources)
        exact_items = [
            item for item in search_items if str(item.get("codigoBE") or "") == bank_code
        ]
        candidates: list[dict[str, Any]] = []
        for item in exact_items:
            if item.get("idelemento") is None:
                continue
            element_id = int(item["idelemento"])
            detail = registry_detail(session, base_url, element_id, sources, detail_cache)
            detail_source_id = "registry-detail:%s" % element_id
            candidates.append(
                candidate_from_detail(
                    bank_code,
                    item,
                    detail,
                    "registry-search:%s:page:1" % bank_code,
                    detail_source_id,
                )
            )

        # A code may be historical rather than the entity's current code.  In
        # that case inspect the small search result set and retain only an
        # official code-history hit.  This path does not infer continuity.
        if not candidates:
            for item in search_items:
                if item.get("idelemento") is None:
                    continue
                element_id = int(item["idelemento"])
                detail = registry_detail(session, base_url, element_id, sources, detail_cache)
                history = registry_code_history(
                    session, base_url, element_id, sources, history_cache
                )
                if any(str(entry.get("codigoBE") or "") == bank_code for entry in history):
                    candidates.append(
                        candidate_from_detail(
                            bank_code,
                            item,
                            detail,
                            "registry-search:%s:page:1" % bank_code,
                            "registry-detail:%s" % element_id,
                            history,
                        )
                    )
        unique: dict[int, dict[str, Any]] = {int(item["idelemento"]): item for item in candidates}
        resolved = [unique[element_id] for element_id in sorted(unique)]
        for candidate in resolved:
            if candidate.get("code_history") is None:
                candidate["code_history"] = registry_code_history_or_none(
                    session,
                    base_url,
                    candidate["idelemento"],
                    sources,
                    history_cache,
                )
        output[bank_code] = resolved
    return output


def parse_date(value: Any) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def candidate_lifecycle_status(candidate: dict[str, Any], period_end: dt.date) -> str:
    roles = candidate.get("roles", [])
    if not roles:
        return "unknown"
    intervals: list[tuple[dt.date | None, dt.date | None]] = []
    for role in roles:
        start = parse_date(role.get("fechaAltaRol"))
        end = parse_date(role.get("fechaBajaRol"))
        intervals.append((start, end))
    active = [
        (start, end)
        for start, end in intervals
        if start is not None and start <= period_end and (end is None or period_end < end)
    ]
    if active:
        return "active"
    known = [(start, end) for start, end in intervals if start is not None]
    if not known:
        return "unknown"
    if all(start > period_end for start, _ in known):
        return "unknown"
    if all(start <= period_end and end is not None and end <= period_end for start, end in known):
        return "inactive"
    return "unknown"


def registry_status_for_period(
    candidates: list[dict[str, Any]], period_end: dt.date
) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
    classified = [
        {"candidate": candidate, "status": candidate_lifecycle_status(candidate, period_end)}
        for candidate in candidates
    ]
    active = [item for item in classified if item["status"] == "active"]
    if len(active) == 1:
        return "active", active[0]["candidate"], classified
    if len(active) > 1:
        return "unknown", None, classified
    inactive = [item for item in classified if item["status"] == "inactive"]
    if inactive and len(inactive) == len(classified):
        if len(inactive) == 1:
            return "inactive", inactive[0]["candidate"], classified
        return "inactive", None, classified
    return "unknown", None, classified


def candidate_leis(candidate: dict[str, Any]) -> set[str]:
    return {
        str(document["numeroDocumento"])
        for document in candidate.get("documents", [])
        if isinstance(document, dict)
        and document.get("tipoDocumento") == "LEI"
        and document.get("numeroDocumento")
    }


def code_ownership_at(
    candidate: dict[str, Any], bank_code: str, period_end: dt.date
) -> bool | None:
    """Whether the element's official code history claims bank_code at
    period_end. Interval ends are inclusive: a transfer day belongs to both
    the ending and the starting assignment. Returns None when the registry
    history is unavailable."""
    history = candidate.get("code_history")
    if history is None:
        return None
    for entry in history:
        if str(entry.get("codigoBE") or "") != bank_code:
            continue
        start = parse_date(entry.get("fechaInicio"))
        end = parse_date(entry.get("fechaFin"))
        if (start is None or start <= period_end) and (end is None or period_end <= end):
            return True
    return False


def registry_observation_mapping(
    candidates: list[dict[str, Any]],
    bank_code: str,
    period_end: dt.date,
    catalog_lei: str | None = None,
) -> tuple[str, dict[str, Any] | None, str, list[dict[str, Any]], str | None, str]:
    """Map a catalog observation to one registry element.

    Primary evidence is the official code-assignment history: exactly one
    element must hold bank_code at period_end. When several elements hold
    the code (a transfer boundary day) the catalog-label LEI may
    disambiguate. Role activity is used only when no history is available.
    A catalog LEI that contradicts the resolved element's LEI document is a
    source conflict and stays UNKNOWN.
    """
    status, role_candidate, classified = registry_status_for_period(candidates, period_end)
    ownership = [
        (candidate, code_ownership_at(candidate, bank_code, period_end))
        for candidate in candidates
    ]
    holders = [candidate for candidate, owns in ownership if owns is True]
    basis: str | None = None
    candidate: dict[str, Any] | None = None
    if len(holders) == 1:
        candidate = holders[0]
        basis = "CODE_OWNERSHIP_HISTORY"
    elif len(holders) > 1 and catalog_lei:
        lei_matches = [holder for holder in holders if catalog_lei in candidate_leis(holder)]
        if len(lei_matches) == 1:
            candidate = lei_matches[0]
            basis = "CODE_OWNERSHIP_HISTORY_LEI_DISAMBIGUATED"
    elif not holders and ownership and all(owns is None for _, owns in ownership):
        if role_candidate is not None and status in {"active", "inactive"}:
            candidate = role_candidate
            basis = "ROLE_ACTIVITY_SINGLE_ACTIVE_FALLBACK"

    lei_crosscheck = "NOT_APPLICABLE_NO_LABEL_LEI"
    if candidate is not None and catalog_lei:
        leis = candidate_leis(candidate)
        if not leis:
            lei_crosscheck = "NO_CANDIDATE_LEI_DOCUMENT"
        elif catalog_lei in leis:
            lei_crosscheck = "MATCH"
        else:
            candidate = None
            basis = None
            lei_crosscheck = "MISMATCH"

    if candidate is None:
        return "UNKNOWN", None, status, classified, basis, lei_crosscheck, ownership
    lifecycle_status = candidate_lifecycle_status(candidate, period_end)
    return "PROVEN", candidate, lifecycle_status, classified, basis, lei_crosscheck, ownership


def source_catalog_table(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for period in periods:
        period_id = str(period["id"])
        for state in period.get("states", []):
            source = source_from_catalog(period_id, state)
            records[source["source_id"]] = source
    return [records[key] for key in sorted(records)]


def xbrl_context_proof(
    session: requests.Session,
    period: dict[str, Any],
    state: dict[str, Any],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    period_id = str(period["id"])
    state_id = str(state["id"])
    artifacts = [
        artifact
        for artifact in state.get("artifacts", [])
        if artifact.get("extension") == ".xbrl"
    ]
    if len(artifacts) != 1:
        raise IdentityLifecycleError("expected one XBRL artifact for %s/%s" % (period_id, state_id))
    url = str(artifacts[0]["url"])
    source_id = "xbrl:%s:%s" % (period_id, state_id)
    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=True,
        headers={"Accept": "application/xml, text/xml, application/octet-stream, */*"},
    )
    body = response.content
    source = add_source(sources, source_id, response, body, "SIFDIFU_XBRL_IDENTITY_PROOF")
    if response.status_code != 200:
        raise IdentityLifecycleError("XBRL download failed: %s" % url)
    try:
        root = DefusedET.fromstring(body.lstrip(b"\xef\xbb\xbf"))
    except Exception as exc:  # defusedxml raises several parser-specific exceptions
        raise IdentityLifecycleError("XBRL is not safely parseable: %s" % url) from exc
    if not root.tag.endswith("xbrl"):
        raise IdentityLifecycleError("XBRL root is not xbrl: %s" % url)

    schema_refs = sorted(
        str(value)
        for element in root.iter()
        if element.tag.endswith("schemaRef")
        for key, value in element.attrib.items()
        if key.endswith("href")
    )
    if not schema_refs:
        raise IdentityLifecycleError("XBRL has no schemaRef: %s" % url)

    context_keys: set[str] = set()
    identifiers: dict[str, set[tuple[str | None, str | None]]] = defaultdict(set)
    dimensions: dict[str, set[str]] = defaultdict(set)
    context_periods: set[str] = set()
    context_count = 0
    for context in [element for element in root.iter() if element.tag.endswith("context")]:
        context_count += 1
        context_id = str(context.get("id") or "")
        match = XBRL_CONTEXT_KEY_RE.match(context_id)
        if not match:
            raise IdentityLifecycleError("unparseable XBRL context ID: %s" % context_id)
        key = "%s(%s)" % (match.group("bank_code"), match.group("component"))
        context_keys.add(key)
        identifier = next(
            (element for element in context.iter() if element.tag.endswith("identifier")),
            None,
        )
        if identifier is None:
            raise IdentityLifecycleError("XBRL context has no entity identifier: %s" % context_id)
        identifiers[key].add((identifier.get("scheme"), identifier.text))
        for element in context.iter():
            if element.tag.endswith("explicitMember"):
                dimension_name = qname_local(element.get("dimension") or "")
                value_name = qname_local(element.text or "")
                if dimension_name == "Agrupacion":
                    dimensions[match.group("component")].add(value_name)
            if element.tag.endswith("instant") or element.tag.endswith("endDate"):
                if element.text:
                    context_periods.add(element.text.strip())

    catalog_keys = {str(entity["id"]) for entity in state.get("entities", [])}
    if context_keys != catalog_keys:
        raise IdentityLifecycleError(
            "XBRL/catalog key mismatch for %s/%s: missing=%s extra=%s"
            % (period_id, state_id, sorted(catalog_keys - context_keys), sorted(context_keys - catalog_keys))
        )
    identifier_mismatches = sorted(
        {
            key
            for key, values in identifiers.items()
            if len(values) != 1
            or next(iter(values))[1] != "ES" + key.split("(", 1)[0]
        }
    )
    if identifier_mismatches:
        raise IdentityLifecycleError("XBRL entity identifier mismatch for %s" % url)

    expected_component_values = {
        "0000": "AgrupacionGrupoConsolidado",
        "0001": "AgrupacionSubgrupoConsolidado",
        "0002": "AgrupacionIndividual",
    }
    component_evidence: dict[str, Any] = {}
    for component, expected_value in expected_component_values.items():
        keys_for_component = {
            key for key in context_keys if key.endswith("(%s)" % component)
        }
        if not keys_for_component:
            continue
        observed = sorted(dimensions.get(component, set()))
        component_evidence[component] = {
            "expected_xbrl_member": expected_value,
            "observed_xbrl_members": observed,
            "member_matches": expected_value in observed,
            "key_count": len(keys_for_component),
        }
        if expected_value not in observed:
            raise IdentityLifecycleError(
                "XBRL Agrupacion member mismatch for component %s in %s" % (component, url)
            )

    expected_period_end = parse_period_end(period_id).isoformat()
    if expected_period_end not in context_periods:
        raise IdentityLifecycleError(
            "XBRL does not contain expected period end %s: %s" % (expected_period_end, url)
        )
    standard_namespaces = {
        "http://www.xbrl.org/2003/instance",
        "http://www.xbrl.org/2003/linkbase",
        "http://www.w3.org/1999/xlink",
        "http://www.w3.org/2001/XMLSchema-instance",
    }
    fact_count = sum(
        1
        for element in root
        if not (element.tag.startswith("{") and element.tag[1:].split("}", 1)[0] in standard_namespaces)
    )
    if fact_count <= 0:
        raise IdentityLifecycleError("XBRL contains no financial facts: %s" % url)
    return {
        "period_id": period_id,
        "period_end": expected_period_end,
        "statement_id": state_id,
        "statement_text": state.get("text"),
        "artifact_url": url,
        "artifact_final_url": response.url,
        "artifact_source_id": source_id,
        "artifact_sha256": source["sha256"],
        "artifact_bytes": source["bytes"],
        "schema_refs": schema_refs,
        "context_count": context_count,
        "entity_key_count": len(context_keys),
        "entity_identifier_scheme_values": {
            key: [list(value) for value in sorted(values)]
            for key, values in sorted(identifiers.items())
        },
        "context_period_values": sorted(context_periods),
        "component_evidence": component_evidence,
        "fact_count": fact_count,
    }


def canonical_candidates(candidates: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        {"bank_code": bank_code, "candidates": value}
        for bank_code, value in sorted(candidates.items())
    ]


def relationship_records(candidates: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    records: dict[tuple[Any, ...], dict[str, Any]] = {}
    for bank_code, values in candidates.items():
        for candidate in values:
            for successor in candidate.get("successors", []):
                record = {
                    "relationship_type": "SUCCESSOR",
                    "predecessor_bank_code": bank_code,
                    "predecessor_candidate_id": candidate["candidate_id"],
                    "successor_idelemento": successor.get("idelemento"),
                    "successor_name": successor.get("nombre"),
                    "successor_bank_code": successor.get("codigoBE"),
                    "effective_date": successor.get("fechaSucesion"),
                    "source_id": candidate["detail_source_id"],
                }
                key = tuple(record.get(field) for field in record)
                records[key] = record
    return [records[key] for key in sorted(records, key=lambda item: tuple(str(x) for x in item))]


def build_observations(
    periods: list[dict[str, Any]],
    candidates: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    observations: list[dict[str, Any]] = []
    all_codes: set[str] = set()
    for period in periods:
        period_id = str(period["id"])
        period_end = parse_period_end(period_id)
        for state in sorted(period.get("states", []), key=lambda item: str(item.get("id"))):
            state_id = str(state["id"])
            source_id = catalog_source_id(period_id, state_id)
            for entity in sorted(state.get("entities", []), key=lambda item: str(item.get("id"))):
                parsed = parse_catalog_label(str(entity["id"]), str(entity.get("text", "")))
                all_codes.add(parsed["bank_code"])
                (
                    mapping_status,
                    candidate,
                    lifecycle_status,
                    classified,
                    mapping_basis,
                    lei_crosscheck,
                    ownership,
                ) = registry_observation_mapping(
                    candidates.get(parsed["bank_code"], []),
                    parsed["bank_code"],
                    period_end,
                    parsed.get("catalog_lei"),
                )
                record: dict[str, Any] = {
                    **parsed,
                    "period_id": period_id,
                    "period_end": period_end.isoformat(),
                    "statement_id": state_id,
                    "statement_text": state.get("text"),
                    "catalog_presence_status": "present-in-period-statement",
                    "catalog_entities_source_id": source_id,
                    "registry_mapping_status": mapping_status,
                    "mapping_basis": mapping_basis,
                    "lei_crosscheck": lei_crosscheck,
                    "ownership_classification": [
                        {
                            "candidate_id": item[0]["candidate_id"],
                            "holds_code_at_period_end": item[1],
                        }
                        for item in ownership
                    ],
                    "registry_lifecycle_status": lifecycle_status,
                    "registry_candidate_id": candidate.get("candidate_id") if candidate else None,
                    "registry_code": candidate.get("codigoBE") if candidate else None,
                    "registry_official_name": candidate.get("official_name") if candidate else None,
                    "registry_detail_source_id": candidate.get("detail_source_id") if candidate else None,
                    "name_comparison": (
                        name_comparison(parsed["catalog_name"], candidate["official_name"])
                        if candidate
                        else "UNKNOWN"
                    ),
                    "candidate_classification": [
                        {
                            "candidate_id": item["candidate"]["candidate_id"],
                            "status": item["status"],
                        }
                        for item in classified
                    ],
                }
                observations.append(record)

    identity_groups: dict[str, dict[str, Any]] = {}
    for observation in observations:
        key = observation["raw_sifdifu_key"]
        group = identity_groups.setdefault(
            key,
            {
                "raw_sifdifu_key": key,
                "bank_code": observation["bank_code"],
                "component_or_suffix": observation["component_or_suffix"],
                "period_ids": set(),
                "statement_ids": set(),
                "catalog_labels": set(),
                "registry_candidate_ids": set(),
                "candidate_ids_considered": set(),
                "registry_official_names": set(),
                "unresolved_observation_count": 0,
                "period_mapping_statuses": {},
                "period_registry_candidate_ids": {},
            },
        )
        group["period_ids"].add(observation["period_id"])
        group["statement_ids"].add(observation["statement_id"])
        group["catalog_labels"].add(observation["raw_catalog_label"])
        group["candidate_ids_considered"].update(
            item["candidate_id"] for item in observation["candidate_classification"]
        )
        if observation["registry_candidate_id"]:
            group["registry_candidate_ids"].add(observation["registry_candidate_id"])
        if observation["registry_official_name"]:
            group["registry_official_names"].add(observation["registry_official_name"])
        if observation["registry_mapping_status"] != "PROVEN":
            group["unresolved_observation_count"] += 1
        group["period_mapping_statuses"].setdefault(
            observation["period_id"], set()
        ).add(observation["registry_mapping_status"])
        if observation["registry_candidate_id"]:
            group["period_registry_candidate_ids"].setdefault(
                observation["period_id"], set()
            ).add(observation["registry_candidate_id"])

    identity_keys = []
    for key, group in sorted(identity_groups.items()):
        identity_keys.append(
            {
                "raw_sifdifu_key": group["raw_sifdifu_key"],
                "bank_code": group["bank_code"],
                "component_or_suffix": group["component_or_suffix"],
                "period_ids": sorted(group["period_ids"]),
                "statement_ids": sorted(group["statement_ids"]),
                "catalog_labels": sorted(group["catalog_labels"]),
                "registry_candidate_ids": sorted(group["registry_candidate_ids"]),
                "candidate_ids_considered": sorted(group["candidate_ids_considered"]),
                "registry_official_names": sorted(group["registry_official_names"]),
                "unresolved_observation_count": group["unresolved_observation_count"],
                "period_mappings": [
                    {
                        "period_id": period_id,
                        "mapping_statuses": sorted(
                            group["period_mapping_statuses"][period_id]
                        ),
                        "registry_candidate_ids": sorted(
                            group["period_registry_candidate_ids"].get(period_id, set())
                        ),
                    }
                    for period_id in sorted(group["period_mapping_statuses"])
                ],
                "temporal_stability": (
                    "STABLE_SINGLE_REGISTRY_ID"
                    if not group["unresolved_observation_count"]
                    and len(group["registry_candidate_ids"]) <= 1
                    else "CHANGED_OR_AMBIGUOUS"
                ),
            }
        )
    return observations, identity_keys, all_codes


def build_absence_matrix(
    periods: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    candidates: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    period_ids = [str(period["id"]) for period in periods]
    period_end_by_id = {str(period["id"]): parse_period_end(str(period["id"])) for period in periods}
    present: dict[tuple[str, str], bool] = {
        (observation["period_id"], observation["bank_code"]): True
        for observation in observations
    }
    all_codes = sorted({observation["bank_code"] for observation in observations})
    matrix: list[dict[str, Any]] = []
    for period_id in period_ids:
        period_end = period_end_by_id[period_id]
        for bank_code in all_codes:
            is_present = present.get((period_id, bank_code), False)
            registry_status, candidate, classified = registry_status_for_period(
                candidates.get(bank_code, []), period_end
            )
            if is_present:
                status = registry_status
                absence_classification = "NOT_APPLICABLE_PRESENT"
                expected_absence = None
            else:
                status = "absent-from-period"
                if registry_status == "inactive":
                    absence_classification = "EXPECTED_REGISTRY_INACTIVE"
                    expected_absence = True
                elif registry_status == "active":
                    absence_classification = "ABSENT_FROM_PERIOD_ACTIVE_REGISTRY_SCOPE_ONLY"
                    expected_absence = False
                else:
                    absence_classification = "ABSENT_FROM_PERIOD_UNRESOLVED_SCOPE"
                    expected_absence = None
            matrix.append(
                {
                    "period_id": period_id,
                    "period_end": period_end.isoformat(),
                    "bank_code": bank_code,
                    "catalog_presence": "present" if is_present else "absent",
                    "lifecycle_status": status,
                    "registry_status_at_period_end": registry_status,
                    "registry_candidate_id": candidate.get("candidate_id") if candidate else None,
                    "absence_classification": absence_classification,
                    "expected_absence": expected_absence,
                    "candidate_classification": [
                        {
                            "candidate_id": item["candidate"]["candidate_id"],
                            "status": item["status"],
                        }
                        for item in classified
                    ],
                }
            )
    return matrix


def focus_lifecycle_checks(
    periods: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    candidates: dict[str, list[dict[str, Any]]],
    relationships: list[dict[str, Any]],
) -> dict[str, Any]:
    period_ids = [str(period["id"]) for period in periods]
    presence = {
        bank_code: {observation["period_id"] for observation in observations if observation["bank_code"] == bank_code}
        for bank_code in FOCUS_CODES
    }
    target_results: dict[str, Any] = {}
    for bank_code in FOCUS_CODES:
        code_candidates = candidates.get(bank_code, [])
        role_bajas = sorted(
            {
                role.get("fechaBajaRol")
                for candidate in code_candidates
                for role in candidate.get("roles", [])
                if role.get("nombreRol") == "Banco" and role.get("fechaBajaRol")
            }
        )
        baja = parse_date(role_bajas[-1]) if role_bajas else None
        expected_presence = {
            period_id: (parse_period_end(period_id) < baja if baja else None)
            for period_id in period_ids
        }
        observed_presence = {period_id: period_id in presence.get(bank_code, set()) for period_id in period_ids}
        successor_records = [
            record for record in relationships if record.get("predecessor_bank_code") == bank_code
        ]
        target_results[bank_code] = {
            "official_bank_role_baja": baja.isoformat() if baja else None,
            "expected_presence_from_official_baja": expected_presence,
            "observed_catalog_presence": observed_presence,
            "presence_matches_official_baja_expectation": (
                baja is not None and expected_presence == observed_presence
            ),
            "successors": successor_records,
        }
    relationship_expectations = {
        "2038": {"successor_bank_code": "2100", "effective_date": "2021-03-26"},
        "2048": {"successor_bank_code": "2103", "effective_date": "2021-07-30"},
    }
    successor_checks = {}
    for predecessor, expected in relationship_expectations.items():
        successor_checks[predecessor] = any(
            record.get("successor_bank_code") == expected["successor_bank_code"]
            and record.get("effective_date") == expected["effective_date"]
            for record in relationships
            if record.get("predecessor_bank_code") == predecessor
        )
    return {
        "targets": target_results,
        "successor_expectations": successor_checks,
        "all_target_presence_checks_pass": all(
            result["presence_matches_official_baja_expectation"]
            for result in target_results.values()
        ),
        "all_successor_expectations_pass": all(successor_checks.values()),
    }


def gate_results(
    observations: list[dict[str, Any]],
    identity_keys: list[dict[str, Any]],
    absence_matrix: list[dict[str, Any]],
    xbrl_proofs: list[dict[str, Any]],
    lifecycle_checks: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    malformed = []
    label_mismatches = []
    for observation in observations:
        try:
            parse_sifdifu_key(observation["raw_sifdifu_key"])
        except IdentityLifecycleError:
            malformed.append(observation["raw_sifdifu_key"])
        if not observation["raw_catalog_label"].startswith(observation["bank_code"] + " - "):
            label_mismatches.append(observation["raw_sifdifu_key"])
    key_decomposed = not malformed and not label_mismatches and len(observations) > 0
    mapping_unknown = [
        observation["raw_sifdifu_key"]
        for observation in observations
        if observation["registry_mapping_status"] != "PROVEN"
    ]
    mapping_unknown_keys = sorted(set(mapping_unknown))
    mapping_unknown_by_key = [
        {
            "raw_sifdifu_key": key,
            "observation_count": sum(
                observation["raw_sifdifu_key"] == key for observation in observations
            ),
            "unresolved_observation_count": sum(
                observation["raw_sifdifu_key"] == key
                and observation["registry_mapping_status"] != "PROVEN"
                for observation in observations
            ),
        }
        for key in mapping_unknown_keys
    ]
    xbrl_ok = all(
        proof.get("entity_key_count", 0) > 0
        and all(item.get("member_matches") for item in proof.get("component_evidence", {}).values())
        for proof in xbrl_proofs
    )
    temporal_changes = [
        item["raw_sifdifu_key"]
        for item in identity_keys
        if item["temporal_stability"] != "STABLE_SINGLE_REGISTRY_ID"
    ]
    raw_key_records = observations + identity_keys
    raw_key_preserved = all(
        record["raw_sifdifu_key"]
        == "%s(%s)" % (record["bank_code"], record["component_or_suffix"])
        for record in raw_key_records
    )
    alias_fields = {
        "canonical_entity_id",
        "series_id",
        "aliased_to",
        "predecessor_alias",
        "successor_alias",
    }
    splicing_alias_fields = sorted(
        field
        for record in raw_key_records
        for field in alias_fields
        if field in record
    )
    allowed_statuses = all(
        observation["registry_lifecycle_status"] in ALLOWED_LIFECYCLE_STATUSES
        for observation in observations
    ) and all(item["lifecycle_status"] in ALLOWED_LIFECYCLE_STATUSES for item in absence_matrix)
    absence_distinguished = all(
        item["lifecycle_status"] != "inactive" or item["catalog_presence"] == "present"
        for item in absence_matrix
    )
    checks = {
        "observation_count": len(observations),
        "unique_key_count": len(identity_keys),
        "malformed_keys": sorted(set(malformed)),
        "label_code_mismatches": sorted(set(label_mismatches)),
        "mapping_unknown_count": len(mapping_unknown),
        "mapping_unknown_key_count": len(mapping_unknown_keys),
        "mapping_unknown_by_key": mapping_unknown_by_key,
        "mapping_unknown_examples": mapping_unknown_keys[:20],
        "mapping_basis_counts": dict(
            sorted(
                Counter(
                    observation["mapping_basis"] or "UNRESOLVED"
                    for observation in observations
                ).items()
            )
        ),
        "lei_crosscheck_counts": dict(
            sorted(
                Counter(observation["lei_crosscheck"] for observation in observations).items()
            )
        ),
        "xbrl_proof_count": len(xbrl_proofs),
        "xbrl_proofs_valid": xbrl_ok,
        "temporal_change_count": len(temporal_changes),
        "temporal_change_examples": temporal_changes[:20],
        "temporal_unresolved_key_count": sum(
            item["unresolved_observation_count"] > 0 for item in identity_keys
        ),
        "lifecycle_statuses_complete": allowed_statuses,
        "absence_distinguished": absence_distinguished,
        "raw_key_preserved": raw_key_preserved,
        "merger_series_splicing": "DISABLED",
        "series_splicing_alias_fields": splicing_alias_fields,
        "same_bank_code_multiple_raw_keys": sorted(
            bank_code
            for bank_code in {
                observation["bank_code"] for observation in observations
            }
            if len(
                {
                    observation["raw_sifdifu_key"]
                    for observation in observations
                    if observation["bank_code"] == bank_code
                }
            )
            > 1
        ),
    }
    gates = {
        "ENTITY_KEY_DECOMPOSED": "PASS" if key_decomposed else "FAIL",
        "ENTITY_ID_STABLE": (
            "PASS"
            if key_decomposed and not mapping_unknown_keys and not temporal_changes
            else "FAIL"
        ),
        "ENTITY_MAPPING_PROVEN": "PASS" if not mapping_unknown and xbrl_ok else "FAIL",
        "ENTITY_KEY_TEMPORAL_STABILITY": (
            "PASS" if not mapping_unknown_keys and not temporal_changes else "FAIL"
        ),
        "ENTITY_LIFECYCLE_HANDLED": (
            "PASS"
            if allowed_statuses
            and lifecycle_checks["all_target_presence_checks_pass"]
            and lifecycle_checks["all_successor_expectations_pass"]
            else "FAIL"
        ),
        "EXPECTED_ABSENCE_DISTINGUISHED": "PASS" if absence_distinguished and lifecycle_checks["all_target_presence_checks_pass"] else "FAIL",
        "NO_MERGER_SERIES_SPLICING": (
            "PASS" if raw_key_preserved and not splicing_alias_fields else "FAIL"
        ),
    }
    return gates, checks


def build_logical_output(
    catalog: dict[str, Any],
    periods: list[dict[str, Any]],
    catalog_sources: list[dict[str, Any]],
    candidates: dict[str, list[dict[str, Any]]],
    observations: list[dict[str, Any]],
    identity_keys: list[dict[str, Any]],
    absence_matrix: list[dict[str, Any]],
    xbrl_proofs: list[dict[str, Any]],
    lifecycle_checks: dict[str, Any],
    gates: dict[str, str],
    checks: dict[str, Any],
) -> dict[str, Any]:
    component_semantics = {
        "0000": {
            "classification": "GROUP_CONSOLIDATED",
            "business_meaning_proven_by": ["catalog_label_(Grupo)", "XBRL_AgrupacionGrupoConsolidado"],
        },
        "0001": {
            "classification": "SUBGROUP_CONSOLIDATED",
            "business_meaning_proven_by": ["catalog_label_(Subgrupo)", "XBRL_AgrupacionSubgrupoConsolidado"],
        },
        "0002": {
            "classification": "INDIVIDUAL_OR_SINGLE_ENTITY_SCOPE",
            "business_meaning_proven_by": ["XBRL_AgrupacionIndividual", "SIFDIFU_individual_and_EEE_catalog_scopes"],
        },
    }
    return {
        "schema": "bankcall.g1.identity_lifecycle.v1",
        "scope": "G1-B_IDENTITY_LIFECYCLE_ONLY",
        "catalog_input_sha256": sha256_bytes(canonical_json_bytes(catalog)),
        "source_root": catalog.get("source_root"),
        "evaluation_period_ids": [str(period["id"]) for period in periods],
        "key_parser": {
            "pattern": r"^(?P<bank_code>\d{4})\((?P<component_or_suffix>\d{4})\)$",
            "raw_key_preserved": True,
            "unresolved_component_is_not_normalized": True,
        },
        "component_semantics": component_semantics,
        "catalog_entity_sources": catalog_sources,
        "registry_candidates": canonical_candidates(candidates),
        "identity_keys": identity_keys,
        "observations": observations,
        "absence_matrix": absence_matrix,
        "xbrl_context_proofs": xbrl_proofs,
        "lifecycle_relationships": relationship_records(candidates),
        "focus_lifecycle_checks": lifecycle_checks,
        "series_splicing": {
            "policy": "DISABLED",
            "predecessor_successor_edges_are_evidence_only": True,
            "raw_keys_are_not_aliased": True,
        },
        "checks": checks,
        "gates": gates,
    }


def execute_run(catalog: dict[str, Any], run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    periods = catalog_periods(catalog)
    catalog_sources = source_catalog_table(periods)
    observations_seed: list[dict[str, Any]] = []
    bank_codes: set[str] = set()
    for period in periods:
        for state in period.get("states", []):
            for entity in state.get("entities", []):
                parsed = parse_catalog_label(str(entity["id"]), str(entity.get("text", "")))
                observations_seed.append(parsed)
                bank_codes.add(parsed["bank_code"])

    session = requests.Session()
    session.verify = True
    session.headers.update({"User-Agent": REGISTRY_USER_AGENT, "Accept": "application/json"})
    sources: list[dict[str, Any]] = []
    started = utc_now()
    registry_base_url, _ = registry_bootstrap(session, sources)
    candidates = load_registry_candidates(session, registry_base_url, bank_codes, sources)
    observations, identity_keys, all_codes = build_observations(periods, candidates)
    absence_matrix = build_absence_matrix(periods, observations, candidates)
    relationships = relationship_records(candidates)
    lifecycle_checks = focus_lifecycle_checks(periods, observations, candidates, relationships)

    xbrl_proofs: list[dict[str, Any]] = []
    for period in periods:
        state = choose_state(period, "individual_balance")
        if state is None:
            raise IdentityLifecycleError("individual balance state not found for %s" % period["id"])
        xbrl_proofs.append(xbrl_context_proof(session, period, state, sources))
    first_period = periods[0]
    consolidated = choose_state(first_period, "consolidated_balance")
    if consolidated is None:
        raise IdentityLifecycleError("consolidated balance proof state not found")
    xbrl_proofs.append(xbrl_context_proof(session, first_period, consolidated, sources))
    branch = choose_state(first_period, "branch_or_eee")
    if branch is None:
        raise IdentityLifecycleError("EEE branch proof state not found")
    xbrl_proofs.append(xbrl_context_proof(session, first_period, branch, sources))

    gates, checks = gate_results(
        observations, identity_keys, absence_matrix, xbrl_proofs, lifecycle_checks
    )
    logical = build_logical_output(
        catalog,
        periods,
        catalog_sources,
        candidates,
        observations,
        identity_keys,
        absence_matrix,
        xbrl_proofs,
        lifecycle_checks,
        gates,
        checks,
    )
    finished = utc_now()
    run_meta = {
        "run_id": run_id,
        "status": "PASS" if all(value == "PASS" for value in gates.values()) else "FAIL",
        "started_utc": started,
        "finished_utc": finished,
        "tls_verification": session.verify,
        "user_agent": REGISTRY_USER_AGENT,
        "registry_api_base_url": registry_base_url,
        "source_fetch_count": len(sources),
        "source_fetches": sources,
        "counts": {
            "periods": len(periods),
            "observations": len(observations),
            "unique_keys": len(identity_keys),
            "unique_bank_codes": len(all_codes),
            "absence_matrix_records": len(absence_matrix),
            "xbrl_context_proofs": len(xbrl_proofs),
            "registry_candidates": sum(len(value) for value in candidates.values()),
            "lifecycle_relationships": len(relationships),
        },
        "logical_output_sha256": sha256_bytes(canonical_json_bytes(logical)),
        "gates": gates,
    }
    return logical, run_meta


def render_report(evidence: dict[str, Any], output: dict[str, Any]) -> str:
    gates = evidence["gates"]
    checks = output["checks"]
    focus = output["focus_lifecycle_checks"]
    overall = "PASS" if all(value == "PASS" for value in gates.values()) else "FAIL_CLOSED"
    unstable_keys = [
        item
        for item in output["identity_keys"]
        if item["temporal_stability"] != "STABLE_SINGLE_REGISTRY_ID"
    ]
    lines = [
        "# BankCall España — G1-B Identity & Lifecycle",
        "",
        "**Scope:** frozen ten-period corpus; G1-B only. Taxonomy, concept mapping and product code were not executed.",
        "",
        "## Gate result",
        "",
        "| Gate | Result |",
        "| --- | --- |",
    ]
    lines.extend("| `%s` | **%s** |" % (name, gates[name]) for name in sorted(gates))
    lines.extend(
        [
            "",
            "**Overall result:** **%s**. A failed gate blocks downstream identity-dependent work." % overall,
        ]
    )
    lines.extend(
        [
            "",
            "All identity observations retain the raw SIFDIFU key. The parser accepts only `dddd(dddd)` and stores both components; no component is removed or silently normalized.",
            "",
            "## Proven semantics",
            "",
            "- `0000` is proven as consolidated group by the SIFDIFU `(Grupo)` label and XBRL `AgrupacionGrupoConsolidado`.",
            "- `0001` is proven as consolidated subgroup by the SIFDIFU `(Subgrupo)` label and XBRL `AgrupacionSubgrupoConsolidado`.",
            "- `0002` is proven as the individual/single-entity scope by XBRL `AgrupacionIndividual`; it also appears in the official EEE-branch catalog scope, so the implementation does not equate it with one specific statement family.",
            "- The first component is reconciled to the official registry `codigoBE` and to XBRL identifiers of the form `ES<bank_code>`.",
            "",
            "## Corpus and provenance",
            "",
            "- Observations: **%s**; unique raw keys: **%s**; unique first components: **%s**." % (checks["observation_count"], checks["unique_key_count"], len({item["bank_code"] for item in output["observations"]})),
            "- XBRL identity proofs: **%s** (10 individual balance artifacts, one consolidated balance artifact and one EEE-branch artifact)." % checks["xbrl_proof_count"],
            "- The official BdE Registry API is a supplementary lifecycle authority; it does not discover or replace SIFDIFU catalog URLs.",
            "- Logical run-1/run-2 SHA-256: `%s` / `%s` (%s)." % (evidence["determinism"]["run1_logical_sha256"], evidence["determinism"]["run2_logical_sha256"], evidence["determinism"]["classification"]),
            "",
            "## Identity findings",
            "",
            "- Registry mapping remains unresolved for **%s observations** across **%s raw keys**; these records remain `UNKNOWN` and are not normalized." % (checks["mapping_unknown_count"], checks["mapping_unknown_key_count"]),
            "- Registry mapping basis: %s. Catalog-label LEI cross-checks: %s."
            % (
                ", ".join(
                    "`%s`=%s" % (name, count)
                    for name, count in checks["mapping_basis_counts"].items()
                ),
                ", ".join(
                    "`%s`=%s" % (name, count)
                    for name, count in checks["lei_crosscheck_counts"].items()
                ),
            ),
            "- **%s raw keys** are changed or ambiguous across the evaluation periods. The period-level mapping evidence is retained below; predecessor/successor edges are not used as aliases." % checks["temporal_change_count"],
            "",
            "| Raw SIFDIFU key | Registry IDs observed | Unresolved observations | Period mapping |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for item in unstable_keys:
        period_mapping = "; ".join(
            "%s: %s%s"
            % (
                period["period_id"],
                ",".join(period["mapping_statuses"]),
                " (" + ",".join(period["registry_candidate_ids"]) + ")"
                if period["registry_candidate_ids"]
                else "",
            )
            for period in item["period_mappings"]
        )
        lines.append(
            "| `%s` | %s | %s | %s |"
            % (
                item["raw_sifdifu_key"],
                ", ".join(item["registry_candidate_ids"]) or "none",
                item["unresolved_observation_count"],
                period_mapping,
            )
        )
    lines.extend(
        [
            "",
            "## Bankia and Liberbank boundary",
            "",
            "| BdE code | Official baja | Successor evidence | Catalog presence agrees with baja |",
            "| --- | --- | --- | --- |",
        ]
    )
    for code in FOCUS_CODES:
        item = focus["targets"][code]
        successors = item["successors"]
        successor_text = ", ".join(
            "%s (%s; %s)" % (entry.get("successor_name"), entry.get("successor_bank_code"), entry.get("effective_date"))
            for entry in successors
        ) or "none recorded"
        lines.append(
            "| `%s` | `%s` | %s | `%s` |"
            % (code, item["official_bank_role_baja"], successor_text, item["presence_matches_official_baja_expectation"])
        )
    lines.extend(
        [
            "",
            "Absence is represented as `absent-from-period`, separate from registry `inactive` and from an active-registry scope absence. Successor edges are provenance only. No historical series alias or merger splicing is produced.",
            "",
            "## Reproduction",
            "",
            "```text",
            "python scripts/g1/identity_lifecycle.py",
            "```",
            "",
            "Evidence: `g1-b-evidence.json`; canonical identity output: `entities.json`.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        default=str(Path(__file__).resolve().parents[2] / "evidence" / "g1" / "catalog.json"),
    )
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[2] / "evidence" / "g1"),
    )
    args = parser.parse_args()
    catalog_path = Path(args.catalog).resolve()
    out = Path(args.out).resolve()
    catalog_raw = catalog_path.read_bytes()
    try:
        catalog = json.loads(catalog_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("catalog is not valid UTF-8 JSON: %s" % exc)
    out.mkdir(parents=True, exist_ok=True)

    try:
        logical1, meta1 = execute_run(catalog, "run1")
        logical2, meta2 = execute_run(catalog, "run2")
    except IdentityLifecycleError as exc:
        print("G1-B FAIL_CLOSED: %s" % exc, file=sys.stderr)
        return 2

    logical1_hash = sha256_bytes(canonical_json_bytes(logical1))
    logical2_hash = sha256_bytes(canonical_json_bytes(logical2))
    classification = "IDENTICAL" if logical1_hash == logical2_hash else "UNEXPLAINED_DIFF"
    if classification == "UNEXPLAINED_DIFF":
        logical1["g1_b_determinism"] = "UNEXPLAINED_DIFF"
        logical2["g1_b_determinism"] = "UNEXPLAINED_DIFF"

    gates = dict(logical1["gates"])
    if classification != "IDENTICAL":
        for gate in gates:
            gates[gate] = "FAIL"
    evidence = {
        "schema": "bankcall.g1.identity_lifecycle.evidence.v1",
        "experiment": "BANKCALL_ES_G1_B_IDENTITY_LIFECYCLE",
        "scope": "G1-B only; G1-C/G1-D and product development not executed",
        "source_root": catalog.get("source_root"),
        "registry_authority": {
            "app_root": REGISTRY_APP_ROOT,
            "configuration_path": REGISTRY_CONFIG_PATH,
            "role": "official supplementary identity/lifecycle authority",
        },
        "catalog_input": {
            "path": str(catalog_path),
            "raw_sha256": sha256_bytes(catalog_raw),
            "canonical_sha256": sha256_bytes(canonical_json_bytes(catalog)),
        },
        "determinism": {
            "classification": classification,
            "run1_logical_sha256": logical1_hash,
            "run2_logical_sha256": logical2_hash,
        },
        "result": (
            "PASS"
            if classification == "IDENTICAL"
            and all(value == "PASS" for value in gates.values())
            else "FAIL_CLOSED"
        ),
        "runs": [meta1, meta2],
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "requests": requests.__version__,
            "defusedxml": getattr(__import__("defusedxml"), "__version__", "unknown"),
            "script_sha256": sha256_bytes(Path(__file__).read_bytes()),
            "tls_verification": True,
        },
        "gates": gates,
        "observations": logical1["checks"],
        "identity_findings": {
            "mapping_unknown_by_key": logical1["checks"]["mapping_unknown_by_key"],
            "temporal_instability": [
                {
                    "raw_sifdifu_key": item["raw_sifdifu_key"],
                    "registry_candidate_ids": item["registry_candidate_ids"],
                    "candidate_ids_considered": item["candidate_ids_considered"],
                    "unresolved_observation_count": item["unresolved_observation_count"],
                    "period_mappings": item["period_mappings"],
                }
                for item in logical1["identity_keys"]
                if item["temporal_stability"] != "STABLE_SINGLE_REGISTRY_ID"
            ],
            "raw_key_preserved": logical1["checks"]["raw_key_preserved"],
            "series_splicing_alias_fields": logical1["checks"]["series_splicing_alias_fields"],
        },
        "focus_lifecycle_checks": logical1["focus_lifecycle_checks"],
        "timestamp_utc": utc_now(),
    }
    (out / "entities-run1.json").write_bytes(canonical_json_bytes(logical1))
    (out / "entities-run2.json").write_bytes(canonical_json_bytes(logical2))
    (out / "entities.json").write_bytes(canonical_json_bytes(logical1))
    (out / "g1-b-evidence.json").write_bytes(canonical_json_bytes(evidence))
    (out / "G1-B-REPORT.md").write_text(render_report(evidence, logical1), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if all(value == "PASS" for value in gates.values()) and classification == "IDENTICAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
