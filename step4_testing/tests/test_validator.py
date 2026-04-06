from step4_testing.validator import row_count_match, null_rate_within_5pct


def test_row_count_match_within_tolerance():
    assert row_count_match(10000, 10001).passed


def test_row_count_match_out_of_tolerance():
    assert not row_count_match(10000, 9000).passed


def test_null_rate_within_5pct():
    assert null_rate_within_5pct(0.10, 0.12).passed
    assert not null_rate_within_5pct(0.10, 0.20).passed
