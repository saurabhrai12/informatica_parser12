# Oracle → Snowflake Migration Agent — CLAUDE.md

> **Purpose:** This file is the authoritative specification for an AI coding agent (Claude Code or
> equivalent) executing the full Oracle DWH → Snowflake ELT migration pipeline. The agent reads
> this file on every session start and follows it as an immutable operating protocol.
>
> **Autoresearch strategy decision:** This project uses the **Skills + autoresearch hybrid** pattern
> described at the bottom of this file. Read that section before starting any work.

---

## Project overview

| Attribute | Value |
|---|---|
| Source platform | Oracle Data Warehouse (ETL via Informatica PowerCenter) |
| Target platform | Snowflake (ELT via native SQL stored procedures) |
| Snowflake account | `HUBBXYZ-XA96647` |
| Target database | `PROD_DB` |
| Target schema | `CORTEX_CHAT_APP` |
| Source/staging schema | `RAW_LAYER` |
| Proc name prefix | `SP_` |
| Audit log table | `PROD_DB.CORTEX_CHAT_APP.MIGRATION_AUDIT_LOG` |
| Error log table | `PROD_DB.CORTEX_CHAT_APP.MIGRATION_ERROR_LOG` |
| Procedure language | Snowflake SQL scripting (`LANGUAGE SQL`, `BEGIN…END`) |
| Procedure return type | `VARCHAR` (status message) |
| Transaction scope | COMMIT per procedure |
| Python (tooling only) | 3.11 — used by extractor/matcher/generator scripts, NOT inside procs |

> **Authoritative source spec note (2026-04-06 review):** `proc_generater.txt` mandates
> native Snowflake SQL scripting (not Snowpark Python) — Step 3 procs use `LANGUAGE SQL`,
> `RETURNS VARCHAR`, `BEGIN…END`, with `LET`, `EXECUTE IMMEDIATE`, and SQL `EXCEPTION`
> handlers. The Python/Snowpark template later in this file is RETAINED only as a
> historical reference; the generator MUST emit SQL-scripting procs. Required proc
> parameters per source spec: `P_WATERMARK_FROM`, `P_WATERMARK_TO`, `P_BATCH_ID`,
> `P_BATCH_SIZE`, `P_DRY_RUN`. The error log table requires a `FAILED_SQL` column.
> Step 2 spec (`mapping_identification.txt`) is now populated. The matcher MUST
> additionally emit, after the mapping JSON array, two summary sections:
> `UNMATCHED ORACLE COLUMNS` and `UNMATCHED SNOWFLAKE COLUMNS`. Confidence
> thresholds in source spec (HIGH ≥0.90, MEDIUM 0.65–0.89, LOW 0.40–0.64,
> UNMATCHED <0.40) match this file. The 14 matching strategies (exact →
> normalised → abbreviation → casing → fuzzy → semantic → domain dict → data
> overlap → enum → comment → type → length → PK/FK → nullability) and the
> priority/cap rules (semantic capped 80%, data-overlap-only capped 70%, type
> compat ±5/−10 modifier) are authoritative and must be implemented in
> `step2_mapping/matcher.py`. Field naming in the matcher output may use either
> the CLAUDE.md keys or the source-spec keys provided the eval golden files
> agree — the eval contract wins.

---

## Repository layout

```
ora2sf_migration/
├── CLAUDE.md                      ← this file (agent protocol + research program)
├── README.md                      ← human-facing setup guide
├── pyproject.toml                 ← dependencies (uv-managed)
├── results.tsv                    ← autoresearch run log (untracked by git)
│
├── config/
│   └── env.yaml                   ← connection strings, schema refs, toggles
│
├── step1_lineage/                 ← Informatica XML → lineage JSON
│   ├── extractor.py               ← AGENT-MODIFIABLE
│   ├── function_map.py            ← Informatica → Snowflake function dictionary
│   ├── tests/
│   │   ├── test_extractor.py
│   │   ├── fixtures/              ← sample Informatica XML snippets
│   │   └── expected/              ← golden JSON outputs
│   └── eval.py                    ← scalar metric: lineage_coverage_score (0–1)
│
├── step2_mapping/                 ← Oracle ↔ Snowflake column matching sheet
│   ├── matcher.py                 ← AGENT-MODIFIABLE
│   ├── synonym_dict.py            ← domain-specific abbreviation expansions
│   ├── tests/
│   │   ├── test_matcher.py
│   │   ├── fixtures/              ← oracle_cols.json, snowflake_cols.json
│   │   └── expected/              ← golden mapping_sheet.json
│   └── eval.py                    ← scalar metric: mapping_confidence_score (0–1)
│
├── step3_procgen/                 ← Snowflake stored procedure code generator
│   ├── generator.py               ← AGENT-MODIFIABLE
│   ├── templates/                 ← Jinja2 SQL/Python proc templates
│   ├── tests/
│   │   ├── test_generator.py
│   │   ├── fixtures/              ← lineage.json + mapping_sheet.json inputs
│   │   └── expected/              ← golden .sql proc files
│   └── eval.py                    ← scalar metric: proc_correctness_score (0–1)
│
├── step4_testing/                 ← Migration validation harness
│   ├── validator.py               ← row count, hash, sample checks
│   ├── reconciler.py              ← Oracle vs Snowflake data reconciliation
│   └── tests/
│       └── test_validator.py
│
├── pipeline.py                    ← Orchestrates steps 1–4 end-to-end
├── scripts/
│   ├── run_eval.sh                ← single-shot eval runner (used by autoresearch loop)
│   └── bootstrap_db.sql           ← audit + error table DDL
│
└── autoresearch/
    ├── program_lineage.md         ← research agenda: improve step1 extractor
    ├── program_mapping.md         ← research agenda: improve step2 matcher
    └── program_procgen.md         ← research agenda: improve step3 generator
```

