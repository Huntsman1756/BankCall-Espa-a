# BankCall España — G1 Final Report

**Verdict: PASS** — all nine contract gates evaluated mechanically over the frozen evidence set (no concept reprocessing).

Contract: `methodology/G1-CONTRACT.md` v1.0 (frozen before execution).

## Gate table

| Gate | Result | Evidence |
| --- | --- | --- |
| `DISCOVERY_DETERMINISTIC` | **PASS** | g1-evidence inputs.g1_a (run1 == run2) |
| `ENTITY_KEY_DECOMPOSED` | **PASS** | entities.json checks |
| `ENTITY_MAPPING_PROVEN` | **PASS** | entities.json + g1-br-evidence.json |
| `ENTITY_LIFECYCLE_HANDLED` | **PASS** | entities.json + g1-br-evidence.json |
| `TAXONOMY_AUTO_RESOLVABLE` | **PASS** | g1-c-evidence.json |
| `CROSS_TAXONOMY_CONCEPT_MAPPING` | **PASS** | g1-c-evidence.json |
| `NO_SILENT_SEMANTIC_DRIFT` | **PASS** | g1-c-evidence.json |
| `PROVENANCE_COMPLETE` | **PASS** | field audit (this evidence) |
| `TEN_PERIOD_CORPUS_PASS` | **PASS** | period matrix below |

## Ten-period corpus matrix

| Period | discovered | XBRL valid | identity | taxonomy | provenance | XBRL validated/advertised | entities |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2018Q1 (`201803`) | PASS | PASS | PASS | PASS | PASS | 11/11 | 883 obs |
| 2018Q3 (`201809`) | PASS | PASS | PASS | PASS | PASS | 11/11 | 858 obs |
| 2018Q4 (`201812`) | PASS | PASS | PASS | PASS | PASS | 15/15 | 1266 obs |
| 2020Q4 (`202012`) | PASS | PASS | PASS | PASS | PASS | 15/15 | 1229 obs |
| 2021Q1 (`202103`) | PASS | PASS | PASS | PASS | PASS | 11/11 | 799 obs |
| 2021Q3 (`202109`) | PASS | PASS | PASS | PASS | PASS | 11/11 | 790 obs |
| 2022Q4 (`202212`) | PASS | PASS | PASS | PASS | PASS | 15/15 | 1183 obs |
| 2023Q1 (`202303`) | PASS | PASS | PASS | PASS | PASS | 11/11 | 785 obs |
| 2025Q2 (`202506`) | PASS | PASS | PASS | PASS | PASS | 11/11 | 847 obs |
| 2026Q2 (`202606`) | PASS | PASS | PASS | PASS | PASS | 6/6 | 613 obs |

## G1-B falsification record (kept, not hidden)

```text
Original hypothesis: stable BdE code = stable legal entity
  -> FALSIFIED (ENTITY_ID_STABLE / ENTITY_KEY_TEMPORAL_STABILITY FAIL
     in g1-b-evidence.json, gate g1-b-identity-lifecycle-v1.0)
Corrected model: reporting slot + valid time -> legal entity (ADR-001)
  -> VALIDATED (g1-br-evidence.json; all six model gates PASS, tag
     g1-b-identity-lifecycle-v1.0)
```

- 8 documented slot transfers (code-reuse events, official handoff dates)
- 9253 unique per-period mappings, all basis=CODE_OWNERSHIP_HISTORY
- Merger-series splicing: DISABLED and verified absent

## Cross-taxonomy mapping summary

| Pair | EXACT_EQUIVALENT | NEW | NOT_COMPARABLE | REMOVED | RENAMED_EQUIVALENT | STRUCTURALLY_CHANGED | UNKNOWN |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `publicos_2018_01__publicos_2018_12` | 20145 | 1 | 0 | 0 | 4 | 57 | 0 |
| `publicos_2018_12__publicos_2023_03` | 20203 | 0 | 0 | 0 | 4 | 0 | 0 |

## All non-equivalences (66)

Every compared concept not classified `EXACT_EQUIVALENT`. Full evidence (fingerprints, changed fields, versioning events) in `concept-mapping.json`.

