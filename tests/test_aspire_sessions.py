"""aspire_sessions.py records which session owns each running AppHost and refuses commands
that would stop, or clash with, another session's."""
import json
import os

import pytest

import aspire_sessions as aspire
from conftest import SCRIPTS_DIR, run_py

NOW = 1_800_000_000.0
PROJECT = "src/Wallet.AppHost"
CSPROJ = '<Project Sdk="Aspire.AppHost.Sdk/9.5.0">\n  <PropertyGroup><OutputType>Exe</OutputType></PropertyGroup>\n</Project>\n'
SETTINGS = {
    "profiles": {
        "https": {
            "commandName": "Project",
            "applicationUrl": "https://localhost:17001;http://localhost:15001",
            "environmentVariables": {
                "ASPNETCORE_ENVIRONMENT": "Development",
                "ASPIRE_DASHBOARD_OTLP_ENDPOINT_URL": "https://localhost:21001",
            },
        },
        "kit-2": {
            "commandName": "Project",
            "applicationUrl": "https://localhost:17002",
            "environmentVariables": {"ASPIRE_DASHBOARD_OTLP_ENDPOINT_URL": "https://localhost:21002"},
        },
    }
}


def checkout(base, name):
    """A worktree holding the Wallet AppHost project, with the same ports in every copy."""
    root = base / name
    (root / ".git").mkdir(parents=True)
    project = root / PROJECT
    (project / "Properties").mkdir(parents=True)
    (project / "Wallet.AppHost.csproj").write_text(CSPROJ, encoding="utf-8")
    (project / "Properties" / "launchSettings.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
    api = root / "src" / "Wallet.Api"
    api.mkdir(parents=True)
    (api / "Wallet.Api.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk.Web"></Project>\n', encoding="utf-8")
    return root


def stack(root, base_pid, launcher=True):
    """The processes `dotnet run` leaves for one AppHost: launcher, AppHost, DCP, dashboard, an API."""
    exe = f"{aspire.norm(root)}/{PROJECT}/bin/Debug/net9.0/Wallet.AppHost"
    procs = [
        {"pid": base_pid + 1, "ppid": base_pid, "name": "Wallet.AppHost", "cmdline": [exe], "exe": exe},
        {"pid": base_pid + 2, "ppid": base_pid + 1, "name": "dcp", "cmdline": ["/nuget/dcp", "start-apiserver"], "exe": "/nuget/dcp"},
        {"pid": base_pid + 3, "ppid": base_pid + 1, "name": "dotnet",
         "cmdline": ["dotnet", "/nuget/aspire.dashboard/tools/Aspire.Dashboard.dll"], "exe": "/usr/bin/dotnet"},
        {"pid": base_pid + 4, "ppid": base_pid + 2, "name": "Wallet.Api",
         "cmdline": [f"{aspire.norm(root)}/src/Wallet.Api/bin/Debug/net9.0/Wallet.Api"], "exe": ""},
    ]
    if launcher:
        procs.insert(0, {"pid": base_pid, "ppid": 1, "name": "dotnet",
                         "cmdline": ["dotnet", "run", "--project", PROJECT], "exe": "/usr/bin/dotnet"})
    return procs


SHELL = {"pid": 1, "ppid": 0, "name": "bash", "cmdline": ["bash"], "exe": "/bin/bash"}


def snap(*stacks, listen=None):
    procs = [SHELL] + [proc for group in stacks for proc in group]
    return aspire.Snapshot(procs, listen=listen if listen is not None else {201: [17001, 15001], 203: [21001], 204: [7101]})


@pytest.fixture
def world(tmp_path):
    a = checkout(tmp_path, "a")
    b = checkout(tmp_path, "b")
    registry = tmp_path / "registry"
    return {"a": a, "b": b, "dir": registry}


def me(session, root, label=""):
    return {"session": session, "root": aspire.norm(root), "repo": "", "branch": f"feat/{session}", "label": label}


def owned_by_b(world, now=NOW):
    """Session B has scanned its own running AppHost into the registry."""
    entries = aspire.scan(world["dir"], me("B", world["b"], "#402 Payment retries"), snap(stack(world["b"], 200)), now)
    assert [e["pid"] for e in entries] == [201]
    return entries


def judge(world, command, session="A", root=None, now=NOW, snapshot=None):
    who = me(session, root or world["a"], "#391 Wallet top-up")
    s = snapshot or snap(stack(world["b"], 200))
    entries = aspire.scan(world["dir"], who, s, now)
    return aspire.check(command, aspire.norm(root or world["a"]), who, s, entries, world["dir"], now)


# --- scanning ----------------------------------------------------------------------------

def test_given_apphost_in_own_worktree_then_scan_records_it_for_this_session(world):
    entry = owned_by_b(world)[0]
    saved = json.loads((world["dir"] / "201.json").read_text(encoding="utf-8"))
    assert saved["session"] == "B" and saved["label"] == "#402 Payment retries"
    assert entry["project"] == "Wallet.AppHost" and entry["isMine"] is True
    assert entry["dashboard"] == "https://localhost:17001"
    assert entry["launchPorts"] == [15001, 17001, 21001]
    assert entry["ports"] == [7101, 15001, 17001, 21001]
    assert sorted(entry["pids"]) == [200, 201, 202, 203, 204], "the launcher and every child go with the AppHost"


def test_given_apphost_in_another_worktree_then_scan_lists_it_as_someone_elses(world):
    owned_by_b(world)
    entries = aspire.scan(world["dir"], me("A", world["a"]), snap(stack(world["b"], 200)), NOW + 5)
    assert [(e["session"], e["isMine"], e["isStale"]) for e in entries] == [("B", False, False)]
    assert json.loads((world["dir"] / "201.json").read_text(encoding="utf-8"))["session"] == "B"


def test_given_apphost_nobody_owns_then_scan_leaves_it_out(world):
    entries = aspire.scan(world["dir"], me("A", world["a"]), snap(stack(world["b"], 200)), NOW)
    assert entries == [] and not list(world["dir"].glob("*.json"))


def test_given_process_gone_then_its_entry_is_deleted(world):
    owned_by_b(world)
    assert aspire.scan(world["dir"], me("A", world["a"]), snap(), NOW + 5) == []
    assert not (world["dir"] / "201.json").exists()


def test_given_pid_reused_by_another_project_then_the_entry_is_deleted(world):
    owned_by_b(world)
    entries = aspire.scan(world["dir"], me("C", world["b"]), snap(stack(world["a"], 200)), NOW + 5)
    assert entries == []
    assert not (world["dir"] / "201.json").exists()


def test_given_owner_went_quiet_then_a_session_in_the_same_worktree_takes_it_over(world):
    owned_by_b(world)
    later = NOW + aspire.STALE_AFTER + 1
    elsewhere = aspire.scan(world["dir"], me("A", world["a"]), snap(stack(world["b"], 200)), later)
    assert [(e["session"], e["isStale"]) for e in elsewhere] == [("B", True)]
    taken = aspire.scan(world["dir"], me("C", world["b"]), snap(stack(world["b"], 200)), later)
    assert [(e["session"], e["isMine"]) for e in taken] == [("C", True)]


def test_given_owner_still_scanning_then_a_session_in_the_same_worktree_leaves_it(world):
    owned_by_b(world)
    entries = aspire.scan(world["dir"], me("C", world["b"]), snap(stack(world["b"], 200)), NOW + 30)
    assert [(e["session"], e["isMine"]) for e in entries] == [("B", False)]


def test_given_owner_ended_then_its_entry_is_free_at_once(world):
    owned_by_b(world)
    path = world["dir"] / "201.json"
    path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "seenAt": 0}), encoding="utf-8")
    taken = aspire.scan(world["dir"], me("C", world["b"]), snap(stack(world["b"], 200)), NOW + 1)
    assert [(e["session"], e["isMine"]) for e in taken] == [("C", True)]


