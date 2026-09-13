# BankCall España — G1-B Identity & Lifecycle

**Scope:** frozen ten-period corpus; G1-B only. Taxonomy, concept mapping and product code were not executed.

## Gate result

| Gate | Result |
| --- | --- |
| `ENTITY_ID_STABLE` | **FAIL** |
| `ENTITY_KEY_DECOMPOSED` | **PASS** |
| `ENTITY_KEY_TEMPORAL_STABILITY` | **FAIL** |
| `ENTITY_LIFECYCLE_HANDLED` | **PASS** |
| `ENTITY_MAPPING_PROVEN` | **PASS** |
| `EXPECTED_ABSENCE_DISTINGUISHED` | **PASS** |
| `NO_MERGER_SERIES_SPLICING` | **PASS** |

**Overall result:** **FAIL_CLOSED**. A failed gate blocks downstream identity-dependent work.

All identity observations retain the raw SIFDIFU key. The parser accepts only `dddd(dddd)` and stores both components; no component is removed or silently normalized.

## Proven semantics

- `0000` is proven as consolidated group by the SIFDIFU `(Grupo)` label and XBRL `AgrupacionGrupoConsolidado`.
- `0001` is proven as consolidated subgroup by the SIFDIFU `(Subgrupo)` label and XBRL `AgrupacionSubgrupoConsolidado`.
- `0002` is proven as the individual/single-entity scope by XBRL `AgrupacionIndividual`; it also appears in the official EEE-branch catalog scope, so the implementation does not equate it with one specific statement family.
- The first component is reconciled to the official registry `codigoBE` and to XBRL identifiers of the form `ES<bank_code>`.

## Corpus and provenance

- Observations: **9253**; unique raw keys: **288**; unique first components: **233**.
- XBRL identity proofs: **12** (10 individual balance artifacts, one consolidated balance artifact and one EEE-branch artifact).
- The official BdE Registry API is a supplementary lifecycle authority; it does not discover or replace SIFDIFU catalog URLs.
- Logical run-1/run-2 SHA-256: `c6ca6ea35d8d99a91fe603773680dfbee65afb8cc6d99e999fdba1e53a9c17f4` / `c6ca6ea35d8d99a91fe603773680dfbee65afb8cc6d99e999fdba1e53a9c17f4` (IDENTICAL).

## Identity findings

- Registry mapping remains unresolved for **0 observations** across **0 raw keys**; these records remain `UNKNOWN` and are not normalized.
- Registry mapping basis: `CODE_OWNERSHIP_HISTORY`=9253. Catalog-label LEI cross-checks: `MATCH`=4722, `NOT_APPLICABLE_NO_LABEL_LEI`=4522, `NO_CANDIDATE_LEI_DOCUMENT`=9.
- **8 raw keys** are changed or ambiguous across the evaluation periods. The period-level mapping evidence is retained below; predecessor/successor edges are not used as aliases.

| Raw SIFDIFU key | Registry IDs observed | Unresolved observations | Period mapping |
| --- | --- | ---: | --- |
| `0073(0002)` | registry:33119, registry:33408 | 0 | 201803: PROVEN (registry:33119); 201809: PROVEN (registry:33119); 201812: PROVEN (registry:33119); 202012: PROVEN (registry:33119); 202103: PROVEN (registry:33119); 202109: PROVEN (registry:33119); 202212: PROVEN (registry:33119); 202303: PROVEN (registry:33119); 202506: PROVEN (registry:33119); 202606: PROVEN (registry:33408) |
| `0152(0002)` | registry:34542, registry:37779 | 0 | 201803: PROVEN (registry:34542); 201809: PROVEN (registry:34542); 201812: PROVEN (registry:34542); 202012: PROVEN (registry:37779); 202103: PROVEN (registry:37779); 202109: PROVEN (registry:37779); 202212: PROVEN (registry:37779); 202303: PROVEN (registry:37779); 202506: PROVEN (registry:37779); 202606: PROVEN (registry:37779) |
| `0160(0002)` | registry:32850, registry:37755 | 0 | 201803: PROVEN (registry:32850); 201809: PROVEN (registry:37755); 201812: PROVEN (registry:37755); 202012: PROVEN (registry:37755); 202103: PROVEN (registry:37755); 202109: PROVEN (registry:37755); 202212: PROVEN (registry:37755); 202303: PROVEN (registry:37755); 202506: PROVEN (registry:37755); 202606: PROVEN (registry:37755) |
| `0162(0002)` | registry:34543, registry:37781 | 0 | 201803: PROVEN (registry:34543); 201809: PROVEN (registry:34543); 201812: PROVEN (registry:34543); 202012: PROVEN (registry:37781); 202103: PROVEN (registry:37781); 202109: PROVEN (registry:37781); 202212: PROVEN (registry:37781); 202303: PROVEN (registry:37781); 202506: PROVEN (registry:37781); 202606: PROVEN (registry:37781) |
| `0220(0002)` | registry:32858, registry:37877 | 0 | 201803: PROVEN (registry:32858); 201809: PROVEN (registry:32858); 201812: PROVEN (registry:32858); 202012: PROVEN (registry:32858); 202103: PROVEN (registry:32858); 202109: PROVEN (registry:32858); 202212: PROVEN (registry:37877); 202303: PROVEN (registry:37877); 202506: PROVEN (registry:37877); 202606: PROVEN (registry:37877) |
| `1485(0002)` | registry:37689, registry:37769 | 0 | 201803: PROVEN (registry:37689); 201809: PROVEN (registry:37689); 201812: PROVEN (registry:37769); 202012: PROVEN (registry:37769); 202103: PROVEN (registry:37769); 202109: PROVEN (registry:37769); 202212: PROVEN (registry:37769); 202303: PROVEN (registry:37769); 202506: PROVEN (registry:37769); 202606: PROVEN (registry:37769) |
| `1551(0002)` | registry:34306, registry:37800 | 0 | 201803: PROVEN (registry:34306); 201809: PROVEN (registry:34306); 201812: PROVEN (registry:34306); 202012: PROVEN (registry:37800); 202103: PROVEN (registry:37800); 202109: PROVEN (registry:37800); 202212: PROVEN (registry:37800); 202303: PROVEN (registry:37800); 202506: PROVEN (registry:37800); 202606: PROVEN (registry:37800) |
| `1565(0002)` | registry:33482, registry:34311 | 0 | 201812: PROVEN (registry:33482); 202012: PROVEN (registry:34311); 202103: PROVEN (registry:34311); 202109: PROVEN (registry:34311); 202212: PROVEN (registry:34311); 202303: PROVEN (registry:34311) |

## Bankia and Liberbank boundary

| BdE code | Official baja | Successor evidence | Catalog presence agrees with baja |
| --- | --- | --- | --- |
| `2038` | `2021-03-26` | CAIXABANK, S.A. (2100; 2021-03-26) | `True` |
| `2048` | `2021-07-30` | UNICAJA BANCO, S.A. (2103; 2021-07-30) | `True` |

Absence is represented as `absent-from-period`, separate from registry `inactive` and from an active-registry scope absence. Successor edges are provenance only. No historical series alias or merger splicing is produced.

## Reproduction

```text
python scripts/g1/identity_lifecycle.py
```

Evidence: `g1-b-evidence.json`; canonical identity output: `entities.json`.
