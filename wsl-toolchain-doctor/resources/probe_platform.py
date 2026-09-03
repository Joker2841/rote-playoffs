#!/usr/bin/env python3
"""Probe 1: is this WSL, which version, and is Windows interop live.

Every field degrades to a labelled unknown rather than raising, because a
diagnostic that dies on its first missing file is useless on the machines
that need it most.
"""
import json
import os
import platform


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return None


def main():
    release = platform.release()
    proc_version = read("/proc/version")
    interop_node = read("/proc/sys/fs/binfmt_misc/WSLInterop")

    # WSL2 kernels carry "microsoft-standard-WSL2"; WSL1 carries "Microsoft"
    # with no WSL2 suffix. Neither is guaranteed, so record what we saw.
    lowered = (release or "").lower()
    if "microsoft-standard-wsl2" in lowered:
        flavour = "wsl2"
    elif "microsoft" in lowered:
        flavour = "wsl1"
    elif proc_version and "microsoft" in proc_version.lower():
        flavour = "wsl-unknown-version"
    else:
        flavour = "not-wsl"

    if interop_node is None:
        interop = "unknown"
    elif "enabled" in interop_node:
        interop = "enabled"
    else:
        interop = "disabled"

    result = {
        "probe": "platform",
        "flavour": flavour,
        "kernel_release": release or "unknown",
        "interop": interop,
        "wsl_distro_name": os.environ.get("WSL_DISTRO_NAME") or "unknown",
        "wsl_interop_socket": "present" if os.environ.get("WSL_INTEROP") else "absent",
        "applicable": flavour in ("wsl1", "wsl2", "wsl-unknown-version"),
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
