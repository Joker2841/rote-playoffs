#!/usr/bin/env python3
"""Join what wins with where the PATH came from.

The two halves are only useful together. Knowing nvm beats Homebrew does not
tell you which line to edit, and a list of rc lines does not tell you which one
is currently costing you anything.
"""
import json
import sys
import textwrap
import time

BAR = "#"
ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

EXPLAIN = {
    "broken_link": "looks installed, resolves to nothing",
    "windows_shadows_native": "Windows copy beats your native copy",
    "windows_only": "runs as a Windows program",
    "windows_exe_only": "command not found, but installed on Windows",
    "shadowed": "more than one copy on PATH",
    "duplicate_path_entry": "duplicate PATH entry",
    "script_on_windows_fs": "on the Windows drive, but runs as a Linux process",
    "integration_mount": "resolves only while its integration is running",
    "stale_manager_entry": "on PATH, but the directory is gone",
}


def load(source):
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


def argument(index, default):
    if len(sys.argv) <= index:
        return default
    raw = sys.argv[index].strip()
    return default if not raw or raw.startswith("$") else raw


def main():
    if len(sys.argv) < 3:
        print("usage: render_report.py <shadow> <shell_config> [format]", file=sys.stderr)
        return 2
    shadow = load(sys.argv[1])
    config = load(sys.argv[2])
    output_format = argument(3, "text").lower()
    if output_format not in ("text", "json"):
        print("format must be text or json", file=sys.stderr)
        return 2

    probes = [("commands", shadow), ("shell config", config)]
    ok = [n for n, d in probes if "_unavailable" not in d]
    findings = list(shadow.get("findings", [])) + list(config.get("findings", []))
    findings.sort(key=lambda f: ORDER.get(f.get("severity"), 9))
    actionable = [f for f in findings if f.get("severity") in ("high", "medium")]
    host = shadow.get("host", {})

    if output_format == "json":
        print(json.dumps({
            "schema": "which-actually-runs/v1",
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "host": host,
            "path_source": shadow.get("path_source"),
            "path_entry_count": shadow.get("path_entry_count"),
            "version_managers_on_path": shadow.get("version_managers_on_path", []),
            "version_managers_initialised": sorted(config.get("managers", {})),
            "severity_counts": {s: sum(1 for f in findings if f.get("severity") == s)
                                for s in ("high", "medium", "low")},
            "findings": findings,
            "path_lines": config.get("path_lines", []),
            "probes_ok": ok,
        }, indent=2, sort_keys=True))
        return 0

    lines = []
    lines.append("WHICH ACTUALLY RUNS" + " " * 34 + time.strftime("%Y-%m-%d %H:%M", time.gmtime()) + " UTC")
    lines.append("")
    lines.append("  probes    " + BAR * (12 * len(ok)) + " " * (12 * (2 - len(ok)))
                 + "  %d/2 ok" % len(ok))
    lines.append("")
    lines.append("  host      %s on %s, %d PATH entries (%s)"
                 % (host.get("flavour", "unknown"), host.get("machine", "?"),
                    shadow.get("path_entry_count", 0), shadow.get("path_source", "inherited")))
    managers = shadow.get("version_managers_on_path", [])
    if managers:
        lines.append("  managers  %s on PATH" % ", ".join(managers))
    lines.append("")

    high = sum(1 for f in findings if f.get("severity") == "high")
    quiet_count = sum(1 for f in findings if f.get("severity") == "low")
    if not actionable and quiet_count:
        lines.append("VERDICT  Nothing is broken, but %d command(s) resolve past "
                     "another copy." % quiet_count)
    elif not actionable:
        absent = shadow.get("absent_count") or 0
        watched = shadow.get("watched_count") or 0
        if watched and absent >= watched:
            lines.append("VERDICT  None of the %d watched commands are on this PATH, "
                         "so there is nothing to compare." % watched)
        elif absent:
            lines.append("VERDICT  Every command that resolves resolves cleanly, but "
                         "%d of %d are not on this PATH at all." % (absent, watched))
        else:
            lines.append("VERDICT  Every watched command resolves to a single, working copy.")
    elif high:
        lines.append("VERDICT  %d command(s) resolve to something that is not there or not native." % high)
    else:
        named = len({f.get("command") for f in actionable if f.get("command")})
        other = len(actionable) - named
        summary = "%d command(s) whose winner is not obvious" % named if named else ""
        if other:
            summary += (" and " if summary else "") + "%d PATH problem(s)" % other
        lines.append("VERDICT  Working, with %s." % summary)
    lines.append("")

    lines.append("WHAT WINS, AND WHAT IT BEAT")
    ranked = [f for f in shadow.get("findings", []) if f.get("severity") in ("high", "medium")]
    if not ranked:
        lines.append("  nothing worth reporting")
    for finding in ranked:
        lines.append("  %-6s %-10s %s" % (finding["severity"].upper(),
                                          (finding.get("command")
                                           or finding.get("origin") or "-")[:10],
                                          EXPLAIN.get(finding["kind"], finding["kind"])))
        lines.append("         %s" % finding.get("path", ""))
        if finding.get("target"):
            label = ("resolves to" if finding.get("kind") == "integration_mount"
                     else "target missing")
            lines.append("         %s: %s" % (label, finding["target"]))
        for extra in (finding.get("examples") or [])[1:]:
            lines.append("         %s" % extra)
        if finding.get("entry_count", 0) > 3:
            lines.append("         ... and %d more" % (finding["entry_count"] - 3))
        if not finding.get("command") and finding.get("detail"):
            for wrapped in textwrap.wrap(" ".join(finding["detail"].split()), width=68):
                lines.append("         " + wrapped)
        for shadowed in (finding.get("shadowed") or [])[:4]:
            lines.append("         beats: %s" % shadowed)
    lines.append("")

    # Low findings answer the same question the play is named for, so they are
    # listed rather than only counted. Grouped, one line of evidence each.
    quiet = [f for f in shadow.get("findings", []) if f.get("severity") == "low"]
    if quiet:
        resolved = sorted([f for f in quiet if f.get("kind") == "shadowed"],
                          key=lambda f: f.get("command") or "")
        other = [f for f in quiet if f.get("kind") != "shadowed"]
        lines.append("ALSO RESOLVED, NOTHING WRONG")
        for finding in resolved[:40]:
            beaten = finding.get("other_copies",
                                 len(finding.get("shadowed") or []))
            lines.append("  %-10s %s wins, over %d other cop%s on PATH"
                         % (finding.get("command") or "-",
                            finding.get("origin") or "the first",
                            beaten, "y" if beaten == 1 else "ies"))
            lines.append("         %s" % finding.get("path", ""))
        if len(resolved) > 40:
            lines.append("  ... and %d more, all resolving to a single working copy"
                         % (len(resolved) - 40))
        for finding in other:
            lines.append("  %s" % EXPLAIN.get(finding.get("kind", ""),
                                              finding.get("kind", "")))
            lines.append("         %s"
                         % " ".join((finding.get("detail") or "").split()))
            if finding.get("path"):
                lines.append("         %s" % finding["path"])
        lines.append("")

    path_lines = config.get("path_lines", [])
    if path_lines:
        lines.append("WHERE YOUR PATH COMES FROM")
        for item in path_lines[:12]:
            lines.append("  %s:%-4s %s" % (item["file"], item["line"], item["text"]))
        if len(path_lines) > 12:
            lines.append("  ... and %d more line(s) that put a directory on PATH"
                         % (len(path_lines) - 12))
        lines.append("")

    config_findings = config.get("findings", [])
    if config_findings:
        lines.append("WHY IT IS SHAPED THAT WAY")
        for finding in config_findings:
            lines.append("  %-6s %s" % (finding["severity"].upper(), finding["kind"]))
            for wrapped in textwrap.wrap(" ".join(finding["detail"].split()), width=74):
                lines.append("         " + wrapped)
            for place in (finding.get("places") or [])[:4]:
                lines.append("         at %s" % place)
        lines.append("")

    detail = shadow.get("detail_level")
    if detail and detail != "full":
        lines.append("WHAT WAS LEFT OUT")
        for wrapped in textwrap.wrap(
                "The command probe produced more than it could hand on, so it "
                "reduced what it reported: %s." % detail, width=70):
            lines.append("  " + wrapped)
        lines.append("")

    lines.append("SCOPE")
    lines.append("  Read-only. It reads PATH, stats files, and parses the text of shell")
    lines.append("  startup files without ever sourcing them. Nothing is changed and no")
    lines.append("  command is repaired. A line assigning a secret-looking name is")
    lines.append("  reported as present but never echoed. Results describe the PATH of")
    lines.append("  the shell that invoked it, which is why a login shell and an editor")
    lines.append("  terminal can legitimately disagree.")
    lines.append("")
    lines.append("STAGES")
    for name, data in probes:
        lines.append("  %s  %-14s %s" % (BAR * 8, name,
                                         "ok" if "_unavailable" not in data else "unavailable"))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
