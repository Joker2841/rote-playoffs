#!/usr/bin/env python3
"""Find which shell startup file put each directory on PATH.

Knowing that nvm wins over Homebrew is half an answer. The other half is which
line to edit, and that is not obvious once several files each prepend something:
a login shell reads a different set than an interactive one, and version manager
installers append their init line to whichever file they found first.

Read-only. It parses the text of these files and never sources them, so a
malformed or hostile rc file cannot execute anything here. It also never reports
the content of a line that assigns something secret-looking.
"""
import json
import os
import re

CANDIDATES = [
    "~/.bashrc", "~/.bash_profile", "~/.bash_login", "~/.profile",
    "~/.zshrc", "~/.zprofile", "~/.zshenv", "~/.zlogin",
    "~/.config/fish/config.fish", "~/.kshrc", "~/.cshrc",
]

PATH_ASSIGN = re.compile(r"""(?x)
    ^\s*(?:export\s+)?PATH\s*=            # bash/zsh assignment
  | ^\s*set\s+-gx?\s+PATH\b               # fish
  | ^\s*fish_add_path\b                   # fish helper
  | ^\s*path\+=                           # zsh array append
""")

INIT_LINES = [
    (re.compile(r"\bnvm\.sh\b|\bNVM_DIR\b"), "nvm"),
    (re.compile(r"\bpyenv\s+init\b|\bPYENV_ROOT\b"), "pyenv"),
    (re.compile(r"\brbenv\s+init\b"), "rbenv"),
    (re.compile(r"\basdf\.sh\b|\basdf\.fish\b"), "asdf"),
    (re.compile(r"\bconda\s+initialize\b|\bconda\.sh\b"), "conda"),
    (re.compile(r"\bbrew\s+shellenv\b"), "homebrew"),
    (re.compile(r"\bvolta\b"), "volta"),
    (re.compile(r"\bfnm\s+env\b"), "fnm"),
    (re.compile(r"\brye\b.*\benv\b"), "rye"),
    (re.compile(r"\bcargo/env\b"), "cargo"),
]

SECRET = re.compile(r"(?i)\b[A-Z0-9_]*(TOKEN|SECRET|PASSWORD|API_?KEY|CREDENTIAL)[A-Z0-9_]*\s*=")


def read(path):
    try:
        with open(os.path.expanduser(path), "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()
    except OSError:
        return None


def main():
    files, managers, path_lines = [], {}, []
    for candidate in CANDIDATES:
        lines = read(candidate)
        if lines is None:
            continue
        entry = {"file": candidate, "lines": len(lines), "path_assignments": 0,
                 "sources": [], "initializers": []}
        for number, raw in enumerate(lines, 1):
            line = raw.rstrip()
            if not line.strip() or line.strip().startswith("#"):
                continue
            if PATH_ASSIGN.search(line):
                entry["path_assignments"] += 1
                path_lines.append({
                    "file": candidate, "line": number,
                    # Never echo a line that assigns something secret-looking.
                    "text": "[redacted: line assigns a secret-looking name]"
                            if SECRET.search(line) else line.strip()[:160],
                })
            for pattern, manager in INIT_LINES:
                if pattern.search(line):
                    entry["initializers"].append({"manager": manager, "line": number})
                    managers.setdefault(manager, []).append("%s:%d" % (candidate, number))
            stripped = line.strip()
            if stripped.startswith(("source ", ". ")) and "nvm" not in stripped:
                entry["sources"].append(stripped[:120])
        files.append(entry)

    findings = []
    for manager, places in sorted(managers.items()):
        if len(places) > 1:
            findings.append({
                "severity": "medium", "kind": "manager_initialized_twice",
                "manager": manager, "places": places,
                "detail": ("%s is initialised in more than one startup file. Each one "
                           "prepends its shim directory, so the effective PATH depends on "
                           "which files this shell actually read." % manager),
            })
    if len(managers) > 1:
        overlapping = sorted(managers)
        findings.append({
            "severity": "medium", "kind": "multiple_version_managers",
            "managers": overlapping,
            "detail": ("More than one version manager initialises here: %s. Whichever "
                       "runs last wins, and that order is set by file, not by intent."
                       % ", ".join(overlapping)),
        })

    busiest = sorted(files, key=lambda f: -f["path_assignments"])
    for entry in busiest[:1]:
        if entry["path_assignments"] >= 4:
            findings.append({
                "severity": "low", "kind": "many_path_assignments",
                "file": entry["file"], "count": entry["path_assignments"],
                "detail": ("%d separate PATH assignments in one file. Each is a place a "
                           "duplicate or an unintended precedence can enter."
                           % entry["path_assignments"]),
            })

    print(json.dumps({
        "probe": "shell_config",
        "files_present": [f["file"] for f in files],
        "files": files,
        "managers": managers,
        "path_lines": path_lines,
        "findings": findings,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
