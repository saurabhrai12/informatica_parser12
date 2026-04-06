"""Lineage + mapping → Snowflake SQL-scripting stored procedure.

Per proc_generater.txt: emit native LANGUAGE SQL procs (NOT Python/Snowpark).
Consumes:
  - Step 1 output: field-level lineage JSON (extractor.py)
  - Step 2 output: Oracle↔Snowflake column mapping sheet (matcher.py)

Agent-modifiable. Goal: maximise proc_correctness_score from eval.py.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

DB = "PROD_DB"
TARGET_SCHEMA = "CORTEX_CHAT_APP"
SOURCE_SCHEMA = "RAW_LAYER"

# ─────────────────────────────────────────────────────
# Informatica → Snowflake expression translator
# ─────────────────────────────────────────────────────
_IIF_RE = re.compile(r'\bIIF\s*\(', re.IGNORECASE)
_NVL_RE = re.compile(r'\bNVL\s*\(', re.IGNORECASE)
_NVL2_RE = re.compile(r'\bNVL2\s*\(', re.IGNORECASE)
_DECODE_RE = re.compile(r'\bDECODE\s*\(', re.IGNORECASE)
_SYSDATE_RE = re.compile(r'\bSYSDATE\b', re.IGNORECASE)
_SUBSTR_RE = re.compile(r'\bSUBSTR\s*\(', re.IGNORECASE)
_INSTR_RE = re.compile(r'\bINSTR\s*\(', re.IGNORECASE)
_TO_CHAR_RE = re.compile(r'\bTO_CHAR\s*\(', re.IGNORECASE)
_ADD_MONTHS_RE = re.compile(r'\bADD_MONTHS\s*\(', re.IGNORECASE)
_TRUNC_RE = re.compile(r'\bTRUNC\s*\(', re.IGNORECASE)
_DATE_DIFF_RE = re.compile(r'\bDATE_DIFF\s*\(([^,]+),([^,]+),([^)]+)\)', re.IGNORECASE)
_ADD_TO_DATE_RE = re.compile(r'\bADD_TO_DATE\s*\(([^,]+),\'([^\']+)\',([^)]+)\)', re.IGNORECASE)
_LTRIM_RE = re.compile(r'\bLTRIM\s*\(', re.IGNORECASE)
_RTRIM_RE = re.compile(r'\bRTRIM\s*\(', re.IGNORECASE)


def _translate_expr(expr: str | None) -> str | None:
    """Translate Informatica expression syntax to Snowflake SQL."""
    if not expr:
        return expr
    out = expr

    # IIF → CASE WHEN ... THEN ... ELSE ... END
    # Simple single-level replacement — nested handled recursively by Snowflake parser
    out = _IIF_RE.sub('CASE WHEN (', out)
    # After CASE WHEN we need to split at the first comma into condition/true/false
    # This regex is a best-effort for IIF rewrite — complex nesting preserved as-is
    # Full correct nesting requires a proper parser; we handle the most common patterns
    out = re.sub(r'CASE WHEN \(([^,]+),([^,]+),([^)]+)\)',
                 lambda m: f'CASE WHEN {m.group(1).strip()} THEN {m.group(2).strip()} ELSE {m.group(3).strip()} END',
                 out, flags=re.IGNORECASE)

    # NVL → COALESCE
    out = _NVL_RE.sub('COALESCE(', out)

    # NVL2 → IFF
    out = _NVL2_RE.sub('IFF(', out)

    # DECODE → CASE  (handled at CTE-build time for column-level)
    # Leave multi-arg DECODE as a comment note if not simple

    # SYSDATE → CURRENT_TIMESTAMP()
    out = _SYSDATE_RE.sub('CURRENT_TIMESTAMP()', out)

    # SUBSTR → SUBSTRING
    out = _SUBSTR_RE.sub('SUBSTRING(', out)

    # TO_CHAR → TO_VARCHAR
    out = _TO_CHAR_RE.sub('TO_VARCHAR(', out)

    # TRUNC(date) → DATE_TRUNC('DAY', date)
    out = _TRUNC_RE.sub("DATE_TRUNC('DAY', ", out)

    # DATE_DIFF(date1, date2, 'DD') → DATEDIFF(day, date2, date1)
    def _date_diff_repl(m: re.Match) -> str:
        d1, d2, unit = m.group(1).strip(), m.group(2).strip(), m.group(3).strip().strip("'\"")
        sf_unit = {"DD": "day", "MM": "month", "YY": "year", "HH": "hour"}.get(unit.upper(), unit.lower())
        return f"DATEDIFF({sf_unit}, {d2}, {d1})"
    out = _DATE_DIFF_RE.sub(_date_diff_repl, out)

    # ADD_TO_DATE(date, 'DD', n) → DATEADD(day, n, date)
    def _add_to_date_repl(m: re.Match) -> str:
        date, unit, n = m.group(1).strip(), m.group(2), m.group(3).strip()
        sf_unit = {"DD": "day", "MM": "month", "YY": "year", "HH": "hour"}.get(unit.upper(), unit.lower())
        return f"DATEADD({sf_unit}, {n}, {date})"
    out = _ADD_TO_DATE_RE.sub(_add_to_date_repl, out)

    return out


def _translate_decode(expr: str) -> str:
    """Best-effort DECODE → CASE WHEN translation."""
    m = re.match(r'DECODE\s*\((.*)\)$', expr.strip(), re.IGNORECASE | re.DOTALL)
    if not m:
        return expr
    inner = m.group(1)
    # split by commas (naive — doesn't handle nested parens)
    parts = [p.strip() for p in inner.split(',')]
    if len(parts) < 3:
        return expr
    col = parts[0]
    default = parts[-1] if len(parts) % 2 == 0 else None
    pairs = parts[1:] if default is None else parts[1:-1]
    cases = []
    for i in range(0, len(pairs) - 1, 2):
        cases.append(f"        WHEN {pairs[i]} THEN {pairs[i+1]}")
    result = f"CASE {col}\n" + "\n".join(cases)
    if default:
        result += f"\n        ELSE {default}"
    result += "\n    END"
    return result


def _qualify(table: str) -> str:
    """Return fully qualified Snowflake table reference."""
    return f"{DB}.{TARGET_SCHEMA}.{table}"


def _qualify_src(table: str) -> str:
    return f"{DB}.{SOURCE_SCHEMA}.{table}"


# ─────────────────────────────────────────────────────
# Mapping sheet helpers
# ─────────────────────────────────────────────────────

def _build_col_map(mapping_sheet: dict) -> dict[tuple, dict]:
    """Index mapping sheet by (oracle_table, oracle_column) → mapping row."""
    idx: dict[tuple, dict] = {}
    for m in mapping_sheet.get("mappings", []):
        key = (m.get("oracle_table", "").upper(), m.get("oracle_column", "").upper())
        idx[key] = m
    return idx


def _confidence_comment(row: dict, mapping_row: dict | None) -> str:
    tier = (mapping_row or {}).get("confidence_tier", row.get("lineage_confidence", "HIGH"))
    if tier == "MEDIUM":
        return "  -- TODO: VERIFY — MEDIUM confidence mapping"
    if tier in ("LOW", "UNMATCHED"):
        note = (mapping_row or {}).get("match_basis", "")
        return f"  -- TODO: MANUAL REVIEW REQUIRED — LOW confidence. {note}"
    return ""


# ─────────────────────────────────────────────────────
# CTE builders
# ─────────────────────────────────────────────────────

def _build_sq_cte(sq_name: str, target_rows: list[dict], sq_sql: str | None) -> str:
    """Build Source Qualifier CTE."""
    source_table = target_rows[0].get("source_table") or "UNKNOWN_SOURCE"
    if sq_sql:
        # Translate Oracle-specific functions in override SQL
        translated = _translate_expr(sq_sql) or sq_sql
        return (
            f"  -- [INFA: SourceQualifier] {sq_name} — SQ override SQL\n"
            f"  {translated}"
        )
    else:
        cols = sorted({r["source_column"] for r in target_rows if r.get("source_column")})
        col_list = ",\n         ".join(cols) if cols else "*"
        return (
            f"  -- [INFA: SourceQualifier] {sq_name}\n"
            f"  SELECT {col_list}\n"
            f"  FROM   {_qualify_src(source_table)}"
        )


def _build_expr_cte(expr_name: str, prev_cte: str, target_rows: list[dict],
                    col_map: dict) -> str:
    """Build Expression transformer CTE."""
    lines = [
        f"  -- [INFA: Expression] {expr_name}"
    ]
    lines.append("  SELECT")
    select_parts = []
    for r in target_rows:
        tgt_col = r["target_column"]
        src_col = r.get("source_column") or "NULL"
        raw_expr = r.get("final_expression")
        complexity = r.get("migration_complexity", "SIMPLE")
        mapping_row = col_map.get(
            ((r.get("source_table") or "").upper(), (r.get("source_column") or "").upper())
        )

        # Translate expression
        if raw_expr:
            if re.match(r'^DECODE\s*\(', raw_expr.strip(), re.I):
                sf_expr = _translate_decode(raw_expr)
            else:
                sf_expr = _translate_expr(raw_expr) or raw_expr
        elif src_col != "NULL":
            sf_expr = src_col
        else:
            sf_expr = "NULL"

        conf_comment = _confidence_comment(r, mapping_row)

        col_comment = (
            f"    -- [INFA] Complexity={complexity} "
            f"src={r.get('source_table')}.{r.get('source_column')} → tgt={r['target_table']}.{tgt_col}"
        )
        if raw_expr:
            col_comment += f"\n    -- Expression: {raw_expr}"
            col_comment += f"\n    -- SF rewrite:  {sf_expr}"

        line = f"{col_comment}"
        if conf_comment:
            line += f"\n{conf_comment}"
        line += f"\n    {sf_expr} AS {tgt_col}"
        select_parts.append(line)

    lines.append(",\n".join(select_parts))
    lines.append(f"  FROM {prev_cte}")
    return "\n".join(lines)


def _build_lookup_ctes(lookup_rows: list[dict], prev_cte: str) -> tuple[str, str]:
    """
    Build LEFT JOIN CTE(s) for lookup transformations.
    Returns (cte_body, last_cte_name).
    """
    if not lookup_rows:
        return "", prev_cte

    # Group lookups by transform name
    by_transform: dict[str, list[dict]] = defaultdict(list)
    for r in lookup_rows:
        seq = r.get("transformation_sequence", [])
        # Find the lookup transform name in the sequence
        lkp_name = next((s for s in seq if s.startswith("LKP_")), "LKP_UNKNOWN")
        by_transform[lkp_name].append(r)

    cte_parts = []
    current_prev = prev_cte
    last_name = prev_cte

    for lkp_name, rows in by_transform.items():
        lkp_table = rows[0].get("lookup_table", "UNKNOWN_LKP_TABLE")
        lkp_cond = rows[0].get("lookup_condition", "")
        ret_cols = [r["target_column"] for r in rows]

        # Parse condition: "COL_A = COL_B" → split
        join_clause = ""
        if lkp_cond:
            # Translate "input = lookup_key" → "lkp.lookup_key = src.input"
            parts = [p.strip() for p in lkp_cond.split("=")]
            if len(parts) == 2:
                join_clause = f"lkp.{parts[1]} = src.{parts[0]}"
            else:
                join_clause = lkp_cond

        cte_body = (
            f"  -- [INFA: Lookup] {lkp_name} → {lkp_table}\n"
            f"  SELECT\n"
            f"    src.*,\n"
            f"    " + ",\n    ".join(f"lkp.{c}" for c in ret_cols) + "\n"
            f"  FROM   {current_prev} src\n"
            f"  LEFT   JOIN {_qualify(lkp_table)} lkp\n"
            f"      ON {join_clause}"
        )
        cte_parts.append((lkp_name, cte_body))
        current_prev = lkp_name
        last_name = lkp_name

    return cte_parts, last_name


def _build_agg_cte(agg_name: str, prev_cte: str, target_rows: list[dict]) -> str:
    """Build Aggregator CTE."""
    group_cols = []
    agg_exprs = []
    for r in target_rows:
        agg = r.get("aggregation_logic", "")
        tgt_col = r["target_column"]
        sf_expr = _translate_expr(r.get("final_expression")) or r.get("source_column") or "NULL"
        if agg and agg.upper().startswith("GROUP BY"):
            group_cols.append((sf_expr, tgt_col))
        else:
            agg_exprs.append((sf_expr, tgt_col, agg or ""))

    select_parts = []
    for expr, col in group_cols:
        select_parts.append(f"    {expr} AS {col}  -- GROUP BY key")
    for expr, col, agg_logic in agg_exprs:
        sf_expr = _translate_expr(expr) or expr
        select_parts.append(f"    {sf_expr} AS {col}  -- AGG: {agg_logic}")

    group_by_cols = ", ".join(col for _, col in group_cols) if group_cols else "1"

    return (
        f"  -- [INFA: Aggregator] {agg_name}\n"
        f"  SELECT\n"
        + ",\n".join(select_parts) + "\n"
        f"  FROM {prev_cte}\n"
        f"  GROUP BY {group_by_cols}"
    )


def _build_joiner_cte(join_name: str, target_rows: list[dict], source_ctes: list[str]) -> str:
    """Build Joiner CTE — two-source JOIN."""
    join_cond = target_rows[0].get("join_condition", "1=1")
    masters = [r for r in target_rows if r.get("source_table")]
    tgt_cols = ", ".join(
        f"    {_translate_expr(r.get('final_expression')) or r.get('source_column') or 'NULL'} AS {r['target_column']}"
        for r in target_rows
    )
    src_a = source_ctes[0] if source_ctes else "SRC_A"
    src_b = source_ctes[1] if len(source_ctes) > 1 else "SRC_B"
    return (
        f"  -- [INFA: Joiner] {join_name} — join condition: {join_cond}\n"
        f"  SELECT\n{tgt_cols}\n"
        f"  FROM   {src_a} a\n"
        f"  JOIN   {src_b} b ON {join_cond}"
    )


# ─────────────────────────────────────────────────────
# Write strategy builders
# ─────────────────────────────────────────────────────

def _build_insert(target_table: str, target_rows: list[dict], final_cte: str,
                  router_condition: str | None = None) -> str:
    cols = ", ".join(r["target_column"] for r in target_rows)
    where = f"\nWHERE  {router_condition}" if router_condition else ""
    return (
        f"INSERT INTO {_qualify(target_table)}\n"
        f"  ({cols})\n"
        f"SELECT {', '.join(r['target_column'] for r in target_rows)}\n"
        f"FROM   {final_cte}{where};"
    )


def _build_merge(target_table: str, target_rows: list[dict], final_cte: str) -> str:
    pk_rows = [r for r in target_rows if r.get("target_pk_flag")]
    non_pk = [r for r in target_rows if not r.get("target_pk_flag")]
    if not pk_rows:
        pk_rows = target_rows[:1]
        non_pk = target_rows[1:]

    on_clause = " AND ".join(
        f"tgt.{r['target_column']} = src.{r['target_column']}" for r in pk_rows
    )
    update_clause = ",\n    ".join(
        f"tgt.{r['target_column']} = src.{r['target_column']}" for r in non_pk
    )
    all_cols = ", ".join(r["target_column"] for r in target_rows)
    all_vals = ", ".join(f"src.{r['target_column']}" for r in target_rows)

    return (
        f"MERGE INTO {_qualify(target_table)} tgt\n"
        f"USING {final_cte} src\n"
        f"ON ({on_clause})\n"
        f"WHEN MATCHED THEN UPDATE SET\n    {update_clause}\n"
        f"WHEN NOT MATCHED THEN INSERT ({all_cols})\n"
        f"  VALUES ({all_vals});"
    )


# ─────────────────────────────────────────────────────
# Main generator
# ─────────────────────────────────────────────────────

def generate_proc(lineage: list[dict], mapping_sheet: dict | None = None) -> str:
    """Generate a Snowflake SQL stored procedure from lineage + mapping sheet."""
    if not lineage:
        return "-- No lineage data provided"

    col_map = _build_col_map(mapping_sheet or {})
    mapping_name = lineage[0]["mapping_name"]

    # Group rows by target table
    by_target: dict[str, list[dict]] = defaultdict(list)
    for r in lineage:
        by_target[r["target_table"]].append(r)

    # Detect patterns across all rows
    all_load_types  = {r.get("load_type", "INSERT") for r in lineage}
    has_truncate    = any(r.get("truncate_before_load") for r in lineage)
    has_router      = any(r.get("router_condition") for r in lineage)
    has_lookup      = any(r.get("lookup_table") for r in lineage)
    has_agg         = any(r.get("aggregation_logic") for r in lineage)
    has_join        = any(r.get("join_condition") for r in lineage)
    load_type       = "UPSERT" if "UPSERT" in all_load_types else (
                      "DELETE" if "DELETE" in all_load_types else "INSERT")

    # Use the first (or only) target table for procedure naming
    target_table = list(by_target.keys())[0]
    target_rows  = by_target[target_table]
    source_table = target_rows[0].get("source_table") or "UNKNOWN_SOURCE"
    sq_override  = next((r.get("sq_override_sql") for r in target_rows if r.get("sq_override_sql")), None)

    # Build transformation sequence from lineage
    seq = target_rows[0].get("transformation_sequence") or []

    # ── CTE ladder ─────────────────────────────────────────────────────
    ctes: list[tuple[str, str]] = []  # [(cte_name, cte_body)]

    # 1. Source Qualifier CTE
    sq_name = next((s for s in seq if s.startswith("SQ_")), f"SQ_{mapping_name}")
    ctes.append((sq_name, _build_sq_cte(sq_name, target_rows, sq_override)))
    prev = sq_name

    # 2. Expression CTE (if expr present in any row)
    expr_rows = [r for r in target_rows if r.get("final_expression") or r.get("source_column")]
    expr_name = next((s for s in seq if s.startswith("EXPR_")), None)
    if expr_name or expr_rows:
        expr_cte_name = expr_name or f"EXPR_{mapping_name}"
        ctes.append((expr_cte_name, _build_expr_cte(expr_cte_name, prev, target_rows, col_map)))
        prev = expr_cte_name

    # 3. Lookup CTE(s)
    if has_lookup:
        lkp_rows = [r for r in target_rows if r.get("lookup_table")]
        lkp_cte_pairs, prev = _build_lookup_ctes(lkp_rows, prev)
        if isinstance(lkp_cte_pairs, list):
            ctes.extend(lkp_cte_pairs)

    # 4. Aggregator CTE
    if has_agg:
        agg_name = next((s for s in seq if s.startswith("AGG_")), f"AGG_{mapping_name}")
        ctes.append((agg_name, _build_agg_cte(agg_name, prev, target_rows)))
        prev = agg_name

    # 5. Joiner CTE
    if has_join:
        join_name = next((s for s in seq if s.startswith("JNR_")), f"JNR_{mapping_name}")
        src_ctes = [c[0] for c in ctes if c[0].startswith("SQ_")]
        ctes.append((join_name, _build_joiner_cte(join_name, target_rows, src_ctes)))
        prev = join_name

    final_cte = prev  # last CTE feeds the write

    # ── SQL body ────────────────────────────────────────────────────────
    cte_block = "WITH\n" + ",\n".join(
        f"{name} AS (\n{body}\n)" for name, body in ctes
    )

    # ── Write statements ────────────────────────────────────────────────
    write_stmts: list[str] = []

    if has_truncate and load_type == "INSERT":
        write_stmts.append(f"-- [INFA: TruncateTarget] truncate before full reload\nTRUNCATE TABLE {_qualify(target_table)};")

    if has_router:
        # One INSERT per Router group per target
        router_groups_seen: set[str] = set()
        all_conditions: list[str] = []
        for tname, trows in by_target.items():
            seen_conditions = set()
            for r in trows:
                cond = r.get("router_condition")
                if cond and cond not in seen_conditions:
                    seen_conditions.add(cond)
                    all_conditions.append(cond)
                    comment = f"-- [INFA: Router] group condition: {cond}"
                    write_stmts.append(
                        f"{comment}\n" + _build_insert(tname, trows, final_cte, cond)
                    )
            # DEFAULT group (catch-all) — rows with router_condition == "TRUE" or None
            default_rows = [r for r in trows if not r.get("router_condition") or r.get("router_condition") == "TRUE"]
            if default_rows and all_conditions:
                neg_cond = " AND ".join(f"NOT ({c})" for c in all_conditions[:-1]) if len(all_conditions) > 1 else f"NOT ({all_conditions[0]})"
                write_stmts.append(
                    f"-- [INFA: Router] DEFAULT group\n" +
                    _build_insert(tname, default_rows, final_cte, neg_cond if all_conditions else None)
                )
    elif load_type == "UPSERT":
        write_stmts.append(_build_merge(target_table, target_rows, final_cte))
    else:
        write_stmts.append(_build_insert(target_table, target_rows, final_cte))

    main_sql = f"{cte_block}\n" + "\n".join(write_stmts)

    # ── Complexity annotation ───────────────────────────────────────────
    has_complex = any(r.get("migration_complexity") == "COMPLEX" for r in lineage)
    complex_note = (
        "\n-- ⚠ COMPLEX MIGRATION NOTE: This procedure includes complex transformation patterns.\n"
        "-- Requires human review before production deployment.\n"
    ) if has_complex else ""

    # ── Watermark filter for incremental loads ─────────────────────────
    watermark_col = next(
        (r["source_column"] for r in lineage
         if r.get("source_column") and any(kw in (r["source_column"] or "").upper()
                                            for kw in ("LAST_MOD", "MOD_DT", "UPD_DT", "CHANGE_DT"))),
        None
    )
    watermark_clause = (
        f"    -- Incremental filter — applied to source\n"
        f"    -- WHERE {watermark_col} >= :P_WATERMARK_FROM AND {watermark_col} < :P_WATERMARK_TO\n"
    ) if watermark_col else ""

    # ────────────────────────────────────────────────────────────────────
    # Full procedure text
    # ────────────────────────────────────────────────────────────────────
    proc = f"""
{complex_note}CREATE OR REPLACE PROCEDURE {DB}.{TARGET_SCHEMA}.SP_{target_table}(
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
    v_status        VARCHAR        DEFAULT 'RUNNING';
    v_rows_inserted INTEGER        DEFAULT 0;
    v_rows_updated  INTEGER        DEFAULT 0;
    v_err_msg       VARCHAR;
    v_failed_sql    VARCHAR;
    v_start_ts      TIMESTAMP_NTZ  DEFAULT CURRENT_TIMESTAMP();
BEGIN
    -- ── AUDIT: start ─────────────────────────────────────────────────
    INSERT INTO {DB}.{TARGET_SCHEMA}.MIGRATION_AUDIT_LOG
        (MAPPING_NAME, PROCEDURE_NAME, EXEC_START_TS, EXEC_END_TS, STATUS,
         ROWS_INSERTED, ROWS_UPDATED, ROWS_DELETED, INFORMATICA_MAPPING_REF, ERROR_MESSAGE, BATCH_ID)
    VALUES ('{mapping_name}', 'SP_{target_table}',
            :v_start_ts, NULL, 'RUNNING',
            0, 0, 0, '{mapping_name}', NULL, :P_BATCH_ID);

    -- ── PRE-HOOK ─────────────────────────────────────────────────────
    -- (no pre-SQL declared in lineage; add session params here if needed)
{watermark_clause}
    -- ── MAIN TRANSFORMATION ──────────────────────────────────────────
    -- [INFA: Mapping] {mapping_name}  →  Target: {target_table}
    -- Source: {source_table}
    -- Load strategy: {load_type}  Truncate: {has_truncate}
    BEGIN
        LET stmt VARCHAR := $${main_sql}$$;

        IF (NOT P_DRY_RUN) THEN
            EXECUTE IMMEDIATE :stmt;
            v_rows_inserted := SQLROWCOUNT;
        ELSE
            -- DRY RUN mode: return preview query, do not write
            RETURN 'DRY_RUN: ' || :stmt;
        END IF;

        v_status := 'SUCCESS';
    EXCEPTION
        WHEN OTHER THEN
            v_status     := 'FAILED';
            v_err_msg    := SQLERRM;
            v_failed_sql := stmt;
            INSERT INTO {DB}.{TARGET_SCHEMA}.MIGRATION_ERROR_LOG
                (PROC_NAME, ERROR_CODE, ERROR_MESSAGE, FAILED_SQL, EXEC_TS, BATCH_ID)
            VALUES ('SP_{target_table}', SQLCODE, :v_err_msg,
                    :v_failed_sql, CURRENT_TIMESTAMP(), :P_BATCH_ID);
    END;

    -- ── ROW COUNT VALIDATION ─────────────────────────────────────────
    -- Check inserted vs expected; raise if delta > 5%
    -- (Adjust threshold per data volume SLA)

    -- ── AUDIT: end ────────────────────────────────────────────────────
    UPDATE {DB}.{TARGET_SCHEMA}.MIGRATION_AUDIT_LOG
    SET    EXEC_END_TS   = CURRENT_TIMESTAMP(),
           STATUS        = :v_status,
           ROWS_INSERTED = :v_rows_inserted,
           ROWS_UPDATED  = :v_rows_updated,
           ERROR_MESSAGE = :v_err_msg
    WHERE  MAPPING_NAME    = '{mapping_name}'
      AND  PROCEDURE_NAME  = 'SP_{target_table}'
      AND  STATUS          = 'RUNNING';

    RETURN :v_status;
END;
$$;
"""
    return proc


def write_proc(lineage_json: Path, mapping_json: Path | None, out: Path) -> None:
    lineage = json.loads(lineage_json.read_text())
    mapping = json.loads(mapping_json.read_text()) if mapping_json and mapping_json.exists() else {}
    out.write_text(generate_proc(lineage, mapping))
