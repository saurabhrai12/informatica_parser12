"""IMMUTABLE — defines lineage_coverage_score.

Reads every fixture in tests/fixtures/, compares against tests/expected/,
emits a single float to stdout. Used by the autoresearch loop.
"""
from __future__ import annotations

import json
from pathlib import Path

from step1_lineage.extractor import extract_lineage, REQUIRED_KEYS


FIELD_WEIGHTS = {
    "target_table": 3.0, "target_column": 3.0, "source_table": 2.0,
    "source_column": 2.0, "final_expression": 2.0, "load_type": 2.0,
    "transformation_sequence": 1.5, "function_mappings": 1.5,
    "lookup_table": 1.5, "lookup_condition": 1.5, "router_condition": 1.5,
    "aggregation_logic": 1.5, "migration_complexity": 1.0,
    "lineage_confidence": 1.0,
}
DEFAULT_WEIGHT = 0.5

FIXTURES = Path(__file__).parent / "tests" / "fixtures"
EXPECTED = Path(__file__).parent / "tests" / "expected"


def _key(row: dict) -> tuple:
    return (row.get("target_table"), row.get("target_column"))


def score() -> float:
    total = 0.0
    earned = 0.0
    fixtures = sorted(FIXTURES.glob("*.xml"))
    if not fixtures:
        return 0.0
    for xml in fixtures:
        gold_path = EXPECTED / f"{xml.stem}.json"
        if not gold_path.exists():
            continue
        gold = {(_key(r)): r for r in json.loads(gold_path.read_text())}
        actual = {(_key(r)): r for r in extract_lineage(xml.read_text())}
        for k, gold_row in gold.items():
            for field in REQUIRED_KEYS:
                w = FIELD_WEIGHTS.get(field, DEFAULT_WEIGHT)
                total += w
                act_row = actual.get(k)
                if act_row is not None and act_row.get(field) == gold_row.get(field):
                    earned += w
    return earned / total if total else 0.0


if __name__ == "__main__":
    print(f"{score():.6f}")
