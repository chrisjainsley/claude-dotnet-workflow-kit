"""jev_checks.py scores profile checks over diff hunks with a fake transport; no network."""
import json
import os
from pathlib import Path

import pytest

import jev_checks
from conftest import FIXTURES_DIR, SCRIPTS_DIR, run_py

DIFF = FIXTURES_DIR / "checks.diff"
PROFILE = FIXTURES_DIR / "profile-checks.json"
SCRIPT = SCRIPTS_DIR / "jev_checks.py"
PLACEHOLDER_KEY = "placeholder-key-for-tests"


class FakeTransport:
    """Answers every question from a table of violation probabilities, recording requests."""

    def __init__(self, violates=None, statuses=None, extract=None, noul=None):
        self.violates = violates or {}
        self.statuses = list(statuses or [])
        self.extract = extract or {}
        self.noul = noul or {}
        self.requests = []

    def __call__(self, body_bytes, headers):
        body = json.loads(body_bytes)
        self.requests.append((body, headers))
        status = self.statuses.pop(0) if self.statuses else 200
        if status != 200:
            return status, json.dumps({"error": "nope"})
        answers = {}
        for qid, question in body["questions"].items():
            if question["type"] == "noul":
                answers[qid] = {"type": "noul", "noul": self.noul.get(qid, 0.9)}
            elif qid in self.extract:
                choice = self.extract[qid]
                answers[qid] = {"type": "choice", "choice": choice, "probabilities": {choice: 0.9}, "confidence": 0.9}
            else:
                p = self.violates.get(qid, 0.05)
                answers[qid] = {"type": "choice", "choice": "violates" if p >= 0.5 else "follows",
                                "probabilities": {"violates": p, "follows": 1 - p, "not_applicable": 0.0},
                                "confidence": max(p, 1 - p)}
        return 200, json.dumps({"model": "jev-test", "answers": answers, "usage": {}})


def profile():
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def rules():
    return jev_checks.enabled_checks(profile())


def hunks():
    return jev_checks.parse_diff(DIFF.read_text(encoding="utf-8"))


def test_given_fixture_diff_then_hunks_carry_paths_and_first_added_line():
    parsed = hunks()
    paths = [h["path"] for h in parsed]
    assert paths == ["src/Orders/Application/CancelOrderHandler.cs", "src/Orders/Api/appsettings.Development.json", "README.md"]
    assert parsed[0]["line"] == 12
    assert parsed[2]["line"] == 2
    assert "+        order.Cancel(DateTime.Now);" in parsed[0]["text"]
    assert all("Old.cs" not in h["path"] for h in parsed), "a deleted file has no added lines"


def test_given_secret_file_then_it_never_reaches_the_transport():
    safe, skipped = jev_checks.split_hunks(hunks())
    assert [h["path"] for h in safe] == ["src/Orders/Application/CancelOrderHandler.cs", "README.md"]
    assert skipped == ["src/Orders/Api/appsettings.Development.json: secret pattern, not sent"]
    transport = FakeTransport()
    jev_checks.score_hunks(safe, rules(), {"flag_at": 0.75, "review_at": 0.4}, PLACEHOLDER_KEY, transport)
    sent = json.dumps([r[0] for r in transport.requests])
    assert "not-a-real-key" not in sent and "appsettings" not in sent


def test_given_files_globs_then_only_matching_rules_are_asked():
    safe, _ = jev_checks.split_hunks(hunks())
    _, requests = jev_checks.score_hunks(safe, rules(), {"flag_at": 0.75, "review_at": 0.4}, dry_run=True)
    by_path = {r["state"]["path"]: sorted(r["questions"]) for r in requests}
    assert by_path["src/Orders/Application/CancelOrderHandler.cs"] == ["cancellation", "clock", "docs"]
    assert by_path["README.md"] == ["docs"]


@pytest.mark.parametrize(
    "pattern,path,expected",
    [("**/*", "README.md", True), ("**/*.cs", "a/b.cs", True), ("**/*.cs", "b.cs", True),
     ("src/**/*.cs", "src/x/y.cs", True), ("src/**/*.cs", "tests/x.cs", False), ("*.md", "docs/a.md", False)],
)
def test_given_glob_then_path_matches(pattern, path, expected):
    assert jev_checks.path_matches(pattern, path) is expected


def test_given_long_hunk_then_chunked_on_line_boundaries():
    lines = ["+" + ("x" * 99) for _ in range(300)]
    chunks = jev_checks.chunk_text("\n".join(lines), limit=12000)
    assert len(chunks) == 3
    assert all(len(c) <= 12000 for c in chunks)
    assert "\n".join(chunks) == "\n".join(lines)


