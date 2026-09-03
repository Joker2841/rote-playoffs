#!/usr/bin/env python3
"""Render the audit as something a play author can act on.

Ordered by what is worth fixing first: the signals costing the most across the
most plays, then the per-play breakdown, then the exact edit for each signal.
"""
import json
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
            return {"_unavailable": "unparsable audit output: %s" % error}
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
    if len(sys.argv) < 2:
        print("usage: render_report.py <audit> [format] [min_score]", file=sys.stderr)
        return 2

    audit = load(sys.argv[1])
    output_format = argument(2, "text").lower()
    if output_format not in ("text", "json"):
        print("format must be text or json", file=sys.stderr)
        return 2
    try:
        floor = float(argument(3, "1.0"))
    except ValueError:
        floor = 1.0

    if "_unavailable" in audit:
        print("The audit stage produced nothing usable: %s" % audit["_unavailable"])
        return 0

    results = [r for r in audit.get("results", []) if r.get("state") == "audited"]
    shown = [r for r in results if r.get("predicted_score", 1.0) < floor]
    shown.sort(key=lambda r: r.get("predicted_score", 1.0))
    unreadable = [r for r in audit.get("results", []) if r.get("state") != "audited"]

    fixes = {}
    cost = {}
    for result in results:
        for item in result.get("unsatisfied", []):
            fixes[item["signal"]] = item
            cost[item["signal"]] = cost.get(item["signal"], 0) + 1

    if output_format == "json":
        print(json.dumps({
            "schema": "play-quality-doctor/v1",
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "parser": audit.get("parser"),
            "audited": len(results),
            "capped": audit.get("capped"),
            "at_full_score": audit.get("at_full"),
            "signal_counts": audit.get("signal_counts", {}),
            "unresolved": audit.get("unresolved", []),
            "unreadable": [{"play": r.get("play"), "detail": r.get("detail")} for r in unreadable],
            "plays": [{
                "play": r["play"],
                "predicted_score": r["predicted_score"],
                "points_lost": r["points_lost"],
                "unsatisfied": [u["signal"] for u in r["unsatisfied"]],
                "path": r["path"],
            } for r in shown],
        }, indent=2, sort_keys=True))
        return 0

    lines = []
    stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    lines.append("PLAY QUALITY DOCTOR" + " " * 34 + stamp + " UTC")
    lines.append("")
    lines.append("  audited   " + BAR * 24 + "  %d play(s)" % len(results))
    lines.append("")

    if not results:
        lines.append("VERDICT  Nothing to audit.")
        for note in audit.get("unresolved", []):
            lines.append("  %s" % note)
        print("\n".join(lines))
        return 0

    capped = audit.get("capped", 0)
    if capped == 0:
        lines.append("VERDICT  All %d audited play(s) satisfy every rubric signal." % len(results))
    else:
        lines.append("VERDICT  %d of %d audited play(s) are capped below 1.00."
                     % (capped, len(results)))
        lines.append("  rote play validate reports Pass with no error and no warning")
        lines.append("  for every one of them. The cap is silent.")
    lines.append("")

    if cost:
        lines.append("WHAT IS COSTING THE MOST")
        for signal, count in sorted(cost.items(), key=lambda kv: (-fixes[kv[0]]["weight"], -kv[1])):
            item = fixes[signal]
            lines.append("  -%.2f  %-26s %d play(s)   needs %s"
                         % (item["weight"], signal, count, item["requires"]))
        lines.append("")

    lines.append("PER PLAY")
    if not shown:
        lines.append("  every audited play is at or above the requested score")
    for result in shown:
        lines.append("  %.2f  %-32s -%.2f" % (result["predicted_score"], result["play"],
                                              result["points_lost"]))
        for item in result["unsatisfied"]:
            if item.get("scored", True):
                lines.append("        -%.2f %s" % (item["weight"], item["signal"]))
            else:
                lines.append("         0.00 %s (not scored while %s is missing; "
                             "it starts costing once that is fixed)"
                             % (item["signal"], item.get("gated_by", "another signal")))
    lines.append("")

    if fixes:
        lines.append("HOW TO FIX EACH ONE")
        for signal, item in sorted(fixes.items(), key=lambda kv: -kv[1]["weight"]):
            lines.append("  %s  (-%.2f)" % (signal, item["weight"]))
            for wrapped in textwrap.wrap(" ".join(item["fix"].split()), width=74):
                lines.append("      " + wrapped)
        lines.append("")

    for note in audit.get("unresolved", []):
        lines.append("NOT RESOLVED")
        lines.append("  %s" % note)
        lines.append("")

    if unreadable:
        lines.append("COULD NOT READ")
        for result in unreadable:
            lines.append("  %-32s %s" % (result.get("play", "?"), result.get("detail", "")))
        lines.append("")

    lines.append("METHOD AND ITS LIMITS")
    method = (
        "The rubric is not published. These weights were derived by taking a play "
        "that scored 1.00, removing one frontmatter field at a time, and reading "
        "the score back from rote play validate. They were then refined against "
        "five published plays: two were predicted correctly first time, and three "
        "were mispredicted and revealed additional signals, so treat the "
        "genuinely held-out evidence as two plays rather than five. One "
        "interaction is measured rather than assumed: with metadata.version "
        "absent, discoverability is not scored, so those two weights do not add. "
        "A known residual: modiqo/hello scores 0.45 where this predicts 0.40, and "
        "no adjustment fixes it without breaking another play, so a factor here "
        "is still unaccounted for. This is a model of the scorer, not the scorer. "
        "rote play validate is authoritative; where they disagree, this is wrong. "
        "Do not take the weights on trust: tools/derive_rubric.py in the source "
        "repository re-derives them against any play of your own that scores 1.00."
    )
    for wrapped in textwrap.wrap(method, width=74):
        lines.append("  " + wrapped)
    lines.append("")
    lines.append("  Read-only: no play is modified. Frontmatter parsed with %s."
                 % (audit.get("parser") or "unknown"))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
