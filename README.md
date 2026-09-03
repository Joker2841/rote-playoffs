# wsl-toolchain-doctor

A Play for the Rote Playoffs. It answers one question on a WSL machine: which
of the commands you type are not the program you think they are.

Read-only. No credentials. Needs python3 and nothing else.

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

## Fixtures

The fixtures under `presentation-fixtures/` are synthetic and use generic paths.
A real run names the machine's actual software and its Windows user directory,
which does not belong in a public artifact.

## Licence

MIT
