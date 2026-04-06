"""Migration validation harness — row count, hash, null-rate, sample checks.

These checks run AFTER procs are deployed to a Snowflake test schema.
Live DB connections are guarded behind the `integration` pytest marker.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


CHECK_NAMES = [
    "row_count_match",
    "pk_uniqueness",
    "null_rate_within_5pct",
    "numeric_sum_match",
    "date_range_match",
    "sample_row_hash_match",
    "enum_value_coverage",
    "audit_log_populated",
    "no_error_log_entries",
]


def row_count_match(src: int, tgt: int, tol: float = 0.001) -> CheckResult:
    if src == 0:
        return CheckResult("row_count_match", tgt == 0, f"src=0 tgt={tgt}")
    delta = abs(src - tgt) / src
    return CheckResult("row_count_match", delta < tol, f"src={src} tgt={tgt} delta={delta:.4%}")


def null_rate_within_5pct(src_pct: float, tgt_pct: float) -> CheckResult:
    return CheckResult(
        "null_rate_within_5pct",
        abs(src_pct - tgt_pct) <= 0.05,
        f"src={src_pct:.2%} tgt={tgt_pct:.2%}",
    )
