#!/usr/bin/env python3
"""Which copy of each tool actually runs, and what it beat, on any Unix host.

The shadowing problem is not WSL's. It is the same shape everywhere and the
cause differs by platform:

  version managers  nvm, pyenv, rbenv, asdf and conda all work by putting a
                    shim ahead of the system copy. That is the intended
                    behaviour until two of them fight, or a shim points at an
                    uninstalled version and resolves to nothing.
  package managers  Homebrew on Apple silicon installs to /opt/homebrew, on
                    Intel to /usr/local, and the system copies stay in /usr/bin.
                    Which one wins depends on PATH order nobody set deliberately.
  WSL interop       Windows directories are appended to the Linux PATH and
                    Windows executables are reachable, so a command can resolve
                    to a Windows program with Windows path semantics.
  broken links      Docker Desktop and similar integrations drop symlinks into
                    the Linux filesystem pointing at paths that exist only while
                    the integration is running. The directory listing shows the
                    tool. Running it finds nothing.

All four produce the same symptom and none of them announce themselves.
"""
import json
import os
import platform
import re
import stat
import sys

WATCHLIST = [
    "node", "npm", "npx", "yarn", "pnpm", "bun", "deno", "tsc",
    "python", "python3", "pip", "pip3", "poetry", "uv",
    "ruby", "gem", "bundle", "go", "cargo", "rustc",
    "java", "mvn", "gradle", "git", "gh", "make", "cmake",
    "docker", "kubectl", "helm", "terraform", "aws", "psql", "redis-cli",
]

WINDOWS_EXTENSIONS = [".exe", ".cmd", ".bat", ".ps1"]

# Directory patterns that explain WHY a copy is where it is.
ORIGINS = [
    (re.compile(r"/\.nvm/"), "nvm", "version manager"),
    (re.compile(r"/\.pyenv/"), "pyenv", "version manager"),
    (re.compile(r"/\.rbenv/"), "rbenv", "version manager"),
    (re.compile(r"/\.asdf/"), "asdf", "version manager"),
    (re.compile(r"/\.rye/|/\.local/share/rye/"), "rye", "version manager"),
    (re.compile(r"/(mini)?conda3?/|/anaconda3?/"), "conda", "version manager"),
    (re.compile(r"/\.volta/"), "volta", "version manager"),
    (re.compile(r"/\.fnm/|/fnm_multishells/"), "fnm", "version manager"),
    (re.compile(r"^/opt/homebrew/"), "homebrew (apple silicon)", "package manager"),
    (re.compile(r"^/usr/local/(bin|opt)/"), "usr-local or homebrew (intel)", "package manager"),
    (re.compile(r"^/home/linuxbrew/"), "linuxbrew", "package manager"),
    (re.compile(r"^/snap/"), "snap", "package manager"),
    (re.compile(r"^/var/lib/flatpak/|/\.local/share/flatpak/"), "flatpak", "package manager"),
    (re.compile(r"^/mnt/[a-z]/"), "windows filesystem", "wsl interop"),
    (re.compile(r"^/mnt/wsl/"), "wsl integration mount", "wsl interop"),
    (re.compile(r"^/(usr/)?s?bin/"), "system", "system"),
    (re.compile(r"/\.cargo/bin/"), "cargo", "language toolchain"),
    (re.compile(r"/\.local/bin/"), "user-local", "user"),
    (re.compile(r"/\.rote/bin/"), "rote bundled runtime", "tool-managed"),
]


def classify_dir(directory):
    normalised = directory.replace("\\", "/")
    for pattern, origin, kind in ORIGINS:
        if pattern.search(normalised + "/"):
            return origin, kind
    return "other", "other"


def is_windows_path(directory):
    normalised = directory.replace("\\", "/")
    return normalised == "/mnt" or normalised.startswith("/mnt/")


def runnable(path):
    try:
        info = os.stat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and os.access(path, os.X_OK)


def dangling(path):
    return os.path.islink(path) and not os.path.exists(path)


def host():
    system = platform.system()
    release = platform.release()
    lowered = release.lower()
    if "microsoft" in lowered:
        flavour = "wsl2" if "wsl2" in lowered else "wsl"
    elif system == "Darwin":
        flavour = "macos"
    elif system == "Linux":
        flavour = "linux"
    else:
        flavour = system.lower() or "unknown"
    return {"flavour": flavour, "system": system, "release": release,
            "machine": platform.machine()}