---

## Immutable files (DO NOT MODIFY)

The agent must never modify these files. They define the evaluation contract.

| File | Reason frozen |
|---|---|
| `step1_lineage/eval.py` | Defines `lineage_coverage_score` — the metric autoresearch optimises |
| `step2_mapping/eval.py` | Defines `mapping_confidence_score` |
| `step3_procgen/eval.py` | Defines `proc_correctness_score` |
| `step*/tests/fixtures/` | Ground-truth inputs — changing them invalidates comparisons |
| `step*/tests/expected/` | Golden outputs — changing them invalidates the ratchet |
| `config/env.yaml` | Connection config — edit manually only |
| `CLAUDE.md` | This file |

---

## Agent-modifiable files

| File | What to improve |
|---|---|
| `step1_lineage/extractor.py` | Lineage extraction accuracy, coverage, XML parsing robustness |
| `step1_lineage/function_map.py` | Informatica → Snowflake function translation completeness |
| `step2_mapping/matcher.py` | Semantic matching precision/recall, confidence scoring |
| `step2_mapping/synonym_dict.py` | Abbreviation dictionary completeness |
| `step3_procgen/generator.py` | Proc correctness, CTE pattern quality, expression translation |
| `step3_procgen/templates/` | SQL/Snowpark template fidelity and edge-case handling |

---

## Step 1 — Informatica lineage extraction

### What it does
Parses Informatica PowerCenter mapping XML exports and produces a structured JSON array
where each element is one source-column → target-column field mapping with the full
transformation chain, expressions, lookup details, and migration complexity.

### Input
`step1_lineage/tests/fixtures/*.xml` — Informatica mapping XML exports.

### Output contract (each JSON element must contain all of these keys)
```jsonc
{
  "mapping_name": "string",
  "source_table": "string",
  "source_schema": "string",
  "source_column": "string",
  "source_datatype": "string",
  "source_length": "integer|null",
  "source_nullable": "boolean",
  "source_pk_flag": "boolean",
  "source_filter": "string|null",
  "transformation_sequence": ["string"],   // ordered list of transformation names
  "final_expression": "string|null",       // verbatim Informatica expression text
  "pass_through": "boolean",
  "default_value": "string|null",
  "null_handling": "string|null",
  "type_cast": "string|null",
  "function_mappings": [                   // one entry per Informatica function used
    { "infa_fn": "string", "sf_fn": "string", "notes": "string|null" }
  ],
  "lookup_table": "string|null",
  "lookup_condition": "string|null",
  "aggregation_logic": "string|null",
  "join_condition": "string|null",
  "router_condition": "string|null",
  "sorter_logic": "string|null",
  "sq_override_sql": "string|null",
  "target_table": "string",               // Informatica target table name — preserved verbatim
  "target_schema": "string",
  "target_column": "string",             // Informatica target column name — preserved verbatim
  "target_datatype": "string",
  "load_type": "INSERT|UPDATE|UPSERT|DELETE",
  "update_override_sql": "string|null",
  "target_pk_flag": "boolean",
  "truncate_before_load": "boolean",
  "reject_handling": "string|null",
  "lineage_confidence": "HIGH|MEDIUM|LOW",
  "ambiguity_notes": "string|null",
  "migration_complexity": "SIMPLE|MODERATE|COMPLEX"
}
```

### Evaluation metric — `lineage_coverage_score`
```
score = (fields_correctly_populated / total_expected_fields_across_all_rows)
        weighted by field_importance (see eval.py)
```
Target: ≥ 0.92. Autoresearch ratchet keeps improvements, reverts regressions.

### Key Informatica → Snowflake function translation rules
Stored in `function_map.py`. The agent may extend this dictionary. Never remove entries.

