#!/usr/bin/env python3
"""Re-derive the rote quality rubric yourself. Do not take my weights on trust.

Point this at any play package that currently scores 1.00. It copies the
package, removes one frontmatter field at a time, runs `rote play validate`
after each removal, and prints what each field is worth. Nothing is written to
the original package.

    python3 tools/derive_rubric.py ~/.rote/flows/<a-play-scoring-1.00>

Add --pairs to also test combinations, which is how the interaction between
metadata.version and top-level tags was found: removing tags costs 0.12,
removing version costs 0.25, removing both costs 0.25 rather than 0.37,
because discoverability is not scored while version is absent.

Requires rote on PATH and a play that validates at 1.00 to start with; the
whole method depends on having a clean control.
"""
import argparse
import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile

SCORE = re.compile(r"Quality score: ([0-9.]+)")
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def drop_line(text, needle):
    return "".join(l for l in text.splitlines(keepends=True) if needle not in l)


def drop_block(text, pattern):
    return re.sub(pattern, "", text, count=1)


# Each mutation removes exactly one thing a play might declare.
MUTATIONS = {
    "top-level tags:":
        lambda s: drop_block(s, r" \* tags:\n(?: \* - [^\n]*\n)+"),
    "top-level source:":
        lambda s: drop_line(s, " * source:"),
    "metadata.version":
        lambda s: re.sub(r" \*   version: [^\n]*\n", "", s, count=1),
    "metadata.contract.output":
        lambda s: drop_block(s, r" \*     output:\n(?: \*       [^\n]*\n)+"),
    "license":
        lambda s: drop_line(s, " * license:"),
    "provenance.url":
        lambda s: drop_line(s, " *   url:"),
    "presentation_fixtures":
        lambda s: drop_block(s, r" \* presentation_fixtures:\n(?: \*   [^\n]*\n)+"),
    "step timeout_ms":
        lambda s: drop_line(s, "timeout_ms:"),
    "step depends_on":
        lambda s: drop_block(s, r" \*     depends_on:\n(?: \*     - [^\n]*\n)+"),
}


def score_of(entrypoint):
    try:
        result = subprocess.run(["rote", "play", "validate", entrypoint],
                                capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None
    match = SCORE.search(ANSI.sub("", result.stdout + result.stderr))
    return float(match.group(1)) if match else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package", help="a play package directory scoring 1.00")
    parser.add_argument("--pairs", action="store_true", help="also test pairs of removals")
    args = parser.parse_args()

    source = os.path.abspath(os.path.expanduser(args.package))
    entry = os.path.join(source, "main.ts")
    if not os.path.isfile(entry):
        print("no main.ts in %s" % source, file=sys.stderr)
        return 2

    workspace = tempfile.mkdtemp(prefix="derive-rubric-")
    package = os.path.join(workspace, "control")
    shutil.copytree(source, package)
    target = os.path.join(package, "main.ts")
    original = open(target, encoding="utf-8").read()
    # A play name collision with the real store would be confusing; rename.
    original = re.sub(r"^ \* name: .*$", " * name: rubric-control", original, count=1, flags=re.M)
    open(target, "w", encoding="utf-8").write(original)

    baseline = score_of(target)
    print("control: %s" % source)
    print("baseline score: %s" % baseline)
    if baseline is None or baseline < 0.999:
        print("\nThe control does not score 1.00, so removals cannot be attributed.")
        print("Pick a play that validates at 1.00 and try again.")
        shutil.rmtree(workspace, ignore_errors=True)
        return 1

    print("\n%-30s %-8s %s" % ("REMOVED", "SCORE", "COSTS"))
    weights = {}
    for label, mutate in MUTATIONS.items():
        mutated = mutate(original)
        if mutated == original:
            print("%-30s %-8s %s" % (label, "-", "not present in this control"))
            continue
        open(target, "w", encoding="utf-8").write(mutated)
        score = score_of(target)
        if score is None:
            print("%-30s %-8s %s" % (label, "n/a", "validation produced no score"))
            continue
        cost = round(baseline - score, 2)
        weights[label] = cost
        print("%-30s %-8.2f %s" % (label, score, ("-%.2f" % cost) if cost else "nothing"))

    if args.pairs:
        print("\n%-46s %-10s %-8s %s" % ("REMOVED TOGETHER", "IF ADDITIVE", "ACTUAL", "DELTA"))
        costly = [k for k, v in weights.items() if v > 0]
        for a, b in itertools.combinations(costly, 2):
            mutated = MUTATIONS[b](MUTATIONS[a](original))
            open(target, "w", encoding="utf-8").write(mutated)
            score = score_of(target)
            if score is None:
                continue
            additive = round(baseline - weights[a] - weights[b], 2)
            print("%-46s %-10.2f %-8.2f %+.2f"
                  % (a + " + " + b, additive, score, score - additive))

    open(target, "w", encoding="utf-8").write(original)
    shutil.rmtree(workspace, ignore_errors=True)
    print("\nNothing was modified in %s" % source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
