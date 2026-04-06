from step2_mapping.matcher import match_columns


def test_exact_match_high_confidence():
    o = [{"table": "CUST", "column": "CUST_ID", "data_type": "NUMBER"}]
    s = [{"table": "CUSTOMER", "column": "CUST_ID", "data_type": "NUMBER"}]
    out = match_columns(o, s)
    assert out["mappings"][0]["confidence_tier"] == "HIGH"


def test_unmatched_listed():
    o = [{"table": "T", "column": "ZZZ_FOO", "data_type": "NUMBER"}]
    s = [{"table": "T", "column": "BAR_QUUX", "data_type": "DATE"}]
    out = match_columns(o, s)
    assert out["unmatched_oracle"] or out["unmatched_snowflake"]
