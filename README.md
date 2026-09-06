# rote-playoffs

## A note on how these were tested

Every Play here was verified by pulling it fresh from the registry and running
that copy, not the working tree. That is the artifact a stranger receives, and
it is the only way one class of bug shows up at all: `rote` truncates a process
step's stdout at exactly 65536 bytes, silently, mid-JSON, and the step that
consumes it then fails to parse. Three of these five would have shipped broken
on a machine slightly larger than mine.

Output budgets and their measured breaking points are documented per Play below.

They were also read cold, as a stranger would, and then audited a second time by
five independent reviewers who did not write them and were told to try to break
them. That second pass found more than the first, and the worst of it was a
class I had not looked for: claims that were confidently false rather than
merely missing.

The headline ones, each written up under the Play it belongs to:

- `which-actually-runs` printed secrets. Redaction was a denylist of five
  words, so `SSH_PRIVATE_KEY`, `OPENAI_KEY`, `NPM_AUTH`, `STRIPE_SK` and
  `DATABASE_URL` all reached the report. It is an allowlist now.
- Both PATH plays counted `/bin/git` and `/usr/bin/git` as two copies of git.
  `/bin` is a symlink to `usr/bin`, so eight of thirteen findings on this
  machine were one file counted twice, and a duplicated PATH entry made a
  command shadow itself.
- Both called `code`, `tsc` and `yarn` Windows programs. They are POSIX shell
  scripts that happen to live on the Windows drive and run as ordinary Linux
  processes. Living under `/mnt` is not the test; the two-byte `MZ` header is.
- `play-quality-doctor` said `rote play validate` calls capped plays a clean
  pass. It does not: it reports them as warnings and names two of the three
  signals itself. The real gap is one signal, `frontmatter_completeness`, which
  validate rates `info` and therefore never mentions.
- `is-it-taken` called a play about files an agent touched a collision with an
  idea about watching web pages, because both names contained "since" and
  "last". Its stemmer also turned `files` into `fil` and `notes` into `not`.
- Given a PATH where nothing resolved, both PATH plays reported that every
  watched command resolved correctly.

Every one of those is a false statement about the user's machine, which is the
worst thing any of these can produce, and none of them would have shown up in a
run that went well.

Five Plays for the Rote Playoffs. Two are WSL-specific, three run anywhere. All
five are read-only and need nothing but python3 and coreutils. No credentials,
no network except the registry search in `is-it-taken`, no adapters.

    sai0000/wsl-toolchain-doctor    which commands are not the program you think
    sai0000/wsl-disk-reclaim        why the Windows drive is full when WSL is not
    sai0000/play-quality-doctor     why your Play's quality score is capped
    sai0000/which-actually-runs     which copy of a command actually runs, on any Unix
    sai0000/is-it-taken             has someone already published the thing you are about to build

---

# wsl-toolchain-doctor

Answers one question on a WSL machine: which of the commands you type are not
the program you think they are.

## Why this exists

WSL appends the Windows PATH to the Linux PATH by default, and interop makes
Windows executables reachable. That produces three failures that look identical
in a terminal, and the fix for each is different:

1. A command resolves to an extensionless Windows shim under `/mnt/c` and runs
   as a Windows program. `docker` with a bind mount then hands a Windows client
   a Linux path it cannot see.
2. A command does not resolve at all, while its `.exe` sits on PATH. The shell
   says "command not found" about a tool that is plainly installed. This is the
   most confusing symptom of the three.
3. A command is a symlink into `/mnt/wsl` left by a Docker Desktop style
   integration, which fills that path only while it is running. Listing the
   directory shows the tool. Running it finds nothing, and a Windows copy
   further down PATH silently takes over.

Separating those is the point.

## What it reports

- Which watched command wins, the exact path, and what it beat.
- The configuration behind it: `appendWindowsPath`, drive mounts missing the
  `metadata` option so `chmod` appears to succeed and does nothing,
  case-insensitive mounts that collapse two tracked files into one, and whether
  your home and project sit on the slow 9p filesystem.
- Its own scope. It reports the PATH of the shell that invoked it and says so.

