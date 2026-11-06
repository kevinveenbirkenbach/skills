---
name: kvb-ci-triage
description: >
  Triage a failing CI run to verified root causes and real fixes, one
  cluster per worktree. Trigger when a build, test or deploy pipeline fails.
---

Drive a red pipeline green by root cause. Every failing job is its own
investigation; no fix before its root cause is proven. For GitHub Actions,
the `kvb-ci-artifacts` skill's `ci_failures.py <run>` does the mechanics of
steps 0 to 2; the judgement stays yours.

## Procedure

0. **Run against HEAD, first**: `git log --oneline <run-sha>..HEAD | wc -l`.
   Zero: the run speaks for the current tree. Otherwise read `stale-run.md`
   next to this file before anything else.
1. **Enumerate** every job that failed, was cancelled or timed out. An
   aggregate job failing only because an upstream one did is noted, not a
   root cause.
2. **Cluster** by the actual failing line, not the job name; messages that
   differ beyond interpolated identifiers (host, app, port, path) are
   separate clusters.
3. **Coordinate** each cluster via the `kvb-org-organize` Peer protocol,
   lineage included: `${CLAUDE_SKILL_DIR}/../kvb-git-hotfix/scripts/hotfix.py
   match --line '<line>'` first; claim it; read `council.py list`, the
   register, the radio and `find_fix.py`; ask every live peer, one batched
   `radio.py send call --to <peer>` per peer for all clusters nothing there
   answers. Investigate
   while waiting; take their fix or keep yours. Register (`kvb-org-rasci`):
   objective the root cause fixed, one key result per failing job passing.
4. **Artifacts** per cluster (the `kvb-ci-artifacts` skill: in-progress
   logs, which bundle, grep hygiene): every artifact of one representative
   job (reports, rescue diagnostics, inventories, container logs); a second
   member's only when the first leaves part of the cluster unexplained. Pull
   them even when the log looks conclusive: it only names the artifact; the
   assertion, server-side exception and state dumps are inside.
5. **One funnel per cluster** via the `kvb-org-split` skill: one agent per
   claimed cluster, its own worktree and branch from the exact current HEAD,
   that cluster its only concern, worked as `funnel.md` next to this file
   says (dialectic, shared vs hidden causes, root fix); read it before
   working one yourself. Spawn only as many as the stakes justify; each
   brief names that file, the failing line, artifact paths, files and the
   claim to prove or refute, a time cap for the interim report and an answer
   cap (verdict table, at most 15 lines). Parallel only when the fixes touch
   different files and the machine has room.
6. **Timeouts**: only for a cluster whose jobs died on their time budget, or
   on operator request, hand the furthest-running job log to `kvb-code-tune`;
   its candidates get funnels of their own and never delay the fix.
7. **Follow** a run still in progress and triage each newly failed job; done
   when the run finished and every failure has a verified fix.

## Rules

- Explore code through the codebase-memory-mcp graph first (`search_graph`,
  `trace_path`, `get_architecture`, `detect_changes`; the
  `kvb-agent-optimize` skill sets it up), grep and read after.
- Only the job log, the artifact, the code at the run's commit and command
  output you just ran count as evidence, quoted literally; a summary, your
  earlier message, an old cluster table or a subagent's report proves
  nothing. After a context compaction, rebuild every attribution from the job
  logs before acting on it.
- Classify each failure: real defect (fix), flake or infra (prove it
  transient first), or fixed by a later commit (compare `<run-sha>..HEAD`,
  never the run's commit alone; name the fixing commit).
- Per job verdict: root cause, the proving artifact path and line, the fix,
  the sidetree branch, the funnel verdict (merged or proposal). A verdict
  citing only the job log has not finished step 4.
