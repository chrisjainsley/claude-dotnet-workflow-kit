#!/usr/bin/env python
"""Which Aspire AppHosts run on this machine, and which Claude session owns each.

    python aspire_sessions.py scan    --session <id> --root <worktree> [--repo <git common dir>]
                                      [--branch <branch>] [--label <item>] [--dir <registry dir>]
    python aspire_sessions.py check   ...the scan options... --cwd <dir> --command <shell command>

The kit's mod runs it from every session. `scan` finds the AppHost processes running now
(a process started from a project's `bin/` whose `.csproj` uses the Aspire AppHost SDK),
the processes each one started and the TCP ports they listen on. An AppHost belongs to
the worktree whose `.git` sits above its project, and a session owns the AppHosts of its
own worktree: it writes `<pid>.json` for each into the registry, ~/.claude/
dotnet-workflow-kit/aspire, and refreshes `seenAt` on every scan. An entry whose process
has exited is deleted by whichever session sees it first; one whose session stopped
scanning for STALE_AFTER is free for a session in the same worktree to take over; a session
that ends sets its entries' `seenAt` to 0 so that happens at once.

`check` scans, then judges a command a session is about to run. It refuses a command that
would stop another live session's AppHost (`kill`, `pkill`, `killall`, `taskkill`,
`Stop-Process`, freeing a port with `lsof`, `fuser` or `Get-NetTCPConnection`), and the
start of an AppHost (`dotnet run`, `dotnet watch`, `aspire run`) whose project another
session already runs, or whose launch profile names a port another session's AppHost
holds. An allowed start leaves a claim, so the starting session owns the new AppHost
even when another session shares the worktree.

Both print JSON: `{"entries": [...]}`; a check adds `deny` when it refuses the command, or
`starts`, the AppHost project, when it lets a start through. `--snapshot <file>` reads the processes from a file instead of the system,
for tests: `{"procs": [{"pid", "ppid", "name", "cmdline": [...], "exe"}], "listen":
{"<pid>": [ports]}}`.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_DIR = Path.home() / ".claude" / "dotnet-workflow-kit" / "aspire"
# A session scans every few seconds while it is open; one silent this long has gone.
STALE_AFTER = 120
# How long a start's claim holds the AppHost it starts for the session that started it.
CLAIM_FOR = 600
# `dotnet run` on an AppHost hands off through `dnx aspire.cli run` to the Aspire CLI.
LAUNCHERS = {"dotnet", "aspire", "dnx"}
APPHOST_MARKERS = re.compile(r"Aspire\.AppHost\.Sdk|<IsAspireHost>\s*true\s*</IsAspireHost>", re.I)
URL_PORT = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s;\"',]*?:(\d{2,5})", re.I)
SKIP_DIRS = {"bin", "obj", "node_modules", ".git", ".vs", ".idea"}


# --- paths -------------------------------------------------------------------------------

def norm(path):
    """A path with forward slashes and no trailing slash, as every comparison here reads it."""
    text = str(path or "").replace("\\", "/")
    return text if re.fullmatch(r"([a-zA-Z]:)?/", text) else text.rstrip("/")


def same_path(a, b):
    """Two paths are one: case-blind for a Windows drive path, exact otherwise."""
    a, b = norm(a), norm(b)
    if re.match(r"^[a-zA-Z]:/", a) or re.match(r"^[a-zA-Z]:/", b):
        return a.lower() == b.lower()
    return a == b


def is_apphost_dir(folder, cache):
    """Whether a project folder holds a .csproj built on the Aspire AppHost SDK."""
    key = norm(folder)
    if key not in cache:
        found = False
        try:
            for project in Path(key).glob("*.csproj"):
                if APPHOST_MARKERS.search(project.read_text(encoding="utf-8", errors="replace")):
                    found = True
                    break
        except OSError:
            pass
        cache[key] = found
    return cache[key]


def worktree_root(folder):
    """The nearest folder at or above `folder` holding `.git`, a checkout's or a worktree's."""
    path = Path(norm(folder))
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return norm(candidate)
    return ""


def project_dir_of(proc, cache):
    """The AppHost project a process runs from its `bin/`, or None for any other process."""
    candidates = [proc.get("exe") or ""] + [str(arg) for arg in proc.get("cmdline") or []][:3]
    for candidate in candidates:
        path = norm(candidate)
        index = path.lower().rfind("/bin/")
        if index <= 0:
            continue
        folder = path[:index]
        if is_apphost_dir(folder, cache):
            return folder
    return None


def proc_name(proc):
    """A process's name as the kill commands match it: lower case, without `.exe`."""
    name = str(proc.get("name") or "") or Path(norm((proc.get("cmdline") or [""])[0])).name
    name = name.lower()
    return name[:-4] if name.endswith(".exe") else name


