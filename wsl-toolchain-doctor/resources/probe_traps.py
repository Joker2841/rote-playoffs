#!/usr/bin/env python3
"""Probe 3: the WSL settings and mount facts that cause the symptoms.

Probe 2 reports what is broken. This reports why, and it is the half that
tells you which single line to change.

Read-only by construction: it parses configuration and mount tables and
tests case sensitivity by reading two spellings of a directory that already
exists. It never writes a probe file, which matters because the usual way to
test a case-insensitive filesystem is to create two files, and a diagnostic
that writes into the filesystem it is judging is not a diagnostic.
"""
import json
import os
import re


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def parse_ini(text):
    """Minimal INI parse. wsl.conf is small and we only need flat keys."""
    sections = {}
    current = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().lower()
            sections[current] = {}
        elif "=" in line and current is not None:
            key, _, value = line.partition("=")
            sections[current][key.strip().lower()] = value.strip()
    return sections


def wsl_conf():
    text = read("/etc/wsl.conf")
    if text is None:
        return {
            "present": False,
            "append_windows_path": "default-true",
            "systemd": "default-false",
            "generate_resolv_conf": "default-true",
        }
    parsed = parse_ini(text)
    interop = parsed.get("interop", {})
    boot = parsed.get("boot", {})
    network = parsed.get("network", {})
    return {
        "present": True,
        "append_windows_path": interop.get("appendwindowspath", "default-true"),
        "systemd": boot.get("systemd", "default-false"),
        "generate_resolv_conf": network.get("generateresolvconf", "default-true"),
    }


def windows_mounts():
    """Only real Windows drive mounts: /mnt/<letter> backed by drvfs or 9p.

    Correction from the first pass: matching every mountpoint under /mnt/ swept
    in WSL's own plumbing -- /mnt/wsl, /mnt/wslg, Docker Desktop's tmpfs and
    iso9660 mounts -- and produced sixteen identical warnings about a metadata
    option that is meaningless on those filesystems.
    """
    text = read("/proc/mounts") or ""
    mounts = []
    drive = re.compile(r"^/mnt/[a-z]$")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        device, mountpoint, fstype, options = parts[0], parts[1], parts[2], parts[3]
        if not drive.match(mountpoint) or fstype not in ("9p", "drvfs", "virtiofs"):
            continue
        option_list = options.split(",")
        mounts.append({
            "mountpoint": mountpoint,
            "fstype": fstype,
            "device": device,
            "has_metadata": "metadata" in option_list,
            "case_option": next((o for o in option_list if o.startswith("case=")), "unset"),
        })
    return mounts


def on_windows_filesystem(path):
    try:
        resolved = os.path.realpath(path)
    except OSError:
        return None
    return resolved == "/mnt" or resolved.startswith("/mnt/")


def case_insensitive(directory):
    """Read-only case test, tolerant of entries we cannot stat.

    Correction from the first pass: os.path.exists returns False for a
    permission-denied path, so the very first unreadable entry -- on a Windows
    root that is reliably $Recycle.Bin -- was being read as proof of case
    sensitivity. Only entries we can actually resolve get a vote, and a
    sensitive verdict needs several of them to agree.
    """
    try:
        names = [n for n in os.listdir(directory) if n.lower() != n.upper()]
    except OSError:
        return "unknown"

    checked = 0
    for name in names:
        original = os.path.join(directory, name)
        if not os.path.exists(original):
            continue  # unreadable entry: no vote either way
        flipped = os.path.join(
            directory, name.upper() if name != name.upper() else name.lower()
        )
        if flipped == original:
            continue
        if os.path.exists(flipped):
            return "insensitive"
        checked += 1
        if checked >= 5:
            return "sensitive"
    return "sensitive" if checked else "unknown"


def main():
    conf = wsl_conf()
    mounts = windows_mounts()
    home = os.path.expanduser("~")
    cwd = os.getcwd()

    resolv = read("/etc/resolv.conf") or ""
    systemd_pid1 = (read("/proc/1/comm") or "").strip() or "unknown"

    findings = []

    if str(conf["append_windows_path"]).lower() in ("default-true", "true"):
        findings.append({
            "severity": "info",
            "kind": "windows_path_appended",
            "detail": ("Windows PATH is appended to the Linux PATH. This is the root cause of "
                       "every shadowing result in the command probe. Setting "
                       "appendWindowsPath=false under [interop] in /etc/wsl.conf removes the "
                       "Windows entries, at the cost of losing interop conveniences such as "
                       "calling code or explorer.exe from the shell."),
        })

    if on_windows_filesystem(home):
        findings.append({
            "severity": "high",
            "kind": "home_on_windows_filesystem",
            "detail": ("Your home directory sits on the Windows filesystem. Every file operation "
                       "crosses the 9p boundary, which is roughly an order of magnitude slower "
                       "and does not carry real Unix permissions."),
            "path": home,
        })

    if on_windows_filesystem(cwd):
        findings.append({
            "severity": "high",
            "kind": "project_on_windows_filesystem",
            "detail": ("This project lives on the Windows filesystem. Installs and builds that "
                       "touch many small files pay the 9p crossing on every one of them."),
            "path": cwd,
        })

    for mount in mounts:
        if not mount["has_metadata"]:
            findings.append({
                "severity": "medium",
                "kind": "mount_without_metadata",
                "detail": ("Mounted without the metadata option, so Unix ownership and "
                           "permission bits are not stored. chmod appears to succeed and "
                           "silently does nothing, and scripts here can read as executable "
                           "when they are not."),
                "path": mount["mountpoint"],
            })

    windows_case = None
    for mount in mounts:
        if mount["mountpoint"].startswith("/mnt/") and os.path.isdir(mount["mountpoint"]):
            windows_case = case_insensitive(mount["mountpoint"])
            if windows_case == "insensitive":
                findings.append({
                    "severity": "medium",
                    "kind": "case_insensitive_mount",
                    "detail": ("Case-insensitive mount. Two tracked files differing only in case "
                               "collapse into one, so a clean checkout can silently disagree with "
                               "the repository."),
                    "path": mount["mountpoint"],
                })
            break

    if "automatically generated by WSL" in resolv and str(conf["generate_resolv_conf"]).lower() in ("default-true", "true"):
        findings.append({
            "severity": "info",
            "kind": "generated_resolv_conf",
            "detail": ("/etc/resolv.conf is regenerated by WSL on every boot. Hand edits to fix "
                       "DNS are discarded; the durable fix is generateResolvConf=false under "
                       "[network] in /etc/wsl.conf plus your own resolv.conf."),
        })

    if systemd_pid1 != "systemd" and str(conf["systemd"]).lower() in ("default-false", "false"):
        findings.append({
            "severity": "info",
            "kind": "systemd_off",
            "detail": ("PID 1 is not systemd, so systemctl will not manage services. Enable it "
                       "with systemd=true under [boot] in /etc/wsl.conf if you need services."),
        })

    print(json.dumps({
        "probe": "traps",
        "wsl_conf": conf,
        "pid1": systemd_pid1,
        "home": home,
        "home_on_windows": on_windows_filesystem(home),
        "cwd": cwd,
        "cwd_on_windows": on_windows_filesystem(cwd),
        "windows_mounts": mounts,
        "windows_mount_case": windows_case or "unknown",
        "linux_root_case": case_insensitive("/usr"),
        "findings": findings,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
