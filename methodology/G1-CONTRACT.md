# BankCall España — G1 Contract

**Status:** FROZEN BEFORE G1 EXECUTION

**Contract version:** 1.0

**Freeze date:** 2026-09-13

**Predecessor baseline:** `g0-acquisition-green` (`ea91a93`)

## 1. Objective

G1 must establish that the official Banco de España public-statements corpus can
be discovered, identified and interpreted across taxonomy generations with
reproducible evidence. G1 is an experimental data-and-semantics phase; it is
not the BankCall España product.

The acceptance gates are:

```text
DISCOVERY_DETERMINISTIC
ENTITY_KEY_DECOMPOSED
ENTITY_MAPPING_PROVEN
ENTITY_LIFECYCLE_HANDLED
TAXONOMY_AUTO_RESOLVABLE
CROSS_TAXONOMY_CONCEPT_MAPPING
NO_SILENT_SEMANTIC_DRIFT
PROVENANCE_COMPLETE
TEN_PERIOD_CORPUS_PASS
```

All gates must be `PASS`. `UNKNOWN` is not a pass condition.

## 2. Scope and frozen corpus

The only source root is:

```text
https://app.bde.es/sifdifu/es/#/
```

URLs below that root must be discovered from the official catalog responses.
Derived period, statement, entity and artifact URLs must not be hardcoded in
the G1 extractor. The extractor may retain the source root, parsing rules and
field names as code-level constants.

The corpus is exactly these ten period IDs:

| Period label | BdE period ID |
| --- | --- |
| 2018Q1 | `201803` |
| 2018Q3 | `201809` |
| 2018Q4 | `201812` |
| 2020Q4 | `202012` |
| 2021Q1 | `202103` |
| 2021Q3 | `202109` |
| 2022Q4 | `202212` |
| 2023Q1 | `202303` |
| 2025Q2 | `202506` |
| 2026Q2 | `202606` |

The expected taxonomy generations to resolve are:

```text
publicos_2018_01
publicos_2018_12
publicos_2023_03
```

Their association with a period must be derived from the XBRL itself, normally
through `link:schemaRef` and the entry-point URI. This contract does not
pre-authorize a period-to-taxonomy mapping that the source does not prove.

The corpus must cover the official catalog inventory for each frozen period:
periods, statements, entities and available XBRL/XLSX/PDF artifacts. An
artifact that is unavailable, malformed or no longer advertised is recorded as
such and cannot silently disappear from the inventory. At least one valid
official XBRL artifact must be validated for every frozen period where the
catalog advertises XBRL.

The 2021Q1 and 2021Q3 observations are mandatory lifecycle boundary checks.
Presence, disappearance, name changes or code changes are observations; they
are not evidence of a merger relationship by themselves.

## 3. Deliverables

G1 produces evidence and experimental outputs only:

```text
evidence/g1/catalog.json
evidence/g1/entities.json
evidence/g1/taxonomy-registry.json
evidence/g1/concept-mapping.json
evidence/g1/g1-evidence.json
evidence/g1/G1-REPORT.md
```

The canonical JSON outputs must use stable ordering and stable serialization.
Retrieval timestamps and other run metadata belong in provenance/evidence and
must not make a logically identical inventory appear different.

Raw downloads may remain local or be stored outside Git when large or
sensitive. Their URL, final URL, SHA-256, byte count, content type and
validation result must remain in the evidence. No private cookies, bearer
tokens, session IDs or other reusable secrets may be committed.

## 4. Execution protocol

1. Start from a clean working directory and a fresh HTTP session.
2. Discover the catalog from the source root; follow only URLs returned by the
   source or deterministic links derived from those responses.
3. Use HTTP with TLS verification enabled. A browser is not part of the G1
   method unless a separately documented blocker proves it is unavoidable.
4. Validate status, final URL, content type and payload structure. HTTP 200 is
   never sufficient evidence of an expected artifact.
5. Parse XBRL/XML with external entity resolution and network access disabled.
6. Preserve the raw source hash before producing normalized or canonical data.
7. Run the discovery and normalization procedure twice from clean sessions.
   Differences must be classified; they must not be normalized away globally.
8. Fail closed on an invalid, missing, changed or semantically ambiguous source.
   A stale prior output must never be presented as a current successful run.

## 5. Gate definitions

### `DISCOVERY_DETERMINISTIC`

`PASS` requires that two clean runs from the source root produce the same
canonical inventory of the ten periods, their advertised statements, entities
and artifacts, subject only to explicitly recorded source changes. Every
record must retain the source URL and final URL. Any unclassified ordering,
missing entry or source substitution is `FAIL`.

### `ENTITY_KEY_DECOMPOSED`

Every SIFDIFU key such as `0049(0002)` or `0049(0000)` must be retained in raw
form and parsed into at least:

```text
bank_code
component_or_suffix
```

The parser must reject malformed keys and must not assign business meaning to
the component/suffix until an official source proves that meaning.

### `ENTITY_MAPPING_PROVEN`

