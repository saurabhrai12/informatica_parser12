# Project skills

These `SKILL.md` files encode static domain knowledge the agent loads **before**
it edits any modifiable `.py` file. They are the "Skills half" of the
Skills + autoresearch hybrid described in `CLAUDE.md`.

| Skill | Owner step | Loaded before editing |
|---|---|---|
| `informatica_xml` | step1_lineage | `extractor.py`, `function_map.py` |
| `column_matching` | step2_mapping | `matcher.py`, `synonym_dict.py` |
| `oracle_to_snowflake_types` | step2_mapping + step3_procgen | both |
| `snowflake_sql_scripting` | step3_procgen | `generator.py`, `templates/` |

## How they differ from autoresearch `program_*.md`

- **SKILL.md** = static knowledge, updated manually by the human or appended
  to (never rewritten) by autoresearch in dedicated "Learned patterns" sections.
- **program_\*.md** = research agenda — the list of directions autoresearch is
  allowed to try on the modifiable code.

## Autoresearch may improve skills, too

The `autoresearch/program_skills.md` agenda allows autoresearch to append new
patterns it discovers during eval runs to the "Learned patterns" sections at
the bottom of each SKILL.md. It may NOT rewrite canonical sections.

## Loading skills programmatically

```python
from skills.loader import load_skill
knowledge = load_skill("informatica_xml")   # returns SKILL.md text
```
