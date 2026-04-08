Goal: grow the project's SKILL.md files with patterns discovered during
eval runs, WITHOUT degrading the three eval scores.

Modifiable files (append-only — only the "Learned patterns" section at the
bottom of each):
  - skills/informatica_xml/SKILL.md
  - skills/snowflake_sql_scripting/SKILL.md
  - skills/oracle_to_snowflake_types/SKILL.md
  - skills/column_matching/SKILL.md

Canonical sections (everything ABOVE the "Learned patterns" heading) are
FROZEN. Autoresearch must use skills.loader.append_learned_pattern(...) —
it must NOT rewrite the file with Write/Edit.

Propose → eval → keep/revert loop:
  1. Read the relevant SKILL.md and the corresponding modifiable .py file.
  2. Identify a pattern or rule the .py is missing.
  3. EITHER:
     a) append a new pattern line to SKILL.md via the loader, AND
        modify the .py to take advantage of it, OR
     b) only append to SKILL.md (safe — never affects eval score).
  4. Run all three evals:
        python -m step1_lineage.eval
        python -m step2_mapping.eval
        python -m step3_procgen.eval
  5. If the total across all three improved (or stayed flat) AND the
     specific step targeted by the change improved strictly, keep the commit.
     Otherwise revert.

Promising directions:
  - informatica_xml: record new TRANSFORMATION TYPE values found in fixtures
  - snowflake_sql_scripting: record new rewrite patterns for nested IIF
  - oracle_to_snowflake_types: record observed Oracle NUMBER precision edge cases
  - column_matching: record new domain abbreviations and synonym pairs

Stop condition: 10 consecutive iterations with no score improvement.
