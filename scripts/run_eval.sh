#!/usr/bin/env bash
# Run all three eval metrics and print scalar scores.
set -euo pipefail
cd "$(dirname "$0")/.."
echo -n "lineage_coverage_score: "; python -m step1_lineage.eval
echo -n "mapping_confidence_score: "; python -m step2_mapping.eval
echo -n "proc_correctness_score:  "; python -m step3_procgen.eval
