---
name: kvb-org-unify
description: >
  Merge a swarm's branches, gate once, land on the operator's word, then clean up.
---

The `kvb-org-swarm` skill splits a goal into sidetrees; this skill brings them
home in one pass. Invoking it clears the merges into `unify/<goal>`; the line
receives nothing, and nothing is removed, without the operator's word in this
run. Never push: that stays with the operator (`kvb-git-push`).

## Step 0: claim

Claim `work/unify-<goal>` through the `kvb-org-organize` skill and enter it in
the `kvb-org-rasci` register: objective "every swarm branch of `<goal>` at the
bar on `<line>`", key results gate green, landed, cleaned up, overview posted.
`<line>` is the line the operator names, else the default branch.

## Step 1: collect

The register is the swarm's record (stage 2 of `kvb-org-swarm` sets `--branch`
and `--base`):

```bash
jq -r --arg base "<line>" 'to_entries[] | select(.value.base == $base and .value.branch) | [.key, .value.branch, .value.workdir // "-", .value.status] | @tsv' "${AGENTS_COUNCIL_ROOT:-/tmp/agents-council}/rasci.json"
```

Per branch: `git log --oneline <line>..<branch>` (empty: already merged, go
to step 5), `git status --porcelain` in its worktree, its latest
`kvb-check-score` block and its independent review (`kvb-org-swarm` stage 5).
A branch is **ready** only at the bar, clean, reviewed and with its owner's
claim released or the owner's yes by `radio.py post`; everything else is a
proposal with its reason: below the bar (the score), unreviewed, dirty, owner
busy.

## Step 2: integrate

A worktree in a released directory on `unify/<goal>` from `<line>`. Merge the
ready branches, highest register priority first, with
`git merge --no-ff --no-verify <branch>`. A conflict: `git merge --abort`, and
the branch becomes a proposal naming the conflicting files.

## Step 3: gate

The project's full gate on `unify/<goal>` through `queue.py hold`
(`kvb-check-gate`), and `security.py` over `<line>..unify/<goal>`
(`kvb-check-security`), logs under `/tmp`. Red: find the merge that broke it
(`git bisect start --first-parent`), rebuild the branch without it, which
becomes a proposal naming the failing test, and gate again.

## Step 4: land

Show the `kvb-check-score` commit table of `<line>..unify/<goal>` and every
proposal. On the operator's word: `git merge --ff-only unify/<goal>` in the
line's checkout; when the line moved meanwhile, merge it into `unify/<goal>`
and gate again first. The push goes to the operator as a `kvb-org-operator`
row.

## Step 5: clean up

Per merged branch and for `unify/<goal>`, the teardown of `kvb-org-swarm`
(`teardown.md`: jobs, stacks, container-owned files, worktree, register). A
proposal keeps its branch and loses worktree, stacks and temporary files. Then
the dry runs of `kvb-git-branch-cleanup` (`--merged-into <line>`) and the
inventory of `kvb-cleanup` for the swarm's logs, scratch and Docker leftovers,
merged into one table (area, item, size, owner, risk, what breaks if wrong)
and one `AskUserQuestion` pick; each skill removes only the picked items, by
its own execute rules. What the sandbox blocks becomes a `kvb-org-operator`
row.

## Step 6: report

Post the overview to the operator, not merged first:
`${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py post --to Operator
"unify <goal>: <m> of <n> merged; NOT merged: <branch> (<reason>, closes with
<step>), ..."`. Set the register task `done`, or `stopped` while a key result
is open.

## Output

First line, when any branch stayed out: **⚠️ <k> of <n> swarm branches NOT
merged**. Then one table, not merged rows first:

| Branch | Task | Score | Verdict | Reason / what closes the gap |

Verdict: **⚠️ NOT MERGED** (proposal), ✅ merged, 🧹 removed. Below it the
cleanup result per area and the operator rows handed over.
