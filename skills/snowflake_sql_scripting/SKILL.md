---
name: snowflake_sql_scripting
description: Reference patterns for native Snowflake SQL-scripting stored procedures. Load before modifying step3_procgen/generator.py or templates/.
owner: step3_procgen
agent_modifiable: true
improved_by: autoresearch (program_procgen.md)
---

# Snowflake SQL-scripting stored-procedure patterns

Authoritative source: `proc_generater.txt`. Procs MUST be `LANGUAGE SQL` with
`BEGIN…END` blocks, NOT Python/Snowpark.

## Required procedure signature

```sql
CREATE OR REPLACE PROCEDURE PROD_DB.CORTEX_CHAT_APP.SP_<TARGET_TABLE>(
    P_WATERMARK_FROM TIMESTAMP_NTZ DEFAULT NULL,
    P_WATERMARK_TO   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    P_BATCH_ID       VARCHAR       DEFAULT NULL,
    P_BATCH_SIZE     INTEGER       DEFAULT NULL,
    P_DRY_RUN        BOOLEAN       DEFAULT FALSE
)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
    v_status        VARCHAR DEFAULT 'RUNNING';
    v_rows_inserted INTEGER DEFAULT 0;
    v_rows_updated  INTEGER DEFAULT 0;
    v_err_msg       VARCHAR;
    v_failed_sql    VARCHAR;
    v_start_ts      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
BEGIN
    -- ── MAIN TRANSFORMATION ─────────────────────
    BEGIN
        LET stmt VARCHAR := $$<<main cte + write SQL>>$$;
        IF (NOT P_DRY_RUN) THEN
            EXECUTE IMMEDIATE :stmt;
            v_rows_inserted := SQLROWCOUNT;
        END IF;
        v_status := 'SUCCESS';
    EXCEPTION
        WHEN OTHER THEN
            v_status    := 'FAILED';
            v_err_msg   := SQLERRM;
            v_failed_sql := stmt;
            INSERT INTO PROD_DB.CORTEX_CHAT_APP.MIGRATION_ERROR_LOG
                (PROC_NAME, ERROR_CODE, ERROR_MESSAGE, FAILED_SQL, EXEC_TS, BATCH_ID)
                VALUES ('SP_<T>', SQLCODE, :v_err_msg, :v_failed_sql,
                        CURRENT_TIMESTAMP(), :P_BATCH_ID);
    END;

    -- ── AUDIT LOG (always runs) ─────────────────
    INSERT INTO PROD_DB.CORTEX_CHAT_APP.MIGRATION_AUDIT_LOG (...);

    RETURN v_status;
END;
$$;
```

## Non-negotiable rules

1. **`LANGUAGE SQL`** — never `LANGUAGE PYTHON`
2. **`RETURNS VARCHAR`** — never `VARIANT`
3. **Five parameters**, in this order: `P_WATERMARK_FROM`, `P_WATERMARK_TO`, `P_BATCH_ID`, `P_BATCH_SIZE`, `P_DRY_RUN`
4. **Error log insert** must include `FAILED_SQL` column
5. **Fully-qualify every table**: `PROD_DB.CORTEX_CHAT_APP.<tbl>` or `PROD_DB.RAW_LAYER.<tbl>`
6. **Never `SELECT *`** inside CTEs — list columns explicitly
7. **`IF (NOT P_DRY_RUN)`** guard around every DML statement
8. **Column aliases = Informatica target column names verbatim** (unless override in `config/env.yaml`)

## CTE ladder naming

Mirror Informatica component names so the generated SQL is traceable back to
the mapping XML:

```
SQ_<MAPPING>     → Source Qualifier
FIL_<MAPPING>    → Filter
EXPR_<MAPPING>   → Expression
LKP_<MAPPING>    → Lookup Procedure
JNR_<MAPPING>    → Joiner
AGG_<MAPPING>    → Aggregator
RTR_<MAPPING>_<GROUP>  → Router group
SRT_<MAPPING>    → Sorter
```

Each CTE gets an inline comment header:

```sql
SQ_CUST_DIM_LOAD AS (
  -- [INFA: SourceQualifier] SQ_CUSTOMER_SRC
  -- Source: PROD_DB.RAW_LAYER.CUSTOMER_SRC
  -- Filter: LAST_UPD_DT > :P_WATERMARK_FROM
  SELECT CUST_ID, CUST_NAME, ...
  FROM   PROD_DB.RAW_LAYER.CUSTOMER_SRC
  WHERE  LAST_UPD_DT > COALESCE(:P_WATERMARK_FROM, DATE '1900-01-01')
)
```

## Write-strategy dispatch

| Lineage `load_type` | Emit |
|---|---|
| `INSERT` | `INSERT INTO ... SELECT ... FROM <last_cte>` |
| `UPSERT` | `MERGE INTO tgt USING (<last_cte>) src ON (tgt.<pk>=src.<pk>) WHEN MATCHED THEN UPDATE SET ... WHEN NOT MATCHED THEN INSERT ...` |
| `INSERT` + `truncate_before_load=true` | `TRUNCATE TABLE tgt; INSERT INTO tgt SELECT ...` (in same `BEGIN` block for atomicity) |
| `DELETE` | `DELETE FROM tgt WHERE <key> IN (SELECT <key> FROM <last_cte>)` |
| Router group | One `INSERT INTO tgt SELECT ... FROM RTR_<MAPPING>_<GROUP> WHERE <group_cond>` per group; DEFAULT uses `WHERE NOT (g1 OR g2 ...)` |

## Confidence-tier TODO injection

- **HIGH** — emit column normally, no comment
- **MEDIUM** — prepend `-- TODO: VERIFY — MEDIUM confidence mapping` above the column
- **LOW** — emit `NULL AS <col>` placeholder plus `-- TODO: MANUAL REVIEW REQUIRED — <match_basis>`
- **UNMATCHED** — skip entirely and add `-- MISSING: <oracle_col> has no mapped target`

## Informatica → Snowflake expression rewrites

| Informatica | Snowflake |
|---|---|
| `IIF(cond, t, f)` | `CASE WHEN cond THEN t ELSE f END` |
| `DECODE(col, v1, r1, ..., default)` | `CASE col WHEN v1 THEN r1 ... ELSE default END` |
| `NVL(a, b)` | `COALESCE(a, b)` |
| `NVL2(a, b, c)` | `IFF(a IS NOT NULL, b, c)` |
| `SYSDATE` | `CURRENT_TIMESTAMP()` |
| `SUBSTR(s, p, l)` | `SUBSTRING(s, p, l)` |
| `TO_CHAR(d, fmt)` | `TO_VARCHAR(d, fmt)` |
| `TRUNC(d)` | `DATE_TRUNC('DAY', d)` |
| `ADD_TO_DATE(d, 'DD', n)` | `DATEADD(day, n, d)` |
| `DATE_DIFF(d1, d2, 'DD')` | `DATEDIFF(day, d2, d1)` |
| `:LKP.proc(key)` | `(SELECT col FROM tbl WHERE k = val LIMIT 1)` or LEFT JOIN |

## Learned patterns (append-only)

<!-- autoresearch may append observed rewrite patterns and edge cases -->