On a host that is not WSL it returns a single applicability verdict rather than
inventing findings.

## Running it

    rote play run wsl-toolchain-doctor/main.ts

Optional parameter, comma separated, added to the built-in watchlist:

    rote play run wsl-toolchain-doctor/main.ts commands=poetry,rbenv,deno

## Layout

    wsl-toolchain-doctor/
      main.ts                  frontmatter steps + presentation
      deps.toml                declares python3
      resources/
        probe_platform.py      WSL flavour and interop state
        probe_shadow.py        PATH resolution across the watchlist
        probe_traps.py         wsl.conf, drive mounts, case sensitivity
        render.py              joins the three into one briefing
        presentation-fixtures/ representative evidence for lint

The three probes are independent root steps and run in parallel. The renderer
depends on all three.

## Two corrections kept on the record

The first version of the command probe assumed bash appends `.exe` when
resolving a bare name. It does not; only an exact filename resolves. That made
it report `python`, `java`, `psql`, `kubectl` and `redis-cli` as actively
running Windows programs when they do not resolve at all. Checking `kubectl`
against ground truth exposed the mistake, and also turned up the dangling
`/mnt/wsl` symlink case, which became the most useful finding in the Play.

The first version of the configuration probe treated every mountpoint under
`/mnt/` as a Windows drive, sweeping in WSL's own tmpfs and iso9660 plumbing and
producing sixteen identical warnings. It also read `/mnt/c` as case sensitive,
because `os.path.exists` returns False for a permission-denied path and the
first unreadable entry on a Windows root is reliably `$Recycle.Bin`.

Both are fixed. They are described here because a diagnostic that hides how it
was wrong is harder to trust than one that shows it.

## A third correction, found by reading the output cold

The header counted `9 medium, 11 low, 2 info` and the report listed nine and
two. The eleven low findings were computed, counted, and then filtered out of
the text by a `high, medium` check in the renderer, so they existed only in the
JSON. A stranger could count what was on screen and find eleven missing.

They are now listed, grouped by kind because they repeat heavily. The counts
also come from every finding rather than the filtered set, so raising
`min_severity` no longer quietly shrinks the totals; it says `(showing medium
and above)` instead. `which-actually-runs` had the same bug and hid thirteen
findings, which mattered more there because those findings are the question the
Play is named for.

## Fixtures

The fixtures under `presentation-fixtures/` are synthetic and use generic paths.
A real run names the machine's actual software and its Windows user directory,
which does not belong in a public artifact.

## Licence

MIT


---

# wsl-disk-reclaim

Answers a different question on the same machine: why is the Windows drive full
when the distro says it is not.

A WSL2 distro lives in a virtual disk that grows on demand and never shrinks on
its own. Delete forty gigabytes inside and the file Windows sees stays exactly
as large as it ever got. `df`, run inside, reports only the inside view, so the
space is invisible from the one place people look for it.

## What it reports

- Each virtual disk on the Windows side, sized, and what the distro admits to
  using inside. The gap is what a compaction would give back.
- The caches inside worth clearing, with nesting marked so a parent directory
  and its child are never counted twice.
- Commands, in the order that works. Freeing space inside does nothing to the
  Windows file until the image is compacted, and compacting before freeing
  reclaims almost nothing. That ordering is why people try one half, see no
  change, and conclude the whole thing is a myth.

## Running it

    rote play run wsl-disk-reclaim/main.ts
    rote play run wsl-disk-reclaim/main.ts format=json threshold_mb=1000
    rote play run wsl-disk-reclaim/main.ts extra_paths=~/work/node_modules

## Two more corrections kept on the record

The first version summed both virtual disks and subtracted the distro's inside
usage, which counted Docker Desktop's live data as reclaimable and overstated
the answer by about 50 GB. Docker keeps a separate disk whose interior is not
visible from inside the distro, so it is now reported on its own terms with a
pointer to `docker system df`.

The second version double-counted caches: `~/.cache/pip` and
`~/.cache/ms-playwright` both sit inside `~/.cache`, so the total claimed 12.25
GB where the honest figure was 6.92 GB. Nested paths are now detected and
excluded from the total, and labelled in the output.

