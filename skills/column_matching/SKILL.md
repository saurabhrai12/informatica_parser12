---
name: column_matching
description: The 14-strategy Oracle↔Snowflake column matching methodology. Load before modifying step2_mapping/matcher.py or synonym_dict.py.
owner: step2_mapping
agent_modifiable: true
improved_by: autoresearch (program_mapping.md)
---

# Column matching methodology — 14 strategies

Authoritative source: `mapping_identification.txt`. Step 2 eval is the final
arbiter; this skill encodes the reasoning shortcuts.

## Strategies in priority order

1. **Exact name match** → 1.00 (always wins)
2. **Normalised match** — strip prefixes/suffixes, collapse `_` → 0.93
3. **Abbreviation expansion** — via `synonym_dict.ABBREV` → 0.85–0.95 by edit distance
4. **CamelCase / snake_case alignment** → same tier as normalised
5. **Edit-distance fuzzy** — Levenshtein ratio → score × 0.85
6. **Semantic synonym inference** — via `synonym_dict.SYNONYMS` → **capped at 0.80**
7. **Domain-aware dictionary** — AML/fraud/risk terms
8. **Sample data value overlap** — **capped at 0.70** if name has no similarity
9. **Enumeration / code set matching** — shared small distinct-value set
10. **Column comment match** — keyword overlap → +0.05 boost
11. **Data type compatibility** — **modifier**: +0.05 same family, −0.10 cross
12. **Length / precision alignment** — tiebreaker only
13. **Primary/foreign key relationship** — PK↔PK bonus +0.05
14. **Nullability consistency** — tiebreaker only

## Scoring formula

```
name_score  = <strategy 1-7 top hit>
score       = name_score
            + (+0.10 if same-table anchor, −0.20 if cross-table)
            + (+0.05 if type family match, −0.10 if mismatch)
            + (+0.05 if comment keyword overlap)
            + (+0.05 if both PK or both FK)
score       = min(1.0, max(0.0, score))
tier        = HIGH ≥0.90 | MEDIUM ≥0.65 | LOW ≥0.40 | UNMATCHED <0.40
```

## Table-anchor rule (critical)

**Always resolve table-level matching BEFORE column-level.** Apply abbreviation
and synonym expansion to table names first. Then for every Oracle column:
- If the best-scoring Snowflake candidate is in a **different** table, apply a
  −0.20 penalty. This prevents `CUST_ID` in `TXN_FACT` from wrongly mapping
  to `CUSTOMER_DIM.CUSTOMER_ID`.
- If both sides are in the same table (or abbreviation-equivalent tables),
  apply a +0.10 bonus.

## Prefix/suffix normalisation

Strip these Oracle-style prefixes before matching:
- Table-name prefixes: `CUST_` from `CUST_ID` in `CUSTOMER_DIM`
- Single-letter type prefixes: `C_`, `N_`, `D_` (char/numeric/date)
- Hungarian-like: `STR_`, `NUM_`, `DT_`

Common Oracle suffixes meaning the same thing: `_ID` / `_KEY` / `_NO` / `_NBR`
(numeric identifier), `_CD` / `_CODE` / `_TYP` / `_TYPE` (enum), `_DT` / `_DATE`
/ `_TS` / `_TMSTMP` (temporal), `_FLG` / `_IND` (boolean flag).

## Cap rules

- Semantic inference alone (no name similarity, no data overlap) → **cap 0.80**
- Data overlap alone (distinct value set match, no name similarity) → **cap 0.70**
- These caps can only be exceeded when corroborated by another strategy

## Unmatched output

Every column on both sides must appear exactly once in the output:
- matched → `mappings[]`
- unmatched Oracle → `unmatched_oracle[]` with `action = NEW_COLUMN_NEEDED | DEPRECATED | INVESTIGATE`
- unmatched Snowflake → `unmatched_snowflake[]` with `action = NEW_FIELD | DERIVED | INVESTIGATE`

Columns like `LOAD_TS` and `IS_HIGH_VALUE` that exist only in Snowflake are
usually DERIVED (populated by the proc itself) — mark them `DERIVED`, not
`INVESTIGATE`.

## Domain abbreviations (reference — extend in `synonym_dict.py`)

Financial crime / AML: `TXN`→TRANSACTION, `ALERT`, `SAR`→SAR_FLAG, `STRCT`→STRUCTURING,
`RISK`→RISK_SCORE, `KYC`, `FRAUD`.

Temporal: `CRT`/`CREATE`→CREATED, `UPD`/`MOD`→UPDATED, `INS`→INSERT, `LOAD`,
`EFF`→EFFECTIVE, `EXP`→EXPIRY.

Flags: `FLG`/`IND`→FLAG/INDICATOR, `IS_*` convention on Snowflake side.

## Learned synonym pairs (append-only)

<!-- autoresearch appends new synonym pairs discovered during eval runs -->
