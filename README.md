# BankCall España

**BankCall España** provides reproducible, entity-level historical financial
statements for Spanish banks from Banco de España public XBRL data, with
temporal legal-entity identity, taxonomy evolution and source-level
provenance.

```console
$ bankcall compare 0049 0081 0128 --period 2026Q2 --concept "patrimonio neto"
                     Compare — 2026Q2
  Metric          Dims                 0049        0081        0128
  Importe en      BAS=Patrimonio    85,083,626  10,155,716   6,056,638
  libros          neto; MCY=Todo         EUR         EUR         EUR
                  el patrimonio
                  neto
  0049: BANCO SANTANDER, S.A. | 0081: BANCO DE SABADELL, S.A.
    | 0128: BANKINTER, S.A.
```

## Commands

```bash
bankcall ingest                                   # build data/*.parquet (offline, once)
bankcall entity 0073                              # reporting-slot ownership history
bankcall statement 0049 --period 2026Q2 --statement balance
bankcall history 0049 anticipos --from 2020       # time series per dimension combo
bankcall compare 0049 0081 0128 --period 2026Q2   # cross-entity, same period
bankcall changes 0049 --from 2025Q2 --to 2026Q2   # diff with taxonomy-drift flags
```

Statement groups: `balance` (2701–2703), `pl` (4701, 4702), or raw statement
ids. Periods: `2018Q1`, `2026Q2`, or raw `YYYYMM`.

## A bank code is not a legal entity

`0049` is a **reporting slot**, not a company. When the slot changes legal
owner — a documented transfer in the official register — the CLI warns and
segments the series instead of silently splicing it:

```console
$ bankcall entity 0073
  Reporting slot 0073 — legal owner per period
   Period  Raw key     Legal entity      Status
   2018Q1  0073(0002)  OPEN BANK, S.A.   active
   ...
   2026Q2  0073(0002)  OPEN BANK, S.A.   active
  warning: slot 0073 changed legal owner — OPEN BANK, S.A. (until 202506)
  -> OPEN BANK, S.A. (from 202606), official handoff 2026-05-04. Series
  below is segmented; it is NOT one continuous legal entity.
```

9,253 unique slot-to-entity mappings and 8 documented ownership transfers
were extracted and validated in the identity layer (see below).

## Facts are dimensional — nothing is silently aggregated

Every fact carries its dimensional qualifiers (MCI line item, MCY scope,
BAS, APL, ...). `history` returns **one series per dimension combination**;
`statement` lists raw facts with member labels resolved; `changes` flags
facts whose concepts drifted between taxonomy generations
(`STRUCTURALLY_CHANGED`, `RENAMED_EQUIVALENT`, `NEW`, `REMOVED` — from the
G1-C concept mapping). Ambiguous concept names fail closed.

## Methodology and provenance

The corpus underneath this CLI was produced by a reproducible evidence
phase:

| Phase | Scope | Result |
|-------|-------|--------|
| G0 | Acquisition of the official BdE corpus | `g0-acquisition-green` |
| G1-A | Catalog discovery, deterministic | PASS |
| G1-B | Hypothesis "bank code = legal entity" | **falsified** by evidence |
| G1-BR | Corrected model: slot + valid time -> legal entity | PASS (9,253 mappings, 8 transfers) |
| G1-C | Taxonomy versioning, concept mapping, semantic drift | PASS (`g1-c-taxonomy-pass`) |
| G1-D | Integration: 9 contract gates, 10 periods, 117/117 XBRL | PASS (`g1-green`) |

- 117 official XBRL instances, 10 reference periods (2018Q1 – 2026Q2),
  ~197,700 facts ingested.
- Three BdE public-statement taxonomy generations fingerprinted and mapped
  concept-by-concept; 66 non-equivalences detected, none silent.
- Evidence and the code-to-evidence chain: `evidence/g1/`,
  `G1-REPORT.md`, `G1-C-PROVENANCE.md`.
- The G1-B falsification is preserved in `G1-REPORT.md` — the corrected
  temporal-identity model is a feature of this product, not a footnote.

## Install

```bash
pip install -e .
bankcall ingest   # requires the local frozen corpus (see g0_acquisition/)
```

Requires Python >= 3.11. Data products (`data/*.parquet`) are generated
locally and are not committed.

## License

Apache-2.0 — see `LICENSE`.
