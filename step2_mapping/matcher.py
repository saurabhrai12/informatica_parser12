"""Oracle ↔ Snowflake column mapping sheet generator.

Implements the 14-strategy matching methodology from mapping_identification.txt,
plus Strategy 15: Snowflake Cortex Complete LLM semantic matching.

Agent-modifiable. Goal: maximise mapping_confidence_score from eval.py.

## Strategy 15 — Cortex Complete LLM

When ``use_cortex_llm=True`` is passed (or the ``CORTEX_ENABLED`` env-var is set),
``match_columns()`` calls ``SNOWFLAKE.CORTEX.COMPLETE()`` for any column pair that
scored below HIGH on the 14 rule-based strategies.  The LLM is asked to rank the
top-N candidate Snowflake columns for a given Oracle column and return a JSON
confidence score.

Design principles:
- **Opt-in only**: no live Snowflake session is required for unit tests.
- **Corroboration cap**: a Cortex-only match (no rule-based signal) is capped at 0.82
  to stay below the 0.90 HIGH threshold unless a rule-based strategy also fires.
- **Batching**: one CORTEX.COMPLETE call per Oracle column (not per pair) to minimise
  latency.
- **Graceful degradation**: any network error, parse error, or missing session falls
  through silently, leaving the rule-based score unchanged.
- **Model choice**: defaults to ``mistral-7b`` (fastest Cortex model); override via
  ``CORTEX_MODEL`` env-var or the ``cortex_model`` kwarg.
"""
from __future__ import annotations

import json
import logging
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .synonym_dict import expand, synonyms_of

logger = logging.getLogger(__name__)

HIGH, MED, LOW = 0.90, 0.65, 0.40

# Cortex-only match cap (can be exceeded when corroborated by a rule-based strategy)
_CORTEX_SOLO_CAP = 0.82
# Model used for Cortex Complete calls
_DEFAULT_CORTEX_MODEL = os.environ.get("CORTEX_MODEL", "mistral-7b")
# Top-N Snowflake candidates sent to the LLM per Oracle column
_CORTEX_TOP_N = 8


# ──────────────────────────────────────────────────────────────────────────────
# Normalisation helpers
# ──────────────────────────────────────────────────────────────────────────────

def _normalise(name: str) -> str:
    n = re.sub(r"[^A-Z0-9]", "_", name.upper())
    parts = [expand(p) for p in n.split("_") if p]
    return "_".join(parts)


def _strip_single_letter_prefix(name: str) -> str:
    """Strip Oracle-style single-letter type prefixes: C_, N_, D_."""
    m = re.match(r"^[CND]_(.+)$", name.upper())
    return m.group(1) if m else name.upper()


def _normalise_with_prefix_strip(name: str) -> str:
    stripped = _strip_single_letter_prefix(name)
    return _normalise(stripped)


# ──────────────────────────────────────────────────────────────────────────────
# Scoring helpers
# ──────────────────────────────────────────────────────────────────────────────

def _name_score(o: str, s: str) -> tuple[float, str]:
    """Return (score, match_type) for an Oracle/Snowflake column name pair."""
    if o.upper() == s.upper():
        return 1.0, "EXACT"

    no, ns = _normalise(o), _normalise(s)
    if no == ns:
        return 0.93, "NORMALISED"

    # Try prefix-stripped normalisation
    no2 = _normalise_with_prefix_strip(o)
    ns2 = _normalise_with_prefix_strip(s)
    if no2 == ns2:
        return 0.92, "NORMALISED"

    # Synonym / semantic check
    if ns in synonyms_of(o) or no in synonyms_of(s):
        return 0.80, "SEMANTIC"   # capped per spec

    # Abbreviation / fuzzy
    ratio = SequenceMatcher(None, no, ns).ratio()
    if ratio >= 0.85:
        return 0.85 * ratio, "ABBREVIATION"

    # Try with prefix-stripped versions
    ratio2 = SequenceMatcher(None, no2, ns2).ratio()
    best_ratio = max(ratio, ratio2)
    if best_ratio >= 0.70:
        return best_ratio * 0.75, "ABBREVIATION"

    return best_ratio * 0.60, "INFERRED"


