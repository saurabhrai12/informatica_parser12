Goal: maximise lineage_coverage_score (target ≥ 0.92).
Metric file: step1_lineage/eval.py  →  outputs a single float to stdout.
Modifiable: step1_lineage/extractor.py, step1_lineage/function_map.py

Promising directions:
  - Improve XPath traversal for deeply nested transformation chains
  - Detect connected vs unconnected lookups
  - Handle Router multi-group extraction (one row per group)
  - Separate aggregator group-by from aggregate expressions
  - Extend function_map.py with date arithmetic patterns
  - Multi-line SQ override SQL with subqueries
  - Flag NORMALIZER patterns as COMPLEX
  - Improve port-to-port wiring confidence

Do NOT change: XML fixtures, eval.py, expected/.
Stop: score ≥ 0.92 OR 5 consecutive runs with no improvement.