def cmdline_text(proc):
    return " ".join(str(arg) for arg in proc.get("cmdline") or [])


# --- launch profiles ---------------------------------------------------------------------

def load_launch_settings(project_dir):
    path = Path(norm(project_dir)) / "Properties" / "launchSettings.json"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    try:
        return json.loads(text)
    except ValueError:
        # Comments or trailing commas: drop them and try once more.
        text = re.sub(r"(?m)^\s*//.*$", "", text)
        text = re.sub(r",(\s*[}\]])", r"\1", text)
        try:
            return json.loads(text)
        except ValueError:
            return None


def launch_profile(project_dir, name=None):
    """The profile `dotnet run` picks: the one named, else the first that runs the project."""
    settings = load_launch_settings(project_dir) or {}
    profiles = settings.get("profiles") or {}
    if not isinstance(profiles, dict):
        return {}
    if name:
        return profiles.get(name) or {}
    for profile in profiles.values():
        if isinstance(profile, dict) and profile.get("commandName", "Project") == "Project":
            return profile
    return {}


def launch_env(project_dir, profile_name=None, overrides=None, use_profile=True):
    """The URL-bearing settings an AppHost starts with: the command's own, then its profile's on
    top, since `dotnet run` sets a profile's variables over whatever the shell already had."""
    env = dict(overrides or {})
    if use_profile:
        profile = launch_profile(project_dir, profile_name)
        if profile.get("applicationUrl"):
            env["ASPNETCORE_URLS"] = str(profile["applicationUrl"])
        for key, value in (profile.get("environmentVariables") or {}).items():
            env[str(key)] = str(value)
    return env


def ignores_no_profile(project_dir):
    """Whether `--no-launch-profile` is lost on the way: from Aspire 13, `dotnet run` hands an
    AppHost to the Aspire CLI, which drops the flag and starts the first profile anyway."""
    try:
        for project in Path(norm(project_dir)).glob("*.csproj"):
            match = re.search(r"Aspire\.AppHost\.Sdk/(\d+)", project.read_text(encoding="utf-8", errors="replace"))
            if match:
                return int(match.group(1)) >= 13
    except OSError:
        pass
    return False


def ports_in(env):
    ports = set()
    for value in env.values():
        ports.update(int(port) for port in URL_PORT.findall(str(value)))
    return sorted(port for port in ports if 0 < port < 65536)


def dashboard_url(env):
    urls = [url for url in re.split(r"[;\s]+", env.get("ASPNETCORE_URLS", "")) if url]
    https = [url for url in urls if url.lower().startswith("https://")]
    return (https or urls or [""])[0]


# --- the process snapshot ----------------------------------------------------------------

def run(argv, timeout=20):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def snapshot_linux():
    procs = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        base = f"/proc/{entry}"
        try:
            with open(f"{base}/stat", encoding="utf-8", errors="replace") as handle:
                stat = handle.read()
            with open(f"{base}/cmdline", "rb") as handle:
                cmdline = [part.decode("utf-8", "replace") for part in handle.read().split(b"\0") if part]
            with open(f"{base}/comm", encoding="utf-8", errors="replace") as handle:
                name = handle.read().strip()
        except OSError:
            continue
        try:
            exe = os.readlink(f"{base}/exe")
        except OSError:
            exe = ""
        ppid = int(stat[stat.rfind(")") + 2:].split()[1])
        procs.append({"pid": int(entry), "ppid": ppid, "name": name, "cmdline": cmdline, "exe": exe})
    return procs