_TYPE_FAMILIES = {
    "NUMBER": {"NUMBER", "INTEGER", "BIGINT", "DECIMAL", "FLOAT", "NUMERIC", "INT"},
    "STRING": {"VARCHAR", "VARCHAR2", "CHAR", "TEXT", "STRING", "CLOB", "NVARCHAR"},
    "DATE":   {"DATE", "TIMESTAMP", "TIMESTAMP_NTZ", "TIMESTAMP_LTZ", "DATETIME"},
    "BINARY": {"RAW", "BLOB", "BINARY", "BYTEA"},
    "VARIANT": {"XMLTYPE", "CLOB", "VARIANT", "JSON"},
}


def _type_family(t: str | None) -> str | None:
    if not t:
        return None
    t = t.upper()
    for fam, members in _TYPE_FAMILIES.items():
        if any(m in t for m in members):
            return fam
    return None


def _type_compatible(o_type: str | None, s_type: str | None) -> bool:
    fo, fs = _type_family(o_type), _type_family(s_type)
    return fo is not None and fo == fs


def _suggested_cast(o_type: str | None, s_type: str | None) -> str | None:
    if not o_type or not s_type:
        return None
    fo, fs = _type_family(o_type), _type_family(s_type)
    if fo == fs:
        return None
    if fs == "DATE":
        return "TRY_TO_TIMESTAMP_NTZ(col)"
    if fs == "NUMBER":
        return "TRY_TO_NUMBER(col)"
    if fs == "STRING":
        return "TO_VARCHAR(col)"
    return None


def _tier(score: float) -> str:
    if score >= HIGH:
        return "HIGH"
    if score >= MED:
        return "MEDIUM"
    if score >= LOW:
        return "LOW"
    return "UNMATCHED"


def _table_name_score(o_table: str, s_table: str) -> float:
    """Score similarity between two table names (0-1)."""
    if o_table.upper() == s_table.upper():
        return 1.0
    no, ns = _normalise(o_table), _normalise(s_table)
    if no == ns:
        return 0.95
    return SequenceMatcher(None, no, ns).ratio()


def _comment_boost(oc: dict, sc: dict) -> float:
    """+0.05 boost if oracle comment keywords appear in the snowflake column name or comment."""
    oc_comment = (oc.get("comment") or "").upper()
    sc_name = sc.get("column", "").upper()
    sc_comment = (sc.get("comment") or "").upper()
    if not oc_comment:
        return 0.0
    words = set(re.findall(r"[A-Z]{3,}", oc_comment))
    target = sc_name + " " + sc_comment
    if any(w in target for w in words):
        return 0.05
    return 0.0


def _pk_boost(oc: dict, sc: dict) -> float:
    """+0.05 if both sides are PK columns."""
    if oc.get("pk") and sc.get("pk"):
        return 0.05
    return 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Strategy 15 — Snowflake Cortex Complete LLM
# ──────────────────────────────────────────────────────────────────────────────

def _build_cortex_prompt(oracle_col: dict, candidates: list[dict]) -> str:
    """Build the prompt sent to CORTEX.COMPLETE for one Oracle column."""
    col_name = oracle_col.get("column", "")
    col_type = oracle_col.get("data_type", "UNKNOWN")
    col_comment = oracle_col.get("comment") or ""
    table_name = oracle_col.get("table", "")

    candidate_list = "\n".join(
        f"  - {c['column']} ({c.get('data_type','?')}) in {c.get('table','?')}"
        + (f" — {c['comment']}" if c.get("comment") else "")
        for c in candidates
    )

    return (
        f"You are a data migration expert matching Oracle DWH columns to Snowflake columns.\n\n"
        f"Oracle column: {col_name}\n"
        f"Oracle table: {table_name}\n"
        f"Oracle type: {col_type}\n"
        f"Oracle description: {col_comment}\n\n"
        f"Candidate Snowflake columns:\n{candidate_list}\n\n"
        f"Task: identify which Snowflake column is the best semantic match for the Oracle column.\n"
        f"Consider abbreviation expansions (e.g. CNTRY=COUNTRY, CRT=CREATED, FLG=FLAG, TYP=TYPE),\n"
        f"domain synonyms, and column descriptions.\n\n"
        f"Respond ONLY with valid JSON in exactly this format, no markdown, no explanation:\n"
        f'{{"best_match": "SNOWFLAKE_COLUMN_NAME", "confidence": 0.85, "reason": "brief"}}\n\n'
        f"If none of the candidates are a good match, use null for best_match and 0.0 for confidence."
    )


