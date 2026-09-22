import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from conftest import SETUP_PY, import_module_from_path, run_py

KIT_PLUGIN = "dotnet-claude-kit"


def minimal_path_env(tmp_path):
    """A PATH with the python interpreter and OS essentials, but no claude/az/gh.

    On POSIX /usr/bin often carries az and gh (GitHub runners do), so instead of adding
    it wholesale the test links only the tools setup needs into a private bin folder.
    """
    python_dir = str(Path(sys.executable).resolve().parent)
    parts = [python_dir]
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        parts += [os.path.join(system_root, "System32"), system_root]
    else:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        for tool in ("sh", "git", "env", "uname"):
            found = shutil.which(tool)
            if found and not (bin_dir / tool).exists():
                (bin_dir / tool).symlink_to(found)
        parts.append(str(bin_dir))
    return os.pathsep.join(parts)


def run_setup(tmp_path, *args, home=None, cwd=None, input=None):
    env = {
        "PATH": minimal_path_env(tmp_path),
        "HOME": str(home or tmp_path),
        "USERPROFILE": str(home or tmp_path),
    }
    return run_py(SETUP_PY, *args, cwd=cwd or tmp_path, env=env, input=input)


def write_answers(tmp_path, answers, name="answers.json"):
    path = tmp_path / name
    path.write_text(json.dumps(answers), encoding="utf-8")
    return path


def project_profile_path(cwd):
    return Path(cwd) / ".claude" / "dotnet-workflow-kit.json"


def test_given_fixture_answers_then_writes_project_file(tmp_path):
    answers = write_answers(tmp_path, {"user": "Ada", "architecture": "clean"})
    code, out, err = run_setup(tmp_path, "--profile", str(answers), "--no-install", "--yes")
    assert code == 0, err
    written = project_profile_path(tmp_path)
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["user"] == "Ada"
    assert data["architecture"] == "clean"
    assert "wrote" in out


def test_given_dry_run_then_writes_nothing(tmp_path):
    answers = write_answers(tmp_path, {"user": "Ada"})
    code, out, err = run_setup(tmp_path, "--profile", str(answers), "--dry-run", "--no-install")
    assert code == 0, err
    assert not project_profile_path(tmp_path).exists()
    assert not (tmp_path / ".claude").exists()
    # offer_install() prints a recommendation line before the profile body, so only
    # the trailing JSON object is parsed.
    data = json.loads(out[out.index("{"):])
    assert data["user"] == "Ada"


