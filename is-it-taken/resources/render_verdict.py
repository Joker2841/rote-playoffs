#!/usr/bin/env python3
"""Present the verdict so it can be acted on in under a minute."""
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
            return {"error": "unparsable assessment: %s" % error}
    try:
        with open(source, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        return {"error": str(error)}


def argument(index, default):
    if len(sys.argv) <= index:
        return default
    raw = sys.argv[index].strip()
    return default if not raw or raw.startswith("$") else raw


def block(title, rows, lines):
    if not rows:
        return
    lines.append(title)
    for row in rows:
        lines.append("  %.2f  %-46s %3d dl  q=%.2f"
                     % (row["similarity"], row["reference"][:46], row["downloads"],
                        row["quality"]))
        summary = " ".join((row.get("description") or "").split())[:150]
        if summary:
            for wrapped in textwrap.wrap(summary, width=70):
                lines.append("        " + wrapped)
        if row.get("shared_name_words"):
            lines.append("        shares in the name: %s" % ", ".join(row["shared_name_words"]))
    lines.append("")


def main():
    data = load(sys.argv[1] if len(sys.argv) > 1 else "")
    output_format = argument(2, "text").lower()
    if output_format not in ("text", "json"):
        print("format must be text or json", file=sys.stderr)
        return 2

    if data.get("error"):
        print("Could not assess this idea: %s" % data["error"])
        return 0

    if output_format == "json":
        print(json.dumps({
            "schema": "is-it-taken/v1",
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "idea": data.get("idea"),
            "verdict": data.get("verdict"),
            "headline": data.get("headline"),
            "same_idea": [c["reference"] for c in data.get("same_idea", [])],
            "adjacent": [c["reference"] for c in data.get("adjacent", [])],
            "candidates_examined": data.get("candidate_count"),
            "queries_run": data.get("queries_run", []),
            "queries_failed": data.get("queries_failed", []),
            "ranked": data.get("all_ranked", [])[:12],
        }, indent=2, sort_keys=True))
        return 0

    lines = []
    lines.append("IS IT TAKEN" + " " * 42 + time.strftime("%Y-%m-%d %H:%M", time.gmtime()) + " UTC")
    lines.append("")
    lines.append("  searched  " + BAR * 24 + "  %d queries, %d candidate(s) examined"
                 % (len(data.get("queries_run", [])), data.get("candidate_count", 0)))
    lines.append("")
    lines.append("  idea      %s" % " ".join((data.get("idea") or "").split())[:70])
    lines.append("")
    lines.append("VERDICT  %s" % data.get("verdict", "unknown").upper())
    for wrapped in textwrap.wrap(" ".join((data.get("headline") or "").split()), width=72):
        lines.append("  " + wrapped)
    lines.append("")

    block("ALREADY DOES THIS", data.get("same_idea", []), lines)
    block("CLOSE ENOUGH TO READ FIRST", data.get("adjacent", []), lines)
    block("LOOSELY RELATED", data.get("loosely_related", [])[:3], lines)

    failed = data.get("queries_failed", [])
    if failed:
        lines.append("QUERIES THAT DID NOT RETURN")
        for query in failed[:6]:
            lines.append("  %s" % query)
        lines.append("  A failed query is not an empty result. Treat this as partial.")
        lines.append("")

    lines.append("WHAT THIS CANNOT TELL YOU")
    limit = (
        "Matching is lexical. Two people can describe the same idea in words that "
        "share nothing, and this will not connect them, so 'nothing close found' "
        "means no lexical match rather than nothing built. It also only sees public "
        "plays visible to your session. Read the near matches before deciding: the "
        "point is not the score, it is that you looked."
    )
    for wrapped in textwrap.wrap(limit, width=72):
        lines.append("  " + wrapped)
    lines.append("")
    lines.append("  Read-only: it searches the registry and changes nothing.")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
