"""Skill loader — reads SKILL.md files and supports append-only updates.

Usage from an agent or run_loop:
    from skills.loader import load_skill, append_learned_pattern

    knowledge = load_skill("informatica_xml")
    append_learned_pattern("informatica_xml",
        "2026-04-09 | multi-target mapping with shared SQ | complex_chain.xml")

Autoresearch MUST only call `append_learned_pattern`; it must never overwrite
the canonical sections of a SKILL.md. The canonical sections are everything
ABOVE the `## Learned patterns` heading (or `## Learned edge cases` /
`## Learned synonym pairs`).
"""
from __future__ import annotations

from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parent

SKILL_NAMES = [
    "informatica_xml",
    "snowflake_sql_scripting",
    "oracle_to_snowflake_types",
    "column_matching",
]

# Each skill's append section heading (matches the ## line in SKILL.md).
_APPEND_HEADINGS = {
    "informatica_xml":           "## Learned patterns (append-only",
    "snowflake_sql_scripting":   "## Learned patterns (append-only",
    "oracle_to_snowflake_types": "## Learned edge cases (append-only",
    "column_matching":           "## Learned synonym pairs (append-only",
}


def skill_path(name: str) -> Path:
    if name not in SKILL_NAMES:
        raise ValueError(f"Unknown skill: {name!r}. Known: {SKILL_NAMES}")
    return SKILLS_ROOT / name / "SKILL.md"


def load_skill(name: str) -> str:
    """Return the full SKILL.md text for a given skill name."""
    return skill_path(name).read_text()


def list_skills() -> list[dict]:
    """List all skills with their metadata frontmatter."""
    out = []
    for name in SKILL_NAMES:
        text = load_skill(name)
        fm: dict[str, str] = {}
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                for line in text[3:end].strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        fm[k.strip()] = v.strip()
        out.append({"name": name, "path": str(skill_path(name)), **fm})
    return out


def append_learned_pattern(name: str, entry: str) -> None:
    """Append one line to the Learned-patterns section of a SKILL.md.

    Autoresearch may call this to persist a pattern discovered during eval.
    The canonical sections above the heading are never modified.
    """
    path = skill_path(name)
    text = path.read_text()
    heading = _APPEND_HEADINGS[name]
    idx = text.find(heading)
    if idx == -1:
        raise RuntimeError(f"{name} SKILL.md has no append-only section")
    line = entry.strip()
    if not line.startswith("<!--"):
        line = f"- {line}"
    # Ensure file ends with a newline before appending.
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + line + "\n")
