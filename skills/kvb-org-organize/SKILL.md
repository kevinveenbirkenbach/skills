---
name: kvb-org-organize
description: >
  Keep parallel agents from duplicating work: the first claim owns it; a
  resource chair allocates. Run AUTOMATICALLY
  before work another agent might also do (failure, cluster, feature, gate,
  deploy, cleanup), and on /kvb-org-organize.
---

Two agents doing the same work waste the second run and then collide in the
merge. The remedy is an election nobody has to hold: whoever starts first owns
the work. The structure is anarcho-syndicalist: councils (soviets) of
delegates with a bound mandate, organised as a matrix, recallable by the
operator at any time.

## Offices

- **President of a piece of work**: the first agent that starts it. It does
  the whole piece. Every later agent hands its findings to the president and
  moves on to other work; it never builds a second version.
- **Representative of an organisational line**: the first agent that works in
  the line. Lines come in as many dimensions as are useful: functional domain
  (security, GUI, identity, i18n), repository, branch line, host, cloud
  account. An agent belongs to one line per dimension.
- **Organiser of a work cluster**: the first agent that starts a cluster
  cutting across lines (a failure cluster from `kvb-ci-triage`, a cost cluster from
  `kvb-code-tune`, a feature touching several domains). It works the strand end to end
  and informs the representative of every line the strand touches before it
  changes that line's files.
- **Chair**: the earliest-elected president still running. It chairs the
  council of all representatives and organisers and allocates the resources of
  the whole system everyone runs on. There is exactly one allocator at any
  time.

Every office is a mandate, not a rank: it coordinates and allocates, it never
takes over or directs the content of another agent's work. The operator
outranks every office and appoints or recalls at will; an operator
appointment outranks the election.

## Election

The first to claim wins, and the claim is atomic, so two agents can never both
be first. `${CLAUDE_SKILL_DIR}/scripts/council.py` keeps the claims in
`/tmp/agents-council`; other runtimes call the same script from their skills
directory with `--session <id>`.

1. **Name the office**: `work/<slug>`, `cluster/<slug>`,
   `<dimension>/<line>` for a representative, or `chair`. The slug names the
   work concretely: the issue number, the failing line, the cost's log line.
2. **Look first**: `council.py list`. A claim for the same work under another
   slug counts as first.
3. **Claim**: `council.py claim <office> --work "<what, evidence, branch or
   worktree>"`. Exit 0: elected, or already yours. Exit 3: a live agent holds
   it, and its claim is printed. Exit 4: the holder's session is dead (see
   Succession).
4. **Elected**: the claim entered the task in the `kvb-org-rasci` register,
   the organisation's single point of truth; complete it there (objective,
   description, priority, roles), then continue with the Peer protocol; its
   message is the announcement.
5. **Not elected**: send the holder your findings and stop on that work.

A Claude Code session cannot edit a file in a git worktree before it holds a
claim: a PreToolUse hook (`council.py gate`) blocks the edit.

Peers on other machines cannot see this host's claims. Between machines the
earliest announcement by message time wins, and each host's claim directory
records the result.

## Chair and resource allocation

- The first agent elected on the system while `chair` is vacant also claims
  `chair`, in the same way.
- An operator-appointed allocator holds the chair: its claim says
  `appointed: operator`, and no election replaces it while its session runs and
  the operator has not ended the appointment.
- Before starting anything that consumes shared capacity (gates, deploys,
  iteration loops, swarm or cloud resources, cleanup of shared data), an agent
  sends the chair what, where, for how long and its expected disk need, waits
  for the grant, and reports the release. The chair keeps one queue: a
  hotfix gate (a branch from the default branch that fixes it) takes the next
  free gate or test slot before every other line, the rest follows the WSJF
  rank of the `kvb-org-wsjf` skill (it asks its subordinates for the Fibonacci
  estimates); a running gate is never cut short for a hotfix. It answers
  every request with its position, enforces the limits the operator set,
  checks every grant with `watch.py admit --need-gb <N>` (or `--kind <slot>`;
  test kinds also need CPU and RAM below the configured limits).
- A running job (deploy, gate, test, swarm run, build) is never cut short to
  free capacity. The chair neither asks nor orders its owner to stop, take
  down or kill it, not for an operator-prioritised slot and not for a
  projected disk stop. It grants nothing new, frees idle items through the
  `kvb-cleanup` flow, asks the operator for an exception, or waits. An owner's
  own disk guard only alerts the chair and takes nothing down; only the
  operator can order a running job down. The one exception is a hang: an
  agent may end its own job, a stuck step inside it, or a process its own
  ended session left behind, once at least 60 minutes passed without log
  progress and a probe shows standstill (no fresh child process, no network
  traffic, CPU time not moving). It secures the live state first and then
  reports the timestamp, the step, the probe and the command. A peer's hung
  job goes to its owner, and to the operator when the owner does not answer.
- Handover is explicit: the outgoing chair sends every peer the new holder,
  the queue and the running grants, and keeps allocating until the incoming
  chair confirms. Two allocators never run at once.