def listening_linux(pids):
    """Ports each of `pids` listens on, read from /proc/net and the processes' socket fds."""
    inodes = {}
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table, encoding="utf-8") as handle:
                rows = handle.read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            fields = row.split()
            if len(fields) > 9 and fields[3] == "0A":
                inodes[fields[9]] = int(fields[1].rsplit(":", 1)[1], 16)
    found = {}
    for pid in pids:
        try:
            links = [os.readlink(f"/proc/{pid}/fd/{fd}") for fd in os.listdir(f"/proc/{pid}/fd")]
        except OSError:
            continue
        ports = {inodes[link[8:-1]] for link in links if link.startswith("socket:[") and link[8:-1] in inodes}
        if ports:
            found[pid] = sorted(ports)
    return found


def snapshot_mac():
    procs = []
    for line in (run(["ps", "-axww", "-o", "pid=", "-o", "ppid=", "-o", "args="]) or "").splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        args = parts[2].split()
        procs.append({"pid": int(parts[0]), "ppid": int(parts[1]), "name": Path(args[0]).name,
                      "cmdline": args, "exe": args[0]})
    return procs


def listening_mac(pids):
    found = {}
    pid = None
    for line in (run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"]) or "").splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid in pids:
            match = re.search(r":(\d+)$", line)
            if match:
                found.setdefault(pid, set()).add(int(match.group(1)))
    return {pid: sorted(ports) for pid, ports in found.items()}


WINDOWS_SCRIPT = (
    "$p = @(Get-CimInstance Win32_Process | ForEach-Object { @{pid=[int]$_.ProcessId; ppid=[int]$_.ParentProcessId;"
    " name=[string]$_.Name; command=[string]$_.CommandLine; exe=[string]$_.ExecutablePath} });"
    " $l = @(); try { $l = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | ForEach-Object {"
    " @{pid=[int]$_.OwningProcess; port=[int]$_.LocalPort} }) } catch {};"
    " @{procs=$p; listen=$l} | ConvertTo-Json -Compress -Depth 4"
)


def split_windows_command(text):
    """A Windows command line as its arguments, quotes removed, backslashes kept."""
    return [part.strip('"') for part in re.findall(r'"[^"]*"|\S+', text or "")]


def snapshot_windows():
    out = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_SCRIPT], timeout=30)
    try:
        data = json.loads(out or "{}")
    except ValueError:
        return [], {}
    procs = [{"pid": p.get("pid"), "ppid": p.get("ppid"), "name": p.get("name") or "",
              "cmdline": split_windows_command(p.get("command")), "exe": p.get("exe") or ""}
             for p in data.get("procs") or [] if isinstance(p, dict)]
    listen = {}
    for row in data.get("listen") or []:
        if isinstance(row, dict) and row.get("pid"):
            listen.setdefault(int(row["pid"]), set()).add(int(row["port"]))
    return procs, {pid: sorted(ports) for pid, ports in listen.items()}


class Snapshot:
    """The processes running now, with the ports a chosen few listen on."""

    def __init__(self, procs, listen=None, listen_of=None):
        self.procs = {int(p["pid"]): p for p in procs if p.get("pid") is not None}
        self.children = {}
        for proc in self.procs.values():
            self.children.setdefault(int(proc.get("ppid") or 0), []).append(int(proc["pid"]))
        self._listen = listen
        self._listen_of = listen_of
        self._looked_at = set()

    def descendants(self, pid):
        found, stack = [], [pid]
        while stack:
            for child in self.children.get(stack.pop(), []):
                if child not in found and child != pid:
                    found.append(child)
                    stack.append(child)
        return found

    def monitors(self, pid):
        """What a process started detached that watches it: DCP runs apart from its AppHost as
        `dcp start-apiserver --monitor <pid>`, with the dashboard and every resource beneath it."""
        found = []
        for other, proc in self.procs.items():
            args = [str(arg) for arg in proc.get("cmdline") or []]
            watched = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "--monitor"]
            if str(pid) in watched and other != pid:
                found += [other, *(child for child in self.descendants(other) if child != pid)]
        return found

    def listening(self, pids):
        if self._listen_of:
            # Read on demand: only for processes not yet looked at, and kept for the next stack.
            fresh = set(pids) - self._looked_at
            if fresh:
                self._listen = {**(self._listen or {}), **self._listen_of(fresh)}
                self._looked_at |= fresh
        return sorted({port for pid in pids for port in (self._listen or {}).get(pid, [])})