Both were caught by checking the numbers against the machine rather than
trusting them. A tool that tells you how much space you can get back is worth
nothing if the number is inflated.


---

# play-quality-doctor

Answers one question about a published Play: why is its quality score capped,
when nothing is telling you.

`rote play validate` prints a score, reports zero errors and zero warnings, says
Pass, and stops. If the score is 0.65 it will not say which signal is
unsatisfied, what it wanted, or what the missing field is worth.

## Where the numbers come from

`rote play score <main.ts>` reports every signal with its weight and status,
and it is authoritative. This Play runs it across every Play you have, ranks the
signals by what they are costing you in total, and adds the exact edit for the
ones whose required shape is not obvious from the wording.

    frontmatter_completeness  0.25   partial credit; tags and discoverability
    parametrization           0.25
    output_format             0.25
    provenance_url            0.10
    response_id_leak          0.05
    dag_structure             0.05
    jsonpath_syntax           0.05

Run `rote play score` on any single Play and the numbers here will match,
because they are the same numbers.

## A wrong turn worth recording

The first two versions of this Play did not wrap `rote play score`. They
reconstructed the rubric from the outside, by mutating a Play that scored 1.00
one field at a time, because I had not found that the command existed. It was
listed in `rote play --help` the whole time.

That reconstruction produced roughly correct totals from a structurally wrong
model:

    output_format             0.25   correct
    frontmatter_completeness  0.25   correct, but modelled as all-or-nothing
    parametrization           0.13   actually 0.25
    discoverability           0.12   not a signal at all
    provenance_url            0.10   correct
    dag_structure             0.08   actually 0.05
                                     response_id_leak 0.05 was missed entirely

The invented `discoverability` signal is also the real reason for an interaction
I had measured and could not explain, where removing tags and version together
cost less than the sum of removing each alone. They were never separate signals:
tags are one input to `frontmatter_completeness`, which is scored at partial
credit.

Chi blu pointed out the command in the Rote Playoffs Discord. The model is gone
from the Play, which calls the real scorer. `tools/derive_rubric.py` is kept and
marked superseded, because the mutation method is still reasonable for probing
an undocumented scorer, and because deleting the evidence of a wrong turn is
worse than leaving it in.


## Why this exists

Two of the rules are counterintuitive. Tags under
`metadata.discoverability.tags` do not satisfy the discoverability signal, and
that is the shape the workspace exporter generates, so a Play can carry nine
tags and still lose the points. And `provenance_url` reads a top-level `source:`
field, not `provenance.url`.

An earlier version of this section claimed `validate` reports a clean pass on
capped Plays. An audit showed that is false, so here is what is actually true.
`rote play validate` prints the score, and it reports the signals it rates as
warnings, with suggestions. For `modiqo/hello` at 0.52 it names `output_format`
and `provenance_url` itself.

What it never mentions is `frontmatter_completeness`, because that signal is
rated `info` rather than `warning`. So a Play can be marked down 0.125 with
validate printing Pass and saying nothing at all about the reason. That was true
of 5 of the 18 Plays installed when this was written, and it is the one signal
this Play surfaces that nothing else does.

The rest of what it adds is arithmetic rather than discovery: validate runs on
one Play at a time, so it cannot tell you that `provenance_url` is costing you
0.60 across six Plays, or which single edit clears the most.

## What it is not

It is not a model of the scorer. It shells out to `rote play score --format
json` once per Play and reports what comes back, so the numbers cannot drift:
run `rote play score` on any single Play and they will match, because they are
the same numbers. It is also not a general Play linter, deliberately. It answers
one question.

## Running it

    rote play run play-quality-doctor/main.ts
    rote play run play-quality-doctor/main.ts play=modiqo/hello
    rote play run play-quality-doctor/main.ts format=json min_score=0.99

Read-only. It reads frontmatter and nothing else, modifies no Play, needs no
credentials and no network. pyyaml is used only when already importable, with a
structural-scan fallback, so running it never requires installing anything.


---

# which-actually-runs

Answers one question on any Unix machine: when you type a command, which copy
actually runs, and what did it beat.

