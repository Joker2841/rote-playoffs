#!/usr/bin/env python3
"""Probe: what is actually using the space inside the distro.

Every target is measured with its own timeout and degrades to a labelled
unknown, because du on a large tree can be slow and a diagnostic that hangs is
worse than one that admits it did not finish. Nothing is deleted here: each
finding carries the command that would reclaim it, for a person to run.
"""
import json
import os
import subprocess
import sys

# label, path, the command that reclaims it, whether it is safe to suggest freely
TARGETS = [
    ("apt package cache", "/var/cache/apt", "sudo apt clean", True),
    ("apt lists", "/var/lib/apt/lists", "sudo apt clean", True),
    ("systemd journal", "/var/log/journal", "sudo journalctl --vacuum-size=200M", True),
    ("user cache", "~/.cache", "review ~/.cache; it is safe to clear but tools will rebuild", False),
    ("pip cache", "~/.cache/pip", "pip cache purge", True),
    ("npm cache", "~/.npm", "npm cache clean --force", True),
    ("playwright browsers", "~/.cache/ms-playwright", "remove unused browser builds", False),
    ("cargo registry", "~/.cargo/registry", "cargo cache is safe to clear; crates re-download", False),
    ("go module cache", "~/go/pkg/mod", "go clean -modcache", False),
    ("docker (in-distro)", "/var/lib/docker", "docker system prune", False),
    ("snap revisions", "/var/lib/snapd/snaps", "remove old snap revisions", False),
    ("trash", "~/.local/share/Trash", "empty the trash", True),
]

DEFAULT_THRESHOLD_MB = 512


def argument(index, default):
    """Optional positional argument; an unresolved token means absent."""
    if len(sys.argv) <= index:
        return default
    raw = sys.argv[index].strip()
    return default if not raw or raw.startswith("$") else raw


def threshold_bytes():
    raw = argument(1, str(DEFAULT_THRESHOLD_MB))
    try:
        value = int(float(raw))
    except ValueError:
        value = DEFAULT_THRESHOLD_MB
    return max(0, value) * 1024 * 1024


def extra_targets():
    """Caller-supplied paths, measured alongside the built-in list.

    A node_modules tree or a dataset directory is often the real answer on a
    particular machine, and no fixed list can know where it lives.
    """
    raw = argument(2, "")
    targets = []
    for item in raw.split(","):
        item = item.strip()
        if item:
            targets.append((item, item, "review this path yourself", False))
    return targets


def measure(path, timeout=45):
    resolved = os.path.expanduser(path)
    if not os.path.exists(resolved):
        return {"state": "absent", "bytes": None}
    try:
        result = subprocess.run(["du", "-sb", "--one-file-system", resolved],
                                capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"state": "timed-out", "bytes": None}
    except (OSError, subprocess.SubprocessError):
        return {"state": "unknown", "bytes": None}
    if result.returncode != 0 and not result.stdout.strip():
        return {"state": "unreadable", "bytes": None}
    try:
        return {"state": "measured", "bytes": int(result.stdout.split()[0])}
    except (ValueError, IndexError):
        return {"state": "unknown", "bytes": None}


def main():
    consumers = []
    findings = []
    incomplete = []

    limit = threshold_bytes()
    for label, path, remedy, routine in TARGETS + extra_targets():
        measurement = measure(path)
        entry = {
            "label": label,
            "path": path,
            "state": measurement["state"],
            "bytes": measurement["bytes"],
            "remedy": remedy,
            "routine": routine,
        }
        consumers.append(entry)
        if measurement["state"] in ("timed-out", "unknown", "unreadable"):
            incomplete.append(label)
        elif measurement["bytes"] and measurement["bytes"] >= limit:
            findings.append({
                "severity": "medium" if measurement["bytes"] >= 2 * 1024 ** 3 else "low",
                "kind": "reclaimable_cache",
                "label": label,
                "path": path,
                "bytes": measurement["bytes"],
                "remedy": remedy,
                "routine": routine,
            })

    findings.sort(key=lambda f: -(f["bytes"] or 0))

    # Several targets nest: ~/.cache/pip and ~/.cache/ms-playwright both sit
    # inside ~/.cache. Summing every measurement counts those bytes twice and
    # invents free space that does not exist. Total only the outermost measured
    # paths, and mark the ones contained by another so the report can say so.
    measured = [c for c in consumers if c["state"] == "measured"]
    resolved = {c["label"]: os.path.realpath(os.path.expanduser(c["path"])) for c in measured}
    for consumer in measured:
        mine = resolved[consumer["label"]]
        consumer["contained_by"] = next(
            (other["label"] for other in measured
             if other is not consumer
             and mine.startswith(resolved[other["label"]].rstrip("/") + "/")),
            None,
        )
    for finding in findings:
        finding["contained_by"] = next(
            (c.get("contained_by") for c in measured if c["label"] == finding["label"]), None)

    measured_total = sum(c["bytes"] or 0 for c in measured if not c.get("contained_by"))

    print(json.dumps({
        "probe": "consumers",
        "threshold_bytes": limit,
        "measured_total_bytes": measured_total,
        "incomplete": incomplete,
        "consumers": consumers,
        "findings": findings,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