def take_snapshot(path=None):
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        listen = {int(pid): ports for pid, ports in (data.get("listen") or {}).items()}
        return Snapshot(data.get("procs") or [], listen=listen)
    if sys.platform.startswith("win"):
        procs, listen = snapshot_windows()
        return Snapshot(procs, listen=listen)
    if sys.platform == "darwin":
        return Snapshot(snapshot_mac(), listen_of=listening_mac)
    return Snapshot(snapshot_linux(), listen_of=listening_linux)


# --- AppHost stacks ----------------------------------------------------------------------

def find_stacks(snap):
    """Every AppHost running now: its process, the launchers above it and what it started."""
    cache = {}
    stacks = []
    for pid, proc in sorted(snap.procs.items()):
        folder = project_dir_of(proc, cache)
        if not folder:
            continue
        # A `dotnet run` or `aspire run` above the AppHost goes with it, and so does its profile.
        launchers, profile, no_profile = [], None, False
        parent = snap.procs.get(int(proc.get("ppid") or 0))
        while parent and proc_name(parent) in LAUNCHERS and int(parent["pid"]) != pid:
            launchers.append(int(parent["pid"]))
            args = [str(arg) for arg in parent.get("cmdline") or []]
            for i, arg in enumerate(args):
                if arg in ("--launch-profile", "-lp") and i + 1 < len(args):
                    profile = profile or args[i + 1]
                no_profile = no_profile or arg == "--no-launch-profile"
            parent = snap.procs.get(int(parent.get("ppid") or 0))
        pids = [pid, *snap.descendants(pid), *snap.monitors(pid)]
        env = launch_env(folder, profile, use_profile=not no_profile or ignores_no_profile(folder))
        stacks.append({
            "pid": pid,
            "project": Path(folder).name,
            "projectDir": folder,
            "root": worktree_root(folder),
            "pids": launchers + pids,
            "ports": snap.listening(pids),
            "launchPorts": ports_in(env),
            "dashboard": dashboard_url(env),
        })
    return stacks


# --- the registry ------------------------------------------------------------------------

def read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def remove(path):
    try:
        Path(path).unlink()
    except OSError:
        pass


def claim_path(folder, project_dir):
    digest = hashlib.sha1(norm(project_dir).lower().encode("utf-8")).hexdigest()[:16]
    return Path(folder) / "claims" / f"{digest}.json"


def is_stale(entry, now):
    return now - float(entry.get("seenAt") or 0) > STALE_AFTER


def scan(folder, me, snap, now):
    """Updates this session's entries and drops dead ones; returns every live entry."""
    folder = Path(folder)
    stacks = {stack["pid"]: stack for stack in find_stacks(snap)}
    entries = {}
    if folder.is_dir():
        for path in folder.glob("*.json"):
            entry = read_json(path)
            stack = stacks.get(int((entry or {}).get("pid") or 0))
            # Gone, or the pid now belongs to some other process: the entry goes.
            if not entry or not stack or not same_path(stack["projectDir"], entry.get("projectDir")):
                remove(path)
                continue
            entries[stack["pid"]] = entry

    for path in folder.glob("claims/*.json"):
        if now - float((read_json(path) or {}).get("at") or 0) >= CLAIM_FOR:
            remove(path)

    live = []
    for pid, stack in sorted(stacks.items()):
        entry = entries.get(pid)
        is_mine_here = bool(me.get("session")) and same_path(stack["root"], me.get("root"))
        if entry and entry.get("session") != me.get("session"):
            # Another session's; free to take over only when it went quiet in this worktree.
            if not (is_mine_here and is_stale(entry, now)):
                live.append({**entry, **stack_fields(stack)})
                continue
        if not entry and not is_mine_here:
            continue
        if not entry:
            claim = read_json(claim_path(folder, stack["projectDir"]))
            if claim and claim.get("session") != me["session"] and now - float(claim.get("at") or 0) < CLAIM_FOR:
                continue
        entry = {
            "pid": pid,
            "firstSeen": (entry or {}).get("firstSeen") or now,
            **(entry or {}),
            **stack_fields(stack),
            "session": me["session"],
            "repo": me.get("repo") or "",
            "branch": me.get("branch") or "",
            "label": me.get("label") or "",
            "seenAt": now,
        }
        write_json(folder / f"{pid}.json", entry)
        live.append(entry)

    for entry in live:
        entry["isMine"] = entry.get("session") == me.get("session")
        entry["isStale"] = is_stale(entry, now)
    return live


