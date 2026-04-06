"""Informatica PowerCenter XML → field-level lineage JSON.

Agent-modifiable. Goal: maximise lineage_coverage_score from eval.py.
See CLAUDE.md §"Step 1 — Informatica lineage extraction" for the output contract.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lxml import etree

from .function_map import INFA_TO_SF


REQUIRED_KEYS = [
    "mapping_name", "source_table", "source_schema", "source_column",
    "source_datatype", "source_length", "source_nullable", "source_pk_flag",
    "source_filter", "transformation_sequence", "final_expression",
    "pass_through", "default_value", "null_handling", "type_cast",
    "function_mappings", "lookup_table", "lookup_condition",
    "aggregation_logic", "join_condition", "router_condition",
    "sorter_logic", "sq_override_sql", "target_table", "target_schema",
    "target_column", "target_datatype", "load_type", "update_override_sql",
    "target_pk_flag", "truncate_before_load", "reject_handling",
    "lineage_confidence", "ambiguity_notes", "migration_complexity",
]


def _empty_row() -> dict[str, Any]:
    return {k: None for k in REQUIRED_KEYS} | {
        "transformation_sequence": [],
        "function_mappings": [],
        "pass_through": False,
        "source_nullable": True,
        "source_pk_flag": False,
        "target_pk_flag": False,
        "truncate_before_load": False,
        "lineage_confidence": "MEDIUM",
        "migration_complexity": "SIMPLE",
        "load_type": "INSERT",
    }


# ─────────────────────────────────────────────
# Helper: extract function mappings from expression
# ─────────────────────────────────────────────
_INFA_FN_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in INFA_TO_SF) + r')\s*\(',
    re.IGNORECASE,
)

def _extract_function_mappings(expression: str | None) -> list[dict]:
    if not expression:
        return []
    seen = set()
    result = []
    for m in _INFA_FN_PATTERN.finditer(expression):
        fn = m.group(1).upper()
        if fn not in seen:
            seen.add(fn)
            result.append({
                "infa_fn": fn,
                "sf_fn": INFA_TO_SF.get(fn, fn),
                "notes": None,
            })
    return result


def _null_handling(expression: str | None) -> str | None:
    if not expression:
        return None
    if re.search(r'\bNVL\s*\(', expression, re.I):
        return "NVL"
    return None


def _type_cast(expression: str | None) -> str | None:
    if not expression:
        return None
    for fn in ("TO_DATE", "TO_CHAR", "TO_NUMBER", "CAST"):
        if re.search(rf'\b{fn}\s*\(', expression, re.I):
            return fn
    return None


def _complexity(expr: str | None, seq: list[str]) -> str:
    """Infer migration_complexity from transformation chain length and expression content."""
    complex_transforms = {"Lookup Procedure", "Router", "Joiner", "Aggregator"}
    if any(t in seq for t in complex_transforms):
        return "COMPLEX"
    if expr and any(fn in expr.upper() for fn in ("IIF", "DECODE", "NVL2", "ADD_TO_DATE", "DATE_DIFF")):
        return "MODERATE"
    if expr and any(fn in expr.upper() for fn in ("NVL", "UPPER", "LOWER", "LTRIM", "RTRIM",
                                                    "SUBSTR", "TO_DATE", "TO_CHAR", "TRUNC")):
        return "MODERATE"
    if expr and expr.strip() not in (None, ""):
        # has some expression but nothing complex
        return "SIMPLE"
    return "SIMPLE"


def _get_tableattr(elem: etree._Element, name: str) -> str | None:
    """Return VALUE of first TABLEATTRIBUTE with matching NAME (case-insensitive)."""
    for ta in elem.findall("TABLEATTRIBUTE"):
        if (ta.get("NAME") or "").lower() == name.lower():
            val = ta.get("VALUE") or ""
            # unescape XML entities that lxml already handles, clean newline entities
            val = val.replace("&#10;", "\n").replace("&#13;", "\r").strip()
            return val if val else None
    return None


def _parse_source_field(sf_elem: etree._Element) -> dict:
    ktype = (sf_elem.get("KEYTYPE") or "").upper()
    nullable_attr = (sf_elem.get("NULLABLE") or "").upper()
    return {
        "datatype": sf_elem.get("DATATYPE"),
        "length": _int(sf_elem.get("LENGTH")),
        "nullable": nullable_attr != "NOT NULL",
        "pk": "PRIMARY KEY" in ktype,
    }


def _int(v: str | None) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────
# Main extractor
# ─────────────────────────────────────────────

def extract_lineage(xml_text: str) -> list[dict[str, Any]]:
    """Parse an Informatica mapping XML and return a list of lineage rows."""
    if not xml_text.strip():
        return []

    try:
        root = etree.fromstring(xml_text.encode("utf-8"))
    except etree.XMLSyntaxError:
        return []

    rows: list[dict[str, Any]] = []

    for mapping in root.iter("MAPPING"):
        mapping_name = mapping.get("NAME", "UNKNOWN")

        # ── Collect sources and their fields ──────────────────────────────
        sources: dict[str, etree._Element] = {
            s.get("NAME"): s for s in mapping.iter("SOURCE")
        }
        source_fields: dict[str, dict[str, dict]] = {}
        for sname, selem in sources.items():
            source_fields[sname] = {
                f.get("NAME"): _parse_source_field(f)
                for f in selem.iter("SOURCEFIELD")
            }

        # ── Collect targets ───────────────────────────────────────────────
        targets: dict[str, etree._Element] = {
            t.get("NAME"): t for t in mapping.iter("TARGET")
        }

        # ── Collect transformations ───────────────────────────────────────
        transforms: dict[str, etree._Element] = {
            t.get("NAME"): t for t in mapping.iter("TRANSFORMATION")
        }

        # ── Map Source Qualifier transform → backing source table ─────────
        # Strategy: for each SQ transform, collect its port names and find
        # which SOURCE element has the highest field-name overlap.
        sq_to_source: dict[str, str] = {}   # SQ_name → source_table_name
        for t in mapping.iter("TRANSFORMATION"):
            if t.get("TYPE") != "Source Qualifier":
                continue
            sq_name = t.get("NAME", "")
            sq_ports = {tf.get("NAME") for tf in t.iter("TRANSFORMFIELD")}
            best_src, best_overlap = None, 0
            for sname, sfields in source_fields.items():
                overlap = len(sq_ports & set(sfields.keys()))
                if overlap > best_overlap:
                    best_src, best_overlap = sname, overlap
            if best_src:
                sq_to_source[sq_name] = best_src

        # ── Collect TARGETINSTANCE attributes (load strategy) ─────────────
        ti_map: dict[str, dict] = {}
        for ti in mapping.iter("TARGETINSTANCE"):
            tname = ti.get("NAME", "")
            truncate = (ti.get("TRUNCATETARGET") or "").upper() == "YES"
            strategy = (ti.get("UPDATESTRATEGY") or "").upper()
            if "DD_INSERT" in strategy and "DD_UPDATE" in strategy:
                ltype = "UPSERT"
            elif "DD_DELETE" in strategy:
                ltype = "DELETE"
            else:
                ltype = "INSERT"
            ti_map[tname] = {"truncate": truncate, "load_type": ltype}

        # ── Build CONNECTOR graph: (from_transform, from_field) → [(to_transform, to_field)] ──
        conn_fwd: dict[tuple, list[tuple]] = {}
        for conn in mapping.iter("CONNECTOR"):
            key = (conn.get("FROMTRANSFORMATION"), conn.get("FROMFIELD"))
            conn_fwd.setdefault(key, []).append(
                (conn.get("TOTRANSFORMATION"), conn.get("TOFIELD"))
            )

        # ── Reverse map: (to_transform, to_field) → (from_transform, from_field) ──
        conn_bwd: dict[tuple, tuple] = {}
        for conn in mapping.iter("CONNECTOR"):
            key = (conn.get("TOTRANSFORMATION"), conn.get("TOFIELD"))
            conn_bwd[key] = (conn.get("FROMTRANSFORMATION"), conn.get("FROMFIELD"))

        # ── Extract Router group conditions ───────────────────────────────
        router_groups: dict[str, list[dict]] = {}  # transform_name → [{name, condition}]
        for t in mapping.iter("TRANSFORMATION"):
            if t.get("TYPE") != "Router":
                continue
            tname = t.get("NAME", "")
            attrs = list(t.findall("TABLEATTRIBUTE"))
            groups = []
            i = 0
            while i < len(attrs):
                if (attrs[i].get("NAME") or "").upper() == "GROUP NAME":
                    gname = attrs[i].get("VALUE", "")
                    gcond = None
                    if i + 1 < len(attrs) and (attrs[i+1].get("NAME") or "").upper() == "GROUP FILTER CONDITION":
                        gcond = attrs[i+1].get("VALUE", "")
                        i += 1
                    groups.append({"name": gname, "condition": gcond})
                i += 1
            router_groups[tname] = groups

        # ── Trace lineage backwards from each target field ─────────────────
        def _trace_back(target_name: str, target_field: str) -> dict:
            """Walk backwards through CONNECTORs to find the source and expression chain."""
            seq: list[str] = []
            expr: str | None = None
            current = (target_name, target_field)
            visited = set()
            router_cond: str | None = None
            join_cond: str | None = None
            agg_logic: str | None = None
            lkp_table: str | None = None
            lkp_cond: str | None = None
            sq_sql: str | None = None

            while current in conn_bwd:
                if current in visited:
                    break
                visited.add(current)
                prev = conn_bwd[current]
                from_transform, from_field = prev

                t_elem = transforms.get(from_transform)
                t_type = t_elem.get("TYPE") if t_elem is not None else ""

                # Track sequence (prepend to keep order source→target)
                if from_transform and from_transform not in seq:
                    seq.insert(0, from_transform)

                # ── Source Qualifier ──────────────────────────────────────
                if t_type == "Source Qualifier":
                    raw_sql = _get_tableattr(t_elem, "Sql Query")
                    if raw_sql:
                        sq_sql = raw_sql

                # ── Expression transformation ─────────────────────────────
                elif t_type == "Expression":
                    for tf in t_elem.iter("TRANSFORMFIELD"):
                        if tf.get("NAME") == from_field or tf.get("NAME") == current[1]:
                            candidate = tf.get("EXPRESSION")
                            if candidate and candidate != from_field:
                                expr = candidate
                            break

                # ── Lookup ────────────────────────────────────────────────
                elif t_type == "Lookup Procedure":
                    lkp_table = _get_tableattr(t_elem, "Lookup table name")
                    lkp_cond = _get_tableattr(t_elem, "Lookup condition")
                    # check if the port itself has an expression
                    for tf in t_elem.iter("TRANSFORMFIELD"):
                        if tf.get("NAME") == from_field:
                            e = tf.get("EXPRESSION")
                            if e:
                                expr = e
                            break

                # ── Aggregator ────────────────────────────────────────────
                elif t_type == "Aggregator":
                    for tf in t_elem.iter("TRANSFORMFIELD"):
                        if tf.get("NAME") == from_field:
                            e = tf.get("EXPRESSION")
                            gb = (tf.get("GROUPBY") or "").upper() == "YES"
                            if e:
                                expr = e
                                agg_logic = f"GROUP BY {e}" if gb else e
                            break

                # ── Router ────────────────────────────────────────────────
                elif t_type == "Router":
                    # condition is set per-row (from FROMGROUP attribute on the connector)
                    pass  # handled separately per row via FROMGROUP

                # ── Joiner ────────────────────────────────────────────────
                elif t_type == "Joiner":
                    join_cond = _get_tableattr(t_elem, "Join Condition")

                current = prev

            # current is now the first node — check if it's a Source
            src_name = current[0] if current else None
            src_field_name = current[1] if current else None

            return {
                "seq": seq,
                "expr": expr,
                "router_condition": router_cond,
                "join_condition": join_cond,
                "aggregation_logic": agg_logic,
                "lookup_table": lkp_table,
                "lookup_condition": lkp_cond,
                "sq_override_sql": sq_sql,
                "src_transform": src_name,
                "src_field": src_field_name,
            }

        # ── Find FROMGROUP on connectors going INTO each target ────────────
        # Maps (target_name, target_field) → router_group_name
        target_groups: dict[tuple, str] = {}
        for conn in mapping.iter("CONNECTOR"):
            to_t = conn.get("TOTRANSFORMATION")
            to_f = conn.get("TOFIELD")
            fg = conn.get("FROMGROUP")
            if fg and to_t in targets:
                target_groups[(to_t, to_f)] = fg

        # ── Find which Router transformer feeds each target ────────────────
        # We need to map target → (router_transform, group_name)
        router_feeding_target: dict[str, tuple[str, str]] = {}
        # A connector from ROUTER to TARGET with a FROMGROUP attribute
        for conn in mapping.iter("CONNECTOR"):
            fg = conn.get("FROMGROUP")
            if fg:
                from_t = conn.get("FROMTRANSFORMATION")
                to_t = conn.get("TOTRANSFORMATION")
                if to_t in targets and from_t in transforms:
                    if transforms[from_t].get("TYPE") == "Router":
                        router_feeding_target[to_t] = (from_t, fg)

        # ── Build rows ────────────────────────────────────────────────────
        for tname, telem in targets.items():
            target_schema = telem.get("DATABASETYPE", "")
            ti = ti_map.get(tname, {})
            is_truncate = ti.get("truncate", False)
            load_type = ti.get("load_type", "INSERT")

            # Does a Router route to this target?
            rtr_info = router_feeding_target.get(tname)  # (router_name, group_name)

            for tfield in telem.iter("TARGETFIELD"):
                tf_name = tfield.get("NAME")
                tf_type = tfield.get("DATATYPE")
                tf_pk = ("PRIMARY KEY" in (tfield.get("KEYTYPE") or "").upper())

                # Trace backwards
                trace = _trace_back(tname, tf_name)

                # Collect router condition for this row
                row_router_cond = None
                if rtr_info:
                    rtr_transform_name, rtr_group_name = rtr_info
                    # look up condition for this group in this router
                    for g in router_groups.get(rtr_transform_name, []):
                        if g["name"] == rtr_group_name:
                            row_router_cond = g["condition"]
                            break

                # Resolve source info
                src_transform = trace["src_transform"]
                src_field_name = trace["src_field"]
                source_table: str | None = None
                source_schema: str | None = None
                source_col: str | None = None
                source_dtype: str | None = None
                source_len: int | None = None
                source_nullable: bool = True
                source_pk: bool = False

                # Resolve src_transform: may be a direct SOURCE or a Source Qualifier
                resolved_src: str | None = None
                if src_transform and src_transform in sources:
                    resolved_src = src_transform         # direct source match
                elif src_transform and src_transform in sq_to_source:
                    resolved_src = sq_to_source[src_transform]  # SQ → source

                if resolved_src and resolved_src in sources:
                    selem = sources[resolved_src]
                    source_table = resolved_src
                    source_schema = selem.get("DATABASETYPE", "")
                    # src_field_name is what comes OUT of the SQ (original source col name)
                    lookup_field = src_field_name
                    sfields = source_fields.get(resolved_src, {})
                    if lookup_field and lookup_field in sfields:
                        sf_info = sfields[lookup_field]
                        source_col = lookup_field
                        source_dtype = sf_info["datatype"]
                        source_len = sf_info["length"]
                        source_nullable = sf_info["nullable"]
                        source_pk = sf_info["pk"]
                    else:
                        # Fall back: scan all source fields for best match
                        for fname, sf_info in sfields.items():
                            source_col = fname
                            source_dtype = sf_info["datatype"]
                            source_len   = sf_info["length"]
                            source_nullable = sf_info["nullable"]
                            source_pk = sf_info["pk"]
                            break  # take first if no match
                else:
                    # Last resort: match target col name against any source field
                    for sname2, sfields in source_fields.items():
                        if tf_name in sfields:
                            source_table = sname2
                            source_schema = sources[sname2].get("DATABASETYPE", "")
                            sf_info = sfields[tf_name]
                            source_col = tf_name
                            source_dtype = sf_info["datatype"]
                            source_len   = sf_info["length"]
                            source_nullable = sf_info["nullable"]
                            source_pk = sf_info["pk"]
                            break

                expr = trace["expr"]
                seq = trace["seq"]

                # Pass-through: expression is same as source col name or None
                is_pass_through = (
                    source_col is not None and
                    (expr is None or expr.strip() == (source_col or "").strip())
                )

                # Confidence
                if source_col and expr:
                    confidence = "HIGH"
                elif source_col:
                    confidence = "HIGH"
                elif expr:
                    confidence = "MEDIUM"
                else:
                    confidence = "MEDIUM"

                # Override confidence for lookup-derived fields
                if trace["lookup_table"]:
                    confidence = "MEDIUM"

                row = _empty_row()
                row.update({
                    "mapping_name": mapping_name,
                    "source_table": source_table,
                    "source_schema": source_schema,
                    "source_column": source_col,
                    "source_datatype": source_dtype,
                    "source_length": source_len,
                    "source_nullable": source_nullable,
                    "source_pk_flag": source_pk,
                    "transformation_sequence": seq,
                    "final_expression": expr,
                    "pass_through": is_pass_through,
                    "null_handling": _null_handling(expr),
                    "type_cast": _type_cast(expr),
                    "function_mappings": _extract_function_mappings(expr),
                    "lookup_table": trace["lookup_table"],
                    "lookup_condition": trace["lookup_condition"],
                    "aggregation_logic": trace["aggregation_logic"],
                    "join_condition": trace["join_condition"],
                    "router_condition": row_router_cond,
                    "sq_override_sql": trace["sq_override_sql"],
                    "target_table": tname,
                    "target_schema": target_schema,
                    "target_column": tf_name,
                    "target_datatype": tf_type,
                    "load_type": load_type,
                    "target_pk_flag": tf_pk,
                    "truncate_before_load": is_truncate,
                    "lineage_confidence": confidence,
                    "migration_complexity": _complexity(expr, seq),
                })
                rows.append(row)

    return rows


def write_lineage(xml_path: Path, out_path: Path) -> None:
    rows = extract_lineage(xml_path.read_text())
    out_path.write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(extract_lineage(Path(sys.argv[1]).read_text()), indent=2))
