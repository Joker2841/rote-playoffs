#!/usr/bin/env python3
"""Probe: what WSL costs on the Windows side, versus what it admits to inside.

A WSL2 distro lives in a virtual disk that grows on demand and never shrinks on
its own. Delete forty gigabytes inside the distro and the file on the Windows
side stays exactly as large as it ever got. df, run inside, only ever shows the
inside view, so the space is invisible from the place people look for it.

This reports both numbers and the gap between them. The gap is what a
compaction would hand back.
"""
import json
import os
import re
import subprocess


def windows_user_dirs():
    """Every /mnt/<drive>/Users/<name> that exists, without guessing a name."""
    roots = []
    for drive in "cdef":
        users = "/mnt/%s/Users" % drive
        if not os.path.isdir(users):
            continue
        try:
            for entry in os.listdir(users):
                if entry.lower() in ("public", "default", "default user", "all users"):
                    continue
                candidate = os.path.join(users, entry, "AppData", "Local")
                if os.path.isdir(candidate):
                    roots.append(candidate)
        except OSError:
            continue
    return roots


def classify(path):
    lowered = path.lower()
    if "/docker/" in lowered:
        return "docker"
    if "swap" in os.path.basename(lowered):
        return "swap"
    if "/packages/" in lowered or "/wsl/" in lowered:
        return "distro"
    return "unknown"


def find_images():
    """Bounded search of the locations WSL and Docker actually use."""
    images = []
    seen = set()
    for root in windows_user_dirs():
        for relative in ("wsl", "Packages", "Docker"):
            base = os.path.join(root, relative)
            if not os.path.isdir(base):
                continue
            for current, dirs, files in os.walk(base):
                # Depth guard: these images live shallowly, and walking all of
                # AppData over the 9p boundary is unreasonably slow.
                if current[len(base):].count(os.sep) >= 4:
                    dirs[:] = []
                    continue
                for name in files:
                    if not name.lower().endswith(".vhdx"):
                        continue
                    path = os.path.join(current, name)
                    if path in seen:
                        continue
                    seen.add(path)
                    try:
                        size = os.stat(path).st_size
                    except OSError:
                        size = None
                    images.append({
                        "path": path,
                        "bytes": size,
                        "kind": classify(path),
                    })
    return images


def inside_usage():
    """What the Linux side thinks it is using, for the root filesystem."""
    try:
        stat = os.statvfs("/")
    except OSError:
        return None
    total = stat.f_blocks * stat.f_frsize
    free = stat.f_bfree * stat.f_frsize
    return {"total_bytes": total, "used_bytes": total - free}


def sparse_supported():
    """wsl --manage --set-sparse exists only on newer WSL builds."""
    try:
        result = subprocess.run(["wsl.exe", "--version"], capture_output=True,
                                text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return {"available": "unknown", "version": None}
    if result.returncode != 0:
        return {"available": "unknown", "version": None}
    text = (result.stdout or "").replace("\x00", "")
    match = re.search(r"(\d+\.\d+\.\d+)", text)
    return {"available": "yes", "version": match.group(1) if match else None}


def main():
    images = find_images()
    inside = inside_usage()
    total_windows = sum(i["bytes"] or 0 for i in images if i["kind"] != "swap")

    findings = []

    # Only the distro's own image can be compared against statvfs("/"). Docker
    # Desktop keeps a separate disk whose interior this probe cannot see, so
    # counting it as reclaimable would invent tens of gigabytes that are not
    # free. Report each image against what is actually known about it.
    distro_bytes = sum(i["bytes"] or 0 for i in images if i["kind"] == "distro")
    docker_bytes = sum(i["bytes"] or 0 for i in images if i["kind"] == "docker")
    distro_gap = None

    if inside and distro_bytes:
        distro_gap = distro_bytes - inside["used_bytes"]
        if distro_gap > 10 * 1024 ** 3:
            severity = "high"
        elif distro_gap > 2 * 1024 ** 3:
            severity = "medium"
        else:
            severity = "info"
        if distro_gap > 0:
            findings.append({
                "severity": severity,
                "kind": "unreclaimed_distro_space",
                "detail": ("The distro image occupies more on Windows than the distro "
                           "reports using inside. That difference is space already freed "
                           "inside WSL that Windows has not been given back, and it does "
                           "not return on its own."),
                "bytes": distro_gap,
            })

    if docker_bytes > 20 * 1024 ** 3:
        findings.append({
            "severity": "medium",
            "kind": "large_docker_image_store",
            "detail": ("Docker Desktop keeps its own virtual disk, separate from the "
                       "distro. How much of this is live data is not visible from here: "
                       "run `docker system df` to see it. Pruning frees space inside that "
                       "disk but does not shrink the file, which needs its own compaction."),
            "bytes": docker_bytes,
        })

    print(json.dumps({
        "probe": "images",
        "images": images,
        "windows_total_bytes": total_windows,
        "distro_bytes": distro_bytes,
        "docker_bytes": docker_bytes,
        "distro_reclaimable_bytes": distro_gap,
        "inside": inside,
        "wsl_sparse": sparse_supported(),
        "findings": findings,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