def stack_fields(stack):
    return {key: stack[key] for key in ("project", "projectDir", "root", "pids", "ports", "launchPorts", "dashboard")}


# --- reading a command -------------------------------------------------------------------

SEPARATOR = re.compile(r"&&|\|\||[;|&\n]")


def split_command(text):
    """A shell command as its simple commands, each a token list; quotes come off, backslashes stay."""
    segments, tokens, current, quote, i = [], [], "", "", 0
    pipes = []
    while i < len(text):
        char = text[i]
        if quote:
            if char == quote:
                quote = ""
            else:
                current += char
            i += 1
            continue
        if char in "'\"":
            quote = char
            i += 1
            continue
        match = SEPARATOR.match(text, i)
        if match:
            if current:
                tokens.append(current)
                current = ""
            segments.append(tokens)
            pipes.append(match.group(0) == "|")
            tokens = []
            i = match.end()
            continue
        if char.isspace():
            if current:
                tokens.append(current)
                current = ""
        elif char in "(){}`" or (char == "$" and text[i:i + 2] == "$("):
            # A command substitution, or a PowerShell block, reads as a command of its own; a
            # block goes on the pipeline that feeds it (`... | ForEach-Object { Stop-Process }`).
            if current:
                tokens.append(current)
                current = ""
            segments.append(tokens)
            pipes.append(char in "{}")
            tokens = []
            i += 2 if char == "$" else 1
            continue
        else:
            current += char
        i += 1
    if current:
        tokens.append(current)
    segments.append(tokens)
    pipes.append(False)
    # Each segment, and whether it pipes into the next one.
    return [(tokens, pipes[i]) for i, tokens in enumerate(segments) if tokens or pipes[i]]


ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
PS_ASSIGNMENT = re.compile(r"^\$env:([A-Za-z_][A-Za-z0-9_]*)=?(.*)$", re.I)
WRAPPERS = {"sudo", "command", "exec", "env", "nohup", "time", "&", "."}


def strip_prefix(tokens):
    """The command name and its arguments, past `sudo`, `env` and `NAME=value` prefixes."""
    env = {}
    rest = list(tokens)
    while rest:
        match = ASSIGNMENT.match(rest[0])
        if match:
            env[match.group(1)] = match.group(2)
        elif rest[0].lower() not in WRAPPERS:
            break
        rest.pop(0)
    if not rest:
        return "", [], env
    name = Path(norm(rest[0])).name.lower()
    return (name[:-4] if name.endswith(".exe") else name), rest[1:], env


def flag(arg):
    """`/PID`, `//pid` and `-pid` all read `pid`; any other argument reads None."""
    match = re.match(r"^(?:/{1,2}|-{1,2})([A-Za-z?]+)$", arg)
    return match.group(1).lower() if match else None


