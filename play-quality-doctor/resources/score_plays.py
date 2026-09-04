#!/usr/bin/env python3
"""Score every located play with rote's own scorer and aggregate the result.

An earlier version of this play modelled the rubric from the outside, because I
had not found `rote play score`. It exists, it prints every signal with its
weight and status, and it is authoritative. Chi blu pointed this out in the
Rote Playoffs Discord; the model is gone and this shells out to the real thing.

What is still worth doing on top of it: `rote play score` takes one play at a
time and says what is unsatisfied, not what to type. This runs it across every
play you have, ranks the signals by what they are actually costing you, and
attaches the fix for the two that are easy to get wrong.
"""
import json
import os
import re
import subprocess
import sys

ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

# rote's detail strings say what is unsatisfied. These say what to type, for the
# cases where the wording does not make the required shape obvious.
GUIDANCE = {
    "frontmatter_completeness": (
        "If the detail names tags or discoverability, the fix is a TOP-LEVEL "
        "`tags:` list. Tags under `metadata.discoverability.tags` do not count "
        "toward this signal, and that is the shape `rote workspace export` "
        "generates, so a play can carry nine tags and still be marked down. "
        "Keep the discoverability block as well; add the top-level one."),
    "output_format": (
        "Declare an output contract: an `output:` block with format and "
        "destination, either at the top level or nested under "
        "`metadata.contract:`. Both satisfy this signal."),
    "provenance_url": (
        "Add a top-level `source:` URL. `provenance.url` does not satisfy this "
        "despite the signal name."),
    "parametrization": (
        "Declare the varying inputs as parameters rather than hardcoding them "
        "in step argv."),
    "dag_structure": (
        "Declare the work as `steps:` with valid dependencies."),
    "jsonpath_syntax": (
        "A for_each query is malformed; check it with `rote grammar steps`."),
    "response_id_leak": (
        "A cached response id such as @1 is hardcoded in the play. Reference "
        "the upstream step instead."),
}


def score_one(entrypoint):
    name = os.path.basename(os.path.dirname(entrypoint))
    try:
        result = subprocess.run(["rote", "play", "score", entrypoint, "--format", "json"],
                                capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return {"play": name, "path": entrypoint, "state": "no-rote",
                "detail": "rote is not on PATH, so the authoritative scorer cannot be run"}
    except subprocess.TimeoutExpired:
        return {"play": name, "path": entrypoint, "state": "timed-out"}
    except subprocess.SubprocessError as error:
        return {"play": name, "path": entrypoint, "state": "failed", "detail": str(error)}

    raw = ANSI.sub("", result.stdout).strip()
    try:
        payload = json.loads(raw)
    except ValueError:
        first = ANSI.sub("", result.stderr).strip().splitlines()
        return {"play": name, "path": entrypoint, "state": "unscorable",
                "detail": first[0] if first else "scorer returned no JSON"}

    if not payload.get("ok"):
        return {"play": name, "path": entrypoint, "state": "unscorable",
                "detail": ((payload.get("error") or {}).get("message")
                           or "scorer reported failure")}

    body = payload.get("data", {}).get("result", {})
    findings = body.get("findings", [])
    unsatisfied = [
        {
            "signal": f["signal"],
            "weight": round(f.get("weight", 0.0), 2),
            "score": round(f.get("score", 0.0), 2),
            "lost": round(f.get("weight", 0.0) * (1.0 - f.get("score", 0.0)), 3),
            "detail": f.get("detail", ""),
            "severity": f.get("severity", "info"),
            "fix": GUIDANCE.get(f["signal"], ""),
        }
        for f in findings if f.get("score", 1.0) < 1.0
    ]
    return {
        "play": name,
        "path": entrypoint,
        "state": "scored",
        "score": round(body.get("score", 0.0), 2),
        "decision": body.get("decision"),
        "scorer_version": body.get("scorer_version"),
        "unsatisfied": sorted(unsatisfied, key=lambda u: -u["lost"]),
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"probe": "score", "error": "usage: score_plays.py <locator output>"}))
        return 1
    payload = sys.argv[1].strip()
    if not payload.startswith("{"):
        try:
            payload = open(payload, encoding="utf-8").read()
        except OSError as error:
            print(json.dumps({"probe": "score", "error": "unreadable locator output: %s" % error}))
            return 1
    try:
        located = json.loads(payload)
    except ValueError as error:
        print(json.dumps({"probe": "score", "error": "unusable locator output: %s" % error}))
        return 1

    results = [score_one(e) for e in located.get("entrypoints", [])]
    scored = [r for r in results if r["state"] == "scored"]
    capped = [r for r in scored if r["score"] < 1.0]

    cost = {}
    for result in capped:
        for item in result["unsatisfied"]:
            entry = cost.setdefault(item["signal"], {"plays": 0, "lost": 0.0,
                                                     "weight": item["weight"],
                                                     "fix": item["fix"]})
            entry["plays"] += 1
            entry["lost"] = round(entry["lost"] + item["lost"], 3)

    versions = sorted({r.get("scorer_version") for r in scored if r.get("scorer_version")})

    # rote truncates a process step's stdout at 65536 bytes, silently and mid
    # JSON. This grows at roughly 670 bytes per play, so a store of about a
    # hundred installed plays would overflow and the renderer would fail to
    # parse. Trim to a budget, worst-scoring plays kept, and say what was
    # dropped rather than letting the report look complete.
    BUDGET = 48000

    def emit(rows, note):
        return json.dumps({
            "probe": "score",
            "scorer_version": versions[0] if len(versions) == 1 else (versions or None),
            "target": located.get("target"),
            "unresolved": located.get("unresolved", []),
            "total": len(results),
            "scored": len(scored),
            "capped": len(capped),
            "at_full": len(scored) - len(capped),
            "reported": len(rows),
            "omitted": note,
            "signal_cost": cost,
            "results": rows,
        }, indent=2, sort_keys=True)

    ordered = sorted(results, key=lambda r: r.get("score", 1.0))
    text = emit(ordered, 0)
    while len(text) > BUDGET and len(ordered) > 5:
        step = max(1, len(ordered) // 10)
        ordered = ordered[:-step]
        text = emit(ordered, len(results) - len(ordered))
    print(text)
    return 0


def _unused_original(results, scored, capped, cost, versions, located):
    print(json.dumps({
        "probe": "score",
        "scorer_version": versions[0] if len(versions) == 1 else (versions or None),
        "target": located.get("target"),
        "unresolved": located.get("unresolved", []),
        "total": len(results),
        "scored": len(scored),
        "capped": len(capped),
        "at_full": len(scored) - len(capped),
        "signal_cost": cost,
        "results": sorted(results, key=lambda r: r.get("score", 1.0)),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
