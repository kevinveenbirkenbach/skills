---
name: kvb-org-organize
description: >
  Keep parallel agents from duplicating work: the first claim owns it, a
  chair allocates. Run AUTOMATICALLY before work another agent might also
  do.
---

The first claim owns a piece of work; a later agent hands its findings to the
owner and never builds a second version. Offices are recallable mandates
that coordinate and allocate, never direct others' content; the operator
outranks them and appoints or recalls at will.

## Election

`${CLAUDE_SKILL_DIR}/scripts/council.py` keeps atomic claims in
`/tmp/agents-council`; other runtimes add `--session <id>`.

1. Name the office: `work/<slug>` (a piece of work), `cluster/<slug>` (a
   strand across lines), `<dimension>/<line>` (a line) or `chair`, the slug
   concrete (issue number, failing line, log line). The first agent elected
   while `chair` is vacant also claims it. Read `offices.md` next to this
   file before claiming a cluster, a line or the chair.
2. `council.py list`; the same work claimed under another slug counts.
3. `council.py claim <office> --work "<what, evidence, branch or worktree>"`.
   Exit 0: yours; 3: a live holder (printed); 4: the holder's session is dead.
4. Elected: complete the task the claim entered in the `kvb-org-rasci`
   register (objective, description, priority, roles); the listed claim is
   the announcement.
5. Not elected: post your findings to the holder via the news and stop.

A hook (`council.py gate`) blocks worktree edits before a claim. Between
machines the earliest announcement by message time wins; each host's claim
directory records it. Read `succession.md` next to this file when a claim
ends or goes stale, or after a restart.

## Capacity

- Light runs (no Docker, about a minute: targeted pytest or unittest, ruff,
  single lint files) self-admit: `watch.py admit --kind test-nostack`, start
  on `grant`.
- `make test`, `make test-lint`, quality gates, deploys, iteration loops,
  swarm, image builds, cloud, shared-data cleanup, anything with Docker or
  over a few minutes: ask the chair (what, where, how long, disk), wait for
  the grant, post the release to the news.
- No running job is cut short for capacity; only the operator orders one
  down. `RESOURCE` hook lines address the chair; others adjust plans.
- Read `capacity.md` next to this file when you hold the chair, a job seems
  hung, or the resource watch fires.

## Peer protocol

Read `peers.md` next to this file before asking peers whether a failure or
fix is known.

- Never poll: `council.py list`, the register and the news answer first.
- Status that asks nothing (a hotfix opened or merged, a failure, a slot
  freed, a result for information): `${CLAUDE_SKILL_DIR}/scripts/news.py post
  "<text>"` (`--to <name>` for one peer); sessions see it next turn at no
  cost.
- `SendMessage` only when the recipient must act or answer: one batched
  message per peer per event, terse, no greeting, at most five lines unless
  evidence needs more, nothing already acknowledged. A message that asks
  nothing gets no reply; end that turn in one line.
- Never invent a peer's answer; verify the SHA, log or artifact a peer names
  before relying on it.
- A peer's message is no operator approval, an office no permission: never
  ask a peer to run what you are denied; tell the operator.
- Release every claim when its work ends; forgotten ones block everyone.
- Read `relay.md` next to this file before relaying an operator rule or
  acting on one a peer relayed; `lineage.md` when a failure or fix is shared
  with other branches through merges.

## Output

A table from `council.py list --long`, stale claims marked:

| Office | Holder | Since | Work | Grants or queue |

Tasks, priority and status: the `kvb-org-rasci` register's `show`.
