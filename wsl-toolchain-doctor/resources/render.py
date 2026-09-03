#!/usr/bin/env python3
"""Join the three probes into one briefing a stranger can act on.

Ordering is deliberate: what resolves wrong comes before why, because the
symptom is what sent you looking. Every line names a path you can check
yourself, so no claim here has to be taken on trust.
"""
import json
import sys
import textwrap
import time

BAR = "#"
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

VERDICT_TEXT = {
    "high": "Your toolchain is lying to you.",
    "medium": "Working, with commands that are not what they look like.",
    "low": "Healthy, with cosmetic PATH untidiness.",
    "clean": "Clear. Nothing is shadowed or dangling.",
}

EXPLAIN = {
    "broken_integration_symlink":
        "looks installed, resolves to nothing",
    "windows_shadows_linux":
        "Windows copy beats your Linux copy",
    "windows_only":
        "runs as a Windows program",
    "windows_exe_only":
        "command not found, but installed on Windows",
    "linux_multiple":
        "more than one Linux copy",
    "duplicate_path_entry":
        "duplicate PATH entry",
}


def load(source):
    """Accept either a path or the JSON text itself.

    In the packaged play each probe's stdout arrives directly as an argument,
    so there is no file to open. Standalone runs still pass paths, and both
    have to work or the play cannot be developed outside its own package.
    """
    text = (source or "").strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except ValueError as error:
            return {"_unavailable": "unparsable probe output: %s" % error}
    try:
        with open(source, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        return {"_unavailable": str(error)}


def worst(findings):
    if not findings:
        return "clean"
    return min((f.get("severity", "info") for f in findings),
               key=lambda s: SEVERITY_ORDER.get(s, 9))


def main():
    if len(sys.argv) != 4:
        print("usage: render.py <platform> <shadow> <traps>  (path or JSON text)", file=sys.stderr)
        return 2

    platform = load(sys.argv[1])
    shadow = load(sys.argv[2])
    traps = load(sys.argv[3])

    probes = [("platform", platform), ("commands", shadow), ("config", traps)]
    ok = [name for name, data in probes if "_unavailable" not in data]

    lines = []
    stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    lines.append("WSL TOOLCHAIN DOCTOR" + " " * 33 + stamp + " UTC")
    lines.append("")
    lines.append("  probes    " + BAR * (8 * len(ok)) + " " * (8 * (3 - len(ok)))
                 + f"  {len(ok)}/3 ok")
    lines.append("")

    if not platform.get("applicable", False):
        lines.append("VERDICT  Not applicable. This is not WSL, so nothing here can apply.")
        lines.append(f"  kernel   {platform.get('kernel_release', 'unknown')}")
        print("\n".join(lines))
        return 0

    findings = list(shadow.get("findings", [])) + list(traps.get("findings", []))
    actionable = [f for f in findings if f.get("severity") in ("high", "medium")]
    level = worst(actionable) if actionable else "clean"

    lines.append(f"VERDICT  {VERDICT_TEXT[level]}")
    counts = {}
    for finding in findings:
        counts[finding.get("severity", "info")] = counts.get(finding.get("severity", "info"), 0) + 1
    summary = ", ".join(f"{counts[s]} {s}" for s in ("high", "medium", "low", "info") if s in counts)
    lines.append(f"  {summary or 'nothing to report'}")
    lines.append("")

    lines.append("WHERE YOU ARE")
    lines.append(f"  flavour   {platform.get('flavour', 'unknown')}"
                 f"   distro {platform.get('wsl_distro_name', 'unknown')}"
                 f"   interop {platform.get('interop', 'unknown')}")
    lines.append(f"  kernel    {platform.get('kernel_release', 'unknown')}")
    home_side = "windows" if traps.get("home_on_windows") else "linux"
    cwd_side = "windows" if traps.get("cwd_on_windows") else "linux"
    lines.append(f"  home      on the {home_side} filesystem")
    lines.append(f"  project   on the {cwd_side} filesystem")
    lines.append("")

    ranked = sorted(
        [f for f in shadow.get("findings", []) if f.get("severity") in ("high", "medium")],
        key=lambda f: (SEVERITY_ORDER.get(f.get("severity"), 9), f.get("command") or ""),
    )
    lines.append("WHAT RESOLVES WRONG")
    if not ranked:
        lines.append("  nothing: every watched command resolves to a Linux copy")
    for finding in ranked:
        label = EXPLAIN.get(finding.get("kind"), finding.get("kind", ""))
        lines.append(f"  {finding.get('severity','').upper():6} {(finding.get('command') or '-'):10} {label}")
        lines.append(f"         {finding.get('path','')}")
        if finding.get("target"):
            lines.append(f"         target missing: {finding['target']}")
        for shadowed in finding.get("shadowed", []) or []:
            lines.append(f"         shadows: {shadowed}")
    lines.append("")

    lines.append("WHY")
    trap_findings = sorted(traps.get("findings", []),
                           key=lambda f: SEVERITY_ORDER.get(f.get("severity"), 9))
    if not trap_findings:
        lines.append("  no configuration cause found")
    for finding in trap_findings:
        lines.append(f"  {finding.get('severity','').upper():6} {finding.get('kind','')}"
                     + (f"  {finding['path']}" if finding.get("path") else ""))
        detail = " ".join(str(finding.get("detail", "")).split())
        for wrapped in textwrap.wrap(detail, width=78):
            lines.append("         " + wrapped)
    lines.append("")

    lines.append("PATH SHAPE")
    lines.append(f"  {shadow.get('path_entry_count', '?')} entries"
                 f"   {shadow.get('windows_entry_count', '?')} windows"
                 f"   {shadow.get('duplicate_entry_count', '?')} duplicate")
    for missing in shadow.get("missing_entries", []):
        lines.append(f"  missing   {missing}")
    lines.append("")

    lines.append("SCOPE")
    lines.append("  Reports the PATH of the shell that invoked it. A different shell,")
    lines.append("  or a tool that edits PATH before running this, will see different")
    lines.append("  results. Read-only: no file is written and no command is repaired.")
    lines.append("")

    lines.append("STAGES")
    for name, data in probes:
        state = "ok" if "_unavailable" not in data else "unavailable"
        lines.append(f"  {BAR * 8}  {name:10} {state}")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