# --- refusing kills ----------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "pkill -f dotnet",
    "pkill dotnet",
    "killall -9 dotnet",
    "pkill -f Wallet.AppHost",
    "kill 203",
    "kill -9 200 999",
    "kill $(pgrep -f Aspire.Dashboard)",
    "lsof -ti:17001 | xargs kill -9",
    "fuser -k 21001/tcp",
    "taskkill /F /IM dotnet.exe",
    "taskkill //F //IM Wallet.AppHost.exe",
    'taskkill /F /FI "IMAGENAME eq dcp.exe"',
    "taskkill /PID 200 /T /F",
    "Stop-Process -Name dotnet -Force",
    "Get-Process dotnet | Stop-Process -Force",
    "Get-Process *AppHost* | Stop-Process",
    "Get-NetTCPConnection -LocalPort 17001 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }",
    "Stop-Process -Id 204",
    "cd /tmp && pkill -f Wallet",
])
def test_given_command_that_stops_another_sessions_apphost_then_it_is_refused(world, command):
    owned_by_b(world)
    deny = judge(world, command, now=NOW + 5)
    assert deny and "Wallet.AppHost (pid 201) · #402 Payment retries" in deny


@pytest.mark.parametrize("command", [
    "kill 999",
    "kill %1",
    "pkill -f node",
    "taskkill /IM node.exe /F",
    "lsof -i :17001",
    "pgrep -f dotnet",
    'git commit -m "kill dotnet on exit"',
    "dotnet test",
])
def test_given_command_that_leaves_other_apphosts_alone_then_it_runs(world, command):
    owned_by_b(world)
    assert judge(world, command, now=NOW + 5) is None


