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
import math
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

    if found.get("unsearchable"):
        print(json.dumps({
            "probe": "assess",
            "idea": found.get("idea", ""),
            "verdict": "cannot tell",
            "headline": ("%s, so no search was run. This is not an all-clear: "
                         "nothing was checked. Describe the problem you are "
                         "solving in a sentence of plain words and run it again."
                         % found["unsearchable"].capitalize()),
            "queries_run": [], "queries_failed": [], "candidate_count": 0,
            "distinctive_idea_words": [], "weak_idea_words": [],
            "same_idea": [], "adjacent": [], "loosely_related": [],
            "all_ranked": [],
        }, indent=2, sort_keys=True))
        return 0

    idea = found.get("idea", "")
    idea_words = words_of(idea)
    total_queries = max(1, len(found.get("queries_run", [])))
    candidates = found.get("candidates", [])

    # Not every shared word is evidence. Counting words equally made this call
    # "already built" on an idea about PATH resolution, naming four plays that
    # do nothing of the sort: they shared "first", "copy" or "find", which are
    # near-stopwords in a registry of developer tools. So each word is weighted
    # by how rare it is across the candidates actually retrieved, which is the
    # only sample of the field available here. A word in a quarter of the
    # results says almost nothing; a word in one says a lot.
    cand_words = [(c, name_words(c["name"]) | words_of(c["description"]))
                  for c in candidates]
    doc_freq = {}
    for _, words in cand_words:
        for word in words:
            doc_freq[word] = doc_freq.get(word, 0) + 1
    corpus = max(1, len(candidates))

    # Measuring rarity from the retrieved set is imperfect: the queries were
    # built from the idea, so the idea's own words are over-represented. I
    # tried correcting that by measuring each word only over the candidates
    # some other query found, and it fails exactly when it matters. If search
    # returns nearly every play containing a word, the complement holds none
    # of them and the word scores as maximally rare, which turned "first" into
    # strong evidence. So the weighting stays deliberately simple and is used
    # for ranking, while the verdict rests on a structural rule below.
    def weight(word):
        return math.log((corpus + 1.0) / (1.0 + doc_freq.get(word, 0)))

    def mass(words):
        return sum(weight(w) for w in words)

    # The line between a word that carries signal and one that does not, used
    # to label a shared word as common in the output and to add a small bonus
    # for rare ones. It is the weight of a word appearing in about six percent
    # of the candidates, so it scales with the sample rather than being a
    # number picked once against one registry.
    evidence_floor = math.log((corpus + 1.0) / (1.0 + 0.06 * corpus))

    assessed = []
    for candidate in candidates:
        n_words = name_words(candidate["name"])
        d_words = words_of(candidate["description"])
        t_words = {t.split("-", 1)[-1] for t in candidate.get("tags", [])}

        shared_name = n_words & idea_words
        evidence = mass(shared_name)
        name_overlap = evidence / max(1e-9, mass(n_words)) if n_words else 0.0
        # How much of your idea their name accounts for, which is a different
        # question from how much of their name your idea accounts for. Without
        # it a one-word name scores a perfect match on that one word: an
        # unrelated play called audit-play outranked the play that actually
        # covered the idea, because "play" is a stopword and "audit" was then
        # its whole name.
        idea_cover = evidence / max(1e-9, mass(idea_words)) if idea_words else 0.0
        desc_overlap = mass(d_words & idea_words) / max(1e-9, mass(idea_words))
        tag_overlap = (mass(t_words & idea_words) / max(1e-9, mass(t_words))
                       if t_words else 0.0)
        query_share = len(candidate["matched_queries"]) / total_queries

        # Name similarity dominates: a matching name is the collision that
        # actually costs you, and description overlap is noisy at this length.
        score = (0.35 * name_overlap + 0.20 * idea_cover + 0.20 * desc_overlap
                 + 0.10 * tag_overlap + 0.15 * query_share)
        # Two independently shared name words are a different kind of evidence
        # from one, which is what the verdict below turns on, so the score has
        # to know it too. Without this a play can sit in a lower band while
        # showing a higher number than the band above it, which reads as a
        # sorting bug rather than as the judgement it is.
        if len(shared_name) >= 2:
            score += 0.12

        # "Already built" is a strong claim, so it needs more than one word.
        # A single shared word is how this once called four unrelated plays a
        # collision, on "first", "copy" and "find". One word now caps at
        # adjacent, which still puts the play in front of you to read.
        if len(shared_name) >= 2 and name_overlap >= 0.4:
            closeness = "same idea"
        elif name_overlap >= 0.25 or score >= 0.35:
            closeness = "adjacent"
        elif score >= 0.18:
            closeness = "loosely related"
        else:
            closeness = "unrelated"

        common = sorted(w for w in shared_name if weight(w) < evidence_floor)
        candidate = dict(candidate)
        candidate.update({
            "similarity": round(score, 3),
            "name_overlap": round(name_overlap, 2),
            "shared_name_words": sorted(shared_name),
            "common_shared_words": common,
            "evidence": round(evidence, 2),
            "idea_cover": round(idea_cover, 2),
            "evidence_floor": round(evidence_floor, 2),
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

    # An idea built entirely from words that are common in this field cannot be
    # matched reliably by any word matcher, including this one. Saying so is
    # more useful than a verdict computed from words that carry no signal.
    distinctive = [w for w in sorted(idea_words) if weight(w) >= evidence_floor]
    if idea_words and not distinctive:
        weak_idea = sorted(idea_words)
        headline += (" Every word in the idea is common in these results (%s), so the "
                     "ranking below is weak. Rephrase with the specific noun for the "
                     "thing you are building and run it again."
                     % ", ".join(weak_idea))
    else:
        weak_idea = []

    print(json.dumps({
        "probe": "assess",
        "idea": idea,
        "verdict": verdict,
        "headline": headline,
        "queries_run": found.get("queries_run", []),
        "queries_failed": found.get("queries_failed", []),
        "candidate_count": len(assessed),
        "distinctive_idea_words": distinctive,
        "weak_idea_words": weak_idea,
        "same_idea": same[:5],
        "adjacent": adjacent[:6],
        "loosely_related": related[:6],
        "all_ranked": assessed[:20],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
