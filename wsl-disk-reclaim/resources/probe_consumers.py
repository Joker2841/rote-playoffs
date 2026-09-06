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
import time
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


EXTRA_PATH_LIMIT = 80


def threshold_bytes():
    raw = argument(1, str(DEFAULT_THRESHOLD_MB))
    try:
        value = int(float(raw))
    except (ValueError, OverflowError):
        # float("inf") parses fine and then fails to become an int.
        value = DEFAULT_THRESHOLD_MB
    return max(0, value) * 1024 * 1024


def extra_targets():
    """Caller-supplied paths, measured alongside the built-in list.

    A node_modules tree or a dataset directory is often the real answer on a
    particular machine, and no fixed list can know where it lives.
    """
    raw = argument(2, "")
    targets, seen = [], set()
    for item in raw.split(","):
        item = item.strip()
        # Duplicates in the list would each be measured and each be added to
        # the total. The containment rule below only catches a path inside
        # another, not the same path twice.
        if not item or item in seen:
            continue
        seen.add(item)
        targets.append((item, item, "review this path yourself", False))
    # Each extra path costs about 240 bytes of JSON, and rote cuts a step's
    # stdout at 65536 without saying so. Cap the list and report the cap rather
    # than emit a document that gets truncated mid-structure.
    if len(targets) > EXTRA_PATH_LIMIT:
        dropped = len(targets) - EXTRA_PATH_LIMIT
        targets = targets[:EXTRA_PATH_LIMIT]
        targets.append(("%d more extra paths were not measured" % dropped,
                        "", "raise the threshold or pass fewer paths", False))
    return targets


def measure(path, timeout=20):
    # realpath, not expanduser alone: du -sb reports a symlink's own size, a
    # handful of bytes, while the containment rule resolves it. Pointing
    # extra_paths at a symlinked dataset directory used to report 20 bytes.
    resolved = os.path.realpath(os.path.expanduser(path))
    if not os.path.exists(resolved):
        return {"state": "absent", "bytes": None}
    try:
        result = subprocess.run(["du", "-sb", "--one-file-system", resolved],
                                capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"state": "timed-out", "bytes": None}
    except (OSError, subprocess.SubprocessError):
        return {"state": "unknown", "bytes": None}
    # du prints a total on stdout AND exits non-zero when it could not read
    # part of the tree, so the presence of output does not mean the number is
    # complete. Reading /root this way returned "0" with exit 1, which the play
    # then reported as a measured zero. A partial answer is worse than none
    # here, because the whole report is a subtraction.
    partial = result.returncode != 0
    reason = " ".join((result.stderr or "").split())[:160]
    try:
        measured = int(result.stdout.split()[0])
    except (ValueError, IndexError):
        return {"state": "unreadable", "bytes": None,
                "detail": reason or "du exited %d" % result.returncode}
    # The plausibility check has to come before the partial branch, not after
    # it: du over /proc exits non-zero AND prints 128 TiB, so it took the
    # partial path and skipped the bound entirely, putting 128 TiB into the
    # headline.
    capacity = 0
    for probe_path in (resolved, "/"):
        try:
            stat_info = os.statvfs(probe_path)
            capacity = stat_info.f_blocks * stat_info.f_frsize
        except OSError:
            capacity = 0
        # A pseudo-filesystem reports zero blocks, which is exactly the case
        # this bound exists for, so fall back to the root filesystem rather
        # than treating "no capacity known" as "no limit".
        if capacity:
            break
    if capacity and measured > capacity:
        return {"state": "implausible", "bytes": None,
                "detail": ("du reported %d bytes, more than the %d-byte filesystem "
                           "holding it, so it is not real disk usage"
                           % (measured, capacity))}
    if partial:
        # du walked part of the tree and still printed a total. Reading /root
        # this way gives "0" with exit 1, and the apt caches give a real number
        # with a couple of unreadable subdirectories. The number is a floor,
        # not a measurement, so it is labelled and it is what the report shows
        # as a minimum. Understating what can be freed is the safe direction.
        if measured <= 0:
            return {"state": "unreadable", "bytes": None,
                    "detail": reason or "nothing readable in this tree"}
        return {"state": "partial", "bytes": measured,
                "detail": reason or "part of this tree could not be read"}
    # A pseudo-filesystem reports sizes that are not disk usage at all: du over
    # /proc returns about 128 TiB. Anything larger than the filesystem holding
    # it cannot be a real consumer, so it is refused rather than added.
    try:
        stat = os.statvfs(resolved)
        capacity = stat.f_blocks * stat.f_frsize
    except OSError:
        capacity = 0
    if capacity and measured > capacity:
        return {"state": "implausible", "bytes": None,
                "detail": ("du reported %d bytes, more than the %d-byte filesystem "
                           "holding it, so it is not real disk usage"
                           % (measured, capacity))}
    return {"state": "measured", "bytes": measured}


