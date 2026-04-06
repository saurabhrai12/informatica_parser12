Goal: maximise mapping_confidence_score (target ≥ 0.88).
Metric file: step2_mapping/eval.py  →  outputs a single float to stdout.
Modifiable: step2_mapping/matcher.py, step2_mapping/synonym_dict.py

Promising directions:
  - Tune confidence weight formula
  - Levenshtein normalised by name length
  - Anchor table-level matching before column-level
  - Add domain synonyms (AML/fraud/risk)
  - Sample-data value overlap matching
  - Strip prefixes (C_CUST_ID → CUSTOMER_ID)
  - Penalise cross-table matches
  - Improve UNMATCHED classification (reduce false negatives)

Do NOT change: fixture JSON, eval.py, expected/.
Stop: score ≥ 0.88 OR 5 plateau runs.
