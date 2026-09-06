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
    "script_on_windows_fs_shadows_linux":
        "a script on the Windows drive beats your Linux copy",
    "script_on_windows_fs":
        "on the Windows drive, but runs as a Linux process",
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


SEVERITY_FLOOR = ["high", "medium", "low", "info"]


def argument(index, default):
    """Optional positional argument; an unresolved token means absent."""
    if len(sys.argv) <= index:
        return default
    raw = sys.argv[index].strip()
    return default if not raw or raw.startswith("$") else raw


def main():
    if len(sys.argv) < 4:
        print("usage: render.py <platform> <shadow> <traps> [format] [min_severity]",
              file=sys.stderr)
        return 2

    output_format = argument(4, "text").lower()
    if output_format not in ("text", "json"):
        print("format must be text or json", file=sys.stderr)
        return 2
    floor = argument(5, "info").lower()
    if floor not in SEVERITY_FLOOR:
        print("min_severity must be one of: " + ", ".join(SEVERITY_FLOOR), file=sys.stderr)
        return 2
    floor_rank = SEVERITY_ORDER[floor]

    platform = load(sys.argv[1])
    shadow = load(sys.argv[2])
    traps = load(sys.argv[3])

    probes = [("platform", platform), ("commands", shadow), ("config", traps)]
    ok = [name for name, data in probes if "_unavailable" not in data]

    # The floor filters what is reported, never what was checked. A caller
    # asking only for high findings still gets the counts of everything else,
    # because "nothing above medium" and "nothing looked at" must not read the
    # same way.
    def above_floor(items):
        return [f for f in items
                if SEVERITY_ORDER.get(f.get("severity"), 9) <= floor_rank]

    all_findings = list(shadow.get("findings", [])) + list(traps.get("findings", []))
    if floor != "info":
        for data in (shadow, traps):
            if "findings" in data:
                data["findings"] = above_floor(data["findings"])

    if output_format == "json":
        counts = {level: 0 for level in SEVERITY_FLOOR}
        for finding in all_findings:
            severity = finding.get("severity", "info")
            counts[severity] = counts.get(severity, 0) + 1
        print(json.dumps({
            "schema": "wsl-toolchain-doctor/v1",
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "applicable": platform.get("applicable", False),
            "flavour": platform.get("flavour"),
            "interop": platform.get("interop"),
            "path_source": shadow.get("path_source", "inherited"),
            "path_entry_count": shadow.get("path_entry_count"),
            "windows_entry_count": shadow.get("windows_entry_count"),
            "severity_counts": counts,
            "min_severity": floor,
            "kernel_release": platform.get("kernel_release"),
            "wsl_distro_name": platform.get("wsl_distro_name"),
            "duplicate_entry_count": shadow.get("duplicate_entry_count"),
            "missing_entries": shadow.get("missing_entries", []),
            "missing_entry_count": shadow.get("missing_entry_count"),
            "home_on_windows": traps.get("home_on_windows"),
            "cwd_on_windows": traps.get("cwd_on_windows"),
            "detail_level": shadow.get("detail_level"),
            "findings": above_floor(all_findings) if floor != "info" else all_findings,
            "probes_ok": ok,
        }, indent=2, sort_keys=True))
        return 0

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
    # The verdict describes the machine, so it is computed from every finding,
    # never the filtered view. Asking for high only used to print "Clear.
    # Nothing is shadowed or dangling." directly above "9 medium, 11 low".
    actionable = [f for f in all_findings if f.get("severity") in ("high", "medium")]
    level = worst(actionable) if actionable else "clean"

    # The medium and high verdicts talk about commands, so they must not be
    # used when every finding came from the configuration probe instead.
    command_findings = [f for f in all_findings
                        if f.get("command") and f.get("severity") in ("high", "medium")]
    if level in ("high", "medium") and not command_findings:
        lines.append("VERDICT  No command resolves wrong, but the way this machine "
                     "is configured will bite you.")
    else:
        lines.append(f"VERDICT  {VERDICT_TEXT[level]}")
    # Counts come from every finding, not the filtered set, so raising the
    # floor never makes an unchecked machine look clean. What the floor hid
    # is said out loud rather than silently subtracted.
    counts = {}
    for finding in all_findings:
        counts[finding.get("severity", "info")] = counts.get(finding.get("severity", "info"), 0) + 1
    summary = ", ".join(f"{counts[s]} {s}" for s in ("high", "medium", "low", "info") if s in counts)
    if floor != "info":
        summary += f"   (showing {floor} and above)"
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
        # "Nothing wrong" and "nothing resolved at all" are opposite answers
        # and this line used to give the first for both. A PATH of directories
        # that do not exist produced "every watched command resolves to a
        # Linux copy" when none of them resolved.
        absent = shadow.get("absent_count") or 0
        watched = shadow.get("watched_count") or 0
        if watched and absent >= watched:
            lines.append("  nothing resolves at all: none of the %d watched commands"
                         % watched)
            lines.append("  were found on this PATH, so there is nothing to compare")
        elif absent:
            lines.append("  nothing shadowed, but %d of %d watched commands are not on"
                         % (absent, watched))
            lines.append("  this PATH at all")
        else:
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

    # The header counts every severity, so the low ones have to appear
    # somewhere or the counts promise more than the report delivers. They
    # repeat heavily, so they are grouped by kind rather than listed one by
    # one. The floor has already been applied to shadow["findings"] above.
    quiet = [f for f in shadow.get("findings", []) if f.get("severity") == "low"]
    if quiet:
        lines.append("ALSO SEEN")
        by_kind = {}
        for finding in quiet:
            by_kind.setdefault(finding.get("kind", ""), []).append(finding)
        for kind in sorted(by_kind):
            group = by_kind[kind]
            subjects = [f.get("command") or f.get("path") or "" for f in group]
            subjects = [s for s in subjects if s]
            noun = "command" if group[0].get("command") else "entry"
            plural = noun if len(group) == 1 else (
                "entries" if noun == "entry" else noun + "s")
            lines.append(f"  LOW    {kind}  {len(group)} {plural}")
            detail = " ".join(str(group[0].get("detail", "")).split())
            for wrapped in textwrap.wrap(detail, width=78):
                lines.append("         " + wrapped)
            for wrapped in textwrap.wrap(", ".join(sorted(subjects)), width=78):
                lines.append("         " + wrapped)
            # Every other section names a path you can check. This one used to
            # name only the commands, which is exactly how a wrong finding here
            # stayed invisible.
            for finding in sorted(group, key=lambda f: f.get("command") or "")[:6]:
                # Only when the subject line listed command names. For a
                # path-level finding the subject already is the path, and
                # printing it again just repeated the line.
                if finding.get("command") and finding.get("path"):
                    lines.append("         %s%s"
                                 % ((finding.get("command") + ": ")
                                    if finding.get("command") else "",
                                    finding["path"]))
            if len(group) > 6 and group[0].get("command"):
                lines.append("         ... and %d more" % (len(group) - 6))
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
    shown_missing = shadow.get("missing_entries", [])
    for missing in shown_missing:
        lines.append(f"  missing   {missing}")
    total_missing = shadow.get("missing_entry_count", len(shown_missing))
    if total_missing > len(shown_missing):
        lines.append(f"  missing   ... and {total_missing - len(shown_missing)} more")
    lines.append("")

    # Any reduction is said out loud. A report that quietly stopped listing
    # things is worse than one that says it ran out of room.
    detail = shadow.get("detail_level")
    if detail and detail != "full":
        lines.append("WHAT WAS LEFT OUT")
        for wrapped in textwrap.wrap(
                "The command probe produced more than it could hand on, so it "
                "reduced what it reported: %s. Counts above still cover "
                "everything that was checked." % detail, width=74):
            lines.append("  " + wrapped)
        lines.append("")

    lines.append("SCOPE")
    source = shadow.get("path_source", "inherited")
    if source == "supplied":
        lines.append("  Inspected a PATH supplied by the caller, not this shell's own,")
        lines.append("  so these results describe that environment rather than this one.")
    else:
        lines.append("  Reports the PATH of the shell that invoked it. A different shell,")
        lines.append("  or a tool that edits PATH before running this, will see different")
        lines.append("  results.")
    lines.append("  Read-only: no file is written and no command is repaired.")
    lines.append("")

    lines.append("STAGES")
    for name, data in probes:
        state = "ok" if "_unavailable" not in data else "unavailable"
        lines.append(f"  {BAR * 8}  {name:10} {state}")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