def _call_cortex(prompt: str, session: Any, model: str) -> dict | None:
    """Execute a CORTEX.COMPLETE call and return parsed JSON, or None on failure.

    Supports both:
    - snowflake.snowpark.Session  (has .sql(...).collect())
    - snowflake.connector cursor  (has .execute() / .fetchone())
    """
    if session is None:
        return None

    # Escape single quotes in the prompt for SQL embedding
    escaped = prompt.replace("'", "''").replace("\\", "\\\\")
    sql = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{model}', '{escaped}') AS response"

    try:
        # Try Snowpark Session first
        if hasattr(session, "sql"):
            rows = session.sql(sql).collect()
            raw = rows[0]["RESPONSE"] if rows else None
        # Fall back to snowflake.connector cursor
        elif hasattr(session, "execute"):
            session.execute(sql)
            row = session.fetchone()
            raw = row[0] if row else None
        else:
            logger.warning("cortex_semantic_score: unrecognised session type %s", type(session))
            return None

        if not raw:
            return None

        # Strip markdown code fences if the model wrapped the JSON
        raw = re.sub(r"```(?:json)?", "", raw).strip()
        # Extract the first JSON object in the response
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        return json.loads(m.group())

    except Exception as exc:  # noqa: BLE001
        logger.debug("cortex_semantic_score failed: %s", exc)
        return None


def cortex_semantic_score(
    oracle_col: dict,
    sf_candidates: list[dict],
    session: Any = None,
    model: str = _DEFAULT_CORTEX_MODEL,
) -> dict[str, float]:
    """Ask Snowflake Cortex Complete to score Snowflake candidates for an Oracle column.

    Args:
        oracle_col: single Oracle column dict (must have 'column', 'table', 'data_type').
        sf_candidates: list of Snowflake column dicts to score.
        session: optional Snowpark Session or connector cursor.  Pass ``None`` to skip (unit tests).
        model: Cortex model name (default: mistral-7b).

    Returns:
        dict mapping Snowflake column name → confidence float (0–1).
        Returns empty dict if no session or on any error.
    """
    if session is None or not sf_candidates:
        return {}

    prompt = _build_cortex_prompt(oracle_col, sf_candidates[:_CORTEX_TOP_N])
    result = _call_cortex(prompt, session, model)
    if not result:
        return {}

    best_col = result.get("best_match")
    confidence = float(result.get("confidence", 0.0))

    if best_col is None or confidence <= 0:
        return {}

    # Normalise the column name: the LLM sometimes returns it with wrong case
    name_map = {c["column"].upper(): c["column"] for c in sf_candidates}
    canonical = name_map.get(best_col.upper())
    if not canonical:
        # Fuzzy fallback: find the closest candidate name
        best_ratio, best_cand = 0.0, None
        for cname in name_map.values():
            r = SequenceMatcher(None, best_col.upper(), cname.upper()).ratio()
            if r > best_ratio:
                best_ratio, best_cand = r, cname
        if best_ratio >= 0.80:
            canonical = best_cand
        else:
            return {}

    return {canonical: min(confidence, _CORTEX_SOLO_CAP)}