def kill_selectors(command):
    """What a command would stop: [("pid", n) | ("name", glob) | ("regex", pattern, on_cmdline,
    whole, ignore_case) | ("port", n) | ("tree", n)], from every simple command in it."""
    segments = split_command(command)
    selectors = []
    names = [strip_prefix(tokens)[0] for tokens, _ in segments]
    kills = {"kill", "pkill", "killall", "taskkill", "stop-process", "spps", "xargs", "fuser"}
    has_kill = any(name in kills for name in names)
    for index, (tokens, _) in enumerate(segments):
        name, args, _ = strip_prefix(tokens)
        if name == "xargs":
            name, args, _ = strip_prefix(args)
        if name == "kill" and any(a.lower() in ("-id", "-name", "-processname") for a in args):
            name = "stop-process"
        if name == "kill":
            skip = False
            for arg in args:
                if skip:
                    skip = False
                elif arg in ("-s", "-n"):
                    skip = True
                elif re.fullmatch(r"\d+", arg):
                    selectors.append(("pid", int(arg)))
        elif name in ("pkill", "pgrep") and (name == "pkill" or has_kill):
            on_cmdline = whole = ignore_case = False
            pattern, skip = None, False
            for arg in args:
                if skip:
                    skip = False
                elif arg in ("-u", "-U", "-g", "-G", "-P", "-s", "-t", "--signal", "-F", "--pidfile"):
                    skip = True
                elif arg.startswith("-") and len(arg) > 1:
                    on_cmdline |= "f" in arg[1:] and not arg.startswith("--") or arg == "--full"
                    whole |= "x" in arg[1:] and not arg.startswith("--") or arg == "--exact"
                    ignore_case |= "i" in arg[1:] and not arg.startswith("--") or arg == "--ignore-case"
                else:
                    pattern = arg
            if pattern:
                selectors.append(("regex", pattern, on_cmdline, whole, ignore_case))
        elif name == "pidof" and has_kill:
            selectors.extend(("name", arg.lower()) for arg in args if not arg.startswith("-"))
        elif name == "killall":
            is_regex = any(arg in ("-r", "--regexp") for arg in args)
            for arg in args:
                if not arg.startswith("-"):
                    selectors.append(("regex", arg, False, True, False) if is_regex else ("name", arg.lower()))
        elif name == "taskkill":
            is_tree = any(flag(arg) == "t" for arg in args)
            for i, arg in enumerate(args):
                value = args[i + 1] if i + 1 < len(args) else ""
                if flag(arg) == "pid" and value.isdigit():
                    selectors.append(("tree" if is_tree else "pid", int(value)))
                elif flag(arg) == "im" and value:
                    selectors.append(("name", value.lower()))
                elif flag(arg) == "fi":
                    match = re.match(r"^\s*(imagename|pid)\s+eq\s+(\S+)\s*$", value, re.I)
                    if match and match.group(1).lower() == "pid" and match.group(2).isdigit():
                        selectors.append(("pid", int(match.group(2))))
                    elif match:
                        selectors.append(("name", match.group(2).lower()))
        elif name in ("stop-process", "spps"):
            found = False
            mode = "id"
            for arg in args:
                lower = arg.lower()
                if lower in ("-id",):
                    mode = "id"
                elif lower in ("-name", "-processname"):
                    mode = "name"
                elif lower.startswith("-"):
                    continue
                elif not arg.startswith("$"):
                    for value in filter(None, arg.split(",")):
                        if mode == "id" and value.isdigit():
                            selectors.append(("pid", int(value)))
                            found = True
                        elif mode == "name" or not value.isdigit():
                            selectors.append(("name", value.lower()))
                            found = True
            if not found:
                selectors.extend(piped_selectors(segments, index))
        elif name == "fuser" and any(arg in ("-k", "--kill") or re.fullmatch(r"-\w*k\w*", arg) for arg in args):
            for arg in args:
                match = re.fullmatch(r"(\d+)/tcp", arg)
                if match:
                    selectors.append(("port", int(match.group(1))))
        elif name == "lsof" and has_kill:
            for arg in args:
                match = re.search(r":(\d{2,5})$", arg)
                if match:
                    selectors.append(("port", int(match.group(1))))
    return selectors


def piped_selectors(segments, index):
    """What feeds a bare `Stop-Process`: the `Get-Process` names or `Get-NetTCPConnection` ports
    earlier in its pipeline, or the quoted globs a `Where-Object` filter names."""
    found = []
    i = index - 1
    while i >= 0 and segments[i][1]:
        name, args, _ = strip_prefix(segments[i][0])
        if name in ("get-process", "gps", "ps"):
            mode = "name"
            for arg in args:
                if arg.lower() == "-id":
                    mode = "id"
                elif arg.lower() in ("-name", "-processname"):
                    mode = "name"
                elif not arg.startswith("-"):
                    for value in filter(None, arg.split(",")):
                        found.append(("pid", int(value)) if mode == "id" and value.isdigit() else ("name", value.lower()))
        elif name == "get-nettcpconnection":
            for j, arg in enumerate(args):
                if arg.lower() == "-localport" and j + 1 < len(args):
                    found.extend(("port", int(v)) for v in args[j + 1].split(",") if v.isdigit())
        else:
            found.extend(("name", arg.lower()) for arg in args if "*" in arg and not arg.startswith("-"))
        i -= 1
    return found


