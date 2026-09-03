#!/usr/bin/env python3
"""Resolve what to audit into a list of play entrypoints.

Accepts "all" for every installed package, an owner/name reference, or a path.
Reports what it could not resolve rather than silently auditing fewer plays
than the caller asked for, because a quality report that quietly skipped half
its input is worse than no report.
"""
import json
import os
import sys


def argument(index, default):
    if len(sys.argv) <= index:
        return default
    raw = sys.argv[index].strip()
    return default if not raw or raw.startswith("$") else raw


def entrypoint_for(directory):
    for name in ("main.ts", "flow.ts"):
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def walk_root(root):
    """Installed packages sit at <root>/<name> or <root>/<owner>/<name>."""
    found = []
    if not os.path.isdir(root):
        return found
    try:
        first_level = sorted(os.listdir(root))
    except OSError:
        return found
    for entry in first_level:
        path = os.path.join(root, entry)
        if not os.path.isdir(path):
            continue
        direct = entrypoint_for(path)
        if direct:
            found.append(direct)
            continue
        try:
            for sub in sorted(os.listdir(path)):
                nested = entrypoint_for(os.path.join(path, sub))
                if nested:
                    found.append(nested)
        except OSError:
            continue
    return found


def main():
    target = argument(1, "all")
    root = os.path.expanduser(argument(2, "~/.rote/flows"))

    unresolved = []
    if target == "all":
        entrypoints = walk_root(root)
        if not entrypoints:
            unresolved.append("no play packages found under %s" % root)
    elif os.path.exists(os.path.expanduser(target)):
        expanded = os.path.expanduser(target)
        if os.path.isdir(expanded):
            single = entrypoint_for(expanded)
            entrypoints = [single] if single else []
            if not single:
                unresolved.append("%s has no main.ts" % expanded)
        else:
            entrypoints = [expanded]
    else:
        # owner/name or bare name, resolved against the local store only.
        candidates = [os.path.join(root, *target.split("/")), os.path.join(root, target)]
        entrypoints = []
        for candidate in candidates:
            found = entrypoint_for(candidate)
            if found:
                entrypoints = [found]
                break
        if not entrypoints:
            unresolved.append(
                "%s is not installed under %s; pull it first with "
                "`rote registry play pull %s`" % (target, root, target))

    print(json.dumps({
        "probe": "locate",
        "target": target,
        "flows_root": root,
        "entrypoints": entrypoints,
        "count": len(entrypoints),
        "unresolved": unresolved,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
