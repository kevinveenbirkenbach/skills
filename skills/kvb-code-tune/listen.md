# Tune: the session's limits

Ask three questions through the host's structured question mechanism, each a
checklist (multi-select) with suggestions, free text allowed:

1. **What to examine.** Suggestions: CI wall-clock, deploy duration, gate and
   test runtime, image pulls and build caches, per-item loops and process
   spawns, idempotency (work repeated on a second run), network round trips,
   and resource use (CPU, memory, disk, I/O). Language, framework and
   recursion are checked on every run anyway.
2. **Which performance boundaries to keep.** Suggestions: time budgets per
   job, deploy or gate; resource caps (memory, CPU, disk headroom); a minimum
   saving per change (default 10 s per run); the measurement source that
   counts as the verdict.
3. **Which limits apply to optimizations.** Suggestions: the scope that may
   be changed (files, roles, services); whether new dependencies, toolchains
   or languages may be introduced; whether infrastructure or CI configuration
   may change; the merge bar (default: the `kvb-org-split` skill's 90 %
   confidence and under 5 % break risk); a time cap per delegated agent
   (default 60 minutes).
