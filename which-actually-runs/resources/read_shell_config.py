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

# A denylist of five words was the wrong shape for this. SSH_PRIVATE_KEY,
# OPENAI_KEY, NPM_AUTH, STRIPE_SK and DATABASE_URL all walked straight past it
# into the report, and no list of words is going to keep up with the names
# people actually use. So the rule is inverted: an assignment is echoed only
# when its name is one this play recognises as harmless, and every other
# assignment is reported as present without its value.
# Names that legitimately appear in a startup file and carry no secret. These
# are the ones worth showing, because they explain PATH.
SAFE_NAMES = set("""PATH MANPATH INFOPATH LD_LIBRARY_PATH PKG_CONFIG_PATH
CDPATH FPATH GOPATH GOROOT GOBIN JAVA_HOME MAVEN_HOME GRADLE_HOME ANDROID_HOME
NVM_DIR PYENV_ROOT RBENV_ROOT ASDF_DIR CARGO_HOME RUSTUP_HOME VOLTA_HOME
CONDA_PREFIX HOMEBREW_PREFIX EDITOR VISUAL PAGER LANG LC_ALL TERM SHELL HOME
PS1 PROMPT HISTSIZE HISTFILESIZE HISTCONTROL TZ XDG_CONFIG_HOME XDG_DATA_HOME
XDG_CACHE_HOME NODE_ENV PYTHONPATH VIRTUAL_ENV DOCKER_HOST""".split())

ASSIGNMENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=")


def has_secret(line):
    """True when the line assigns something whose value must not be echoed.

    Allowlist first: an assignment to a name this play knows is about paths or
    shell behaviour is safe to print. Anything else is treated as a secret,
    including names nobody thought of, which is the point.
    """
    for name in ASSIGNMENT.findall(line or ""):
        if name.upper() in SAFE_NAMES:
            continue
        return True
    return False


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
                            if has_secret(line) else line.strip()[:160],
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
        # places holds one entry per matching line, and the stock nvm and pyenv
        # blocks are two lines in a single file. Counting lines here reported a
        # normal single-file install as a conflict, so count the files.
        homes = sorted({place.rsplit(":", 1)[0] for place in places})
        if len(homes) > 1:
            findings.append({
                "severity": "medium", "kind": "manager_initialized_twice",
                "manager": manager, "places": places, "files": homes,
                "detail": ("%s is initialised in %d startup files (%s). Each one "
                           "prepends its shim directory, so the effective PATH depends on "
                           "which files this shell actually read."
                           % (manager, len(homes), ", ".join(homes))),
            })
    # probe_shadow classifies cargo as a language toolchain, not a version
    # manager, and this list has to agree with it or the two halves of the
    # report contradict each other.
    NOT_A_VERSION_MANAGER = {"cargo", "homebrew"}
    version_managers = {m: p for m, p in managers.items()
                        if m not in NOT_A_VERSION_MANAGER}
    if len(version_managers) > 1:
        overlapping = sorted(version_managers)
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

    # rote cuts a process step's stdout at 65536 bytes without saying so, and
    # this output scales with the size of the startup files. A 45 KB .bashrc
    # produced 122 KB here, the render step got half a document, and the whole
    # PATH-origin half of the report vanished while the stage still said ok.
    # So it is trimmed to a budget, least useful detail first, and every
    # reduction is named in the payload.
    BUDGET = 48000

    def emit(lines_shown, files_shown, detail):
        return json.dumps({
            "probe": "shell_config",
            "files_present": [f["file"] for f in files],
            "files": files_shown,
            "managers": managers,
            "path_lines": lines_shown,
            "path_line_total": len(path_lines),
            "detail_level": detail,
            "findings": findings,
        }, indent=2, sort_keys=True)

    detail = "full"
    text = emit(path_lines, files, detail)
    if len(text) > BUDGET:
        # The per-file bodies are the bulk and the least useful part: the
        # findings and the PATH lines carry the answer.
        slim = [{k: v for k, v in f.items() if k != "sources"} for f in files]
        detail = "source lines per file omitted"
        text = emit(path_lines, slim, detail)
        files = slim
    if len(text) > BUDGET:
        detail = "PATH lines trimmed to the first 60"
        text = emit(path_lines[:60], files, detail)
    if len(text) > BUDGET:
        detail = "only the findings and the list of files are reported"
        text = emit([], [], detail)
    print(text)


if __name__ == "__main__":
    main()