def test_given_probabilities_then_bands_map_to_severities():
    safe, _ = jev_checks.split_hunks(hunks())
    transport = FakeTransport(violates={"cancellation": 0.92, "clock": 0.55, "docs": 0.1})
    findings, requests = jev_checks.score_hunks(safe, rules(), {"flag_at": 0.75, "review_at": 0.4}, PLACEHOLDER_KEY, transport)
    assert len(requests) == 2 and len(transport.requests) == 2
    assert transport.requests[0][1]["Authorization"] == f"Bearer {PLACEHOLDER_KEY}"
    by_source = {f["source"]: f for f in findings}
    assert by_source["checks:cancellation"]["severity"] == "high"
    assert by_source["checks:cancellation"]["location"] == "src/Orders/Application/CancelOrderHandler.cs:12"
    assert by_source["checks:clock"]["severity"] == "low"
    assert "confirm by reading" in by_source["checks:clock"]["note"]
    assert "checks:docs" not in by_source
    assert [f["severity"] for f in findings] == ["high", "low"]


def test_given_429_then_retried_and_then_answered():
    slept = []
    transport = FakeTransport(statuses=[429, 200])
    answers = jev_checks.post(jev_checks.build_request("a.cs", "+x", rules()[:1]), PLACEHOLDER_KEY, transport, sleep=slept.append)
    assert "cancellation" in answers
    assert len(transport.requests) == 2 and slept == [0.5]


def test_given_500_then_jev_unavailable():
    transport = FakeTransport(statuses=[500])
    with pytest.raises(jev_checks.JevUnavailable, match="api responded 500"):
        jev_checks.post(jev_checks.build_request("a.cs", "+x", rules()[:1]), PLACEHOLDER_KEY, transport)


def test_given_env_key_then_it_beats_the_mcp_config(tmp_path):
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({"projects": {"/home/x": {"mcpServers": {"jev": {"env": {"TYPESAFE_API_KEY": "from-config"}}}}}}), encoding="utf-8")
    assert jev_checks.resolve_key({"TYPESAFE_API_KEY": "from-env"}, claude_json) == ("from-env", "env")
    assert jev_checks.resolve_key({}, claude_json) == ("from-config", "mcp config")
    assert jev_checks.resolve_key({}, tmp_path / "missing.json") == (None, None)


def test_given_top_level_mcp_entry_then_found(tmp_path):
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({"mcpServers": {"jev": {"env": {"TYPESAFE_API_KEY": "top"}}}}), encoding="utf-8")
    assert jev_checks.resolve_key({}, claude_json) == ("top", "mcp config")