| Informatica | Snowflake equivalent |
|---|---|
| `IIF(c, t, f)` | `CASE WHEN c THEN t ELSE f END` |
| `DECODE(col, v1,r1, ...)` | `CASE col WHEN v1 THEN r1 ... END` |
| `NVL(a, b)` | `COALESCE(a, b)` |
| `NVL2(a, b, c)` | `IFF(a IS NOT NULL, b, c)` |
| `SUBSTR(s, p, l)` | `SUBSTRING(s, p, l)` |
| `INSTR(s, sub)` | `POSITION(sub IN s)` |
| `TO_DATE(s, fmt)` | `TO_DATE(s, fmt)` |
| `TO_CHAR(d, fmt)` | `TO_VARCHAR(d, fmt)` |
| `SYSDATE` | `CURRENT_TIMESTAMP()` |
| `TRUNC(date)` | `DATE_TRUNC('DAY', date)` |
| `ADD_TO_DATE(d, 'DD', n)` | `DATEADD(day, n, d)` |
| `DATE_DIFF(d1, d2, 'DD')` | `DATEDIFF(day, d2, d1)` |
| `LTRIM / RTRIM` | `LTRIM / RTRIM` |
| `LENGTH` | `LENGTH` |
| `UPPER / LOWER` | `UPPER / LOWER` |
| `:LKP.proc(key)` | `(SELECT col FROM tbl WHERE k = val LIMIT 1)` |
| `NEXTVAL` (seq gen) | `<SEQ_NAME>.NEXTVAL` |

---

## Step 2 — Oracle ↔ Snowflake column mapping

### What it does
Produces a column-level mapping sheet pairing Oracle columns to their Snowflake equivalents
using name normalisation, semantic synonym inference, data type compatibility, and (when
sample data is available) value-overlap matching.

### Input
- `step2_mapping/tests/fixtures/oracle_cols.json` — output of Oracle `ALL_TAB_COLUMNS` query
- `step2_mapping/tests/fixtures/snowflake_cols.json` — output of Snowflake `INFORMATION_SCHEMA.COLUMNS`

### Output contract (each mapping row)
```jsonc
{
  "oracle_table": "string",
  "oracle_schema": "string",
  "oracle_column": "string",
  "oracle_datatype": "string",
  "oracle_length": "integer|null",
  "oracle_precision": "integer|null",
  "oracle_scale": "integer|null",
  "oracle_nullable": "boolean",
  "oracle_pk_flag": "boolean",
  "oracle_comment": "string|null",
  "snowflake_table": "string",
  "snowflake_schema": "string",
  "snowflake_column": "string",
  "snowflake_datatype": "string",
  "snowflake_length": "integer|null",
  "snowflake_nullable": "boolean",
  "snowflake_pk_flag": "boolean",
  "match_type": "EXACT|NORMALISED|ABBREVIATION|SEMANTIC|DATA_OVERLAP|INFERRED",
  "confidence_score": "float 0-1",
  "confidence_tier": "HIGH|MEDIUM|LOW|UNMATCHED",
  "match_basis": "string",              // human-readable explanation
  "type_compatible": "boolean",
  "suggested_cast": "string|null",      // e.g. "TRY_TO_TIMESTAMP_NTZ(col)"
  "transform_hint": "string|null",      // ELT rewrite note
  "unmatched_reason": "string|null",
  "recommended_action": "MAP|NEW_COLUMN|DEPRECATED|INVESTIGATE"
}
```

### Confidence thresholds
| Tier | Score range | Pipeline treatment |
|---|---|---|
| HIGH | ≥ 0.90 | Auto-include in proc generation |
| MEDIUM | 0.65–0.89 | Include with `-- TODO: VERIFY` comment |
| LOW | 0.40–0.64 | Placeholder `NULL AS col` + `-- MANUAL REVIEW` |
| UNMATCHED | < 0.40 | Separate ORACLE_ONLY / SNOWFLAKE_ONLY lists |

### Evaluation metric — `mapping_confidence_score`
```
score = Σ(confidence_score * is_correct_match) / total_pairs
```
Target: ≥ 0.88. Tested against golden mapping in `tests/expected/mapping_sheet.json`.

