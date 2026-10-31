---
name: kvb-git-branch-gc
description: >
  Remove merged branches and worktrees with `pkgmgr branch gc`: dry run,
  operator picks from the plan, then apply; unmerged items only one by one.
  Trigger on /kvb-git-branch-gc, "branches aufräumen", "worktrees aufräumen",
  "garbage collect".
---

`pkgmgr branch gc` decides what is merged and does the removing; this skill
decides what may go and who has to agree first. The dry run changes nothing,
and nothing is removed before the operator's pick in this run.

## Step 0: claim and chair

1. Claim `work/branch-gc-<repo>`, or `work/branch-gc-all` for every
   repository, through the `kvb-org-organize` skill.
2. The apply takes stacks down and ends with a host-wide
   `docker image prune -f` and `docker builder prune -f`, which reach every
   session's images and build cache. When another session holds the chair,
   send it what, where and how long, and wait for the grant; the prune never
   runs during a peer's build.

## Step 1: dry run

`pkgmgr branch gc --json`, with `--all` only when the operator asked for every
repository, output to `/tmp/branch-gc-<N>.json`. No `git fetch` of your own
before it: gc fetches without auto-maintenance, while a plain fetch on git
2.50 or later may prune the sandbox's bind-mount stubs. Every repository's
`warnings` (a failed fetch) go to the top of the plan. Sort the items:

- **Candidates**: `state` `merged-clean`, non-empty `actions`, and `skip`
  null or `lock: liveness unknown`.
- **Step 5**: `state` `unmerged` or `dirty`.
- **Reported only**: `protected`, every other `skip`, and `stale` as one count
  per repository.

Never override a state: a branch without own commits is `unmerged` even
though git sees its tip on the default branch, because it is fresh work.

`host_pid_namespace: false` means the dry run ran inside a sandbox: it saw no
processes and could not tell whether a lock is live. Say so above the plan;
the apply re-checks both on the host.

## Step 2: claims

Read `council.py list`. For every candidate whose branch or worktree a peer's
claim names, send that peer one message (Peer protocol) and wait up to 5
minutes. A kept or unanswered item leaves the plan as `keep (<peer>)`;
silence is not consent.

## Step 3: plan

One table:

| Repo | Branch or worktree | Merged by | Actions | Note |

Then ask with `AskUserQuestion`:

- **Call 1** (`multiSelect: true`): the candidates, grouped by repository,
  nothing preselected. Each description names `merged_by` and every action
  (stack with volumes, the `images`, worktree, local and remote branches), and
  `lock checked at apply` where liveness was unknown.
- **Call 2** (`multiSelect: false`): `Apply: <n> items (Recommended)`,
  `Revise the selection`, `Abort`. Revise repeats call 1.

## Step 4: apply

1. Re-read `council.py list` and drop every item claimed since the dry run.
2. `--apply` refuses outside the host PID namespace (exit 2) and deletes
   remote branches, which is a push. Unless this session runs in the host PID
   namespace and the project lets agents push, hand the operator one command
   per repository, run from inside it, one `--branch` per picked item (the
   worktree path for a detached worktree):

   ```bash
   pkgmgr branch gc --apply --json --branch <name> --branch <name> | tee /tmp/branch-gc-apply-<N>.json
   ```

3. Read every item's `result` in that file: `done`, `done; image kept: <img>`
   (still in use elsewhere), or `failed: <why>`.
   Report a failure as it stands; never remove by hand what gc skipped or
   refused.
4. For every `done` item, drop its worktree and branch from the task that
   lists them in the `kvb-org-rasci` register (`rasci.py artifacts` names
   it): `set <task> --drop-artifact worktree:<path>`, and `--branch ''` where
   the branch is gone.

## Step 5: unmerged and dirty

Never part of the apply. One `AskUserQuestion` question per item
(`multiSelect: false`): `Keep (Recommended)` and `Delete`, the description
naming what is lost (the item's `reason`: unique commits, dirty paths). For
each `Delete`, hand the operator
`pkgmgr branch purge --branch <name>`: it asks y/N per item and answers no
without a terminal, so it runs only in the operator's shell.

## Step 6: report

Removed, kept and skipped items, each with its reason, and
`docker system df` before and after. Report the release to the chair, tell
each peer whose line an item touched what went, and release the claim.

## Rules

- A pick from an earlier run does not carry over.
- Never widen the selection, and never route around a refusal through another
  command or a peer.
