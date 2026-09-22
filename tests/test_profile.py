import copy
import json

import pytest

import kit_profile as profile_mod


def fresh_defaults():
    return copy.deepcopy(profile_mod.DEFAULTS)


def test_given_defaults_then_valid():
    problems = profile_mod.validate(fresh_defaults())
    assert problems == []


@pytest.mark.parametrize(
    "dotted,value",
    [(dotted, value) for dotted, values in profile_mod.ENUMS.items() for value in values],
)
def test_given_every_enum_value_then_validates(dotted, value):
    prof = fresh_defaults()
    profile_mod.put(prof, dotted, value)
    problems = profile_mod.validate(prof)
    enum_problems = [p for p in problems if p.startswith(f"{dotted} must be one of")]
    assert enum_problems == [], f"{dotted}={value!r} was rejected: {enum_problems}"


def test_given_work_item_evidence_without_tracker_then_rejected():
    prof = fresh_defaults()
    prof["qa"]["evidence"] = "work-item"
    prof["tracker"] = "none"
    problems = profile_mod.validate(prof)
    assert any("qa.evidence cannot be work-item when tracker is none" in p for p in problems)


def test_given_reviewers_missing_builtin_then_migrate_restores_them():
    raw = {"reviewers": ["kit"]}
    merged, _filled = profile_mod.migrate(raw)
    assert merged["reviewers"] == list(profile_mod.BUILT_IN_REVIEWERS) + ["kit"]
    for built_in in profile_mod.BUILT_IN_REVIEWERS:
        assert built_in in merged["reviewers"]


def test_given_schema_zero_partial_file_then_migrates_with_defaults_and_reports_filled(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    partial = {"architecture": "vertical", "schema": 0}
    (claude_dir / profile_mod.FILE_NAME).write_text(json.dumps(partial), encoding="utf-8")

    resolved = profile_mod.resolve_profile(tmp_path)

    assert resolved["schema"] == profile_mod.SCHEMA
    assert resolved["architecture"] == "vertical"
    assert resolved["_source"] == str(claude_dir / profile_mod.FILE_NAME)
    assert "architecture" not in resolved["_filled"]
    assert "testing.tdd" in resolved["_filled"]
    assert "qa.owner" in resolved["_filled"]
    assert resolved["testing"]["tdd"] == profile_mod.DEFAULTS["testing"]["tdd"]


def test_given_no_file_then_defaults_resolve_with_source_defaults(tmp_path, monkeypatch):
    fake_home = tmp_path / "fake-home"
    monkeypatch.setattr(
        profile_mod,
        "profile_paths",
        lambda cwd: [tmp_path / ".claude" / profile_mod.FILE_NAME, fake_home / ".claude" / profile_mod.FILE_NAME],
    )

    resolved = profile_mod.resolve_profile(tmp_path)

    assert resolved["_source"] == "defaults"
    assert resolved["_filled"] == []
    assert resolved["architecture"] == profile_mod.DEFAULTS["architecture"]


def test_given_clean_and_vertical_then_plan_sections_differ():
    clean_sections = profile_mod.plan_sections({"architecture": "clean"})
    vertical_sections = profile_mod.plan_sections({"architecture": "vertical"})
    assert clean_sections != vertical_sections
    clean_names = [name for name, _, _ in clean_sections]
    vertical_names = [name for name, _, _ in vertical_sections]
    assert "Domain" in clean_names
    assert "Slice" in vertical_names
    assert "Domain" not in vertical_names


def test_given_clean_profile_then_needed_skills_include_clean_architecture():
    prof = fresh_defaults()
    assert prof["architecture"] == "clean"
    skills = profile_mod.needed_skills(prof)
    assert "clean-architecture" in skills


def test_given_kit_reviewer_then_needed_skills_include_four_kit_skills():
    prof = fresh_defaults()
    prof["reviewers"] = list(profile_mod.BUILT_IN_REVIEWERS) + ["kit"]
    skills = profile_mod.needed_skills(prof)
    expected = profile_mod.NEEDS[("reviewers", "kit")]
    assert len(expected) == 4
    for skill in expected:
        assert skill in skills


def test_given_defaults_then_jev_and_checks_present():
    prof = fresh_defaults()
    assert prof["optional"]["jev"] is False
    assert prof["jev"] == {"flag_at": 0.75, "review_at": 0.4}
    assert prof["checks"] == []


@pytest.mark.parametrize(
    "check,fragment",
    [
        ({"id": "a", "rule": "x", "severity": "blocker"}, "severity must be one of"),
        ({"id": "Bad Id", "rule": "x", "severity": "high"}, "id must match"),
        ({"id": "a", "rule": "  ", "severity": "high"}, "rule must be non-empty"),
        ({"id": "a", "rule": "x", "severity": "high", "glob": "*.cs"}, "unknown keys glob"),
        ({"id": "a", "rule": "x", "severity": "high", "files": ""}, "files must be a glob"),
        ("not an object", "must be an object"),
    ],
)
def test_given_bad_check_then_rejected(check, fragment):
    prof = fresh_defaults()
    prof["checks"] = [check]
    problems = profile_mod.validate(prof)
    assert any(fragment in p for p in problems), problems


def test_given_duplicate_check_ids_then_rejected():
    prof = fresh_defaults()
    prof["checks"] = [{"id": "a", "rule": "x", "severity": "high"}, {"id": "a", "rule": "y", "severity": "low"}]
    assert any("duplicate id 'a'" in p for p in profile_mod.validate(prof))


def test_given_valid_checks_then_enabled_checks_defaults_files():
    prof = fresh_defaults()
    prof["checks"] = [
        {"id": "ct", "rule": " Propagate CancellationToken ", "severity": "high"},
        {"id": "now", "rule": "No DateTime.Now", "severity": "medium", "files": "src/**/*.cs"},
    ]
    assert profile_mod.validate(prof) == []
    checks = profile_mod.enabled_checks(prof)
    assert checks[0] == {"id": "ct", "rule": "Propagate CancellationToken", "severity": "high", "files": "**/*"}
    assert checks[1]["files"] == "src/**/*.cs"


@pytest.mark.parametrize(
    "jev,fragment",
    [
        ({"flag_at": 1.5, "review_at": 0.4}, "jev.flag_at must be a number"),
        ({"flag_at": 0.5, "review_at": 0.6}, "review_at must not exceed"),
        ({"flag_at": True, "review_at": 0.4}, "jev.flag_at must be a number"),
        ("x", "jev must be an object"),
    ],
)
def test_given_bad_jev_thresholds_then_rejected(jev, fragment):
    prof = fresh_defaults()
    prof["jev"] = jev
    assert any(fragment in p for p in profile_mod.validate(prof))


def test_given_frontend_none_then_no_optional_sections():
    prof = fresh_defaults()
    assert profile_mod.optional_plan_sections(prof) == []
    names = [n for n, _, _ in profile_mod.expected_plan_sections(prof, ["Designs"])]
    assert "Designs" not in names


def test_given_frontend_blazor_and_designs_present_then_slotted_after_specs():
    prof = fresh_defaults()
    prof["stack"]["frontend"] = "blazor"
    names = [n for n, _, _ in profile_mod.expected_plan_sections(prof, ["Specs", "Designs"])]
    assert names.index("Designs") == names.index("Specs") + 1
    assert names[-1] == "Open questions"


def test_given_frontend_blazor_and_designs_absent_then_sections_unchanged():
    prof = fresh_defaults()
    prof["stack"]["frontend"] = "blazor"
    assert profile_mod.expected_plan_sections(prof, ["Specs"]) == list(profile_mod.plan_sections(prof))
