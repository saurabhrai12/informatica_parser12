import json
from pathlib import Path
import pytest
from step1_lineage.extractor import extract_lineage, REQUIRED_KEYS

FIXTURES = Path(__file__).parent / "fixtures"


def test_empty_xml_returns_empty_list():
    assert extract_lineage("") == []


@pytest.mark.parametrize("xml_file", list(FIXTURES.glob("*.xml")))
def test_output_schema(xml_file):
    rows = extract_lineage(xml_file.read_text())
    for row in rows:
        assert set(REQUIRED_KEYS).issubset(row.keys())
