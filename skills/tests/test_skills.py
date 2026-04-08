from skills.loader import SKILL_NAMES, load_skill, list_skills, append_learned_pattern, skill_path


def test_all_skills_loadable():
    for name in SKILL_NAMES:
        text = load_skill(name)
        assert len(text) > 500
        assert text.startswith("---")            # has YAML frontmatter
        assert "Learned" in text                 # has append-only section


def test_skill_metadata_includes_agent_modifiable_flag():
    meta = {s["name"]: s for s in list_skills()}
    for name in SKILL_NAMES:
        assert meta[name].get("agent_modifiable") == "true"
        assert "autoresearch" in meta[name].get("improved_by", "").lower()


def test_append_learned_pattern_roundtrip(tmp_path, monkeypatch):
    # Work on a copy so we don't dirty the real skill files.
    name = "informatica_xml"
    original = load_skill(name)
    try:
        append_learned_pattern(name, "2026-04-09 | test pattern | test_fixture.xml")
        updated = load_skill(name)
        assert updated.endswith("test_fixture.xml\n")
        assert updated.startswith(original[:200])   # canonical sections untouched
    finally:
        skill_path(name).write_text(original)