### Abbreviation dictionary (extend in `synonym_dict.py`, never remove)
```python
ABBREV = {
    "AMT": "AMOUNT", "QTY": "QUANTITY", "DT": "DATE", "CD": "CODE",
    "DESC": "DESCRIPTION", "NBR": "NUMBER", "NO": "NUMBER", "TYP": "TYPE",
    "IND": "INDICATOR", "ADDR": "ADDRESS", "CUST": "CUSTOMER",
    "ACCT": "ACCOUNT", "TXN": "TRANSACTION", "BAL": "BALANCE",
    "EFF": "EFFECTIVE", "EXP": "EXPIRY", "SRC": "SOURCE", "TGT": "TARGET",
    "STR": "START", "CRT": "CREATED", "UPD": "UPDATED", "DEL": "DELETED",
    "FLG": "FLAG", "SEQ": "SEQUENCE", "REF": "REFERENCE", "CAT": "CATEGORY",
    "ID": "IDENTIFIER", "KEY": "KEY", "PK": "PRIMARY_KEY", "FK": "FOREIGN_KEY",
    "DIM": "DIMENSION", "FCT": "FACT", "STG": "STAGING", "AGG": "AGGREGATE",
    # AML / financial crime domain
    "TXN": "TRANSACTION", "CUST": "CUSTOMER", "ACCT": "ACCOUNT",
    "ALERT": "ALERT", "RISK": "RISK_SCORE", "SAR": "SAR_FLAG",
    "STRCT": "STRUCTURING", "FRAUD": "FRAUD_INDICATOR",
}

SYNONYMS = [
    {"CREATED_DATE", "CREATION_DATE", "CREATE_DT", "INSERT_DATE", "LOAD_DATE", "INS_DT"},
    {"MODIFIED_DATE", "UPDATE_DATE", "LAST_UPDATED", "LAST_MODIFIED_DT", "UPD_DT"},
    {"STATUS", "STATE", "STATUS_CD", "RECORD_STATUS", "STAT"},
    {"EFFECTIVE_DATE", "EFF_DT", "START_DATE", "VALID_FROM", "EFF_FROM"},
    {"EXPIRY_DATE", "EXP_DT", "END_DATE", "VALID_TO", "EFF_TO"},
    {"CUSTOMER_ID", "CUST_ID", "CLIENT_ID", "PARTY_ID", "CUST_KEY"},
    {"ACCOUNT_ID", "ACCT_ID", "ACCT_NO", "ACCOUNT_NUMBER", "ACCT_KEY"},
    {"TRANSACTION_ID", "TXN_ID", "TRANS_ID", "TXN_NO"},
    {"AMOUNT", "AMT", "TXN_AMT", "TRANSACTION_AMOUNT", "VALUE"},
    {"DELETED_FLAG", "DEL_FLG", "IS_DELETED", "ACTIVE_FLAG", "IS_ACTIVE"},
]
```

---

## Step 3 — Snowflake stored procedure generation

### What it does
Consumes the lineage JSON (step 1) and mapping sheet (step 2) to generate production-ready
Snowflake stored procedures that replicate every Informatica mapping's transformation logic
in ELT style.

### Critical naming rule
**Target table names and column names default to the Informatica mapping target names verbatim.**
This is the highest-priority rule and overrides all other naming conventions.

Override exceptions are defined in `config/env.yaml` under `column_renames:`. Only columns
listed there are renamed. All others retain the Informatica name.

### Procedure structure template
Each generated proc follows this skeleton:

```sql
CREATE OR REPLACE PROCEDURE PROD_DB.CORTEX_CHAT_APP.SP_<TARGET_TABLE>(
    P_WATERMARK_FROM  TIMESTAMP_NTZ DEFAULT NULL,
    P_WATERMARK_TO    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    P_BATCH_ID        VARCHAR       DEFAULT NULL,
    P_DRY_RUN         BOOLEAN       DEFAULT FALSE
)
RETURNS VARIANT        -- JSON: {status, rows_inserted, rows_updated, rows_deleted, error}
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
AS $$
import json
from datetime import datetime
from snowflake.snowpark.exceptions import SnowparkSQLException

def run(session,
        p_watermark_from, p_watermark_to,
        p_batch_id, p_dry_run):

    proc_name  = 'SP_<TARGET_TABLE>'
    mapping_ref = '<INFORMATICA_MAPPING_NAME>'
    start_ts   = datetime.utcnow()
    result     = {"status": "RUNNING", "rows_inserted": 0,
                  "rows_updated": 0, "rows_deleted": 0, "error": None}

    try:
        # ── PRE-HOOK ────────────────────────────────────────────────────
        # (optional pre-SQL: session parameters, truncate if full-load)

        # ── CTE LADDER ──────────────────────────────────────────────────
        # [INFA: SourceQualifier] <SQ_MAPPING_NAME>
        # Source: ORACLE_SCHEMA.<source_table>
        cte_sql = """
        WITH
        SQ_<MAPPING> AS (
            -- Source filter from Informatica SQ component
            SELECT <source_columns_mapped_per_lineage>
            FROM   PROD_DB.RAW_LAYER.<source_table>
            WHERE  <source_filter>
              AND  (<incremental_filter_if_applicable>)
        ),
        EXPR_<MAPPING> AS (
            -- [INFA: ExpressionTransformation] <EXPR_COMPONENT_NAME>
            -- Applies all expression port rewrites from lineage
            SELECT
                -- Source: ORA.<col>  Target: <INFA_TARGET_COL>
                -- Expression: <verbatim Informatica expression>
                -- Snowflake rewrite: <translated expression>
                <translated_select_list>
            FROM SQ_<MAPPING>
        ),
        LKP_<MAPPING> AS (
            -- [INFA: Lookup] <LKP_COMPONENT_NAME>
            SELECT e.*,
                   lkp.<return_col>  -- Lookup: <lkp_table> ON <condition>
            FROM   EXPR_<MAPPING> e
            LEFT   JOIN PROD_DB.CORTEX_CHAT_APP.<lkp_table> lkp
                   ON lkp.<lkp_key> = e.<input_port>
        )
        """

        # ── WRITE STRATEGY ──────────────────────────────────────────────
        # UPSERT (DD_INSERT + DD_UPDATE)
        merge_sql = """
        MERGE INTO PROD_DB.CORTEX_CHAT_APP.<TARGET_TABLE> tgt
        USING (<final_cte_name>) src
           ON (tgt.<pk_col> = src.<pk_col>)
        WHEN MATCHED THEN UPDATE SET
            <col> = src.<col>, ...
        WHEN NOT MATCHED THEN INSERT
            (<col_list>) VALUES (<val_list>)
        """

        if not p_dry_run:
            full_sql = cte_sql + merge_sql
            affected = session.sql(full_sql).collect()
            result["rows_inserted"] = affected[0]["number of rows inserted"]
            result["rows_updated"]  = affected[0]["number of rows updated"]

        # ── ROW COUNT VALIDATION ────────────────────────────────────────
        src_cnt = session.sql(
            "SELECT COUNT(*) AS n FROM PROD_DB.RAW_LAYER.<source_table>"
        ).collect()[0]["N"]
        tgt_cnt = session.sql(
            "SELECT COUNT(*) AS n FROM PROD_DB.CORTEX_CHAT_APP.<TARGET_TABLE>"
        ).collect()[0]["N"]
        if tgt_cnt == 0 and src_cnt > 0:
            raise ValueError(f"Row count mismatch: src={src_cnt} tgt={tgt_cnt}")

        result["status"] = "SUCCESS"

    except Exception as e:
        result["status"] = "FAILED"
        result["error"]  = str(e)
        session.sql(f"""
            INSERT INTO PROD_DB.CORTEX_CHAT_APP.MIGRATION_ERROR_LOG
            (PROC_NAME, ERROR_CODE, ERROR_MESSAGE, EXEC_TS, BATCH_ID)
            VALUES ('{proc_name}', 'RUNTIME_ERROR',
                    $${str(e).replace("'","''")}$$,
                    CURRENT_TIMESTAMP(), '{p_batch_id}')
        """).collect()

    finally:
        # ── AUDIT LOG ──────────────────────────────────────────────────
        end_ts = datetime.utcnow()
        session.sql(f"""
            INSERT INTO PROD_DB.CORTEX_CHAT_APP.MIGRATION_AUDIT_LOG
            (MAPPING_NAME, PROCEDURE_NAME, EXEC_START_TS, EXEC_END_TS,
             STATUS, ROWS_INSERTED, ROWS_UPDATED, ROWS_DELETED,
             INFORMATICA_MAPPING_REF, ERROR_MESSAGE, BATCH_ID)
            VALUES ('{proc_name}', '{proc_name}',
                    '{start_ts}', '{end_ts}',
                    '{result["status"]}',
                    {result["rows_inserted"]}, {result["rows_updated"]},
                    {result["rows_deleted"]},
                    '{mapping_ref}',
                    $${result.get("error") or ""}$$,
                    '{p_batch_id}')
        """).collect()

    return result
$$;
```

