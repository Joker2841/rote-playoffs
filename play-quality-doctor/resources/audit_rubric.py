#!/usr/bin/env python3
"""Audit each play's frontmatter against the quality rubric.

The rubric is not published. These rules were derived by mutating a play that
scored 1.00, one field at a time, and reading the score back from
`rote play validate`; then checked against published plays scoring 0.45, 0.52,
0.65, 0.77 and 0.90 until the predicted score matched every one. The weights
below are what that produced. They are a model of the scorer, not the scorer,
which is why the report always prints the score rote actually gave you next to
the one this predicts, and says so when they disagree.

pyyaml is not in the standard library and a play that needs pip install on
someone else's machine is a play they will not run, so this uses yaml when it
can import it and falls back to an indentation scan built for this one
generated format when it cannot.
"""
import json
import os
import re
import sys

try:
    import yaml
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False


def contract(front):
    return ((front.get("metadata") or {}).get("contract") or {})


RUBRIC = [
    {
        "signal": "output_format",
        "weight": 0.25,
        "requires": "an output contract",
        "check": lambda f: bool(f.get("output") or contract(f).get("output")),
        "fix": ("Add an output contract. Either a top-level `output:` block, or "
                "`output:` nested under `metadata.contract:`. Both satisfy it; "
                "declare format and destination."),
    },
    {
        "signal": "frontmatter_completeness",
        "weight": 0.25,
        "requires": "metadata.version",
        "check": lambda f: bool((f.get("metadata") or {}).get("version")),
        "fix": ("Add `version:` under `metadata:`. A top-level `version:` alone "
                "does not satisfy this, which is easy to miss because the play "
                "still publishes and still runs."),
    },
    {
        "signal": "parametrization",
        "weight": 0.13,
        "requires": "at least one declared parameter",
        "check": lambda f: bool(f.get("parameters")),
        "fix": ("Declare at least one parameter. A play with no input that varies "
                "is a script; the rubric treats it as one."),
    },
    {
        "signal": "discoverability",
        "weight": 0.12,
        "requires": "a top-level tags: block",
        "check": lambda f: bool(f.get("tags")),
        "fix": ("Add a top-level `tags:` list. Tags under "
                "`metadata.discoverability.tags` do NOT satisfy this, and that is "
                "the shape the exporter generates, so most plays have the tags in "
                "the wrong place. One tag is enough to pass; keep the "
                "discoverability block as well."),
    },
    {
        "signal": "provenance_url",
        "weight": 0.10,
        "requires": "a top-level source: URL",
        "check": lambda f: bool(f.get("source")),
        "fix": ("Add a top-level `source:` URL pointing at where the play comes "
                "from. `provenance.url` does not satisfy this despite the signal "
                "name."),
    },
    {
        "signal": "dag_structure",
        "weight": 0.08,
        "requires": "a steps: block",
        "check": lambda f: bool(f.get("steps")),
        "fix": "Declare the work as `steps:` rather than only inside the body.",
    },
]

FRONTMATTER = re.compile(r"@rote-frontmatter\s*\n(.*?)\n\s*\*\s*---", re.S)


def uncomment(block):
    lines = [re.sub(r"^\s*\*\s?", "", line) for line in block.splitlines()]
    return "\n".join(re.sub(r"^\s*---\s*$", "", line) for line in lines)


def scan_structure(text):
    """Fallback: record which keys exist and whether they carry content.

    Deliberately not a YAML parser. It answers only the questions the rubric
    asks -- does this key exist and is there anything under it -- for a format
    that is machine generated and consistently indented.
    """
    found = {}
    stack = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if stripped.startswith("- "):
            if stack:
                found[".".join(name for _, name in stack)] = True
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", stripped)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, key))
        path = ".".join(name for _, name in stack)
        found.setdefault(path, bool(value))
        if value:
            found[path] = True
    return found


class Structural(dict):
    """Presents scan results through the same interface the rules expect."""

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def get(self, key, default=None):
        if key == "metadata":
            return Structural({k[len("metadata."):]: v
                               for k, v in self.paths.items() if k.startswith("metadata.")})
        if key == "contract":
            return Structural({k[len("contract."):]: v
                               for k, v in self.paths.items() if k.startswith("contract.")})
        return self.paths.get(key, default)


def load_frontmatter(path):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError as error:
        return None, "unreadable: %s" % error
    match = FRONTMATTER.search(text)
    if not match:
        return None, "no @rote-frontmatter block"
    body = uncomment(match.group(1))
    if HAVE_YAML:
        try:
            parsed = yaml.safe_load(body)
            if isinstance(parsed, dict):
                return parsed, None
        except yaml.YAMLError as error:
            return None, "frontmatter is not valid YAML: %s" % str(error).splitlines()[0]
    return Structural(scan_structure(body)), None


def audit(path):
    front, problem = load_frontmatter(path)
    name = os.path.basename(os.path.dirname(path))
    if front is None:
        return {"play": name, "path": path, "state": "unreadable", "detail": problem}

    unsatisfied = []
    for rule in RUBRIC:
        try:
            ok = bool(rule["check"](front))
        except Exception:
            ok = False
        if not ok:
            unsatisfied.append({
                "signal": rule["signal"],
                "weight": rule["weight"],
                "requires": rule["requires"],
                "fix": rule["fix"],
            })

    lost = sum(item["weight"] for item in unsatisfied)
    declared = front.get("name") if isinstance(front.get("name"), str) else name
    return {
        "play": declared or name,
        "path": path,
        "state": "audited",
        "parser": "yaml" if HAVE_YAML else "structural-scan",
        "predicted_score": round(max(0.0, 1.0 - lost), 2),
        "points_lost": round(lost, 2),
        "unsatisfied": unsatisfied,
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"probe": "audit", "error": "usage: audit_rubric.py <locator output>"}))
        return 1
    payload = sys.argv[1].strip()
    if not payload.startswith("{"):
        try:
            payload = open(payload, encoding="utf-8").read()
        except OSError as error:
            print(json.dumps({"probe": "audit", "error": "unreadable locator output: %s" % error}))
            return 1
    try:
        located = json.loads(payload)
    except ValueError as error:
        print(json.dumps({"probe": "audit", "error": "unusable locator output: %s" % error}))
        return 1

    results = [audit(entry) for entry in located.get("entrypoints", [])]
    audited = [r for r in results if r["state"] == "audited"]
    capped = [r for r in audited if r["predicted_score"] < 1.0]
    counts = {}
    for result in capped:
        for item in result["unsatisfied"]:
            counts[item["signal"]] = counts.get(item["signal"], 0) + 1

    print(json.dumps({
        "probe": "audit",
        "parser": "yaml" if HAVE_YAML else "structural-scan",
        "target": located.get("target"),
        "unresolved": located.get("unresolved", []),
        "total": len(results),
        "capped": len(capped),
        "at_full": len(audited) - len(capped),
        "signal_counts": counts,
        "results": sorted(results, key=lambda r: r.get("predicted_score", 1.0)),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
