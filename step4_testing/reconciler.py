"""Oracle vs Snowflake data reconciliation — stub.

Live implementation requires credentials in config/env.yaml. Marked
`integration` so unit-test runs skip it.
"""
from __future__ import annotations


def reconcile(table: str) -> dict:
    return {"table": table, "status": "NOT_IMPLEMENTED"}
