Goal: maximise mapping_confidence_score (target ≥ 0.88).
Metric file: step2_mapping/eval.py  →  outputs a single float to stdout.
Modifiable: step2_mapping/matcher.py, step2_mapping/synonym_dict.py

## Promising directions

### Rule-based improvements (no Snowflake session required)
  - Tune confidence weight formula (currently equal-weight strategies)
  - Add Levenshtein distance normalised by column name length
  - Improve table-level matching before column-level (anchor to table first)
  - Add domain-specific synonym pairs for financial crime (AML, fraud, risk)
  - Improve enum/code set matching using sample data value overlap
  - Handle prefixed column names (e.g. C_CUST_ID → CUSTOMER_ID)
  - Penalise cross-table matches more aggressively
  - Improve UNMATCHED classification to reduce false negatives
  - Add more abbreviations to synonym_dict.ABBREV (check for patterns in eval misses)
  - Improve comment keyword extraction (noun phrase extraction vs bag-of-words)

### Strategy 15 — Snowflake Cortex Complete LLM (requires live session)
  - Enable via: match_columns(..., use_cortex_llm=True, cortex_session=<session>)
  - Or env-var: CORTEX_ENABLED=1
  - Configured in config/env.yaml under cortex_llm:
      enabled: true
      model: mistral-7b     # or llama3-8b / mixtral-8x7b / llama3-70b
      top_n_candidates: 8
  - Design:
      * One CORTEX.COMPLETE call per Oracle column (not per pair) — batches candidates
      * Prompt asks LLM to pick the best Snowflake candidate + assign confidence 0-1
      * Solo cap: 0.82 (LLM-only, no rule-based corroboration)
      * Corroboration lift: if LLM and rule-based agree on same column → +0.05 bonus
      * Same table-anchor and type-compat modifiers applied to Cortex score
      * Falls back silently if no session (unit tests continue to pass)
  - Cortex research directions:
      * Test different models (mistral-7b vs llama3-70b) on the eval fixture
      * Tune prompt: few-shot examples improve abbreviation expansion accuracy
      * Add column comment and table context to the prompt
      * Try chain-of-thought: ask the model to explain its reasoning first
      * Evaluate cost vs. accuracy trade-off across model sizes

Do NOT change: fixture JSON files, eval.py, expected/ golden outputs.
Stop condition: score ≥ 0.88 OR 5 consecutive runs with no improvement.
