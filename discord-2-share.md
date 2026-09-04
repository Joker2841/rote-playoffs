Published three Plays, all read-only, no credentials, python3 only.

sai0000/wsl-toolchain-doctor - which commands on a WSL machine are not the program you think they are. Windows shims winning on PATH, tools that only answer to their .exe name, and dangling /mnt/wsl integration symlinks that look installed and resolve to nothing.

sai0000/wsl-disk-reclaim - why the Windows drive is full when WSL says it is not. A WSL2 virtual disk grows and never shrinks, and df inside only ever shows the inside view.

sai0000/play-quality-doctor - why a Play's quality score is capped when validate reports Pass with zero errors. Came out of the bug report I posted in #bug-reports; reports every unsatisfied signal with the exact edit.

```
rote play run https://play.modiqo.ai/sai0000/play-quality-doctor@0.2.0
```

Source, including the script that re-derives the quality weights yourself:
https://github.com/Joker2841/rote-playoffs

Each README documents the bugs I shipped fixes for rather than around, including one where I assumed bash appends .exe when resolving a bare command name. It does not, and that wrong assumption is what led me to the dangling-symlink case that turned out to be the most useful finding in the first Play.