def test_given_scope_user_then_writes_under_home(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    answers = write_answers(project_dir, {"user": "Ada"})

    code, out, err = run_setup(
        project_dir, "--profile", str(answers), "--scope", "user", "--no-install", "--yes", home=fake_home
    )

    assert code == 0, err
    assert not project_profile_path(project_dir).exists()
    written = project_profile_path(fake_home)
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["user"] == "Ada"


def test_given_invalid_answers_then_exit1(tmp_path):
    answers = write_answers(tmp_path, {"architecture": "bogus-architecture"})
    code, out, err = run_setup(tmp_path, "--profile", str(answers), "--no-install", "--yes")
    assert code == 1
    assert "invalid:" in err


def test_given_clean_without_kit_then_install_offered_in_output(tmp_path):
    answers = write_answers(tmp_path, {"architecture": "clean"})
    code, out, err = run_setup(tmp_path, "--profile", str(answers), "--no-install")
    assert code == 0, err
    assert KIT_PLUGIN in out
    assert "clean-architecture" in out
    assert "installed " + KIT_PLUGIN not in out
    written = project_profile_path(tmp_path)
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["optional"][KIT_PLUGIN] is False


def test_given_declined_then_optional_kit_false(tmp_path):
    answers = write_answers(tmp_path, {"architecture": "clean"})
    code, out, err = run_setup(tmp_path, "--profile", str(answers), input="n\n")
    assert code == 0, err
    written = project_profile_path(tmp_path)
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["optional"][KIT_PLUGIN] is False


def test_given_detect_then_prints_json(tmp_path):
    code, out, err = run_setup(tmp_path, "--detect")
    assert code == 0, err
    data = json.loads(out)
    for key in ("scm", "az", "gh", "claude", "plugins", "codex", "roslyn-mcp", "jev", KIT_PLUGIN):
        assert key in data
    assert data["jev"] is False
    assert data["az"] is False
    assert data["gh"] is False
    assert data["claude"] is False


def test_given_key_in_env_then_detect_reports_jev(tmp_path):
    env = {"PATH": minimal_path_env(tmp_path), "HOME": str(tmp_path), "USERPROFILE": str(tmp_path),
           "TYPESAFE_API_KEY": "placeholder-for-test"}
    code, out, err = run_py(SETUP_PY, "--detect", cwd=tmp_path, env=env)
    assert code == 0, err
    assert json.loads(out)["jev"] is True
    assert "placeholder-for-test" not in out


def test_given_rerun_then_existing_checks_survive(tmp_path):
    first = write_answers(tmp_path, {"architecture": "clean", "checks": [
        {"id": "ct", "rule": "Propagate CancellationToken", "severity": "high"}]}, "first.json")
    code, out, err = run_setup(tmp_path, "--profile", str(first), "--no-install")
    assert code == 0, err
    second = write_answers(tmp_path, {"testing": {"tdd": "strict"}}, "second.json")
    code, out, err = run_setup(tmp_path, "--profile", str(second), "--no-install")
    assert code == 0, err
    data = json.loads(project_profile_path(tmp_path).read_text(encoding="utf-8"))
    assert data["testing"]["tdd"] == "strict"
    assert data["checks"] == [{"id": "ct", "rule": "Propagate CancellationToken", "severity": "high"}]
    assert data["optional"]["jev"] is False


def test_given_bad_check_then_setup_exit1(tmp_path):
    answers = write_answers(tmp_path, {"checks": [{"id": "ct", "rule": "x", "severity": "urgent"}]})
    code, out, err = run_setup(tmp_path, "--profile", str(answers), "--no-install")
    assert code == 1
    assert "severity must be one of" in err


def setup_module_fresh():
    return import_module_from_path("setup_under_test", SETUP_PY)


def write_package_json(root, deps):
    (root / "ClientApp").mkdir(parents=True, exist_ok=True)
    (root / "ClientApp" / "package.json").write_text(json.dumps({"dependencies": deps}), encoding="utf-8")


def test_given_razor_files_then_detect_blazor(tmp_path):
    (tmp_path / "Components" / "Pages").mkdir(parents=True)
    (tmp_path / "Components" / "Pages" / "Home.razor").write_text("@page \"/\"", encoding="utf-8")
    write_package_json(tmp_path, {"react": "^18"})

    assert setup_module_fresh().detect_frontend(tmp_path) == "blazor"


def test_given_cshtml_only_then_detect_razor(tmp_path):
    (tmp_path / "Pages").mkdir()
    (tmp_path / "Pages" / "Index.cshtml").write_text("@page", encoding="utf-8")
    (tmp_path / "wwwroot" / "js").mkdir(parents=True)
    (tmp_path / "wwwroot" / "js" / "site.js").write_text("", encoding="utf-8")

    assert setup_module_fresh().detect_frontend(tmp_path) == "razor"


def test_given_package_json_react_then_detect_react(tmp_path):
    (tmp_path / "Pages").mkdir()
    (tmp_path / "Pages" / "Index.cshtml").write_text("@page", encoding="utf-8")
    write_package_json(tmp_path, {"react": "^18", "react-dom": "^18"})

    assert setup_module_fresh().detect_frontend(tmp_path) == "react"


def test_given_package_json_angular_core_then_detect_angular(tmp_path):
    write_package_json(tmp_path, {"@angular/core": "^18"})

    assert setup_module_fresh().detect_frontend(tmp_path) == "angular"


def test_given_package_json_vue_then_detect_vue(tmp_path):
    write_package_json(tmp_path, {"vue": "^3"})

    assert setup_module_fresh().detect_frontend(tmp_path) == "vue"


def test_given_wwwroot_js_only_then_detect_javascript(tmp_path):
    (tmp_path / "wwwroot" / "js").mkdir(parents=True)
    (tmp_path / "wwwroot" / "js" / "cart.ts").write_text("", encoding="utf-8")

    assert setup_module_fresh().detect_frontend(tmp_path) == "javascript"


def test_given_node_modules_only_then_ignored(tmp_path):
    (tmp_path / "node_modules" / "react").mkdir(parents=True)
    (tmp_path / "node_modules" / "react" / "package.json").write_text(json.dumps({"name": "react"}), encoding="utf-8")

    assert setup_module_fresh().detect_frontend(tmp_path) == "none"


def test_given_no_frontend_then_none(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Program.cs").write_text("", encoding="utf-8")

    assert setup_module_fresh().detect_frontend(tmp_path) == "none"


def test_given_tooling_package_json_only_then_none(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"prettier": "^3"}}), encoding="utf-8")

    assert setup_module_fresh().detect_frontend(tmp_path) == "none"


def test_given_malformed_package_json_then_skipped(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "package.json").write_text(json.dumps({"dependencies": None}), encoding="utf-8")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "package.json").write_text("[]", encoding="utf-8")
    write_package_json(tmp_path, {"vue": "^3"})

    assert setup_module_fresh().detect_frontend(tmp_path) == "vue"


def test_given_razor_library_under_lib_then_detect_blazor(tmp_path):
    (tmp_path / "src" / "lib" / "Ui").mkdir(parents=True)
    (tmp_path / "src" / "lib" / "Ui" / "Card.razor").write_text("<div></div>", encoding="utf-8")

    assert setup_module_fresh().detect_frontend(tmp_path) == "blazor"


@pytest.mark.parametrize(
    "listing,expected",
    [("jev: npx -y @jkudish/jev-mcp - Connected", True),
     ("jev-local: node server.js - Connected", True),
     ("roslyn: dotnet run - Connected", False),
     ("mcp-jevons: node x.js - Connected", False)],
)
def test_given_mcp_listing_then_has_jev_matches_whole_word(monkeypatch, listing, expected):
    setup = setup_module_fresh()
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(setup, "run", lambda *cmd, **kw: type("R", (), {"returncode": 0, "stdout": listing})())
    assert setup.has_jev() is expected


def test_given_rerun_then_existing_stage_checks_survive(tmp_path):
    stage = {"test": [{"id": "green", "prompt": "Did every suite pass?"}]}
    first = write_answers(tmp_path, {"stage_checks": stage}, "first.json")
    assert run_setup(tmp_path, "--profile", str(first), "--no-install")[0] == 0
    second = write_answers(tmp_path, {"testing": {"tdd": "strict"}}, "second.json")
    assert run_setup(tmp_path, "--profile", str(second), "--no-install")[0] == 0
    data = json.loads(project_profile_path(tmp_path).read_text(encoding="utf-8"))
    assert data["stage_checks"] == stage
