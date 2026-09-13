# ADR-001 — BdE codes are temporal reporting slots, not stable legal-entity identifiers

**Status:** ACCEPTED — documents the model correction mandated by the G1-B
v1.0 falsification. G1-CONTRACT.md v1.0 remains unchanged; its two FAIL
results are preserved as the falsification record.

**Date:** 2026-09-13

**Evidence:** `evidence/g1/g1-b-evidence.json`, `evidence/g1/entities.json`
(tag `g1-b-identity-lifecycle-v1.0`).

## Context

G1-B v1.0 assumed that a raw SIFDIFU key (`dddd(dddd)`, e.g. `0049(0002)`)
identifies one legal entity over time. That hypothesis was falsified by
official BdE registry evidence: **8 of 288 keys change the underlying legal
entity across the frozen corpus**.

- `0073(0002)` Open Bank: element `33119` (NIF A28021079, LEI
  `95980020140006024944`) held code 0073 from 1899-06-30 to 2026-05-04; on
  that date Santander Consumer Finance (element `33408`, NIF A28122570, LEI
  `5493000LM0MZ4JPMGM90`, formerly code 0224) absorbed it and adopted code
  0073 and the name "OPEN BANK, S.A." Both elements showed overlapping active
  Banco roles, so role activity alone could not disambiguate; the official
  code-assignment history (`historia-codigosbde`) resolves every period.
- Seven EEE-branch slots (`0152`, `0160`, `0162`, `0220`, `1485`, `1551`,
  `1565` with suffix `(0002)`) transferred between legal entities (e.g.
  Barclays Bank PLC S.E. → Barclays Bank Ireland PLC S.E. on 2019-02-01).
  `0160` has been held by three successive elements.

Every transition is a single documented handoff: the predecessor's ownership
interval ends on the same date the successor's begins. No flip-flopping was
observed.

## Decision

Identity in BankCall is modeled in valid time:

```text
LegalEntity                  ReportingSlot
  registry_element_id          bde_code
  lei                          aggregation_scope
  legal_name                         │
        ▲                            │ period
        └─────── valid-time ─────────┘
                 ownership
                     │
            FinancialObservation
```

- A `ReportingSlot` (`bde_code` + `component_or_suffix`) identifies where a
  report was filed, not who filed it.
- A `LegalEntity` is the registry element (`idelemento`), corroborated by
  LEI when present.
- Slot → entity is a **per-period** mapping proven by the official
  `historia-codigosbde` intervals, with the catalog-label LEI as
  disambiguator and fail-closed conflict check.

## Consequences

- `ENTITY_ID_STABLE` / `ENTITY_KEY_TEMPORAL_STABILITY` stay FAIL in G1-B
  v1.0 as the falsification record.
- The corrected model is validated by `scripts/g1/validate_identity_model.py`
  against the frozen `entities.json` (see `g1-br-evidence.json`).
- A future API must never silently splice history across a slot transfer:
  `Bank("0073").history()` is semantically invalid. Acceptable forms are
  `Entity(registry_id).history()`, `BankCode("0073").history()` returning
  explicit ownership segments, or an `as_of` parameter when the code is
  temporally ambiguous.
- `sucesorasRol` relationships remain lineage/provenance only. No automatic
  financial-series chaining across predecessors and successors.
