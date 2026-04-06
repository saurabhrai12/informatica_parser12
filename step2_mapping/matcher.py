"""Oracle ↔ Snowflake column mapping sheet generator.

Implements the 14-strategy matching methodology from mapping_identification.txt.
Agent-modifiable. Goal: maximise mapping_confidence_score from eval.py.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .synonym_dict import expand, synonyms_of


HIGH, MED, LOW = 0.90, 0.65, 0.40


def _normalise(name: str) -> str:
    n = re.sub(r"[^A-Z0-9]", "_", name.upper())
    parts = [expand(p) for p in n.split("_") if p]
    return "_".join(parts)


def _name_score(o: str, s: str) -> tuple[float, str]:
    if o.upper() == s.upper():
        return 1.0, "EXACT"
    no, ns = _normalise(o), _normalise(s)
    if no == ns:
        return 0.93, "NORMALISED"
    if ns in synonyms_of(o) or no in synonyms_of(s):
        return 0.80, "SEMANTIC"  # capped per spec
    ratio = SequenceMatcher(None, no, ns).ratio()
    if ratio >= 0.85:
        return 0.85 * ratio, "ABBREVIATION"
    return ratio * 0.6, "INFERRED"


_TYPE_FAMILIES = {
    "NUMBER": {"NUMBER", "INTEGER", "BIGINT", "DECIMAL", "FLOAT", "NUMERIC"},
    "STRING": {"VARCHAR", "VARCHAR2", "CHAR", "TEXT", "STRING", "CLOB"},
    "DATE":   {"DATE", "TIMESTAMP", "TIMESTAMP_NTZ", "TIMESTAMP_LTZ"},
    "BINARY": {"RAW", "BLOB", "BINARY"},
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
    return _type_family(o_type) == _type_family(s_type)


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
    """Score similarity between two table names (0-1). Exact wins; abbreviation expansion applied."""
    if o_table.upper() == s_table.upper():
        return 1.0
    no, ns = _normalise(o_table), _normalise(s_table)
    if no == ns:
        return 0.95
    ratio = SequenceMatcher(None, no, ns).ratio()
    return ratio


def _comment_boost(oc: dict, sc: dict) -> float:
    """+0.05 boost if oracle comment keywords appear in snowflake column name or comment."""
    oc_comment = (oc.get("comment") or "").upper()
    sc_name = sc.get("column", "").upper()
    sc_comment = (sc.get("comment") or "").upper()
    if not oc_comment:
        return 0.0
    # extract significant words from oracle comment
    words = set(re.findall(r"[A-Z]{3,}", oc_comment))
    target = sc_name + " " + sc_comment
    if any(w in target for w in words):
        return 0.05
    return 0.0


def match_columns(oracle_cols: list[dict], snowflake_cols: list[dict]) -> dict[str, Any]:
    """Return {mappings: [...], unmatched_oracle: [...], unmatched_snowflake: []}

    Strategy:
    1. Group cols by table on both sides.
    2. For each oracle col, score all snowflake cols but apply a SAME-TABLE BONUS
       (+0.10) when the table names match and a CROSS-TABLE PENALTY (-0.20) when they differ.
    3. This ensures columns like CUST_ID in TXN_FACT map to CUSTOMER_ID in TXN_FACT,
       not CUSTOMER_DIM.CUSTOMER_ID.
    """
    matched_sf: set[tuple] = set()
    mappings: list[dict] = []

    for oc in oracle_cols:
        best = None
        best_score = 0.0
        best_type = "INFERRED"

        for sc in snowflake_cols:
            score, mtype = _name_score(oc["column"], sc["column"])

            # Table-anchor modifier
            tbl_sim = _table_name_score(oc.get("table", ""), sc.get("table", ""))
            if tbl_sim >= 0.90:
                score = min(1.0, score + 0.10)   # same-table bonus
            elif tbl_sim < 0.60:
                score -= 0.20                     # cross-table penalty

            # Type compatibility modifier
            if _type_compatible(oc.get("data_type"), sc.get("data_type")):
                score = min(1.0, score + 0.05)
            else:
                score -= 0.10

            # Comment semantic boost
            score = min(1.0, score + _comment_boost(oc, sc))

            if score > best_score:
                best, best_score, best_type = sc, score, mtype

        if best is None or best_score < LOW:
            continue

        matched_sf.add((best["table"], best["column"]))
        mappings.append({
            "oracle_table": oc["table"],
            "oracle_column": oc["column"],
            "oracle_data_type": oc.get("data_type"),
            "oracle_nullable": oc.get("nullable"),
            "oracle_pk_flag": oc.get("pk", False),
            "snowflake_table": best["table"],
            "snowflake_column": best["column"],
            "snowflake_data_type": best.get("data_type"),
            "snowflake_nullable": best.get("nullable"),
            "snowflake_pk_flag": best.get("pk", False),
            "match_type": best_type,
            "confidence_score": round(min(best_score, 1.0), 4),
            "confidence_tier": _tier(min(best_score, 1.0)),
            "match_basis": f"name_score={best_score:.2f} via {best_type}; "
                           f"table_sim={_table_name_score(oc.get('table',''), best.get('table','')):.2f}",
            "type_compatible": _type_compatible(oc.get("data_type"), best.get("data_type")),
            "suggested_cast": _suggested_cast(oc.get("data_type"), best.get("data_type")),
            "transform_hint": None,
            "unmatched_reason": None,
            "recommended_action": "MAP" if best_score >= MED else "INVESTIGATE",
        })

    matched_oracle = {(m["oracle_table"], m["oracle_column"]) for m in mappings}
    unmatched_oracle = [
        {"oracle_table": c["table"], "oracle_column": c["column"],
         "reason": "no candidate above LOW threshold", "action": "INVESTIGATE"}
        for c in oracle_cols if (c["table"], c["column"]) not in matched_oracle
    ]
    unmatched_snowflake = [
        {"snowflake_table": c["table"], "snowflake_column": c["column"],
         "reason": "no oracle counterpart matched", "action": "INVESTIGATE"}
        for c in snowflake_cols if (c["table"], c["column"]) not in matched_sf
    ]
    return {
        "mappings": mappings,
        "unmatched_oracle": unmatched_oracle,
        "unmatched_snowflake": unmatched_snowflake,
    }


def write_mapping(oracle_json: Path, sf_json: Path, out: Path) -> None:
    o = json.loads(oracle_json.read_text())
    s = json.loads(sf_json.read_text())
    out.write_text(json.dumps(match_columns(o, s), indent=2))
