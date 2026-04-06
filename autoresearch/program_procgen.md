Goal: maximise proc_correctness_score (target ≥ 0.90).
Metric file: step3_procgen/eval.py  →  outputs a single float to stdout.
Modifiable: step3_procgen/generator.py, step3_procgen/templates/

Constraints (NON-NEGOTIABLE):
  - Procs MUST be LANGUAGE SQL with BEGIN…END (per proc_generater.txt)
  - RETURNS VARCHAR
  - Required params: P_WATERMARK_FROM, P_WATERMARK_TO, P_BATCH_ID, P_BATCH_SIZE, P_DRY_RUN
  - Error log inserts MUST include FAILED_SQL column
  - Audit log inserts MUST include all required columns

Promising directions:
  - CTE naming mirrors Informatica component names
  - Multi-target mappings → one proc per target
  - Infer MERGE keys from lineage PK flags
  - DD_INSERT vs UPSERT vs Truncate+Reload routing
  - Translate nested IIF chains
  - Fully-qualified DB.SCHEMA.TABLE refs everywhere
  - DRY_RUN guard around all DML
  - TODO comments for MEDIUM/LOW confidence
  - Router groups → separate INSERT statements

Do NOT change: fixture JSON, eval.py, expected/.
Stop: score ≥ 0.90 OR 5 plateau runs.
