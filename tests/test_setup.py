import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from conftest import SETUP_PY, run_py

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
    for key in ("scm", "az", "gh", "claude", "plugins", "codex", "roslyn-mcp", KIT_PLUGIN):
        assert key in data
    assert data["az"] is False
    assert data["gh"] is False
    assert data["claude"] is False
