#!/usr/bin/env python3
"""Probe 2: which copy of each tool actually wins, and which only look installed.

Correction from the first pass: bash does NOT append .exe when resolving a
bare command name. Only an exact filename resolves. That distinction is the
whole point of this probe, because it separates three situations that look
identical in a terminal:

  1. `docker` resolves to an extensionless Windows shim under /mnt/c. It runs,
     as a Windows program, with Windows path semantics.
  2. `psql` does not resolve at all, even though psql.exe sits on PATH. The
     shell says "command not found" while the tool is plainly installed on the
     machine, which is the single most confusing WSL symptom there is.
  3. `kubectl` is present in /usr/local/bin as a symlink into
     /mnt/wsl/docker-desktop/..., which only exists while Docker Desktop is
     running with WSL integration on. Listing the directory shows kubectl.
     Running it finds nothing.

Only the first is "shadowing" in the usual sense. Reporting all three the same
way, as the first version of this probe did, is wrong.
"""
import json
import os
import stat
import sys

WATCHLIST = [
    "node", "npm", "npx", "yarn", "pnpm", "tsc",
    "python", "python3", "pip", "pip3",
    "git", "gh", "docker", "kubectl", "helm", "terraform",
    "go", "cargo", "rustc", "java", "mvn", "gradle",
    "psql", "redis-cli", "aws", "code", "claude",
]

WINDOWS_EXTENSIONS = [".exe", ".cmd", ".bat", ".ps1"]


def classify(directory):
    normalised = directory.replace("\\", "/")
    if normalised == "/mnt" or normalised.startswith("/mnt/"):
        return "windows"
    return "linux"


def runnable(path):
    """True only if the shell could actually execute this exact path.

    os.access follows symlinks, so a dangling link correctly returns False.
    """
    try:
        info = os.stat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and os.access(path, os.X_OK)


def dangling(path):
    return os.path.islink(path) and not os.path.exists(path)


def path_entries():
    raw = os.environ.get("PATH", "")
    seen = {}
    entries = []
    for index, directory in enumerate(raw.split(os.pathsep)):
        if not directory:
            continue
        duplicate = directory in seen
        if not duplicate:
            seen[directory] = index
        entries.append({
            "index": index,
            "path": directory,
            "kind": classify(directory),
            "exists": os.path.isdir(directory),
            "duplicate_of": seen[directory] if duplicate else None,
        })
    return entries


def scan(command, entries):
    bare = []
    windows_ext = []
    broken = []
    for entry in entries:
        if not entry["exists"]:
            continue
        exact = os.path.join(entry["path"], command)
        if dangling(exact):
            broken.append({
                "path": exact,
                "target": os.readlink(exact),
                "path_index": entry["index"],
            })
        elif runnable(exact):
            bare.append({"path": exact, "kind": entry["kind"], "path_index": entry["index"]})
        for extension in WINDOWS_EXTENSIONS:
            candidate = os.path.join(entry["path"], command + extension)
            if runnable(candidate):
                windows_ext.append({
                    "path": candidate,
                    "kind": entry["kind"],
                    "path_index": entry["index"],
                    "extension": extension,
                })
                break
    return bare, windows_ext, broken


def extra_commands():
    """Optional comma-separated additions from the caller.

    An unresolved template token is treated as absent rather than as a command
    name, so the play still runs when the parameter is omitted.
    """
    if len(sys.argv) < 2:
        return []
    raw = sys.argv[1].strip()
    if not raw or raw.startswith("$"):
        return []
    return [name.strip() for name in raw.split(",") if name.strip()]


def main():
    entries = path_entries()
    commands = []
    findings = []

    watchlist = WATCHLIST + [c for c in extra_commands() if c not in WATCHLIST]
    for command in watchlist:
        bare, windows_ext, broken = scan(command, entries)
        winner = bare[0] if bare else None
        linux_copies = [hit["path"] for hit in bare if hit["kind"] == "linux"]

        if winner is None and windows_ext:
            verdict = "windows_exe_only"
        elif winner is None:
            verdict = "absent"
        elif winner["kind"] == "windows" and linux_copies:
            verdict = "windows_shadows_linux"
        elif winner["kind"] == "windows":
            verdict = "windows_only"
        elif len(linux_copies) > 1:
            verdict = "linux_multiple"
        else:
            verdict = "linux_ok"

        commands.append({
            "command": command,
            "verdict": verdict,
            "resolves_to": winner["path"] if winner else None,
            "bare_hits": bare,
            "windows_extension_hits": windows_ext,
            "broken_links": broken,
        })

        for link in broken:
            findings.append({
                "severity": "high",
                "command": command,
                "kind": "broken_integration_symlink",
                "detail": ("Listed on PATH but the symlink target is missing. "
                           "Typical of Docker Desktop or another WSL integration "
                           "that only populates /mnt/wsl while it is running."),
                "path": link["path"],
                "target": link["target"],
            })

        if verdict == "windows_shadows_linux":
            findings.append({
                "severity": "high",
                "command": command,
                "kind": "windows_shadows_linux",
                "detail": "A Windows copy wins over an installed Linux copy on PATH.",
                "path": winner["path"],
                "shadowed": linux_copies,
            })
        elif verdict == "windows_only":
            findings.append({
                "severity": "medium",
                "command": command,
                "kind": "windows_only",
                "detail": "Resolves to a Windows program. It runs, with Windows path semantics.",
                "path": winner["path"],
            })
        elif verdict == "windows_exe_only":
            findings.append({
                "severity": "medium",
                "command": command,
                "kind": "windows_exe_only",
                "detail": ("Not runnable as a bare command, but a Windows executable is on PATH. "
                           "The shell reports command not found while the tool is installed; "
                           "it only responds to the full name with its extension."),
                "path": windows_ext[0]["path"],
            })
        elif verdict == "linux_multiple":
            findings.append({
                "severity": "low",
                "command": command,
                "kind": "linux_multiple",
                "detail": "More than one Linux copy on PATH; the first one wins.",
                "path": winner["path"],
                "shadowed": linux_copies[1:],
            })

    for entry in entries:
        if entry["duplicate_of"] is not None:
            findings.append({
                "severity": "low",
                "command": None,
                "kind": "duplicate_path_entry",
                "detail": "Duplicate PATH entry, usually an unguarded shell rc append.",
                "path": entry["path"],
            })

    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order.get(f["severity"], 9), f["kind"], f["command"] or ""))

    print(json.dumps({
        "probe": "shadow",
        "path_entry_count": len(entries),
        "windows_entry_count": sum(1 for e in entries if e["kind"] == "windows"),
        "duplicate_entry_count": sum(1 for e in entries if e["duplicate_of"] is not None),
        "missing_entries": [e["path"] for e in entries if not e["exists"]],
        "commands": commands,
        "findings": findings,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