def test_given_own_apphost_then_killing_it_runs_and_the_refusal_names_it(world):
    owned_by_b(world)
    both = snap(stack(world["b"], 200), stack(world["a"], 300))
    assert judge(world, "kill 301", now=NOW + 5, snapshot=both) is None
    deny = judge(world, "pkill -f dotnet", now=NOW + 5, snapshot=both)
    assert "Wallet.AppHost is pid 301" in deny


def test_given_owner_went_quiet_then_its_apphost_may_be_stopped(world):
    owned_by_b(world)
    assert judge(world, "pkill -f dotnet", now=NOW + aspire.STALE_AFTER + 1) is None


# --- refusing clashing starts ------------------------------------------------------------

def test_given_start_on_ports_another_session_holds_then_it_is_refused(world):
    owned_by_b(world)
    deny = judge(world, f"dotnet run --project {PROJECT}", now=NOW + 5)
    assert deny and "ports 15001, 17001, 21001 are held by Wallet.AppHost" in deny
    assert "#402 Payment retries" in deny


@pytest.mark.parametrize("command", [
    f"dotnet run --project {PROJECT} --launch-profile kit-2",
    f"ASPNETCORE_URLS=https://localhost:17101 ASPIRE_DASHBOARD_OTLP_ENDPOINT_URL=https://localhost:21101 dotnet run --project {PROJECT}",
    f'$env:ASPNETCORE_URLS="https://localhost:17101"; $env:ASPIRE_DASHBOARD_OTLP_ENDPOINT_URL="https://localhost:21101"; dotnet run --project {PROJECT}',
])
def test_given_start_on_its_own_ports_then_it_runs_and_claims_the_apphost(world, command):
    owned_by_b(world)
    assert judge(world, command, now=NOW + 5) is None
    claim = json.loads(aspire.claim_path(world["dir"], f"{aspire.norm(world['a'])}/{PROJECT}").read_text(encoding="utf-8"))
    assert claim["session"] == "A"


def test_given_start_from_the_project_folder_then_it_is_read_as_that_apphost(world):
    owned_by_b(world)
    assert "are held by" in judge(world, f"cd {PROJECT} && dotnet run", now=NOW + 5)
    assert "are held by" in judge(world, "aspire run", now=NOW + 5)


def test_given_aspire_settings_then_aspire_run_reads_the_apphost_it_names(world):
    owned_by_b(world)
    (world["a"] / ".aspire").mkdir()
    (world["a"] / ".aspire" / "settings.json").write_text(
        json.dumps({"appHostPath": f"../{PROJECT}/Wallet.AppHost.csproj"}), encoding="utf-8")
    target = aspire.start_target("aspire run", aspire.norm(world["a"] / "src"))
    assert target["projectDir"] == f"{aspire.norm(world['a'])}/{PROJECT}"