def matched_pids(snap, selectors):
    """The processes `selectors` reach, with what `taskkill /T` takes along."""
    hit = set()
    for selector in selectors:
        kind = selector[0]
        if kind in ("pid", "tree") and selector[1] in snap.procs:
            hit.add(selector[1])
            if kind == "tree":
                hit.update(snap.descendants(selector[1]))
        elif kind == "name":
            glob = selector[1][:-4] if selector[1].endswith(".exe") else selector[1]
            hit.update(pid for pid, proc in snap.procs.items() if fnmatch.fnmatchcase(proc_name(proc), glob))
        elif kind == "regex":
            _, pattern, on_cmdline, whole, ignore_case = selector
            try:
                regex = re.compile(pattern, re.I if ignore_case else 0)
            except re.error:
                continue
            for pid, proc in snap.procs.items():
                subject = cmdline_text(proc) if on_cmdline else str(proc.get("name") or proc_name(proc))
                if (regex.fullmatch if whole else regex.search)(subject):
                    hit.add(pid)
    return hit


def start_target(command, cwd):
    """The AppHost project a command starts, with its launch profile and the URLs it sets."""
    cwd = norm(cwd)
    env = {}
    for tokens, _ in split_command(command):
        assignment = PS_ASSIGNMENT.match(tokens[0]) if tokens else None
        if assignment:
            # `$env:NAME="value"` is one token; `$env:NAME = "value"` is three.
            env[assignment.group(1)] = assignment.group(2) or tokens[-1]
            continue
        name, args, assigned = strip_prefix(tokens)
        env.update(assigned)
        if name in ("cd", "set-location", "pushd", "sl", "chdir") and args:
            cwd = resolve(cwd, args[-1])
            continue
        verbs = [arg.lower() for arg in args if not arg.startswith("-")]
        is_dotnet = name == "dotnet" and verbs[:1] in (["run"], ["watch"])
        is_aspire = name == "aspire" and verbs[:1] in (["run"], ["start"])
        if not (is_dotnet or is_aspire):
            continue
        project, profile, no_profile = None, None, False
        for i, arg in enumerate(args):
            value = args[i + 1] if i + 1 < len(args) else ""
            key, _, inline = arg.partition("=")
            if key in ("--project", "-p", "--apphost"):
                project = inline or value
            elif key in ("--launch-profile", "-lp"):
                profile = inline or value
            elif arg == "--no-launch-profile":
                no_profile = True
            elif key == "--urls":
                env["ASPNETCORE_URLS"] = inline or value
        if project:
            folder = resolve(cwd, project)
            folder = norm(Path(folder).parent) if folder.lower().endswith(".csproj") else folder
        elif is_aspire:
            folder = find_apphost(cwd)
        else:
            folder = cwd
        if folder and is_apphost_dir(folder, {}):
            return {"projectDir": folder, "profile": profile, "noProfile": no_profile, "env": env}
    return None


def resolve(cwd, path):
    path = norm(path).strip()
    if re.match(r"^([a-zA-Z]:)?/", path):
        return norm(os.path.normpath(path)).replace("\\", "/")
    if path.startswith("~"):
        return norm(os.path.expanduser(path))
    return norm(os.path.normpath(os.path.join(cwd, path)))


def find_apphost(cwd):
    """The AppHost `aspire run` picks from a folder: the one its settings name (`aspire.config.json`
    from Aspire 13, `.aspire/settings.json` before it), else the only one beneath it."""
    for folder in (Path(cwd), *Path(cwd).parents):
        config = read_json(folder / "aspire.config.json") or {}
        settings = read_json(folder / ".aspire" / "settings.json") or {}
        named = (config.get("appHost") or {}).get("path") if isinstance(config.get("appHost"), dict) else None
        base, path = (norm(folder), named) if named else (norm(folder / ".aspire"), settings.get("appHostPath"))
        if path:
            target = resolve(base, path)
            return norm(Path(target).parent) if target.lower().endswith(".csproj") else target
    found = []
    base = Path(cwd)
    for current, dirs, files in os.walk(base):
        depth = len(Path(current).relative_to(base).parts)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and depth < 4]
        if any(f.endswith(".csproj") for f in files) and is_apphost_dir(current, {}):
            found.append(norm(current))
    return found[0] if len(found) == 1 else None


