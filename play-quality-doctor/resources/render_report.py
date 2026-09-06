#!/usr/bin/env python3
"""Render the portfolio view over rote's own quality scorer."""
import json
import os
import sys
import textwrap
import time

BAR = "#"


def load(source):
    text = (source or "").strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except ValueError as error:
            return {"_unavailable": "unparsable score output: %s" % error}
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


def qualified(row):
    """owner/name, because a bare basename is ambiguous on a real shelf.

    Five of the eighteen plays installed here share a directory name with a
    play by a different owner, and the text report printed only that name, so
    it gave you no way to tell which file to edit.
    """
    name = row.get("play", "?")
    path = row.get("path") or ""
    parts = [p for p in path.split(os.sep) if p]
    if "flows" in parts:
        tail = parts[parts.index("flows") + 1:]
        if len(tail) >= 2 and tail[1] == name:
            return "%s/%s" % (tail[0], name)
    return name


def main():
    if len(sys.argv) < 2:
        print("usage: render_report.py <score output> [format] [min_score]", file=sys.stderr)
        return 2
    data = load(sys.argv[1])
    output_format = argument(2, "text").lower()
    if output_format not in ("text", "json"):
        print("format must be text or json", file=sys.stderr)
        return 2
    try:
        floor = float(argument(3, "1.0"))
    except ValueError:
        floor = 1.0

    if "_unavailable" in data:
        print("The scoring stage produced nothing usable: %s" % data["_unavailable"])
        return 0

    results = [r for r in data.get("results", []) if r.get("state") == "scored"]
    problems = [r for r in data.get("results", []) if r.get("state") != "scored"]
    shown = sorted([r for r in results if r.get("score", 1.0) < floor],
                   key=lambda r: r.get("score", 1.0))
    cost = data.get("signal_cost", {})

    if output_format == "json":
        print(json.dumps({
            "schema": "play-quality-doctor/v2",
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scorer_version": data.get("scorer_version"),
            "scored": data.get("scored"),
            "capped": data.get("capped"),
            "at_full_score": data.get("at_full"),
            "signal_cost": cost,
            "unresolved": data.get("unresolved", []),
            "unscorable": [{"play": p.get("play"), "state": p.get("state"),
                            "detail": p.get("detail")} for p in problems],
            "plays": [{"play": r["play"], "score": r["score"],
                       "unsatisfied": [u["signal"] for u in r["unsatisfied"]],
                       "path": r["path"]} for r in shown],
        }, indent=2, sort_keys=True))
        return 0

    lines = []
    lines.append("PLAY QUALITY DOCTOR" + " " * 34 + time.strftime("%Y-%m-%d %H:%M", time.gmtime()) + " UTC")
    lines.append("")
    total_audited = data.get("total", len(results))
    omitted = data.get("omitted") or 0
    lines.append("  scored    " + BAR * 24 + "  %d play(s), rubric %s"
                 % (total_audited, data.get("scorer_version") or "unknown"))
    if omitted:
        lines.append("            %d audited, %d listed below; the rest scored "
                     "highest and were dropped to fit the output budget"
                     % (total_audited, len(results)))
    lines.append("")

    if not results:
        lines.append("VERDICT  Nothing could be scored.")
        for note in data.get("unresolved", []):
            lines.append("  %s" % note)
        for problem in problems:
            lines.append("  %-30s %s" % (problem.get("play", "?"), problem.get("state")))
        print("\n".join(lines))
        return 0

    capped = data.get("capped", 0)
    if capped == 0:
        lines.append("VERDICT  All %d play(s) satisfy every rubric signal." % total_audited)
    else:
        lines.append("VERDICT  %d of %d play(s) are below 1.00." % (capped, total_audited))
        lines.append("  rote play validate reports only what it rates a warning,")
        lines.append("  so a signal rated info is a silent deduction.")
    lines.append("")

    if cost:
        lines.append("WHAT IT IS COSTING YOU, ACROSS EVERY PLAY")
        for signal, entry in sorted(cost.items(), key=lambda kv: -kv[1]["lost"]):
            lines.append("  -%.3f total  %-26s %d play(s)   weight %.2f"
                         % (entry["lost"], signal, entry["plays"], entry["weight"]))
        lines.append("")

    lines.append("PER PLAY")
    if not shown:
        lines.append("  every scored play is at or above the requested score")
    for result in shown:
        lines.append("  %.2f  %s" % (result["score"], qualified(result)))
        for item in result["unsatisfied"]:
            lines.append("        -%.3f %-26s %s"
                         % (item["lost"], item["signal"], item["detail"]))
    lines.append("")

    # Built from every scored play, not the filtered list. min_score decides
    # which plays are listed; it must not decide whether you are told how to
    # fix the damage the table above just reported. min_score=0 used to print
    # 1.97 points lost and then offer no fix for any of it.
    fixes = {}
    for result in results:
        for item in result.get("unsatisfied", []):
            if item.get("fix"):
                fixes[item["signal"]] = item["fix"]
    if fixes:
        lines.append("WHAT TO TYPE")
        for signal, fix in sorted(fixes.items()):
            lines.append("  %s" % signal)
            for wrapped in textwrap.wrap(" ".join(fix.split()), width=74):
                lines.append("      " + wrapped)
        lines.append("")

    if problems:
        lines.append("COULD NOT SCORE")
        for problem in problems:
            lines.append("  %-30s %s  %s" % (problem.get("play", "?"), problem.get("state"),
                                             problem.get("detail", "")))
        lines.append("")
    notes = data.get("unresolved", []) or []
    if notes:
        lines.append("NOT RESOLVED")
        for note in notes:
            lines.append("  %s" % note)
        lines.append("")

    lines.append("WHERE THESE NUMBERS COME FROM")
    method = (
        "Every score here is rote's own, from `rote play score --format json`, "
        "which reports each signal with its weight and status and is "
        "authoritative. This play runs it across every play you have rather than "
        "one at a time, ranks the signals by what they are actually costing you, "
        "and adds the exact edit for the ones whose required shape is not obvious "
        "from the wording. Run `rote play score <main.ts>` yourself on any single "
        "play; the numbers will match, because they are the same numbers. Thanks "
        "to Chi blu in the Rote Playoffs Discord for pointing out that this "
        "command existed: an earlier version of this play reconstructed the "
        "rubric from the outside and got its structure wrong."
    )
    for wrapped in textwrap.wrap(method, width=74):
        lines.append("  " + wrapped)
    lines.append("")
    lines.append("  Read-only: no play is modified.")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