def test_given_extract_then_rules_take_severity_from_the_class(tmp_path, monkeypatch):
    md = tmp_path / "CLAUDE.md"
    md.write_text(
        "# Rules\n\n- Never call DateTime.Now in domain code.\n- Prefer records for value objects.\n"
        "This project is a modular monolith.\n```csharp\nvar x = 1;\n```\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    transport = FakeTransport(extract={"claude-3": "rule_must", "claude-4": "rule_prefer", "claude-5": "prose"})
    extracted, requests = jev_checks.extract_rules(["CLAUDE.md"], PLACEHOLDER_KEY, transport)
    assert len(requests) == 1
    assert [(r["id"], r["severity"]) for r in extracted] == [("claude-3", "high"), ("claude-4", "medium")]
    assert extracted[0]["rule"] == "Never call DateTime.Now in domain code."
    assert extracted[0]["source"].endswith("CLAUDE.md:3")
    assert jev_checks.enabled_checks({"checks": extracted})[0]["files"] == "**/*"


def test_given_check_rules_then_doubtful_ones_are_named():
    transport = FakeTransport(noul={"docs": 0.2})
    doubtful, requests = jev_checks.check_rules(rules(), PLACEHOLDER_KEY, transport)
    assert doubtful == [("docs", 0.2)]
    assert len(requests) == 1 and requests[0]["questions"]["docs"]["type"] == "noul"


def cli_env(tmp_path, key=None):
    # An empty value overrides any key exported in the developer's shell; resolve_key treats it as absent.
    return {"HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "TYPESAFE_API_KEY": key or ""}


def test_given_dry_run_then_nothing_sent_and_json_written(tmp_path):
    out = tmp_path / "checks.json"
    code, stdout, stderr = run_py(SCRIPT, "--diff-file", DIFF, "--profile", PROFILE, "--dry-run", "--out", out,
                                  cwd=tmp_path, env=cli_env(tmp_path))
    assert code == 0, stderr
    assert "nothing sent" in stdout
    assert "skipped: src/Orders/Api/appsettings.Development.json" in stdout
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["hunks"] == 2 and data["requests"] == 2 and data["findings"] == []
    assert data["key_source"] == "dry-run"
    assert len(data["dry_run"]) == 2


def test_given_no_key_then_exit_2(tmp_path):
    code, stdout, stderr = run_py(SCRIPT, "--diff-file", DIFF, "--profile", PROFILE, cwd=tmp_path, env=cli_env(tmp_path))
    assert code == 2
    assert "jev unavailable: no TYPESAFE_API_KEY and no jev MCP entry" in stderr


def test_given_transport_failure_then_main_exits_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", PLACEHOLDER_KEY)
    monkeypatch.setattr(jev_checks, "default_transport", FakeTransport(statuses=[503]))
    code = jev_checks.main(["--diff-file", str(DIFF), "--profile", str(PROFILE)])
    assert code == 2
    assert "jev unavailable: api responded 503" in capsys.readouterr().err


def test_given_answers_then_main_prints_table_and_writes_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", PLACEHOLDER_KEY)
    monkeypatch.setattr(jev_checks, "default_transport", FakeTransport(violates={"cancellation": 0.9}))
    out = tmp_path / "checks.json"
    code = jev_checks.main(["--diff-file", str(DIFF), "--profile", str(PROFILE), "--out", str(out)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "| high | src/Orders/Application/CancelOrderHandler.cs:12 |" in printed
    assert "checks:cancellation" in printed and "key from env" in printed
    assert PLACEHOLDER_KEY not in printed
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["findings"][0]["source"] == "checks:cancellation"
    assert data["rules"] == ["cancellation", "clock", "docs"]
    assert PLACEHOLDER_KEY not in out.read_text(encoding="utf-8")


def test_given_no_checks_then_nothing_to_score(tmp_path):
    empty = tmp_path / "profile.json"
    empty.write_text(json.dumps({"schema": 1}), encoding="utf-8")
    code, stdout, stderr = run_py(SCRIPT, "--diff-file", DIFF, "--profile", empty, "--dry-run", cwd=tmp_path, env=cli_env(tmp_path))
    assert code == 0, stderr
    assert "nothing to score" in stdout


def test_given_rules_file_then_added_to_profile_checks(tmp_path):
    extra = tmp_path / "rules.json"
    extra.write_text(json.dumps([{"id": "claude-3", "rule": "No DateTime.Now", "severity": "high"}]), encoding="utf-8")
    code, stdout, stderr = run_py(SCRIPT, "--diff-file", DIFF, "--profile", PROFILE, "--rules", extra, "--dry-run",
                                  cwd=tmp_path, env=cli_env(tmp_path))
    assert code == 0, stderr
    assert "claude-3" in stdout


def test_given_two_claude_files_then_extracted_ids_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("- Never call DateTime.Now in domain code.\n", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").write_text("- Prefer records for value objects.\n", encoding="utf-8")
    transport = FakeTransport(extract={"claude-1": "rule_must", "claude-claude-1": "rule_prefer"})
    extracted, _ = jev_checks.extract_rules(["CLAUDE.md", ".claude/CLAUDE.md"], PLACEHOLDER_KEY, transport)
    assert sorted(r["id"] for r in extracted) == ["claude-1", "claude-claude-1"]


def test_given_extract_output_then_rules_flag_round_trips(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TYPESAFE_API_KEY", PLACEHOLDER_KEY)
    (tmp_path / "CLAUDE.md").write_text("- Never call DateTime.Now in domain code.\n", encoding="utf-8")
    monkeypatch.setattr(jev_checks, "default_transport", FakeTransport(extract={"claude-1": "rule_must"}))
    rules_out = tmp_path / "rules.json"
    assert jev_checks.main(["--extract", "CLAUDE.md", "--out", str(rules_out), "--profile", str(PROFILE)]) == 0
    assert json.loads(rules_out.read_text(encoding="utf-8"))["rules"][0]["id"] == "claude-1"
    capsys.readouterr()
    code = jev_checks.main(["--diff-file", str(DIFF), "--profile", str(PROFILE), "--rules", str(rules_out), "--dry-run"])
    assert code == 0
    assert "claude-1" in capsys.readouterr().out