### Evaluation metric — `proc_correctness_score`
```
score = (
    sql_parse_valid      * 0.30 +   # proc compiles without syntax errors
    column_name_match    * 0.25 +   # target column names match Informatica target names
    expression_accuracy  * 0.25 +   # Informatica expressions correctly translated
    cte_coverage         * 0.10 +   # all transformation stages have a CTE
    comment_coverage     * 0.10     # all COMPLEX mappings have REQUIRES_HUMAN_REVIEW flag
)
```
Target: ≥ 0.90.

### Data type conversion rules
| Oracle type | Snowflake type | Notes |
|---|---|---|
| `NUMBER(p,0)` | `NUMBER(38,0)` | Use `BIGINT` for surrogate keys |
| `NUMBER(p,s)` | `NUMBER(p,s)` | Direct |
| `VARCHAR2(n)` | `VARCHAR(n)` | Direct |
| `CHAR(n)` | `CHAR(n)` | |
| `DATE` | `TIMESTAMP_NTZ(0)` | Oracle DATE includes time |
| `TIMESTAMP` | `TIMESTAMP_NTZ(9)` | |
| `CLOB` | `VARCHAR(16777216)` | |
| `RAW` / `BLOB` | `BINARY` | Flag for manual review |
| `XMLTYPE` | `VARIANT` | Requires custom parser |

---

## Step 4 — Migration validation

### Test categories

#### Unit tests (fast, no DB connection required)
Run against fixture data only. Required to pass before any commit.

```
pytest step1_lineage/tests/ -v
pytest step2_mapping/tests/ -v
pytest step3_procgen/tests/ -v
pytest step4_testing/tests/ -v
```

All tests must pass with `pytest -x --tb=short`.

#### Integration tests (require live Snowflake + Oracle credentials in env.yaml)
```
pytest -m integration --co    # list without running
pytest -m integration         # run (needs DB access)
```

#### Data reconciliation tests
Run after deploying procs to a test Snowflake environment:

```python
# validator.py — checks performed for every migrated table
checks = [
    "row_count_match",          # abs(sf_count - ora_count) / ora_count < 0.001
    "pk_uniqueness",            # no duplicate PKs in SF target
    "null_rate_within_5pct",    # null% per column within 5% of Oracle null%
    "numeric_sum_match",        # SUM(amount_cols) within 0.01% of Oracle
    "date_range_match",         # MIN/MAX dates match Oracle ± 1 day
    "sample_row_hash_match",    # MD5 of 1000 random rows matches (after type cast)
    "enum_value_coverage",      # all distinct codes in Oracle exist in SF
    "audit_log_populated",      # MIGRATION_AUDIT_LOG has SUCCESS row for this proc
    "no_error_log_entries",     # MIGRATION_ERROR_LOG has 0 rows for this proc
]
```

---

## Pipeline orchestration

`pipeline.py` runs all steps in sequence for a given Informatica mapping name:

```python
# Usage
python pipeline.py --mapping CUST_DIM_LOAD --dry-run
python pipeline.py --mapping CUST_DIM_LOAD --deploy
python pipeline.py --all --dry-run
```

Steps:
1. Parse `step1_lineage/extractor.py` → `outputs/<mapping>_lineage.json`
2. Run `step2_mapping/matcher.py` → `outputs/<mapping>_mapping_sheet.json`
3. Run `step3_procgen/generator.py` → `outputs/<mapping>_proc.sql`
4. Run `step4_testing/validator.py` → `outputs/<mapping>_validation_report.json`
5. On `--deploy`: execute proc SQL in Snowflake test schema, run integration tests

---

## Autoresearch strategy — why Skills + autoresearch hybrid

### What karpathy/autoresearch actually does
The autoresearch pattern gives an AI agent a real implementation and lets it experiment
autonomously: it modifies the code, runs for a fixed time budget, checks if the result
improved, keeps or discards, and repeats. The key insight is:
The human iterates on the prompt (.md); the AI agent iterates on the code (.py).

### Why NOT pure autoresearch for this project

autoresearch was designed for ML training loops where there is one scalar metric (val_bpb)
and experiments complete in 5 minutes. Our migration pipeline has **three distinct modules**
(lineage extraction, column mapping, proc generation) each with different failure modes,
and **no GPU required** — the bottleneck is SQL correctness and semantic accuracy, not
compute throughput.

Direct use of karpathy/autoresearch is **not appropriate** because:
1. It requires a single NVIDIA GPU — we have none needed here.
2. Its ratchet loop is tuned for LLM training metrics, not SQL AST correctness.
3. Writing a good program.md requires having done the research yourself — you need to know which directions are worth trying, what "better" means for your problem. We have done that work; it is encoded in this file.

### What we USE instead — the autoresearch *pattern* applied to data migration

We adopt the **three-file contract** that makes autoresearch work:

| autoresearch original | This project |
|---|---|
| `prepare.py` (immutable evaluator) | `step*/eval.py` (frozen metric functions) |
| `train.py` (agent-modifiable) | `extractor.py`, `matcher.py`, `generator.py` |
| `program.md` (human research agenda) | `autoresearch/program_*.md` (per-step agendas) |
| `val_bpb` (scalar metric) | `lineage_coverage_score`, `mapping_confidence_score`, `proc_correctness_score` |
| 5-minute training run | `pytest + eval.py` run in ~30 seconds |

The pattern works because it removes the bottleneck: you know the code could be better,
but you will never run 50 iterations manually.

### Skills — what they ARE used for

Project-level **Skills** (`SKILL.md` files under `skills/`) encode domain knowledge
that the agent loads before starting work on a specific component. They are the
right mechanism for:

- **Static knowledge** that doesn't change between runs (Informatica XML schema,
  Snowflake SQL-scripting patterns, Oracle data type quirks).
- **Operational procedures** — how to run tests, how to deploy, how to interpret
  eval output.
- **Not** for iterative optimisation — that is the autoresearch loop's job.

The four skills in this project are:

| Skill | Loaded before editing |
|---|---|
| `skills/informatica_xml/SKILL.md` | `step1_lineage/extractor.py`, `function_map.py` |
| `skills/column_matching/SKILL.md` | `step2_mapping/matcher.py`, `synonym_dict.py` |
| `skills/oracle_to_snowflake_types/SKILL.md` | both `step2_mapping` and `step3_procgen` |
| `skills/snowflake_sql_scripting/SKILL.md` | `step3_procgen/generator.py`, `templates/` |

Each SKILL.md has a frozen canonical section plus an **append-only "Learned
patterns"** section at the bottom. Autoresearch may append new patterns via
`skills.loader.append_learned_pattern(...)` but must NEVER rewrite canonical
sections. The `autoresearch/program_skills.md` agenda governs this loop — it
runs all three evals and only keeps changes that do not regress any step.

### The three autoresearch program files

Each `autoresearch/program_*.md` defines the research agenda for one module. The agent
runs this loop for each:

```
1. Read program_<step>.md  →  propose one improvement to the modifiable .py file
2. Apply change to the file  →  git commit with descriptive message
3. Run:  python step<N>_*/eval.py  →  read scalar score from stdout (single float)
4. If score improved  →  keep commit  (git commit already done)
   If score same/worse  →  git reset HEAD~1  (revert the change)
5. Append result to results.tsv  (do NOT commit results.tsv)
6. Loop back to step 1 (stop after MAX_EXPERIMENTS or when score plateaus)
```