def path_entries():
    override = ""
    if len(sys.argv) > 2 and sys.argv[2].strip() and not sys.argv[2].startswith("$"):
        override = sys.argv[2].strip()
    raw = override or os.environ.get("PATH", "")
    seen, entries = {}, []
    for index, directory in enumerate(raw.split(os.pathsep)):
        if not directory:
            continue
        duplicate = directory in seen
        if not duplicate:
            seen[directory] = index
        origin, kind = classify_dir(directory)
        entries.append({
            "index": index, "path": directory, "exists": os.path.isdir(directory),
            "origin": origin, "origin_kind": kind,
            "windows": is_windows_path(directory),
            "duplicate_of": seen[directory] if duplicate else None,
        })
    return entries, bool(override)


def extra_commands():
    if len(sys.argv) < 2:
        return []
    raw = sys.argv[1].strip()
    if not raw or raw.startswith("$"):
        return []
    return [n.strip() for n in raw.split(",") if n.strip()]


def scan(command, entries):
    bare, win_ext, broken = [], [], []
    for entry in entries:
        if not entry["exists"]:
            continue
        exact = os.path.join(entry["path"], command)
        if dangling(exact):
            broken.append({"path": exact, "target": os.readlink(exact),
                           "origin": entry["origin"], "path_index": entry["index"]})
        elif runnable(exact):
            bare.append({"path": exact, "origin": entry["origin"],
                         "origin_kind": entry["origin_kind"],
                         "windows": entry["windows"], "path_index": entry["index"]})
        for extension in WINDOWS_EXTENSIONS:
            candidate = os.path.join(entry["path"], command + extension)
            if runnable(candidate):
                win_ext.append({"path": candidate, "extension": extension,
                                "path_index": entry["index"]})
                break
    return bare, win_ext, broken