# --- judging a command -------------------------------------------------------------------

def owner(entry):
    return entry.get("label") or entry.get("branch") or "another session"


def describe(entry):
    return f"{entry.get('project')} (pid {entry.get('pid')}) · {owner(entry)}"


def check(command, cwd, me, snap, entries, folder, now):
    """Why the command must not run, or None; an allowed start leaves this session's claim."""
    others = [e for e in entries if not e.get("isMine") and not e.get("isStale")]
    mine = [e for e in entries if e.get("isMine")]

    selectors = kill_selectors(command)
    if selectors and others:
        hit = matched_pids(snap, selectors)
        ports = {s[1] for s in selectors if s[0] == "port"}
        struck = [e for e in others if hit & set(e.get("pids") or []) or ports & set((e.get("ports") or []) + (e.get("launchPorts") or []))]
        if struck:
            lines = "\n".join(f"  · {describe(e)}" for e in struck)
            own = ", ".join(f"{e['project']} is pid {e['pid']}" for e in mine)
            return (
                "Blocked by dotnet-workflow-kit: this would also stop AppHosts other Claude sessions own:\n"
                f"{lines}\n"
                f"Stop only this session's own processes, by pid{f' ({own})' if own else ''}. "
                "To have one of these stopped, message its session or ask the person."
            )

    target = start_target(command, cwd)
    if not target:
        return None
    folder_key = target["projectDir"]
    for entry in others:
        if same_path(entry.get("projectDir"), folder_key):
            return (
                f"Blocked by dotnet-workflow-kit: {entry.get('project')} in this folder already runs for "
                f"{owner(entry)} (pid {entry.get('pid')}). Starting it again stops that copy (the Aspire CLI "
                "stops a running instance of the same AppHost); work from a worktree of your own, or message "
                "that session."
            )
    use_profile = not target["noProfile"] or ignores_no_profile(folder_key)
    env = launch_env(folder_key, target["profile"], target["env"], use_profile=use_profile)
    wanted = set(ports_in(env))
    for entry in others:
        held = sorted(wanted & set((entry.get("ports") or []) + (entry.get("launchPorts") or [])))
        if held:
            names = ", ".join(str(port) for port in held)
            return (
                f"Blocked by dotnet-workflow-kit: port{'s' if len(held) > 1 else ''} {names} "
                f"{'are' if len(held) > 1 else 'is'} held by {entry.get('project')}, which {owner(entry)} owns "
                f"(pid {entry.get('pid')}). Give this worktree ports of its own: add a launch profile with other "
                "ports to its Properties/launchSettings.json and start with --launch-profile <name>; URLs set on "
                "the command lose to the profile's. Or message that session."
            )
    write_json(claim_path(folder, folder_key), {"session": me["session"], "projectDir": folder_key, "at": now})
    return None


# --- the command line --------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("action", choices=("scan", "check"))
    parser.add_argument("--dir", default=str(DEFAULT_DIR))
    parser.add_argument("--session", required=True)
    parser.add_argument("--root", default="")
    parser.add_argument("--repo", default="")
    parser.add_argument("--branch", default="")
    parser.add_argument("--label", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--command", default="")
    parser.add_argument("--snapshot", default="")
    parser.add_argument("--now", type=float, default=None)
    args = parser.parse_args(argv)

    now = args.now if args.now is not None else time.time()
    me = {"session": args.session, "root": norm(args.root), "repo": norm(args.repo),
          "branch": args.branch, "label": args.label}
    snap = take_snapshot(args.snapshot or None)
    entries = scan(args.dir, me, snap, now)
    result = {"entries": entries}
    if args.action == "check":
        cwd = args.cwd or args.root
        deny = check(args.command, cwd, me, snap, entries, args.dir, now)
        if deny:
            result["deny"] = deny
        else:
            target = start_target(args.command, cwd)
            if target:
                result["starts"] = target["projectDir"]
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