Four unrelated causes produce that same symptom and none announce themselves.

- A **version manager** puts a shim ahead of the system copy. Correct, until two
  of them fight or a shim points at a version you uninstalled.
- **Homebrew** installs to `/opt/homebrew` on Apple silicon and `/usr/local` on
  Intel while the system copy stays in `/usr/bin`. Which wins depends on a PATH
  order nobody set on purpose.
- Under **WSL** the Windows PATH is appended, so a command can resolve to a
  Windows program, or fail to resolve while its `.exe` sits on PATH and the
  shell reports command not found about an installed tool.
- An **integration symlink** from Docker Desktop and similar resolves only while
  that integration runs. The listing shows the tool; running it finds nothing.

It names the winning path, what it beat, and which cause explains it. Then it
reads your shell startup files to show which line put each directory on PATH,
because knowing nvm beats Homebrew does not tell you which file to edit.

## A gap that stayed open until the last pass

A version manager on PATH whose directory no longer exists was dropped from the
report rather than named. The summary filtered managers to the ones that exist,
so the "shim points at a version you uninstalled" case - the one the description
leads with - was the one case that produced no output at all. It is now a medium
finding, and running it against my own machine immediately turned up a real
one: `/snap/bin` on PATH, no `/snap` directory.

It is grouped by manager, not listed per entry. A PATH carrying 800 dead pyenv
directories is one problem told 800 times, and the first version of this fix
printed 4000 lines of identical text before the grouping went in.

## Why this exists separately from wsl-toolchain-doctor

`wsl-toolchain-doctor` is the WSL specialist. This is the same engine with the
platform gate removed, because the shadowing problem is not WSL's: it is the
same shape on macOS with nvm and pyenv, and the cause differs by platform rather
than the symptom.

## Running it

    rote play run which-actually-runs/main.ts
    rote play run which-actually-runs/main.ts commands=poetry,rbenv
    rote play run which-actually-runs/main.ts format=json
    rote play run which-actually-runs/main.ts path_override="/usr/bin:/opt/homebrew/bin"

## Testing

Path classification is unit-tested against 17 real path shapes across macOS,
Linux and WSL. Secret redaction is tested against 7 assignment forms. Detection
of competing version managers was verified on a synthetic host with nvm, pyenv
and asdf all on PATH at once, since this machine has none installed.

Read-only. It parses the text of startup files and never sources them, so a
malformed rc file cannot execute anything. A line assigning a secret-looking
name is reported as present and never echoed.


---

# is-it-taken

Answers the question worth asking before you write a line: has someone already
published this.

The public registry went from 242 Plays to 411 in twenty-four hours. Nobody can
hold that in their head, and `rote play search` answers one query at a time
using the words you happened to choose. This fans your idea into a dozen queries
drawn from its own content words, then ranks what comes back by how close it
actually is rather than by how popular it is. A Play with forty downloads
sharing one incidental word is not a collision. A Play with three downloads
whose name is your idea is.

Four verdicts: **already built**, **crowded**, **adjacent work exists**, and
**nothing close found**, the last deliberately not phrased as proof.

## Why it exists

I lost hours to exactly this mistake. I published `play-quality-doctor` without
noticing that `himanshu-jha/play-quality-doctor` had existed for a day and a
half under the same name, with the same finding. My own registry survey had used
the vocabulary of the ideas I had already picked, never the one I later built.

## What it cannot do

Matching is lexical. Two people can describe the same idea in words that share
nothing, and this will not connect them, so "nothing close found" means no
lexical match rather than nothing built. That limit is printed in the output
every run, along with any query that failed, because a failed query is not an
empty result.

## Three bugs, and how each was found

The fixtures caught the first.

The first version scored "nothing close found" against a Play named
`dependency-sweep` for an idea about "unused dependencies", because `dependency`
and `dependencies` do not match as strings. A false all-clear is the most
damaging thing this tool can produce, so it now stems both sides before
comparing. The stemmer is crude and over-collapses, which is the safe direction.

