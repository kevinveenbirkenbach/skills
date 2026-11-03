# Tune: reading the numbers

- **Task profilers** (Ansible `profile_tasks` and similar) print the duration
  of the *previous* task under the *next* task's header. Pair each header
  with the following timestamp line, or read the end-of-run recap.
- **Build logs** (BuildKit): pair `#N [service x/y] RUN …` with `#N DONE Xs`
  by step number; `CACHED` marks a hit.
- **Gates**: per-target wall-clock tables and failed-target lines. An exit
  code piped through `tee` is not a verdict.
- **Code paths**: a profiler (py-spy, cProfile, perf, flame graphs) tells
  whether time goes to CPU, to I/O and waits, or to process start-up.