Each identity record must link the raw SIFDIFU key to the official entity code,
name and period using source evidence. Where the XBRL contains an entity
identifier, that identifier must be recorded separately and reconciled rather
than guessed. An unresolved mapping is explicit `UNKNOWN` or `NOT_COMPARABLE`,
not an inferred match based only on name, prefix or proximity.

### `ENTITY_LIFECYCLE_HANDLED`

For every entity observed in the frozen corpus, records must distinguish:

```text
active / inactive / absent-from-period / unknown
```

Predecessor and successor relationships may be recorded only with authoritative
source evidence. A missing entity, changed code or changed name does not prove
absorption, succession or continuity. BankCall must not splice a historical
series across a merger or successor relationship automatically.

### `TAXONOMY_AUTO_RESOLVABLE`

For every validated XBRL artifact, the taxonomy and entry point must be
resolved from the XBRL (`schemaRef` and related source metadata), recorded with
the artifact hash, period and statement, and assigned to one of the expected
taxonomy generations when the source proves that assignment. Missing or
conflicting taxonomy evidence is `UNKNOWN`/`FAIL`; a manually supplied
period-to-taxonomy table is not sufficient.

### `CROSS_TAXONOMY_CONCEPT_MAPPING`

Concept mappings between taxonomy generations must retain both qualified
concept identities and the evidence used to compare them. A mapping is not
valid merely because labels or local names resemble each other.

### `NO_SILENT_SEMANTIC_DRIFT`

The comparison must check, where present, concept definition, label, data type,
period type, balance attribute, units, dimensions, references and relevant
calculation/presentation structure. A material change must be surfaced in the
mapping classification. No transformation may silently chain facts across a
change it has not explained.

### `PROVENANCE_COMPLETE`

Every fact-level observation and every identity/taxonomy/concept relationship
must be traceable to:

```text
source URL
final URL
source SHA-256
period
statement
taxonomy / entry point
entity and raw entity key when applicable
concept / qualified concept name when applicable
retrieval timestamp
TLS verification result
```

If a field does not exist in the source, the record must say so explicitly; it
must not be fabricated.

### `TEN_PERIOD_CORPUS_PASS`

`PASS` requires all ten frozen periods to be present in the canonical inventory,
to be rediscoverable from the official source, and to pass the applicable
artifact, identity, taxonomy and provenance checks. The report must show the
result for every period and every gate. A ten-file sample that omits advertised
catalog entries is not a corpus pass.

## 6. Cross-taxonomy classification

Every compared concept pair must have exactly one of these classifications:

```text
EXACT_EQUIVALENT
RENAMED_EQUIVALENT
STRUCTURALLY_CHANGED
NEW
REMOVED
NOT_COMPARABLE
UNKNOWN
```

Definitions:

- `EXACT_EQUIVALENT`: identity and reported semantics are proven equivalent.
- `RENAMED_EQUIVALENT`: the qualified identity or label changed, but the
  underlying definition and reporting semantics are proven equivalent.
- `STRUCTURALLY_CHANGED`: a related concept changed in a way that affects
  interpretation, such as type, period, balance, unit, dimension or definition.
- `NEW`: present in the later taxonomy/corpus with no earlier counterpart.
- `REMOVED`: present in the earlier taxonomy/corpus with no later counterpart.
- `NOT_COMPARABLE`: a candidate relationship exists but exact comparability
  cannot be demonstrated, or evidence contradicts equivalence.
- `UNKNOWN`: required evidence is incomplete or unresolved.

The governing rule is:

```text
UNKNOWN != equivalent
NOT_COMPARABLE != equivalent
```

Neither value may be used to create a historical series. `STRUCTURALLY_CHANGED`
also blocks automatic chaining unless a later, explicit semantic rule proves
which transformation is valid.

## 7. Lifecycle and identity records

Identity records must preserve the raw key and include, at minimum:

```text
bank_code
SIFDIFU key
parsed component/suffix
official name
period
active/inactive/absent/unknown status
predecessor/successor records when officially proven
source references and hashes
```

The semantics of `0049(0002)`, `0049(0000)` and other components are an output
of G1 evidence, not a premise of the implementation. No merger-series splicing
is permitted.

## 8. Stop rules and change control

G1 stops with `FAIL` or `HOLD` if any mandatory gate is `FAIL` or `UNKNOWN`, if
the source changes without a new evidence record, or if a concept would need to
be chained without an evidence-backed classification. Thresholds and
classification rules must not be relaxed after observing results.

Changes to this contract after G1 execution begins require a new contract
version, a new freeze commit and a rerun of affected gates. The original
evidence remains immutable.

The following are explicitly outside G1:

```text
public Bank() API
product CLI
UI or frontend
warehouse/database production design
ratios, rankings or derived indicators
public deployment
full AEB cross-source validation
```

G1 is complete only when `G1-REPORT.md` contains the gate table, per-period
results, unresolved items, all non-equivalences and the final falsifiable
verdict.
