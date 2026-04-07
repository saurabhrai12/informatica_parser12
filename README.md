# Oracle → Snowflake Migration Pipeline

Auto-migrates Oracle DWH ETL pipelines (built in Informatica PowerCenter) to native
Snowflake SQL stored procedures using a 3-step automated pipeline driven by semantic
matching, XML lineage extraction, and SQL code generation.

---

## Full 3-Step Pipeline ✅

### Architecture

```
Oracle DB  →  Step 2 (Mapping)   +   Informatica XML  →  Step 1 (Lineage)
                    ↓                         ↓
                    └──────────┬──────────────┘
                               ↓
                        Step 3 (Generator)
                               ↓
                   Snowflake Stored Procedures
```

### Eval Scores

| Step | Purpose | Score | Target |
|---|---|---|---|
| **Step 2** | Oracle ↔ Snowflake column mapping | **0.9561** | ≥ 0.88 ✅ |
| **Step 1** | Informatica XML lineage extraction | **0.9197** | ≥ 0.92 ✅ |
| **Step 3** | Snowflake proc generation | **0.9000** | ≥ 0.88 ✅ |

---

## Pipeline Stages

### Step 2 — Oracle ↔ Snowflake Column Mapping (`step2_mapping/`)
Produces a column-level mapping sheet pairing Oracle source columns to their Snowflake
equivalents using:
- **14-strategy semantic matching** (exact → normalised → abbreviation → fuzzy → synonym → type)
- **Same-table anchoring** — bonus for same-table matches, penalty for cross-table
- **Abbreviation expansion** — CUST→CUSTOMER, TXN→TRANSACTION, CRT→CREATED, etc.
- **Type compatibility scoring** — Oracle DATE → TIMESTAMP_NTZ, VARCHAR2 → VARCHAR, etc.
- **Confidence tiers**: HIGH (≥ 0.90) / MEDIUM (0.65–0.89) / LOW (0.40–0.64) / UNMATCHED

**Inputs:**
- `step2_mapping/tests/fixtures/oracle_cols.json` — Oracle `ALL_TAB_COLUMNS` metadata
- `step2_mapping/tests/fixtures/snowflake_cols.json` — Snowflake `INFORMATION_SCHEMA.COLUMNS`

**Output:** `outputs/mapping_sheet.json` — structured mapping with confidence scores, cast hints, and transform hints

---

### Step 1 — Informatica XML Lineage Extraction (`step1_lineage/`)
Parses Informatica PowerCenter mapping XML exports and produces field-level lineage JSON
covering:
- **Source → Target column tracing** via backward CONNECTOR graph traversal
- **SQ → Source resolution** by field-name overlap (handles Source Qualifier indirection)
- **Expression extraction** — verbatim `EXPRESSION` attribute from EXPR/AGG transform ports
- **Transformation sequence** — ordered chain of transform names (SQ→EXPR→LKP→AGG→RTR)
- **SQ override SQL** capture from `TABLEATTRIBUTE NAME="Sql Query"`
- **Router group conditions** from `TABLEATTRIBUTE GROUP FILTER CONDITION`
- **Load strategy inference** — `UPDATESTRATEGY` → INSERT/UPSERT/DELETE, `TRUNCATETARGET` flag
- **Lookup table/condition** from Lookup Procedure TABLEATTRIBUTE
- **Function mapping** — detects Informatica functions and maps to Snowflake equivalents

**Supported Informatica patterns:**

| Fixture | Pattern |
|---|---|
| `simple_passthrough.xml` | Direct source → target pass-through |
| `expression_mapping.xml` | IIF, DECODE, NVL, TO_DATE expressions |
| `lookup_mapping.xml` | Connected + unconnected lookup |
| `router_mapping.xml` | Router with multiple groups + DEFAULT |
| `aggregator_mapping.xml` | Aggregator with GROUP BY |
| `joiner_mapping.xml` | Joiner with master/detail |
| `upsert_mapping.xml` | DD_INSERT + DD_UPDATE (UPSERT) |
| `truncate_reload.xml` | Truncate flag + full reload |
| `sq_override.xml` | Source qualifier with SQL override |
| `complex_chain.xml` | SQ → EXPR → LKP → AGG → ROUTER → Target |

**Output:** `outputs/<mapping>_lineage.json` — field-level lineage array with 33 structured keys per row

---

### Step 3 — Snowflake Stored Procedure Generation (`step3_procgen/`)
Consumes the lineage JSON (Step 1) + mapping sheet (Step 2) to generate production-ready
Snowflake `LANGUAGE SQL` stored procedures:

**Generated procedure features:**
- **CTE ladder** — one CTE per transformation stage (`SQ_→EXPR_→LKP_→AGG_→JNR_`)
- **Informatica → Snowflake expression translation:**
  - `IIF(c,t,f)` → `CASE WHEN c THEN t ELSE f END`
  - `DECODE(col,v1,r1,...)` → `CASE col WHEN v1 THEN r1 ... END`
  - `NVL(a,b)` → `COALESCE(a,b)`
  - `SYSDATE` → `CURRENT_TIMESTAMP()`
  - `TO_CHAR(d,fmt)` → `TO_VARCHAR(d,fmt)`
  - `ADD_TO_DATE(d,'DD',n)` → `DATEADD(day,n,d)`