def main():
    entries, supplied = path_entries()
    info = host()
    watchlist = WATCHLIST + [c for c in extra_commands() if c not in WATCHLIST]

    commands, findings = [], []
    for command in watchlist:
        bare, win_ext, broken = scan(command, entries)
        winner = bare[0] if bare else None
        others = bare[1:]

        if winner is None and win_ext:
            verdict = "windows_exe_only"
        elif winner is None:
            verdict = "absent"
        elif winner["windows"] and any(not h["windows"] for h in others):
            verdict = "windows_shadows_native"
        elif winner["windows"]:
            verdict = "windows_only"
        elif others:
            verdict = "shadowed"
        else:
            verdict = "single"

        commands.append({"command": command, "verdict": verdict,
                         "resolves_to": winner["path"] if winner else None,
                         "origin": winner["origin"] if winner else None,
                         "bare_hits": bare, "windows_extension_hits": win_ext,
                         "broken_links": broken})

        for link in broken:
            findings.append({
                "severity": "high", "command": command, "kind": "broken_link",
                "path": link["path"], "target": link["target"],
                "detail": ("On PATH but the symlink target is missing. Typical of an "
                           "integration that only populates its mount while running."),
            })
        if verdict == "windows_shadows_native":
            findings.append({
                "severity": "high", "command": command, "kind": "windows_shadows_native",
                "path": winner["path"],
                "shadowed": [h["path"] for h in others if not h["windows"]],
                "detail": "A Windows copy wins over an installed native copy.",
            })
        elif verdict == "windows_only":
            findings.append({
                "severity": "medium", "command": command, "kind": "windows_only",
                "path": winner["path"],
                "detail": "Resolves to a Windows program, with Windows path semantics.",
            })
        elif verdict == "windows_exe_only":
            findings.append({
                "severity": "medium", "command": command, "kind": "windows_exe_only",
                "path": win_ext[0]["path"],
                "detail": ("Not runnable as a bare name, but a Windows executable is on "
                           "PATH. The shell says command not found about an installed tool."),
            })
        elif verdict == "shadowed":
            kinds = {h["origin_kind"] for h in bare}
            managers = [h["origin"] for h in bare if h["origin_kind"] == "version manager"]
            severity = "medium" if len(set(managers)) > 1 or "version manager" in kinds else "low"
            findings.append({
                "severity": severity, "command": command, "kind": "shadowed",
                "path": winner["path"], "origin": winner["origin"],
                "shadowed": ["%s (%s)" % (h["path"], h["origin"]) for h in others],
                "detail": ("%s wins; %d other cop%s on PATH."
                           % (winner["origin"], len(others), "y" if len(others) == 1 else "ies")),
            })

    for entry in entries:
        if entry["duplicate_of"] is not None:
            findings.append({"severity": "low", "command": None,
                             "kind": "duplicate_path_entry", "path": entry["path"],
                             "detail": "Duplicate PATH entry, usually an unguarded rc append."})

    # A manager directory that is on PATH but gone is the "shim points at a
    # version you uninstalled" case this play exists to name, and it used to
    # vanish from the report entirely: the summary below filters managers to
    # the ones that exist, so a stale entry was dropped rather than reported.
    # Grouped by manager rather than one finding per entry. A PATH carrying 800
    # dead pyenv directories is one problem told 800 times, and printing it
    # that way buries every other finding in the report.
    stale = {}
    for entry in entries:
        if entry["exists"] or entry["origin_kind"] not in ("version manager",
                                                           "package manager"):
            continue
        stale.setdefault(entry["origin"], []).append(entry["path"])
    for origin in sorted(stale):
        paths = stale[origin]
        findings.append({
            "severity": "medium", "command": None,
            "kind": "stale_manager_entry", "path": paths[0],
            "origin": origin, "entry_count": len(paths),
            "examples": paths[:3],
            "detail": ("%s has %d director%s on PATH that do not exist, so every "
                       "lookup walks past %s. Either it was removed, or a version "
                       "it pinned was, and a startup file still adds the path."
                       % (origin, len(paths), "y" if len(paths) == 1 else "ies",
                          "it" if len(paths) == 1 else "them")),
        })

    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order.get(f["severity"], 9), f["kind"], f["command"] or ""))
    managers = sorted({e["origin"] for e in entries
                       if e["origin_kind"] == "version manager" and e["exists"]})

    # rote truncates a process step's stdout at 65536 bytes, silently and mid
    # JSON, and the step that consumes it then fails to parse. This output
    # scales with PATH entries times watched commands: 26 KB at 37 entries on
    # the machine it was written on, 77 KB at 40 entries whose directories all
    # hold the watched tools. So it is trimmed to a budget before printing,
    # least useful detail first, and any reduction is named in the payload
    # rather than left for the reader to notice.
    BUDGET = 48000

    def emit(cmds, detail):
        commands = cmds
        return json.dumps({
        "probe": "shadow", "host": info,
        "path_source": "supplied" if supplied else "inherited",
        "path_entry_count": len(entries),
        "windows_entry_count": sum(1 for e in entries if e["windows"]),
        "duplicate_entry_count": sum(1 for e in entries if e["duplicate_of"] is not None),
        "missing_entries": [e["path"] for e in entries if not e["exists"]],
        "version_managers_on_path": managers,
        "commands": commands,
            "detail_level": detail, "findings": findings,
    }, indent=2, sort_keys=True)

    detail = "full"
    text = emit(commands, detail)
    if len(text) > BUDGET:
        commands = [dict(c, bare_hits=c["bare_hits"][:1],
                         windows_extension_hits=c["windows_extension_hits"][:1])
                    for c in commands]
        detail = "hits trimmed to the winning copy per command"
        text = emit(commands, detail)
    if len(text) > BUDGET:
        flagged = {f.get("command") for f in findings}
        commands = [c for c in commands if c["command"] in flagged]
        detail = "only commands with a finding are listed"
        text = emit(commands, detail)
    if len(text) > BUDGET:
        # The findings themselves can dominate on a pathological PATH: one
        # duplicate entry finding per repeat, and a long shadowed list per
        # command. Collapse the repeats into a single counted finding and cap
        # the lists, then drop the least severe findings until it fits. Every
        # reduction is named, because a report that quietly stopped listing
        # things is worse than one that says it ran out of room.
        dupes = [f for f in findings if f.get("kind") == "duplicate_path_entry"]
        if len(dupes) > 3:
            findings = [f for f in findings if f.get("kind") != "duplicate_path_entry"]
            findings.append({
                "severity": "low", "command": None, "kind": "duplicate_path_entry",
                "path": "%d duplicate PATH entries" % len(dupes),
                "detail": ("%d duplicate PATH entries, listed as a count rather than "
                           "individually. Usually an rc file appended in a loop."
                           % len(dupes)),
            })
        findings = [dict(f, shadowed=(f.get("shadowed") or [])[:3]) if f.get("shadowed") else f
                    for f in findings]
        detail = "findings condensed; duplicate PATH entries counted, not listed"
        commands = []
        text = emit(commands, detail)
    while len(text) > BUDGET and len(findings) > 5:
        findings = findings[:max(5, int(len(findings) * 0.8))]
        detail = "output exceeded its budget; only the %d most severe findings are shown" % len(findings)
        text = emit(commands, detail)
    print(text)



if __name__ == "__main__":
    main()