| Pair | From QName | To QName | Classification |
| --- | --- | --- | --- |
| `publicos_2018_01__publicos_2018_12` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-12-01}publicos_2018_12` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-12-01}publicos_2018_12` | `NEW` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-01-01/mod/pc_con1}PC_CON1` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-12-01/mod/pc_con1}PC_CON1` | `RENAMED_EQUIVALENT` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-01-01/mod/pi_in1}PI_IN1` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-12-01/mod/pi_in1}PI_IN1` | `RENAMED_EQUIVALENT` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-01-01/mod/ps_in1}PS_IN1` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-12-01/mod/ps_in1}PS_IN1` | `RENAMED_EQUIVALENT` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-01-01_tab}tgPC_2` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-12-01_tab}tgPC_2` | `RENAMED_EQUIVALENT` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.bde.es/xbrl/dict/dim}MCI` | `{http://www.bde.es/xbrl/dict/dim}MCI` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.bde.es/xbrl/dict/dim}PLO` | `{http://www.bde.es/xbrl/dict/dim}PLO` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}APL` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}APL` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}BAS` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}BAS` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}CNO` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}CNO` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}CPS` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}CPS` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}ENC` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}ENC` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}FRS` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}FRS` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}MCB` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}MCB` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}MCE` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}MCE` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}MCF` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}MCF` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}MCP` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}MCP` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}MCY` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}MCY` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}RPR` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}RPR` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}SOL` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}SOL` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}SUB` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}SUB` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}TYH` | `{http://www.eba.europa.eu/xbrl/crr/dict/dim}TYH` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/BT}x0` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/BT}x0` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x107` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x107` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x108` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x108` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x20` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x20` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x25` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x25` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x269` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x269` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x277` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x277` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x279` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x279` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x28` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x28` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x29` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x29` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x31` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x31` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x409` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x409` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x45` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x45` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x501` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x501` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x516` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x516` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x696` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x696` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x9` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x9` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x92` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/MC}x92` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x3` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x3` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x4` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x4` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x6` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x6` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x686` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x686` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x689` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x689` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x70` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x70` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x73` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x73` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x74` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x74` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x741` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x741` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x76` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x76` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x77` | `{http://www.eba.europa.eu/xbrl/crr/dict/dom/PL}x77` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}AP` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}AP` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}BA` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}BA` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}BT` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}BT` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}CG` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}CG` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}CT` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}CT` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}MC` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}MC` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}PL` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}PL` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}RP` | `{http://www.eba.europa.eu/xbrl/crr/dict/exp}RP` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/met}md103` | `{http://www.eba.europa.eu/xbrl/crr/dict/met}md103` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eba.europa.eu/xbrl/crr/dict/met}mi53` | `{http://www.eba.europa.eu/xbrl/crr/dict/met}mi53` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_01__publicos_2018_12` | `{http://www.eurofiling.info/xbrl/ext/model}hyp` | `{http://www.eurofiling.info/xbrl/ext/model}hyp` | `STRUCTURALLY_CHANGED` |
| `publicos_2018_12__publicos_2023_03` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-01-01}publicos_2018_01` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2023-03-01}publicos_2023_03` | `RENAMED_EQUIVALENT` |
| `publicos_2018_12__publicos_2023_03` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-12-01/mod/pc_con1}PC_CON1` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2023-03-01/mod/pc_con1}PC_CON1` | `RENAMED_EQUIVALENT` |
| `publicos_2018_12__publicos_2023_03` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-12-01/mod/pi_in1}PI_IN1` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2023-03-01/mod/pi_in1}PI_IN1` | `RENAMED_EQUIVALENT` |
| `publicos_2018_12__publicos_2023_03` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2018-12-01/mod/ps_in1}PS_IN1` | `{http://www.bde.es/xbrl/fws/publicos/circ-4-2017/2023-03-01/mod/ps_in1}PS_IN1` | `RENAMED_EQUIVALENT` |

## Unresolved items and recorded defects

- Concepts `UNKNOWN`/`NOT_COMPARABLE` in mapping: **0**
- Entity mappings unknown: **0**
- G1-B falsified gates (historical): `ENTITY_ID_STABLE, ENTITY_KEY_TEMPORAL_STABILITY`
- exp.xsd retains 3 dangling official EBA references (eba_qBA/qCU/qGA) absent from every published EBA dictionary — upstream source defect, recorded in g1-c-evidence.json notes
- contract advertised XLSX; official catalog ships .xls — recorded in g1-evidence contract_discrepancies
- G1-A discarded development run: recorded in `inputs.g1_a.discarded_development_runs`

## Falsifiable verdict

G1 claims: the official BdE SIFDIFU public-statements corpus for the ten frozen periods is discoverable deterministically, every entity key is decomposed and mapped to a unique legal entity per period via official code-ownership history, all advertised XBRL artifacts resolve their taxonomy generation from `schemaRef` alone, and cross-generation concept comparison is complete with zero silent drift.

This verdict is falsified if any of the following is shown: an advertised XBRL artifact in the frozen catalog without a `SCHEMAREF_RESOLVED` registry entry; an entity observation without `PROVEN` mapping basis; a concept pair lacking one of the seven contract classifications; or a re-run of `scripts/g1/g1d_integrate.py` over the same frozen inputs yielding a different evidence hash.
