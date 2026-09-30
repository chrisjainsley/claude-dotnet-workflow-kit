import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
PROFILE_PY = SCRIPTS_DIR / "kit_profile.py"
SETUP_PY = SCRIPTS_DIR / "setup.py"
RENDER_PY = SCRIPTS_DIR / "render.py"
CHECK_PY = SCRIPTS_DIR / "check.py"
PAGE_TEMPLATE = REPO_ROOT / "assets" / "page.html"

PLAN_SKILL_DIR = REPO_ROOT / "skills" / "plan"
REVIEW_SKILL_DIR = REPO_ROOT / "skills" / "review"

CHECK_PLAN_PY = PLAN_SKILL_DIR / "scripts" / "check_plan.py"
BUILD_PLAN_PY = PLAN_SKILL_DIR / "scripts" / "build_plan.py"
PLAN_EXEMPLAR = PLAN_SKILL_DIR / "references" / "exemplar.md"

CHECK_REVIEW_PY = REVIEW_SKILL_DIR / "scripts" / "check_review.py"
BUILD_REVIEW_PY = REVIEW_SKILL_DIR / "scripts" / "build_review.py"
REVIEW_EXEMPLAR = REVIEW_SKILL_DIR / "references" / "exemplar.md"

README_PATH = REPO_ROOT / "README.md"
ADAPTERS_DIR = REPO_ROOT / "adapters"

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
PLAN_FIXTURE_PATH = FIXTURES_DIR / "plan.md"
REVIEW_FIXTURE_PATH = FIXTURES_DIR / "review.md"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

_FENCE_RE = re.compile(r"```markdown\r?\n(.*?)\r?\n```\s*$", re.S)


def extract_fenced_markdown(exemplar_path):
    """Pull the single ```markdown fenced body out of a references/exemplar.md file."""
    text = Path(exemplar_path).read_text(encoding="utf-8")
    match = _FENCE_RE.search(text)
    if not match:
        raise AssertionError(f"no trailing ```markdown fence found in {exemplar_path}")
    body = match.group(1)
    if not body.endswith("\n"):
        body += "\n"
    return body


def run_py(script, *args, cwd=None, env=None, input=None, timeout=60):
    """Run a script with the current interpreter; return (returncode, stdout, stderr)."""
    full_env = dict(os.environ)
    full_env["PYTHONIOENCODING"] = "utf-8"
    full_env["PYTHONUTF8"] = "1"
    if env:
        full_env.update(env)
    cmd = [sys.executable, str(script), *[str(a) for a in args]]
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=full_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=input,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def import_module_from_path(name, path):
    """Import a standalone script file (not a package) as a module, fresh each time."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def repo_root():
    return REPO_ROOT


@pytest.fixture(scope="session")
def scripts_dir():
    return SCRIPTS_DIR


@pytest.fixture(scope="session")
def plan_fixture_text():
    return extract_fenced_markdown(PLAN_EXEMPLAR)


@pytest.fixture(scope="session")
def review_fixture_text():
    return extract_fenced_markdown(REVIEW_EXEMPLAR)


@pytest.fixture()
def plan_fixture_path(tmp_path, plan_fixture_text):
    path = tmp_path / "plan.md"
    path.write_text(plan_fixture_text, encoding="utf-8", newline="\n")
    return path


@pytest.fixture()
def review_fixture_path(tmp_path, review_fixture_text):
    path = tmp_path / "review.md"
    path.write_text(review_fixture_text, encoding="utf-8", newline="\n")
    return path


@pytest.fixture()
def run_py_fixture():
    return run_py
