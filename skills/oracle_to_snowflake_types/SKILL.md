---
name: oracle_to_snowflake_types
description: Oracle → Snowflake data type mapping reference with edge cases and cast recipes. Load before modifying step2_mapping/matcher.py or step3_procgen/generator.py.
owner: step2_mapping, step3_procgen
agent_modifiable: true
improved_by: autoresearch (program_mapping.md, program_procgen.md)
---

# Oracle → Snowflake data type migration

## Canonical mapping

| Oracle type | Snowflake type | Cast recipe |
|---|---|---|
| `NUMBER` (no precision) | `NUMBER(38,0)` | none |
| `NUMBER(p,0)` | `NUMBER(38,0)` (or `BIGINT` for surrogate keys) | none |
| `NUMBER(p,s)` | `NUMBER(p,s)` | none |
| `FLOAT`, `BINARY_FLOAT`, `BINARY_DOUBLE` | `FLOAT` | none |
| `VARCHAR2(n)` | `VARCHAR(n)` | none |
| `NVARCHAR2(n)` | `VARCHAR(n)` | none |
| `CHAR(n)` | `CHAR(n)` (or `VARCHAR(n)` if padding matters) | `RTRIM(col)` if trailing spaces unwanted |
| `CLOB` | `VARCHAR(16777216)` | `TO_VARCHAR(col)` |
| `NCLOB` | `VARCHAR(16777216)` | `TO_VARCHAR(col)` |
| `DATE` | `TIMESTAMP_NTZ(0)` | `TRY_TO_TIMESTAMP_NTZ(col)` — Oracle DATE includes time |
| `TIMESTAMP` | `TIMESTAMP_NTZ(9)` | `TRY_TO_TIMESTAMP_NTZ(col, 9)` |
| `TIMESTAMP WITH TIME ZONE` | `TIMESTAMP_TZ(9)` | `TRY_TO_TIMESTAMP_TZ(col)` |
| `TIMESTAMP WITH LOCAL TIME ZONE` | `TIMESTAMP_LTZ(9)` | `TRY_TO_TIMESTAMP_LTZ(col)` |
| `INTERVAL DAY TO SECOND` | `VARCHAR(64)` (no native equiv) | manual review |
| `RAW(n)` | `BINARY(n)` | `TO_BINARY(col, 'HEX')` — flag for review |
| `BLOB` | `BINARY` | manual review |
| `LONG`, `LONG RAW` | `VARCHAR(16777216)` / `BINARY` | manual review; LONG is deprecated |
| `ROWID`, `UROWID` | `VARCHAR(18)` | drop — Snowflake has no physical row addressing |
| `XMLTYPE` | `VARIANT` | `PARSE_XML(col)` — custom parser required |
| `JSON` | `VARIANT` | `PARSE_JSON(col)` |
| `SDO_GEOMETRY` | `GEOGRAPHY` / `GEOMETRY` | manual conversion, flag as COMPLEX |

## Critical edge cases

### DATE semantics
Oracle `DATE` is actually `TIMESTAMP(0)` — it always carries a time component.
Always map to `TIMESTAMP_NTZ(0)`, NOT to Snowflake `DATE`. Otherwise any
time-of-day data is silently truncated.

### Empty string vs NULL
Oracle treats `VARCHAR2('')` as `NULL`. Snowflake treats them as distinct.
When migrating, insert:
```sql
CASE WHEN col = '' THEN NULL ELSE col END
```
wherever a nullable string column is loaded.

### NUMBER overflow
Oracle `NUMBER` with no precision has a max of ~38 digits; matches Snowflake
`NUMBER(38,0)`. But Oracle `NUMBER(20,0)` stored values over 18 digits may
lose precision when Informatica types them as Java `long` in transit — always
use `TRY_TO_NUMBER` with explicit precision on load.

### Boolean Y/N flags
Oracle has no native BOOLEAN. Common patterns: `CHAR(1)` with `Y`/`N`,
`NUMBER(1)` with `0`/`1`, `VARCHAR2(5)` with `TRUE`/`FALSE`. Keep these as
`VARCHAR` in Snowflake unless the target column is explicitly `BOOLEAN`; then
use:
```sql
CASE UPPER(col) WHEN 'Y' THEN TRUE WHEN 'N' THEN FALSE END
```

### Sequence generators
Oracle `SEQ.NEXTVAL` → create a Snowflake `SEQUENCE` and reference it as
`<SEQ_NAME>.NEXTVAL`. Snowflake sequences are not gap-free, same as Oracle.

## Cast safety

Always use `TRY_CAST` / `TRY_TO_*` variants during migration so bad data
routes to `MIGRATION_ERROR_LOG` instead of killing the proc:
```sql
COALESCE(TRY_TO_NUMBER(col), 0) AS col   -- with error-log side-effect
```

## Type-compatibility matrix (used by matcher confidence scoring)

`matcher.py` groups types into families: `NUMBER`, `STRING`, `DATE`, `BINARY`.
Same-family pairs get a **+5%** confidence bonus; cross-family pairs get a
**−10%** penalty. Edit `_TYPE_FAMILIES` in `matcher.py` to extend.

## Learned edge cases (append-only)

<!-- autoresearch may append observed type mismatches and production fixes -->
