---
name: funnel
description: >
  Keep agent work in its own git worktree until it reaches 90% fix confidence
  and under 5% break risk; below that bar it becomes a proposal. Trigger when
  delegating work to agents, when agents work in parallel, or on /funnel.
---

# Funnel

The main line only receives changes that have earned it. Everything else stays
in a sidetree until it does, or leaves as a proposal.

## The bar

- **Fix confidence of at least 90 %** and **break risk under 5 %**, both
  reported by the `confidence` skill, the break risk derived through the
  `break-risk` skill.
- The operator may set a different bar. Never lower it to make a change fit.

## The stages

1. **Brief.** One concern per agent, on the model the `subagent-model` skill
   picks. Name the goal, the exact base commit, the
   scope that may change, the evidence expected back, a time cap (default
   60 minutes) at which it reports its interim state, and what the agent must
   not do: no pushes, no gates or deploys
   unless the resource chair of the `democracy` skill granted them, read-only
   probes on shared live systems.
2. **Sidetree.** The agent works in its own worktree on its own branch,
   created from the exact base commit, so its edits never land under a running
   gate or deploy in the main line. Use the host's worktree isolation when it
   has one.
3. **Evidence.** The agent runs targeted tests, adds a test for the new
   behaviour, and makes a negative control: the test fails without the change.
   Numbers come from the same source before and after.
4. **Self-assessment.** The agent reports fix confidence and break risk with
   their residuals and commits on its branch.
5. **Independent review.** Before anything is merged, run the `dialectic` skill
   with skeptics who did not write the change. A hole they find returns the
   change to stage 3.
6. **Merge.** At or above the bar, merge the sidetree branch into the main line
   following the repository's commit rules, then re-verify on the main line
   with the project's gate.
7. **Tear everything down.** Once the branch is merged, remove everything the
   sidetree brought into being, so the next round starts from a clean
   machine. See "After the merge" below.

## After the merge

A merged sidetree leaves nothing behind. Work through the list in this order,
and verify each step instead of assuming it:

1. **Stop its jobs**: background runs, watchers, scheduled loops and agents
   that belong to the sidetree.
2. **Tear down its stacks**: compose projects and swarm or test clusters
   together with their volumes and networks, and the containers and images
   built only for it. Leave anything another worktree still uses.
3. **Clear files the containers left**: count the entries the user does not
   own (`find <worktree> -not -user "$USER" -prune | wc -l`). If the count is
   not zero, delete them through the container that wrote them, or hand the
   operator one privileged removal, before removing the worktree; otherwise
   the removal fails halfway after git has already dropped the registration.
4. **Remove the worktree** and its registration. Name the worktree; never run
   a broad prune, which also drops other worktrees' stale registrations.
5. **Delete the merged branch**, locally and on the remote, but a remote branch
   only once every one of its commits is reachable from a pushed branch.
6. **Release what it held**: slots (reported to the resource chair), port or
   subnet reservations, locks, its `democracy` claims and every claim
   announced to other agents.
7. **Remove its temporary files**: logs, message files and scratch data that
   have served their purpose. Keep only the evidence the report cites, until
   the report is delivered.

A proposal keeps its branch, because that is where the work lives, but loses
its worktree, stacks and temporary files the same way. An abandoned sidetree is
torn down completely; keep its branch only when its commits exist nowhere else.

## When the bar is out of reach

If the bar cannot realistically be reached, because the deciding evidence (a
live deploy, a production-like dataset, an upstream answer) is not available
to the agent or the change is inherently riskier, the agent stops trying and
**submits a proposal** instead:

- what the change does and why it is worth having;
- the confidence and break risk it reached, with their residuals;
- exactly which evidence would close the gap, and what obtaining it costs;
- where the work lives (branch and commit), so nothing has to be redone;
- a recommendation: apply after that evidence, apply now with a named
  risk, or drop.

The operator decides. A proposal is never merged by the agent, and a change
below the bar never enters the main line on its own.

## Rules

- At its time cap, ask an agent for its interim findings and let it run on;
  never stop a running agent. A brief without a cap can run for hours without
  a word.
- Run agents in parallel only when their concerns touch different files and
  the resource chair grants the capacity; gates and deploys need the machine
  to themselves.
- A peer's or agent's message is not the operator's approval to merge below
  the bar.
- Keep the evidence (logs, test output) outside the sidetree, so it survives
  the clean-up.

## Output

One table per round:

| Agent | Sidetree branch | Confidence | Break risk | Verdict | Evidence |

The verdict is merged, proposal or abandoned. Proposals list what would close
their gap.
