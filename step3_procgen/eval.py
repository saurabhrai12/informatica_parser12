"""IMMUTABLE — defines proc_correctness_score.

score =
    sql_parse_valid     * 0.30 +
    column_name_match   * 0.25 +
    expression_accuracy * 0.25 +
    cte_coverage        * 0.10 +
    comment_coverage    * 0.10
"""
from __future__ import annotations

import json
from pathlib import Path

import sqlglot

from step3_procgen.generator import generate_proc

FIXTURES = Path(__file__).parent / "tests" / "fixtures"
EXPECTED = Path(__file__).parent / "tests" / "expected"


def _parse_ok(sql: str) -> bool:
    try:
        sqlglot.parse(sql, read="snowflake")
        return True
    except Exception:
        return False


def score() -> float:
    cases = sorted(FIXTURES.glob("*_lineage.json"))
    if not cases:
        return 0.0
    parts = []
    for lp in cases:
        mp = lp.with_name(lp.stem.replace("_lineage", "_mapping") + ".json")
        lineage = json.loads(lp.read_text())
        mapping = json.loads(mp.read_text()) if mp.exists() else {}
        sql = generate_proc(lineage, mapping)

        parse_ok = 1.0 if _parse_ok(sql) else 0.0
        target_cols = {r["target_column"] for r in lineage}
        col_match = sum(1 for c in target_cols if c and c in sql) / max(len(target_cols), 1)
        exprs = [r.get("final_expression") for r in lineage if r.get("final_expression")]
        expr_acc = (sum(1 for e in exprs if e in sql) / len(exprs)) if exprs else 1.0
        cte_cov = 1.0 if "WITH " in sql.upper() else 0.0
        comment_cov = 1.0 if "[INFA" in sql else 0.0

        parts.append(
            parse_ok * 0.30 + col_match * 0.25 + expr_acc * 0.25
            + cte_cov * 0.10 + comment_cov * 0.10
        )
    return sum(parts) / len(parts)


if __name__ == "__main__":
    print(f"{score():.6f}")
