"""End-to-end orchestrator for the Oracle → Snowflake migration pipeline.

Usage:
    python pipeline.py --mapping CUST_DIM_LOAD --dry-run
    python pipeline.py --all --dry-run
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from step1_lineage.extractor import extract_lineage
from step2_mapping.matcher import match_columns
from step3_procgen.generator import generate_proc

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
FIX1 = ROOT / "step1_lineage" / "tests" / "fixtures"
FIX2 = ROOT / "step2_mapping" / "tests" / "fixtures"


def run_one(mapping: str, dry_run: bool) -> None:
    OUT.mkdir(exist_ok=True)
    xml = FIX1 / f"{mapping}.xml"
    if not xml.exists():
        # Fall back to first available fixture for demo runs.
        xml = next(FIX1.glob("*.xml"))
    lineage = extract_lineage(xml.read_text())
    (OUT / f"{mapping}_lineage.json").write_text(json.dumps(lineage, indent=2))

    oracle = json.loads((FIX2 / "oracle_cols.json").read_text())
    sf = json.loads((FIX2 / "snowflake_cols.json").read_text())
    mapping_sheet = match_columns(oracle, sf)
    (OUT / f"{mapping}_mapping_sheet.json").write_text(json.dumps(mapping_sheet, indent=2))

    proc_sql = generate_proc(lineage, mapping_sheet)
    (OUT / f"{mapping}_proc.sql").write_text(proc_sql)
    print(f"[{mapping}] dry_run={dry_run}  → outputs/{mapping}_*.{{json,sql}}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mapping")
    p.add_argument("--all", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--deploy", action="store_true")
    args = p.parse_args()

    if args.all:
        for xml in FIX1.glob("*.xml"):
            run_one(xml.stem, args.dry_run)
    elif args.mapping:
        run_one(args.mapping, args.dry_run)
    else:
        p.error("either --mapping or --all required")


if __name__ == "__main__":
    main()