#### `autoresearch/program_lineage.md` — lineage extraction agenda
```
Goal: maximise lineage_coverage_score (target ≥ 0.92).
Metric file: step1_lineage/eval.py  →  outputs a single float to stdout.
Modifiable: step1_lineage/extractor.py, step1_lineage/function_map.py

Promising directions to try:
  - Improve XPath traversal for deeply nested transformation chains
  - Better detection of unconnected lookups vs connected lookups
  - Handle Router multi-group extraction (each group as separate row)
  - Improve aggregation port separation (group-by vs aggregate expressions)
  - Extend function_map.py with date arithmetic patterns
  - Handle SQ override SQL that spans multiple lines / has subqueries
  - Detect and flag NORMALIZER patterns (mark as COMPLEX)
  - Improve confidence scoring for ambiguous port-to-port wiring

Do NOT change: XML fixture files, eval.py, expected/ golden outputs.
Stop condition: score ≥ 0.92 OR 5 consecutive runs with no improvement.
```

#### `autoresearch/program_mapping.md` — column mapping agenda
```
Goal: maximise mapping_confidence_score (target ≥ 0.88).
Metric file: step2_mapping/eval.py  →  outputs a single float to stdout.
Modifiable: step2_mapping/matcher.py, step2_mapping/synonym_dict.py

Promising directions to try:
  - Tune confidence weight formula (currently equal-weight strategies)
  - Add Levenshtein distance normalised by column name length
  - Improve table-level matching before column-level (anchor to table first)
  - Add domain-specific synonym pairs for financial crime (AML, fraud, risk)
  - Improve enum/code set matching using sample data value overlap
  - Handle prefixed column names (e.g. C_CUST_ID → CUSTOMER_ID)
  - Penalise cross-table matches more aggressively
  - Improve UNMATCHED classification to reduce false negatives

Do NOT change: fixture JSON files, eval.py, expected/ golden outputs.
Stop condition: score ≥ 0.88 OR 5 consecutive runs with no improvement.
```

#### `autoresearch/program_procgen.md` — proc generation agenda
```
Goal: maximise proc_correctness_score (target ≥ 0.90).
Metric file: step3_procgen/eval.py  →  outputs a single float to stdout.
Modifiable: step3_procgen/generator.py, step3_procgen/templates/

Promising directions to try:
  - Improve CTE naming to exactly mirror Informatica component names
  - Better handling of multi-target mappings (one proc per target table)
  - Improve MERGE key inference from lineage PK flags
  - Handle DD_INSERT-only vs UPSERT vs Truncate+Reload correctly per mapping
  - Improve expression translation completeness for nested IIF chains
  - Ensure fully-qualified names (DB.SCHEMA.TABLE) on every table reference
  - Add DRY_RUN guard around all DML statements
  - Improve audit log INSERT to capture all required fields
  - Better TODO comment injection for MEDIUM/LOW confidence columns
  - Handle Router groups as separate INSERT statements with correct WHERE

Do NOT change: fixture JSON files, eval.py, expected/ golden outputs.
Stop condition: score ≥ 0.90 OR 5 consecutive runs with no improvement.
```

---

## Running autoresearch loops

```bash
# Run lineage improvement loop (30-second budget per experiment)
uv run python autoresearch/run_loop.py --step lineage --max-experiments 50

# Run mapping improvement loop
uv run python autoresearch/run_loop.py --step mapping --max-experiments 50

# Run proc generation improvement loop
uv run python autoresearch/run_loop.py --step procgen --max-experiments 50

# View current scores
cat results.tsv
```

`autoresearch/run_loop.py` implements the propose→commit→eval→keep/revert cycle described
above, using this CLAUDE.md as the research agenda context.

---

## Testing framework reference

### Running all tests
```bash
# Fast unit tests (no DB, < 10 seconds)
uv run pytest -x --tb=short -q

# With coverage
uv run pytest --cov=. --cov-report=term-missing

# Integration tests (needs .env with Snowflake + Oracle credentials)
uv run pytest -m integration -v

# Single step
uv run pytest step1_lineage/tests/ -v
```

### Test structure per step

Each step follows the same pattern:

```python
# test_extractor.py (example)
import pytest, json
from pathlib import Path
from step1_lineage.extractor import extract_lineage

FIXTURES = Path("step1_lineage/tests/fixtures")
EXPECTED = Path("step1_lineage/tests/expected")

@pytest.mark.parametrize("xml_file", FIXTURES.glob("*.xml"))
def test_output_schema(xml_file):
    """Every output row must contain all required keys."""
    result = extract_lineage(xml_file.read_text())
    required_keys = {
        "mapping_name", "source_table", "source_column", "final_expression",
        "target_table", "target_column", "load_type", "migration_complexity",
    }
    for row in result:
        assert required_keys.issubset(row.keys()), f"Missing keys in {row}"

@pytest.mark.parametrize("xml_file", FIXTURES.glob("*.xml"))
def test_no_fabricated_column_names(xml_file):
    """Target column names must match Informatica target verbatim."""
    result = extract_lineage(xml_file.read_text())
    stem = xml_file.stem
    golden = json.loads((EXPECTED / f"{stem}.json").read_text())
    golden_targets = {(r["target_table"], r["target_column"]) for r in golden}
    result_targets = {(r["target_table"], r["target_column"]) for r in result}
    assert result_targets == golden_targets

@pytest.mark.parametrize("xml_file", FIXTURES.glob("*.xml"))
def test_expressions_not_simplified(xml_file):
    """Expressions must not be paraphrased — must match verbatim from XML."""
    result = extract_lineage(xml_file.read_text())
    for row in result:
        if row.get("final_expression"):
            assert len(row["final_expression"]) > 0

def test_router_groups_produce_separate_rows():
    """Router with N groups must produce N rows, one per group condition."""
    xml = (FIXTURES / "router_mapping.xml").read_text()
    result = extract_lineage(xml)
    router_rows = [r for r in result if r.get("router_condition")]
    assert len(router_rows) >= 2, "Router should produce at least 2 group rows"

def test_unconnected_lookup_flagged():
    xml = (FIXTURES / "lookup_mapping.xml").read_text()
    result = extract_lineage(xml)
    lkp_rows = [r for r in result if r.get("lookup_table")]
    assert all(r["lookup_condition"] for r in lkp_rows), \
        "Every lookup row must have a condition"

@pytest.mark.integration
def test_live_snowflake_schema_match():
    """Integration: columns in generated proc match live Snowflake schema."""
    import snowflake.connector
    # ... (requires env credentials)
```

### Test data requirements

The agent must maintain fixture files that cover:

| Fixture | Informatica pattern it exercises |
|---|---|
| `simple_passthrough.xml` | All pass-through fields (baseline) |
| `expression_mapping.xml` | IIF, DECODE, NVL, TO_DATE expressions |
| `lookup_mapping.xml` | Connected + unconnected lookup |
| `router_mapping.xml` | Router with 3+ groups including DEFAULT |
| `aggregator_mapping.xml` | Aggregator with GROUP BY and multiple aggs |
| `joiner_mapping.xml` | Joiner with master/detail |
| `upsert_mapping.xml` | DD_INSERT + DD_UPDATE update strategy |
| `truncate_reload.xml` | Truncate flag + reload |
| `sq_override.xml` | Source qualifier with SQL override |
| `complex_chain.xml` | SQ → EXPR → LKP → AGG → ROUTER → target |

---

## Commit discipline

Every commit message by the agent must follow this format:
```
[step<N>] <verb>: <what changed> (score: <before> → <after>)

Example:
[step1] improve: handle Router DEFAULT group extraction (score: 0.847 → 0.863)
[step2] fix: penalise cross-table column matches (score: 0.821 → 0.841)
[step3] add: fully-qualified names on all CTE table refs (score: 0.876 → 0.891)
```

If a change does not improve the score, it is reverted and NOT committed.

---

## Environment setup

```bash
# 1. Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install dependencies
uv sync

# 3. Configure connections
cp config/env.yaml.example config/env.yaml
# Edit env.yaml with your Snowflake + Oracle credentials

# 4. Bootstrap audit/error tables
snowsql -f scripts/bootstrap_db.sql

# 5. Verify setup
uv run pytest -x -q

# 6. Run full pipeline dry-run
uv run python pipeline.py --all --dry-run
```

### `pyproject.toml` dependencies
```toml
[project]
name = "ora2sf-migration"
version = "0.1.0"
requires-python = ">=3.11"

[project.dependencies]
snowflake-snowpark-python = ">=1.14.0"
cx_Oracle = ">=8.3.0"
lxml = ">=5.0.0"
pydantic = ">=2.0.0"
jinja2 = ">=3.1.0"
pytest = ">=8.0.0"
pytest-cov = ">=4.0.0"
sqlglot = ">=23.0.0"    # SQL parsing for proc_correctness_score
pyyaml = ">=6.0.0"
rich = ">=13.0.0"       # progress output in pipeline.py

[tool.pytest.ini_options]
markers = ["integration: requires live DB credentials"]
```

---

## Summary decision table

| Need | Tool | Reason |
|---|---|---|
| Per-session domain knowledge (XML schema, SF API) | Skills (SKILL.md) | Static, loaded once |
| Iterative improvement of extractor.py | autoresearch loop | Propose→eval→keep/revert |
| Iterative improvement of matcher.py | autoresearch loop | Scalar metric available |
| Iterative improvement of generator.py | autoresearch loop | SQL AST score available |
| Migration validation logic | Fixed test suite | Correctness, not optimisation |
| Naming rules, type maps, synonym dicts | This CLAUDE.md | Read by agent every session |

> The human defines what "better" means (this file).
> The agent executes the research loop autonomously.
> The eval.py files are the immune system — they cannot be modified.