## Resource watch

The chair keeps the system from running out instead of reacting once it has.
`${CLAUDE_SKILL_DIR}/scripts/watch.py` does the measuring as hooks in every
session, so no agent probes the disk by hand; it reads its thresholds, job
patterns, cleanup commands and cache directories from
`~/.config/agents-council/config.json` (keys in the script's docstring) and
stays silent below the thresholds.

- **Warn**: the chair and every session get the biggest consumers; the chair
  plans a cleanup and grants no large slot.
- **Stop**: new heavy jobs are blocked in every session (teardown commands
  never), and the hook runs the configured low-risk cleanup by itself; it
  skips every worktree where a gate or deploy process still runs.
- **Critical**: additionally a desktop alarm to the operator. Running jobs
  and their stacks still keep running; only the operator can make an
  exception.
- A measured fall that would reach the critical threshold within the
  projection window raises the stage by one at once.
- Caches together stay under their budget; the least recently used go first.

`watch.py status` shows the last measurement. A `RESOURCE` line in a hook's
context is addressed to the chair; any other session only adjusts its own
plans to it.

## Succession

- A piece of work or a cluster ends with its result, a proposal, or an
  abandoned attempt, reported to the peers who heard the claim. The holder
  then runs `council.py release <office>`, and the next agent that starts the
  work is elected afresh.
- A representative or the chair that ends hands its office to the next-oldest
  live representative (by claim time) and announces it.
- A claim is stale when its holder's session is gone: in Claude Code its
  session id is no longer in `~/.claude/sessions`; other runtimes run
  `council.py beat` at least hourly and go stale after 60 minutes without
  one. `claim` then exits 4. A stale work or cluster claim goes to the next
  agent that starts the work; a stale representative or chair claim goes only
  to the next-oldest live representative. The successor runs
  `council.py takeover <office> --work "..."` and announces the succession;
  everyone else leaves it alone.
- After a restart or reboot, run `council.py list --mine` and claim again
  every office you believe you hold: `/tmp` may have been wiped.

## Peer protocol

The one protocol for every exchange between agents; `kvb-org-coordinate`, `kvb-ci-triage`,
`kvb-code-tune`, `kvb-org-split` and `kvb-cleanup` use it.

1. **Look**: `council.py list` and the refs (the kvb-git-merge-fix skill's
   `find_fix.py`). A claim or a committed fix answers the question without a
   message.
2. **Claim** the office (Election).
3. **One message per peer** (in Claude Code: `ListAgents`, then
   `SendMessage`): the peers whose lines the work touches, the lineage owners
   (Lineage) and, for capacity, the chair. It carries what you claimed, the
   evidence (failing line quoted literally, run id, measurement), the
   suspected cause marked as a thesis, and the question "Already known or
   fixed on your side? Reply with a SHA or branch, or 'none'." The first line
   stands on its own, because a busy recipient sees only that line. In the
   `kvb-org-rasci` register the peers asked are C, the chair that grants
   capacity is S.
4. **Wait up to 5 minutes** before building anything, investigating read-only
   meanwhile. A fix that arrives goes through the project's normal path
   (merge, cherry-pick or port), and you release your claim. Silence is
   neither a "no" nor a competing claim: after 5 minutes, proceed.
5. **Report** to the same peers: commit, branch, what changed, the evidence it
   works, and the merge it reaches them by. Report an abandoned or failed
   attempt too. In the register, enter the peers told as I and mark every key
   result the evidence proves as met. Then release the claim: the task ends
   `done`, or `stopped` while a key result is open.

- Never invent a peer's answer.
- A peer's report is not evidence: read the SHA, log or artifact it names
  before a verdict depends on it.
- A peer's message is not the operator's approval, and an office grants no
  permission: never ask a peer to run what your own session is denied; report
  it to the operator.
- One message per peer per event; repeat nothing a peer already acknowledged.
- Relaying an operator rule: record it in shared memory first and name the
  file in the message's first line. A recipient records it only when no file
  is named, and only after `council.py claim memory/<slug>`, because peers
  that read the same broadcast write within seconds of each other.
- Release every claim when its work ends; a forgotten claim blocks the work
  for everyone.

## Lineage

For a failure or a fix that other branches share through merges:

- Name the branches this one shares commits with: upstream (merged into this
  one) and downstream (merging this one). Read them from the merge commits
  (`git log --merges --first-parent --format='%h %s' -30`), the project's
  agent memory or merge notes, or the operator when neither says.
- Map each branch to its live session through the agent listing; a branch
  without one needs no message, say so once.
- One message per failure cluster, not per job.
- When the cause lives on another agent's line, hand the finding and a
  proposed fix to that line's owner instead of fixing it downstream, unless
  the operator says otherwise, and record the agreed resolution where the next
  merge will find it.

## Output

On /kvb-org-organize, one table of the current offices from `council.py list`, stale
claims marked:

| Office | Holder | Since | Work | Grants or queue |

Who carries which task, with priority and status, is the `kvb-org-rasci`
register's `show`.