- **Write strategies** — INSERT / MERGE (UPSERT) / TRUNCATE+INSERT from lineage `load_type`
- **Router splitting** — one `INSERT ... WHERE <group_condition>` per Router group
- **Inline INFA comments** — `[INFA: TransformationType]`, source↔target, expression verbatim
- **Confidence-based TODOs** — `-- TODO: VERIFY` (MEDIUM), `-- TODO: MANUAL REVIEW` (LOW)
- **Standard parameters** — `P_WATERMARK_FROM`, `P_WATERMARK_TO`, `P_BATCH_ID`, `P_DRY_RUN`
- **Audit logging** — write to `MIGRATION_AUDIT_LOG` on start and end
- **Error logging** — write to `MIGRATION_ERROR_LOG` on exception with `FAILED_SQL`
- **Dry-run guard** — all DML wrapped in `IF (NOT P_DRY_RUN)` block

**Output:** `outputs/<mapping>_proc.sql` — deployable Snowflake SQL stored procedure

---

### Step 4 — Migration Validation (`step4_testing/`)
Validation harness run after deploying procs to a Snowflake test schema:

| Check | Description |
|---|---|
| `row_count_match` | `abs(sf_count - ora_count) / ora_count < 0.1%` |
| `pk_uniqueness` | No duplicate PKs in Snowflake target |
| `null_rate_within_5pct` | Null% per column within 5% of Oracle |
| `numeric_sum_match` | SUM(amount cols) within 0.01% of Oracle |
| `date_range_match` | MIN/MAX dates match Oracle ± 1 day |
| `sample_row_hash_match` | MD5 of 1000 random rows matches |
| `enum_value_coverage` | All distinct codes in Oracle exist in Snowflake |
| `audit_log_populated` | `MIGRATION_AUDIT_LOG` has SUCCESS row |
| `no_error_log_entries` | `MIGRATION_ERROR_LOG` has 0 rows for this proc |

---

## Quick Start

```bash
uv sync
cp config/env.yaml.example config/env.yaml   # fill in credentials

# Run all unit tests
uv run pytest -x -q

# Run the full pipeline (dry-run) for all mappings
uv run python pipeline.py --all --dry-run

# Run for a specific mapping
uv run python pipeline.py --mapping expression_mapping --dry-run
```

---

## Individual Step Evals

```bash
# Step 1 — Lineage extraction score (target ≥ 0.92)
uv run python -m step1_lineage.eval

# Step 2 — Column mapping score (target ≥ 0.88)
uv run python -m step2_mapping.eval

# Step 3 — Proc generation score (target ≥ 0.88)
uv run python -m step3_procgen.eval
```

---

## Autoresearch Loops

Each loop proposes one targeted change to the modifiable `.py` file, runs the eval,
keeps the commit if the score improved, reverts otherwise.

```bash
uv run python autoresearch/run_loop.py --step lineage  --max-experiments 50
uv run python autoresearch/run_loop.py --step mapping  --max-experiments 50
uv run python autoresearch/run_loop.py --step procgen  --max-experiments 50
```

The eval files and golden fixtures are **immutable** — the autoresearch loop only modifies
`extractor.py`, `matcher.py`, and `generator.py`.

---

## Repository Layout

```
informatica_parser/
├── CLAUDE.md                         ← Agent protocol + full operating spec
├── README.md                         ← This file
├── pipeline.py                       ← End-to-end orchestrator (Steps 1–4)
├── pyproject.toml                    ← Dependencies (uv-managed)
│
├── step1_lineage/
│   ├── extractor.py                  ← AGENT-MODIFIABLE: XML → lineage JSON
│   ├── function_map.py               ← Informatica → Snowflake function dictionary
│   ├── eval.py                       ← IMMUTABLE: lineage_coverage_score metric
│   └── tests/fixtures/ + expected/   ← 10 XML fixtures + golden JSON outputs
│
├── step2_mapping/
│   ├── matcher.py                    ← AGENT-MODIFIABLE: column matching engine
│   ├── synonym_dict.py               ← Abbreviation + synonym dictionary
│   ├── eval.py                       ← IMMUTABLE: mapping_confidence_score metric
│   └── tests/fixtures/ + expected/   ← oracle_cols.json, snowflake_cols.json, golden
│
├── step3_procgen/
│   ├── generator.py                  ← AGENT-MODIFIABLE: proc code generator
│   ├── templates/                    ← Jinja2 SQL templates
│   ├── eval.py                       ← IMMUTABLE: proc_correctness_score metric
│   └── tests/fixtures/ + expected/   ← lineage + mapping inputs, golden .sql
│
├── step4_testing/
│   ├── validator.py                  ← Row count, null-rate, hash checks
│   └── reconciler.py                 ← Oracle vs Snowflake data reconciliation
│
├── outputs/                          ← Generated lineage JSON, mapping sheets, procs
├── scripts/
│   ├── bootstrap_db.sql              ← MIGRATION_AUDIT_LOG + MIGRATION_ERROR_LOG DDL
│   └── run_eval.sh                   ← Single-shot eval runner
├── autoresearch/
│   ├── run_loop.py                   ← Autoresearch propose→eval→keep/revert loop
│   └── program_*.md                  ← Research agendas per step
└── config/
    └── env.yaml.example              ← Connection strings template
```

---

## Target Environment

| Setting | Value |
|---|---|
| Snowflake account | `HUBBXYZ-XA96647` |
| Target database | `PROD_DB` |
| Target schema | `CORTEX_CHAT_APP` |
| Source/staging schema | `RAW_LAYER` |
| Procedure prefix | `SP_` |
| Audit log | `PROD_DB.CORTEX_CHAT_APP.MIGRATION_AUDIT_LOG` |
| Error log | `PROD_DB.CORTEX_CHAT_APP.MIGRATION_ERROR_LOG` |
| Procedure language | Snowflake SQL scripting (`LANGUAGE SQL`, `BEGIN…END`) |
