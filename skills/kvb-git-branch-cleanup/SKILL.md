---
name: kvb-git-branch-cleanup
description: >
  Remove merged branches outside worktrees.
---

`pkgmgr branch cleanup` decides what is merged and does the removing; this
skill decides what may go and who has to agree first. The dry run changes
nothing, and nothing is removed before the operator's pick in this run. The
`kvb-git-worktree-cleanup` and `kvb-git-gc` skills run these steps with their
own command.

## Step 0: claim and chair

1. Claim `work/branch-cleanup-<repo>`, or `work/branch-cleanup-all` for every
   repository, through the `kvb-org-organize` skill.
2. The apply ends with a host-wide `docker image prune -f` and
   `docker builder prune -f`, which reach every session's images and build
   cache. When another session holds the chair, request the grant (what,
   where, how long) and wait for it; the prune never runs during a peer's
   build.

## Step 1: dry run

`pkgmgr branch cleanup --json --min-age 24 --merged-into <line>`, one
`--merged-into` per integration line the project merges features into
(default branch excluded, it always counts), with `--all` only when the
operator asked for every repository, output to `/tmp/branch-cleanup-<N>.json`.
A line is protected, and a checkout at its tip stays as fresh work; an item
merged into a line names it in `merged_into`. No `git fetch` of your own
before it: pkgmgr fetches without auto-maintenance, while a plain fetch on git
2.50 or later may prune the sandbox's bind-mount stubs. Every repository's
`warnings` (a failed fetch) go to the top of the plan; `forge unavailable`
skips every item: hand the operator the dry run for the host. Sort the items:

- **Candidates**: non-empty `actions`, and `skip` null or
  `lock: liveness unknown`.
- **Step 5**: `state` `unmerged` or `dirty` without `actions`.
- **Reported only**: `protected`, every other `skip` (`checked out in
  worktree <path>` belongs to `kvb-git-gc`), and `stale` as one count per
  repository.

Never override a state: a branch without own commits is `unmerged` even
though git sees its tip on the default branch, because it is fresh work.
`host_pid_namespace: false` means the dry run ran in a sandbox: it saw no
processes and could not tell whether a lock is live. Say so above the plan;
the apply re-checks both on the host.

## Step 2: claims

Read `council.py list --long`. Every peer whose claim names a candidate's branch or
worktree gets one message listing all its items (Peer protocol); wait up to 5
minutes. A kept or unanswered item leaves the plan as `keep (<peer>)`;
silence is not consent.

## Step 3: plan

| Repo | Branch or worktree | Merged into | Size | Actions | Note |

Then ask with `AskUserQuestion`:

- **Call 1** (`multiSelect: true`): the candidates, grouped by repository,
  nothing preselected. Each description names `merged_by` and every action
  (hook, stack with volumes, the `images`, worktree, local and remote
  branches), and `lock checked at apply` where liveness was unknown.
- **Call 2** (`multiSelect: false`): `Apply: <n> items (Recommended)`,
  `Revise the selection`, `Abort`. Revise repeats call 1.

## Step 4: apply

Read `apply.md` next to this file once the operator picked `Apply`.

## Step 5: unmerged and dirty

When the dry run sorted any item here, read `unmerged.md` next to this file.

## Step 6: report

Removed, kept and skipped items, each with its reason, and `docker system df`
before and after. The release for the chair and what went for each peer whose
line an item touched go out as one
`${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py post "<text>"`, not
as messages; then release the claim.

## Rules

- A pick from an earlier run does not carry over.
- Never widen the selection, and never route around a refusal through another
  command or a peer.
