"""jev_checks.py scores profile checks over diff hunks with a fake transport; no network."""
import json
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


def test_given_quoted_non_ascii_secret_path_then_unquoted_and_never_sent():
    diff = (
        'diff --git "a/src/\\303\\234nterlagen/appsettings.Development.json" "b/src/\\303\\234nterlagen/appsettings.Development.json"\n'
        "index 1111111..2222222 100644\n"
        '--- "a/src/\\303\\234nterlagen/appsettings.Development.json"\n'
        '+++ "b/src/\\303\\234nterlagen/appsettings.Development.json"\n'
        "@@ -1,2 +1,3 @@\n {\n+  \"ApiKey\": \"not-a-real-key\",\n }\n"
    )
    parsed = jev_checks.parse_diff(diff)
    assert parsed[0]["path"] == "src/\u00dcnterlagen/appsettings.Development.json"
    safe, skipped = jev_checks.split_hunks(parsed)
    assert safe == [] and len(skipped) == 1


def test_given_mid_run_failure_then_earlier_findings_are_kept(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", PLACEHOLDER_KEY)
    monkeypatch.setattr(jev_checks, "default_transport", FakeTransport(violates={"cancellation": 0.9}, statuses=[200, 503]))
    out = tmp_path / "checks.json"
    code = jev_checks.main(["--diff-file", str(DIFF), "--profile", str(PROFILE), "--out", str(out)])
    assert code == 2
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["partial"].startswith("api responded 503 after 1 of the requests")
    assert data["requests"] == 1 and data["findings"][0]["source"] == "checks:cancellation"
    assert "partial: 1 requests answered" in capsys.readouterr().out


def test_given_missing_rules_file_then_warned_and_profile_checks_still_scored(tmp_path):
    code, stdout, stderr = run_py(SCRIPT, "--diff-file", DIFF, "--profile", PROFILE, "--rules", tmp_path / "absent.json", "--dry-run",
                                  cwd=tmp_path, env=cli_env(tmp_path))
    assert code == 0, stderr
    assert "warning: rules file" in stderr and "not found" in stderr
    assert "cancellation" in stdout


def test_given_malformed_rules_file_then_exit_1_not_2(tmp_path):
    bad = tmp_path / "rules.json"
    bad.write_text(json.dumps([{"id": "x", "rule": "y"}]), encoding="utf-8")
    code, stdout, stderr = run_py(SCRIPT, "--diff-file", DIFF, "--profile", PROFILE, "--rules", bad, "--dry-run", cwd=tmp_path, env=cli_env(tmp_path))
    assert code == 1
    assert "invalid: rules file" in stderr and "severity" in stderr


def test_given_no_range_or_diff_then_usage_exit_1(tmp_path):
    code, stdout, stderr = run_py(SCRIPT, "--profile", PROFILE, cwd=tmp_path, env=cli_env(tmp_path, key=PLACEHOLDER_KEY))
    assert code == 1
    assert "--range or --diff-file is required" in stderr


def test_given_file_outside_cwd_then_id_carries_a_path_hash(tmp_path, monkeypatch):
    work = tmp_path / "repo"
    work.mkdir()
    monkeypatch.chdir(work)
    outside = tmp_path / "CLAUDE.md"
    outside.write_text("- Never call DateTime.Now in domain code.\n", encoding="utf-8")
    (work / "CLAUDE.md").write_text("- Prefer records for value objects.\n", encoding="utf-8")
    prefix = jev_checks.rule_prefix(str(outside))
    assert prefix.startswith("CLAUDE-") and len(prefix) == len("CLAUDE-") + 6
    assert jev_checks.rule_prefix("CLAUDE.md") == "CLAUDE"
    assert prefix != "CLAUDE"


def test_given_split_hunk_then_each_chunk_reports_its_own_first_added_line():
    lines = ["@@ -1,0 +1,300 @@"] + [f"+line {i} " + ("x" * 90) for i in range(1, 301)]
    hunk = {"path": "a.cs", "line": 1, "start": 1, "text": "\n".join(lines)}
    chunks = jev_checks.chunk_hunk(hunk, limit=12000)
    assert len(chunks) == 3
    expected, seen = [], 0
    for chunk, first in chunks:
        expected.append(seen + 1)
        seen += sum(1 for line in chunk.splitlines() if line.startswith("+"))
    assert [first for _, first in chunks] == expected


def test_given_single_overlong_line_then_cut_hard():
    chunks = jev_checks.chunk_text("+" + "x" * 30000, limit=12000)
    assert len(chunks) == 3 and all(len(c) <= 12000 for c in chunks)


class NoulTransport(FakeTransport):
    def __init__(self, yes):
        super().__init__(noul=yes)


def test_given_stage_evidence_then_each_prompt_is_a_noul_question(tmp_path):
    out = tmp_path / "test-output.txt"
    out.write_text("Passed! 214 tests\n", encoding="utf-8")
    checks = jev_checks.stage_checks(profile(), "test")
    evidence, truncated = jev_checks.load_evidence([str(out)])
    transport = NoulTransport({"suite-green": 0.93, "scenarios-run": 0.5})
    results, requests = jev_checks.score_stage("test", checks, evidence, {"flag_at": 0.75, "review_at": 0.4},
                                               truncated, PLACEHOLDER_KEY, transport)
    body = transport.requests[0][0]
    assert body["state"]["stage"] == "test" and body["state"]["evidence"][0]["id"] == "test-output.txt"
    assert {q["type"] for q in body["questions"].values()} == {"noul"}
    assert [(r["id"], r["verdict"]) for r in results] == [("suite-green", "pass"), ("scenarios-run", "confirm")]
    assert jev_checks.gate_of(results) == "confirm"


@pytest.mark.parametrize(
    "yes,gate",
    [({"suite-green": 0.9, "scenarios-run": 0.9}, "pass"),
     ({"suite-green": 0.9, "scenarios-run": 0.1}, "fix"),
     ({"suite-green": 0.1, "scenarios-run": 0.9}, "stop")],
)
def test_given_verdicts_then_gate_follows_on_fail(tmp_path, yes, gate):
    out = tmp_path / "o.txt"
    out.write_text("x", encoding="utf-8")
    evidence, _ = jev_checks.load_evidence([str(out)])
    results, _ = jev_checks.score_stage("test", jev_checks.stage_checks(profile(), "test"), evidence,
                                        {"flag_at": 0.75, "review_at": 0.4}, False, PLACEHOLDER_KEY, NoulTransport(yes))
    assert jev_checks.gate_of(results) == gate


def test_given_truncated_evidence_then_a_yes_only_confirms(tmp_path):
    big = tmp_path / "big.txt"
    big.write_text("y" * 70000, encoding="utf-8")
    evidence, truncated = jev_checks.load_evidence([str(big)])
    assert truncated and len(evidence[0]["text"]) == jev_checks.EVIDENCE_CHARS
    results, _ = jev_checks.score_stage("test", jev_checks.stage_checks(profile(), "test"), evidence,
                                        {"flag_at": 0.75, "review_at": 0.4}, truncated, PLACEHOLDER_KEY,
                                        NoulTransport({"suite-green": 0.99, "scenarios-run": 0.99}))
    assert {r["verdict"] for r in results} == {"confirm"}


def test_given_secret_evidence_file_then_refused(tmp_path):
    secret = tmp_path / "appsettings.Production.json"
    secret.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="secret-pattern"):
        jev_checks.load_evidence([str(secret)])


