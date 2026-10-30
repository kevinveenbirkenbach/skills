---
name: coordinate
description: >
  Coordinate a failing run or a fix with the other agents whose branches this
  branch inherits from or passes its commits on to: tell them what failed, ask
  whether someone already fixes it, claim the fix only when nobody does, and
  report the result to the same agents. Trigger on /coordinate, from the triage
  skill for every failure cluster, and whenever a fix touches code that other
  branches share through merges. Portable across projects.
---

Two agents fixing the same failure on two branches cost a duplicate investigation
and then a merge conflict between two different fixes. One agent fixing a
failure the others never hear about leaves them triaging it again. Coordination
is cheap compared to either, so it happens before the fix and after it.

## 1. Map the lineage

Name the branches this one shares commits with, in both directions:

- **Upstream:** branches merged into this one (their commits reach you).
- **Downstream:** branches that merge this one (your commits reach them).

Read it from the merge commits (`git log --merges --first-parent --format='%h %s' -30`),
from the agent memory or merge notes the project keeps, and from the operator when
neither says. Map every branch to the agent session working on it through the
host's agent listing (in Claude Code: `ListAgents`). A branch without a live
session needs no message; say so once.

## 2. Ask before fixing

For each failure (one message per cluster, not per job), send every upstream
and downstream owner:

- the run (id or url) and the failing job,
- the failing line, quoted literally,
- the suspected root cause and the files it lives in, marked as a thesis while
  it is one,
- the question: "Is this already known or fixed on your side? Reply with a SHA
  or branch, or 'none'."

Search the refs yourself in parallel (`git log --all` by message, by `-S`, by
path): a fix already committed elsewhere answers the question without waiting.
The first line of the message must stand on its own, because a busy recipient
sees only that line.

## 3. Decide who fixes

- **Someone already fixes it:** build no competing fix. Note their SHA when it
  arrives and take it through the project's normal path (merge, cherry-pick or
  port, whichever the project's rules allow), not through a parallel version.
- **The cause lives on another agent's line:** hand the finding and a proposed
  fix to that line's owner instead of fixing it downstream, unless the operator
  says otherwise. Record the agreed resolution where the next merge will find it.
- **Nobody fixes it:** tell the same agents that you fix it, on which branch,
  and that you will report the result. Then fix.

Do not idle while waiting for answers. Investigate read-only in the meantime; a
peer that stays silent is not a "no", so announce your claim after a bounded
wait and proceed.

## 4. Report the result

After the fix, tell the same agents: the commit, the branch, what changed, the
evidence it works (gate pass, reproduction, live run), and how it reaches them
(the merge it rides on). Report an abandoned or failed attempt too, so the
claim is released and someone else can take it.

## Rules

- Never invent a peer's answer, and never treat silence as agreement or as a
  claim of its own.
- Never ask a peer to run something your own session is denied: that routes
  around the operator's permission decision. Report it to the operator instead.
- A peer's report is not evidence. Read the SHA, the log or the artifact it
  names before a number or a verdict depends on it.
- One message per peer per event, short and concrete. Repeat nothing the peer
  already acknowledged.