def test_given_start_of_an_apphost_another_session_runs_in_this_folder_then_it_is_refused(world):
    owned_by_b(world)
    deny = judge(world, f"dotnet run --project {PROJECT} --launch-profile kit-2", session="C", root=world["b"], now=NOW + 5)
    assert deny and "already runs for #402 Payment retries (pid 201)" in deny


def test_given_project_that_is_not_an_apphost_then_starting_it_runs(world):
    owned_by_b(world)
    assert judge(world, "dotnet run --project src/Wallet.Api --urls https://localhost:17001", now=NOW + 5) is None
    assert not (world["dir"] / "claims").exists()


def test_given_claim_then_the_starting_session_owns_the_new_apphost_in_a_shared_folder(world):
    assert judge(world, f"dotnet run --project {PROJECT}") is None
    running = snap(stack(world["a"], 300), listen={})
    assert aspire.scan(world["dir"], me("D", world["a"]), running, NOW + 10) == []
    entries = aspire.scan(world["dir"], me("A", world["a"]), running, NOW + 12)
    assert [(e["pid"], e["session"]) for e in entries] == [(301, "A")]
    expired = NOW + aspire.CLAIM_FOR + 1
    (world["dir"] / "301.json").unlink()
    assert [e["session"] for e in aspire.scan(world["dir"], me("D", world["a"]), running, expired)] == ["D"]


# --- reading commands --------------------------------------------------------------------

def test_given_windows_paths_then_they_compare_case_blind():
    assert aspire.same_path("C:\\Repos\\App\\", "c:/repos/app")
    assert not aspire.same_path("/repos/App", "/repos/app")


def test_given_command_then_quotes_come_off_and_backslashes_stay():
    segments = aspire.split_command('cd "C:\\src\\My App" && dotnet run --project Wallet.AppHost | tee log')
    assert [tokens for tokens, _ in segments] == [
        ["cd", "C:\\src\\My App"], ["dotnet", "run", "--project", "Wallet.AppHost"], ["tee", "log"]]
    assert [pipe for _, pipe in segments] == [False, True, False]


def test_given_launch_settings_with_comments_then_they_still_read(tmp_path):
    (tmp_path / "Properties").mkdir()
    (tmp_path / "Properties" / "launchSettings.json").write_text(
        '{\n  // the dashboard\n  "profiles": {"http": {"commandName": "Project", "applicationUrl": "http://localhost:15888",},},\n}\n',
        encoding="utf-8")
    assert aspire.ports_in(aspire.launch_env(tmp_path)) == [15888]


def test_given_the_cli_then_it_prints_entries_and_the_refusal(world, tmp_path):
    owned_by_b(world)
    path = tmp_path / "snapshot.json"
    procs = [SHELL] + stack(world["b"], 200)
    path.write_text(json.dumps({"procs": procs, "listen": {"201": [17001]}}), encoding="utf-8")
    code, out, err = run_py(
        SCRIPTS_DIR / "aspire_sessions.py", "check", "--dir", world["dir"], "--session", "A",
        "--root", world["a"], "--cwd", world["a"], "--command", "pkill -f dotnet",
        "--snapshot", path, "--now", NOW + 5)
    assert code == 0, err
    result = json.loads(out)
    assert [e["pid"] for e in result["entries"]] == [201]
    assert "Blocked by dotnet-workflow-kit" in result["deny"]
    code, out, err = run_py(
        SCRIPTS_DIR / "aspire_sessions.py", "check", "--dir", world["dir"], "--session", "A",
        "--root", world["a"], "--cwd", world["a"], "--command", f"dotnet run --project {PROJECT} -lp kit-2",
        "--snapshot", path, "--now", NOW + 5)
    assert json.loads(out)["starts"] == f"{aspire.norm(world['a'])}/{PROJECT}"


def test_given_this_machine_then_the_snapshot_lists_this_process():
    assert os.getpid() in aspire.take_snapshot().procs