# ──────────────────────────────────────────────────────────────────────────────
# Main matching entry point
# ──────────────────────────────────────────────────────────────────────────────

def match_columns(
    oracle_cols: list[dict],
    snowflake_cols: list[dict],
    *,
    use_cortex_llm: bool = False,
    cortex_session: Any = None,
    cortex_model: str = _DEFAULT_CORTEX_MODEL,
) -> dict[str, Any]:
    """Return {mappings: [...], unmatched_oracle: [...], unmatched_snowflake: [...]}.

    Strategy (in order):
    1–14. Rule-based name/type/comment/PK scoring with table-anchor modifier.
    15.   (Optional) Snowflake Cortex Complete LLM for columns below HIGH confidence.

    Args:
        oracle_cols:      List of Oracle column dicts (from oracle_cols.json).
        snowflake_cols:   List of Snowflake column dicts (from snowflake_cols.json).
        use_cortex_llm:   Enable Strategy 15 Cortex semantic matching.
        cortex_session:   Snowpark Session or connector cursor for Cortex calls.
        cortex_model:     Cortex model name (default: mistral-7b).
    """
    # Env-var override: CORTEX_ENABLED=1 activates Cortex even without explicit flag
    if os.environ.get("CORTEX_ENABLED", "").strip() in ("1", "true", "yes"):
        use_cortex_llm = True

    matched_sf: set[tuple] = set()
    mappings: list[dict] = []

    for oc in oracle_cols:
        best_sc: dict | None = None
        best_score = 0.0
        best_type = "INFERRED"

        for sc in snowflake_cols:
            score, mtype = _name_score(oc["column"], sc["column"])

            # ── Table-anchor modifier ──────────────────────────────────────
            tbl_sim = _table_name_score(oc.get("table", ""), sc.get("table", ""))
            if tbl_sim >= 0.90:
                score = min(1.0, score + 0.10)   # same-table bonus
            elif tbl_sim < 0.60:
                score -= 0.20                     # cross-table penalty

            # ── Type compatibility modifier ────────────────────────────────
            if _type_compatible(oc.get("data_type"), sc.get("data_type")):
                score = min(1.0, score + 0.05)
            else:
                score -= 0.10

            # ── Comment keyword boost ──────────────────────────────────────
            score = min(1.0, score + _comment_boost(oc, sc))

            # ── PK/FK alignment boost ──────────────────────────────────────
            score = min(1.0, score + _pk_boost(oc, sc))

            if score > best_score:
                best_sc, best_score, best_type = sc, score, mtype

        # ── Strategy 15: Cortex Complete for sub-HIGH columns ─────────────
        cortex_upgrade: dict[str, float] = {}
        if use_cortex_llm and best_score < HIGH:
            # Send top-N same-table candidates (or all if fewer) to the LLM
            same_table = [
                sc for sc in snowflake_cols
                if _table_name_score(oc.get("table", ""), sc.get("table", "")) >= 0.60
            ]
            candidates = same_table or snowflake_cols
            cortex_upgrade = cortex_semantic_score(
                oc, candidates, session=cortex_session, model=cortex_model
            )

            for sf_col_name, cx_score in cortex_upgrade.items():
                # Find the full SF column dict
                sf_dict = next(
                    (sc for sc in snowflake_cols if sc["column"] == sf_col_name), None
                )
                if sf_dict is None:
                    continue

                # Apply table-anchor and type modifiers to the Cortex score too
                tbl_sim = _table_name_score(oc.get("table", ""), sf_dict.get("table", ""))
                adj_score = cx_score
                if tbl_sim >= 0.90:
                    adj_score = min(1.0, adj_score + 0.10)
                elif tbl_sim < 0.60:
                    adj_score -= 0.20
                if _type_compatible(oc.get("data_type"), sf_dict.get("data_type")):
                    adj_score = min(1.0, adj_score + 0.05)

                # Corroboration lift: if rule-based already found the same column,
                # we can exceed the solo cap
                if best_sc and best_sc["column"] == sf_col_name:
                    combined = min(1.0, max(best_score, adj_score) + 0.05)
                    if combined > best_score:
                        best_score, best_type = combined, "CORTEX_CORROBORATED"
                elif adj_score > best_score:
                    best_sc, best_score, best_type = sf_dict, adj_score, "CORTEX_SEMANTIC"

        if best_sc is None or best_score < LOW:
            continue

        matched_sf.add((best_sc["table"], best_sc["column"]))

        tbl_sim_final = _table_name_score(oc.get("table", ""), best_sc.get("table", ""))
        match_basis = (
            f"name_score via {best_type}; "
            f"table_sim={tbl_sim_final:.2f}; "
            f"type_compat={_type_compatible(oc.get('data_type'), best_sc.get('data_type'))}"
        )
        if best_type.startswith("CORTEX") and cortex_upgrade:
            cx_col = best_sc["column"]
            match_basis += f"; cortex_confidence={cortex_upgrade.get(cx_col, 0):.2f}"

        mappings.append({
            "oracle_table":        oc["table"],
            "oracle_column":       oc["column"],
            "oracle_data_type":    oc.get("data_type"),
            "oracle_nullable":     oc.get("nullable"),
            "oracle_pk_flag":      oc.get("pk", False),
            "snowflake_table":     best_sc["table"],
            "snowflake_column":    best_sc["column"],
            "snowflake_data_type": best_sc.get("data_type"),
            "snowflake_nullable":  best_sc.get("nullable"),
            "snowflake_pk_flag":   best_sc.get("pk", False),
            "match_type":          best_type,
            "confidence_score":    round(min(best_score, 1.0), 4),
            "confidence_tier":     _tier(min(best_score, 1.0)),
            "match_basis":         match_basis,
            "type_compatible":     _type_compatible(oc.get("data_type"), best_sc.get("data_type")),
            "suggested_cast":      _suggested_cast(oc.get("data_type"), best_sc.get("data_type")),
            "transform_hint":      None,
            "unmatched_reason":    None,
            "recommended_action":  "MAP" if best_score >= MED else "INVESTIGATE",
        })

    matched_oracle = {(m["oracle_table"], m["oracle_column"]) for m in mappings}

    unmatched_oracle = [
        {
            "oracle_table":   c["table"],
            "oracle_column":  c["column"],
            "reason":         "no candidate above LOW threshold",
            "action":         "INVESTIGATE",
        }
        for c in oracle_cols
        if (c["table"], c["column"]) not in matched_oracle
    ]

    # Classify unmatched Snowflake columns: derived/load columns vs pure unmatched
    _DERIVED_PATTERNS = re.compile(
        r"^(LOAD_TS|LOAD_DATE|INSERT_TS|IS_HIGH_VALUE|IS_[A-Z_]+|ETL_|DW_)", re.I
    )
    unmatched_snowflake = [
        {
            "snowflake_table":  c["table"],
            "snowflake_column": c["column"],
            "reason":           "no oracle counterpart matched",
            "action":           "DERIVED" if _DERIVED_PATTERNS.match(c["column"]) else "INVESTIGATE",
        }
        for c in snowflake_cols
        if (c["table"], c["column"]) not in matched_sf
    ]

    return {
        "mappings":            mappings,
        "unmatched_oracle":    unmatched_oracle,
        "unmatched_snowflake": unmatched_snowflake,
    }


def write_mapping(
    oracle_json: Path,
    sf_json: Path,
    out: Path,
    *,
    use_cortex_llm: bool = False,
    cortex_session: Any = None,
    cortex_model: str = _DEFAULT_CORTEX_MODEL,
) -> None:
    o = json.loads(oracle_json.read_text())
    s = json.loads(sf_json.read_text())
    result = match_columns(
        o, s,
        use_cortex_llm=use_cortex_llm,
        cortex_session=cortex_session,
        cortex_model=cortex_model,
    )
    out.write_text(json.dumps(result, indent=2))