def main():
    consumers = []
    findings = []
    incomplete = []
    partial = []

    limit = threshold_bytes()
    # The step gets 300 seconds. Twelve built-in targets at 20 seconds each
    # already fits, but extra_paths can add 80 more, and a per-target timeout
    # does nothing once their sum passes the step's own budget: the step is
    # killed and the graceful "not measured" degradation never runs. So the
    # loop watches the clock and stops measuring while it can still report.
    WALL_BUDGET = 240.0
    started = time.time()
    for label, path, remedy, routine in TARGETS + extra_targets():
        left = WALL_BUDGET - (time.time() - started)
        if left <= 1.0:
            consumers.append({"label": label, "path": path, "state": "not-reached",
                              "bytes": None, "remedy": remedy, "routine": routine})
            incomplete.append("%s (ran out of time before it was measured)" % label)
            continue
        measurement = measure(path, timeout=max(1.0, min(20.0, left)))
        entry = {
            "label": label,
            "path": path,
            "state": measurement["state"],
            "bytes": measurement["bytes"],
            "remedy": remedy,
            "routine": routine,
        }
        consumers.append(entry)
        if measurement["state"] in ("timed-out", "unknown", "unreadable",
                                    "implausible", "not-reached"):
            incomplete.append(label)
        if measurement["state"] == "partial":
            # It has a usable number, so it belongs in the table with the
            # others, marked as a floor. Putting it in "incomplete" printed it
            # as n/a and threw the number away.
            partial.append(label)
        if measurement["bytes"] and measurement["bytes"] >= limit:
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
    measured = [c for c in consumers if c["state"] in ("measured", "partial")]
    resolved = [os.path.realpath(os.path.expanduser(c["path"])) for c in measured]
    for index, consumer in enumerate(measured):
        mine = resolved[index]
        owner = None
        for other in range(len(measured)):
            if other == index:
                continue
            theirs = resolved[other]
            # Strictly inside another measured path, or the same directory
            # reached by a different spelling. The second case is why an
            # extra_paths entry naming a directory already on the built-in
            # list used to add its bytes to the total twice: neither was
            # inside the other, so neither was excluded. On an exact match the
            # earlier entry keeps the bytes, so the choice is deterministic.
            if mine.startswith(theirs.rstrip("/") + "/") or (mine == theirs and other < index):
                owner = measured[other]["label"]
                break
        consumer["contained_by"] = owner
    contained = {c["label"]: c.get("contained_by") for c in measured}
    for finding in findings:
        finding["contained_by"] = contained.get(finding["label"])

    measured_total = sum(c["bytes"] or 0 for c in measured if not c.get("contained_by"))

    print(json.dumps({
        "probe": "consumers",
        "threshold_bytes": limit,
        "measured_total_bytes": measured_total,
        "incomplete": incomplete,
        "partial": partial,
        "consumers": consumers,
        "findings": findings,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
