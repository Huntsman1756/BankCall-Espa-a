# BankCall España — G1-BR Corrected Temporal Identity Model

Validates ADR-001 against the frozen `entities.json` produced by G1-B
v1.0 (`g1-b-identity-lifecycle-v1.0`). Pure offline check; no source
fetches. G1-B v1.0 keeps its two FAIL gates as the falsification
record; this report evaluates the corrected model.

## Gate result

| Gate | Result |
| --- | --- |
| `CODE_REUSE_DETECTED` | **PASS** |
| `CODE_TRANSFER_FAIL_CLOSED` | **PASS** |
| `ENTITY_MAPPING_UNIQUE_PER_PERIOD` | **PASS** |
| `LEGAL_ENTITY_IDENTITY_STABLE` | **PASS** |
| `REPORTING_SLOT_TEMPORAL_OWNERSHIP_PROVEN` | **PASS** |
| `SCOPE_SEMANTICS_PROVEN` | **PASS** |

- Observations: **9253**; non-unique mappings: **0**.
- Mapping basis: `CODE_OWNERSHIP_HISTORY`=9253.
- Registry elements observed: **240**; unstable element names: **0**; LEI mismatches: **0**.

## Documented slot transfers

| Raw key | From | To | Handoff date | Documented |
| --- | --- | --- | --- | --- |
| `0073(0002)` | OPEN BANK, S.A.  (registry:33119) | OPEN BANK, S.A.  (registry:33408) | `2026-05-04` | `True` |
| `0152(0002)` | BARCLAYS BANK PLC, SUCURSAL EN ESPAÑA  (registry:34542) | BARCLAYS BANK IRELAND PLC, SUCURSAL EN ESPAÑA  (registry:37779) | `2019-02-01` | `True` |
| `0160(0002)` | THE BANK OF TOKYO-MITSUBISHI UFJ, LTD., SUCURSAL EN ESPAÑA  (registry:32850) | MUFG BANK (EUROPE) N.V., SUCURSAL EN ESPAÑA  (registry:37755) | `2018-04-01` | `True` |
| `0162(0002)` | HSBC BANK PLC, SUCURSAL EN ESPAÑA  (registry:34543) | HSBC CONTINENTAL EUROPE, SUCURSAL EN ESPAÑA  (registry:37781) | `2019-02-01` | `True` |
| `0220(0002)` | BANCO FINANTIA SPAIN, S.A.  (registry:32858) | BANCO FINANTIA, S.A., SUCURSAL EN ESPAÑA  (registry:37877) | `2021-11-25` | `True` |
| `1485(0002)` | BANK OF AMERICA MERRILL LYNCH INTERNATIONAL LIMITED, SUCURSAL EN ESPAÑA  (registry:37689) | BANK OF AMERICA EUROPE  DAC, SUCURSAL EN ESPAÑA  (registry:37769) | `2018-12-01` | `True` |
| `1551(0002)` | SUMITOMO MITSUI BANKING CORPORATION EUROPE LIMITED, SUCURSAL EN ESPAÑA  (registry:34306) | SMBC BANK EU AG, SUCURSAL EN ESPAÑA  (registry:37800) | `2019-04-01` | `True` |
| `1565(0002)` | OPEL BANK GMBH, SUCURSAL EN ESPAÑA  (registry:33482) | OPEL BANK, S.A., SUCURSAL EN ESPAÑA  (registry:34311) | `2019-11-04` | `True` |

## Reproduction

```text
python scripts/g1/validate_identity_model.py
```

Input: `entities.json` (frozen G1-B v1.0 output). Evidence: `g1-br-evidence.json`.
