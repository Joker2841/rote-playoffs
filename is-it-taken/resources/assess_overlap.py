#!/usr/bin/env python3
"""Rank candidates by how close they are to the idea, not by how popular they are.

A play with 40 downloads that shares one incidental word is not a collision. A
play with 3 downloads whose name is your idea is. Popularity is reported because
it tells you what you would be competing against, but it never decides the
ranking.

Similarity here is lexical: shared content words in the name and description,
weighted toward the name, plus how many independent queries surfaced the same
play. It cannot tell that two differently-worded ideas are the same thing. That
limit is stated in the output rather than hidden, because a confident "nothing
similar" from a lexical matcher would be the most damaging thing this could say.
"""
import json
import re
import sys

STOP = set("""a an the and or but for with without of to in on at from by is are be been
this that these those it its your you my our their what which who how why when where
into over under about across before after during while than then them they we us i
play plays run runs using use used make makes made get gets getting build builds
building create creates creating check checks checking report reports reporting
tool tools thing things new all any some more most other another same each every""".split())


def stem(word):
    """Crude singularisation so dependency and dependencies match.

    Found by a fixture: an idea about "unused dependencies" scored nothing-close
    against a play named dependency-sweep, because the plural did not match the
    singular. A false all-clear is the most damaging output this can produce, so
    the matcher errs toward collapsing forms rather than distinguishing them.
    """
    for suffix, replacement in (("ies", "y"), ("sses", "ss"), ("ches", "ch"),
                                ("shes", "sh"), ("xes", "x"), ("ses", "s"),
                                ("es", ""), ("s", "")):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[:-len(suffix)] + replacement
    return word


def words_of(text):
    return {stem(w) for w in re.findall(r"[a-z0-9][a-z0-9-]{2,}", (text or "").lower())
            if w not in STOP}


def name_words(name):
    return {stem(w) for w in re.split(r"[-_]", (name or "").lower())
            if len(w) > 2 and w not in STOP}


def main():
    payload = sys.argv[1] if len(sys.argv) > 1 else ""
    if not payload.strip().startswith("{"):
        try:
            payload = open(payload, encoding="utf-8").read()
        except OSError as error:
            print(json.dumps({"probe": "assess", "error": "unreadable input: %s" % error}))
            return 1
    try:
        found = json.loads(payload)
    except ValueError as error:
        # A truncated payload is the likely cause and it must not read as an
        # empty registry: rote clips a process step's stdout at 65536 bytes
        # without saying so, and half a JSON document fails exactly here.
        size = len(payload)
        hint = (" The input is %d bytes, at or over rote's 65536-byte stdout limit, "
                "so it was probably truncated rather than malformed." % size
                if size >= 65000 else "")
        print(json.dumps({"probe": "assess",
                          "error": "unusable search output: %s.%s" % (error, hint),
                          "input_bytes": size}))
        return 1
    if found.get("error"):
        print(json.dumps({"probe": "assess", "error": found["error"]}))
        return 1

    idea = found.get("idea", "")
    idea_words = words_of(idea)
    total_queries = max(1, len(found.get("queries_run", [])))

    assessed = []
    for candidate in found.get("candidates", []):
        n_words = name_words(candidate["name"])
        d_words = words_of(candidate["description"])
        t_words = {t.split("-", 1)[-1] for t in candidate.get("tags", [])}

        name_overlap = len(n_words & idea_words) / max(1, len(n_words))
        desc_overlap = len(d_words & idea_words) / max(1, len(idea_words))
        tag_overlap = len(t_words & idea_words) / max(1, len(t_words)) if t_words else 0.0
        query_share = len(candidate["matched_queries"]) / total_queries

        # Name similarity dominates: a matching name is the collision that
        # actually costs you, and description overlap is noisy at this length.
        score = (0.50 * name_overlap + 0.20 * desc_overlap
                 + 0.10 * tag_overlap + 0.20 * query_share)

        if name_overlap >= 0.5:
            closeness = "same idea"
        elif name_overlap >= 0.25 or score >= 0.35:
            closeness = "adjacent"
        elif score >= 0.18:
            closeness = "loosely related"
        else:
            closeness = "unrelated"

        candidate = dict(candidate)
        candidate.update({
            "similarity": round(score, 3),
            "name_overlap": round(name_overlap, 2),
            "shared_name_words": sorted(n_words & idea_words),
            "closeness": closeness,
            "matched_query_count": len(candidate["matched_queries"]),
        })
        assessed.append(candidate)

    assessed.sort(key=lambda c: -c["similarity"])
    same = [c for c in assessed if c["closeness"] == "same idea"]
    adjacent = [c for c in assessed if c["closeness"] == "adjacent"]
    related = [c for c in assessed if c["closeness"] == "loosely related"]

    if same:
        verdict = "already built"
        headline = ("%d play(s) already do this. Read them before you write a line."
                    % len(same))
    elif len(adjacent) >= 3:
        verdict = "crowded"
        headline = ("No exact match, but %d adjacent plays. Whatever you build has to be "
                    "different from all of them in a way a stranger can see."
                    % len(adjacent))
    elif adjacent:
        verdict = "adjacent work exists"
        headline = ("%d play(s) are close enough to read first, then decide whether yours "
                    "is a different question or the same one." % len(adjacent))
    else:
        verdict = "nothing close found"
        headline = ("Nothing lexically close. That is not proof it is unbuilt: this matches "
                    "on words, so an idea described in different vocabulary would not "
                    "surface here.")

    print(json.dumps({
        "probe": "assess",
        "idea": idea,
        "verdict": verdict,
        "headline": headline,
        "queries_run": found.get("queries_run", []),
        "queries_failed": found.get("queries_failed", []),
        "candidate_count": len(assessed),
        "same_idea": same[:5],
        "adjacent": adjacent[:6],
        "loosely_related": related[:6],
        "all_ranked": assessed[:20],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
