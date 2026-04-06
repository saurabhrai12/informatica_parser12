"""IMMUTABLE — defines mapping_confidence_score."""
from __future__ import annotations

import json
from pathlib import Path

from step2_mapping.matcher import match_columns

FIXTURES = Path(__file__).parent / "tests" / "fixtures"
EXPECTED = Path(__file__).parent / "tests" / "expected"


def score() -> float:
    oracle = FIXTURES / "oracle_cols.json"
    sf = FIXTURES / "snowflake_cols.json"
    gold_path = EXPECTED / "mapping_sheet.json"
    if not (oracle.exists() and sf.exists() and gold_path.exists()):
        return 0.0
    gold = json.loads(gold_path.read_text())
    gold_pairs = {
        (m["oracle_table"], m["oracle_column"], m["snowflake_table"], m["snowflake_column"])
        for m in gold.get("mappings", [])
    }
    out = match_columns(json.loads(oracle.read_text()), json.loads(sf.read_text()))
    if not out["mappings"]:
        return 0.0
    total = 0.0
    for m in out["mappings"]:
        key = (m["oracle_table"], m["oracle_column"], m["snowflake_table"], m["snowflake_column"])
        if key in gold_pairs:
            total += m["confidence_score"]
    return total / max(len(gold_pairs), 1)


if __name__ == "__main__":
    print(f"{score():.6f}")
