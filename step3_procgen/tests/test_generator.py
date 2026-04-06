import json
from pathlib import Path
from step3_procgen.generator import generate_proc

FIX = Path(__file__).parent / "fixtures"


def test_generates_sql_language_proc():
    lineage = json.loads((FIX / "cust_dim_lineage.json").read_text())
    sql = generate_proc(lineage, {})
    assert "LANGUAGE SQL" in sql
    assert "RETURNS VARCHAR" in sql
    assert "MIGRATION_AUDIT_LOG" in sql
    assert "MIGRATION_ERROR_LOG" in sql
    assert "FAILED_SQL" in sql