Running the **pulled** copy caught the second, and nothing else would have.
`rote` truncates a process step's stdout at exactly 65536 bytes, silently, mid
JSON. A broad idea produced about 123 KB of search results, so the next step
received half a document and failed. Every local test had passed because they
handed the file over as an argument and bypassed the step pipeline entirely.
Output is now trimmed to a 48 KB budget, dropped candidates are counted in the
output rather than hidden, and a parse failure at or above the limit now says it
was probably truncated instead of exiting silently.

The lesson generalises: test the artifact a stranger receives, not the one in
your working tree.

Reading the output cold caught the third, and it was the worst of them. Asked
about "find which copy of a command runs first on PATH", it answered **already
built** and named four Plays: one about duplicated Python files, one about pull
request diffs, one about setup instructions, one about GitHub issues. None of
them do this. They shared a single word with the idea - `copy`, `first`, `find`
- and a shared word in a two-word name was enough to score 0.5, which was the
threshold for declaring a collision. The Play that actually matched, my own
`which-actually-runs`, did not appear at all.

Two things were wrong. Words were counted equally, so `first` weighed the same
as `dependency`, and a name is short enough that one common word is most of it.
Both are fixed: words are now weighted by how rare they are across the retrieved
candidates, and **already built** requires at least two independently shared
name words. One shared word now caps at "adjacent", which still puts the Play in
front of you to read.

One correction attempt is worth recording because it failed. To undo the fact
that the queries are built from the idea, and so over-represent its own words, I
measured each word's frequency only over the candidates that some *other* query
found. That is unbiased in principle and wrong in practice: if search returns
nearly every Play containing a word, the complement holds none of them, and the
word scores as maximally rare. It promoted `first` from common to strong
evidence and brought the false verdict straight back. The weighting is
deliberately simple now, and the verdict rests on the structural rule instead.

When every word in an idea is common in the results, the output says so and
asks you to rephrase, rather than ranking on words that carry no signal.

Two degenerate inputs were fixed in the same pass. An empty idea failed the step
outright, so the play reported a crash where it should have reported a usage
problem. An idea of pure punctuation ran one query, matched nothing, and
returned **nothing close found** - a clean all-clear from a search that never
happened, which is precisely the output this play says is the most damaging
thing it can produce. Both now return a fourth-and-a-half verdict, **cannot
tell**, which states that nothing was checked.

## Running it

    rote play run is-it-taken/main.ts idea="what you are about to build"
    rote play run is-it-taken/main.ts idea="..." format=json

Read-only. It searches the public registry through rote, reads nothing local,
and writes nothing.


---

# Output budgets

`rote` truncates a process step's stdout at 65536 bytes without saying so. Any
step whose output scales with the host can cross that line on someone else's
machine while passing on yours. Measured breaking points before the fix:

    is-it-taken          search results      123 KB on a broad idea
    which-actually-runs  PATH entries x cmds  77 KB at 40 PATH entries
    wsl-toolchain-doctor same                 44 KB at 40 PATH entries
    play-quality-doctor  installed plays      crosses 48 KB at 73 plays,
                                              and 64 KB at about 101
    which-actually-runs  shell startup files 122 KB from a 45 KB .bashrc
    wsl-disk-reclaim     extra_paths          69 KB at 200 paths
    both PATH plays      missing PATH entries 99 KB at 700 dead directories

The last three were found by the second audit and were still live. Every step
now trims to a 48 KB budget, degrading in a stated order rather than being cut
mid-structure, and the reduction is named in the report rather than only in the
payload: there is a WHAT WAS LEFT OUT section, because a trim nobody is told
about is how a truncated probe became a clean bill of health.

Measured after the fix: 700 dead PATH directories give 10 KB, a 45 KB .bashrc
gives 8 KB, 200 extra paths give 23 KB.

Two of these were worse than truncation. When the PATH probe overflowed, the
consuming step could not parse it, and the report then said "every watched
command resolves to a Linux copy" and exited 0. That is an affirmative claim
about a machine that was never examined. And `play-quality-doctor` trimmed the
plays it could not score first, because rows with no score sorted last and the
budget cut from the end, so the plays most worth knowing about were the ones
dropped.

A report that quietly stopped listing things is worse than one that says it ran
out of room.