def test_given_stage_cli_then_table_gate_and_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", PLACEHOLDER_KEY)
    monkeypatch.setattr(jev_checks, "default_transport", NoulTransport({"has-tests": 0.2}))
    out = tmp_path / "implement.json"
    code = jev_checks.main(["--stage", "implement", "--diff-file", str(DIFF), "--profile", str(PROFILE), "--out", str(out)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "| has-tests | fail | 0.20 | fix |" in printed and "gate: fix" in printed
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["gate"] == "fix" and data["evidence"] == ["diff"]
    assert "appsettings" not in json.dumps(data)


def test_given_stage_without_checks_then_pass_without_calling(tmp_path):
    code, stdout, stderr = run_py(SCRIPT, "--stage", "review", "--profile", PROFILE, cwd=tmp_path, env=cli_env(tmp_path))
    assert code == 0 and "no stage_checks for review; gate: pass" in stdout


def test_given_big_diff_then_every_file_survives_the_trim():
    parts = []
    for name in ('a/one.py', 'b/two.py', 'tests/test_last.py'):
        body = chr(10).join('+' + 'x' * 99 for _ in range(400))
        parts.append(f'diff --git a/{name} b/{name}' + chr(10) + f'--- a/{name}' + chr(10) + f'+++ b/{name}' + chr(10) + '@@ -0,0 +1,400 @@' + chr(10) + body)
    evidence, truncated = jev_checks.load_evidence([], chr(10).join(parts) + chr(10), limit=6000)
    text = evidence[0]['text']
    assert truncated and len(text) <= 6000
    assert text.startswith('Changed files:')
    assert text.count('tests/test_last.py') == 2
