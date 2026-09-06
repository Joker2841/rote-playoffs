#!/usr/bin/env python3
"""Search the public registry for anything close to an idea, before it is built.

The registry grew from 242 to 411 plays in twenty-four hours. Nobody can hold
that in their head, and `rote play search` answers one query at a time with the
words you happened to choose. This fans the idea out into several queries drawn
from its own content words, so a play described in different vocabulary still
surfaces.

Every result is the registry's own. Nothing is inferred about a play that the
registry did not say.
"""
import json
import re
import subprocess
import sys

ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

STOP = set("""a an the and or but for with without of to in on at from by is are be been
this that these those it its your you my our their what which who how why when where
into over under about across before after during while than then them they we us i
play plays run runs using use used make makes made get gets getting build builds
building create creates creating check checks checking report reports reporting
tool tools thing things new all any some more most other another same each every""".split())


def argument(index, default=""):
    if len(sys.argv) <= index:
        return default
    raw = sys.argv[index].strip()
    # The guard exists because rote passes an unsubstituted "$name" through
    # when a parameter is unset. Only that exact shape is a placeholder; an
    # idea that merely starts with a dollar is real input and used to be
    # thrown away and reported as "no idea given".
    if not raw or re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*", raw):
        return default
    return raw


def content_words(text):
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9-]{2,}", text.lower()) if w not in STOP]
    seen, ordered = set(), []
    for word in words:
        if word not in seen:
            seen.add(word)
            ordered.append(word)
    return ordered


def queries_for(idea):
    """The whole idea, then its strongest terms, then pairs of them."""
    words = content_words(idea)
    out = [idea.strip()]
    out.extend(words[:6])
    for i in range(min(4, len(words))):
        for j in range(i + 1, min(5, len(words))):
            out.append("%s %s" % (words[i], words[j]))
    seen, unique = set(), []
    for query in out:
        key = query.lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(query)
    return unique[:14], words


def search(query, limit=10):
    # 55 seconds, not 90: there are up to 14 queries and the step gets 900, so
    # 90 each could reach 1260 and the step would be killed before it could
    # print the list of failed queries it had been collecting. The graceful
    # degradation has to fit inside the budget or it never runs.
    try:
        result = subprocess.run(
            ["rote", "play", "search", query, "--source", "registry",
             "--scope", "public", "--limit", str(limit), "--json"],
            capture_output=True, text=True, timeout=55)
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        payload = json.loads(ANSI.sub("", result.stdout))
    except ValueError:
        return None
    if not payload.get("ok"):
        return None
    return payload.get("data", {}).get("result", {}).get("items", [])


def main():
    idea = argument(1)
    queries, words = queries_for(idea or "")

    # No usable words means no search happened, and that must not come out the
    # far end as "nothing close found". An empty idea used to fail the step
    # outright, and an idea of pure punctuation used to run one query, match
    # nothing, and report a clean all-clear, which is the single most damaging
    # thing this can say. Both now return the same honest non-answer.
    if not words:
        print(json.dumps({
            "probe": "search",
            "idea": idea or "",
            "unsearchable": ("no searchable words in the idea"
                             if idea else "no idea given"),
            "queries_run": [], "queries_failed": [], "candidates": [],
        }, indent=2, sort_keys=True))
        return 0

    hits, failed = {}, []
    for query in queries:
        items = search(query)
        if items is None:
            failed.append(query)
            continue
        for item in items:
            record = hits.setdefault(item["play_id"], {
                "reference": item["reference"],
                "name": item["name"],
                "owner": item["owner"]["slug"],
                "owner_kind": item["owner"]["kind"],
                "description": item.get("description") or "",
                "tags": item.get("tags") or [],
                "downloads": (item.get("stats") or {}).get("downloads", 0),
                "quality": item.get("quality_score") or 0.0,
                "published_at": item.get("published_at"),
                "matched_queries": [],
                "best_rank": 0.0,
            })
            record["matched_queries"].append(query)
            record["best_rank"] = max(record["best_rank"], item.get("rank") or 0.0)

    # rote truncates a process step's stdout at 65536 bytes, silently, mid-JSON.
    # The full result for a broad idea runs to about 120 KB, so this trims to a
    # budget instead: descriptions clipped, matched queries reduced to a count,
    # and only the strongest candidates kept. Found by running a pulled copy
    # rather than the working tree, which is the only way this shows up.
    BUDGET = 48000
    DESC = 220

    ranked = sorted(hits.values(),
                    key=lambda c: (-len(c["matched_queries"]), -c["best_rank"]))
    trimmed, dropped = [], 0
    for record in ranked:
        trimmed.append({
            "reference": record["reference"],
            "name": record["name"],
            "owner": record["owner"],
            "owner_kind": record["owner_kind"],
            "description": " ".join(record["description"].split())[:DESC],
            "tags": record["tags"][:8],
            "downloads": record["downloads"],
            "quality": record["quality"],
            "published_at": record["published_at"],
            "matched_queries": record["matched_queries"][:3],
            "matched_query_total": len(record["matched_queries"]),
            "best_rank": record["best_rank"],
        })

    def payload(records, note):
        return json.dumps({
            "probe": "search",
            "idea": idea,
            "content_words": words[:12],
            "queries_run": queries,
            "queries_failed": failed,
            "candidates": records,
            "candidate_count": len(hits),
            "candidates_reported": len(records),
            "candidates_dropped": note,
        }, sort_keys=True)

    text = payload(trimmed, 0)
    while len(text) > BUDGET and len(trimmed) > 5:
        step = max(1, len(trimmed) // 10)
        del trimmed[-step:]
        dropped = len(hits) - len(trimmed)
        text = payload(trimmed, dropped)

    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
