---
name: kvb-skill-transcend
description: >
  Carry the session's skill use and own scripts into the skills repo.
---

What an agent improvised in one session (a scratchpad helper script, a
command sequence run five times, a skill it worked around) goes into the
operator's skills repository for the next agent. Nothing changes before the
operator confirms.

## Step 1: inventory

Read-only:

- **Scripts and skills**: `transcend.py scan` of the `kvb-transcend` skill
  lists the own scratchpad's scripts, peers' scripts, and skills, commands,
  hooks and rules in `~/.claude`, `~/.agents` and `~/.codex` that the skills
  repository does not ship; it skips what was already decided and has not
  changed. Peer and home candidates follow that skill's consent step.
- **Skills used**: every skill this session invoked, how often, and where it
  fell short (a workaround, a step skipped, an operator correction).
- **Recurring moves without a skill**: command sequences, peer exchanges or
  lookups run three times or more; `rasci.py tools` of the `kvb-org-rasci`
  register lists the scripts the session's tasks recorded.

One line each: `candidate -> source -> evidence`.

## Step 2: classify

Per candidate one target: a script under an existing skill's `scripts/`, a
new skill, a sharper step in an existing skill, a memory entry instead, or
drop. A recurring deterministic move without a script goes to the
`kvb-skill-compile` skill, any other recurring move to the `kvb-skill-tune`
skill as evidence. A script is portable only once its host paths, names and
values are explicit parameters (the `kvb-code-no-defaults` skill); one that
needs a secret, a credential or a single host is dropped or stays a memory
entry.

## Step 3: listen and confirm

Run the `kvb-think-listen` skill on the open points: scope, target skill,
generality. Then `AskUserQuestion`: one `multiSelect` with the candidates
(target and evidence in each description, nothing preselected), and per pick
a single-select `Write it` / `Revise it` / `Discard` showing the drafted file
or diff.

## Step 4: write

- Write where the `kvb-skill-tune` skill's **Persistence** section says: the
  skills repository as source of truth, then the live mirrors.
- Read every script whole before carrying it; strip comments the way the
  `kvb-code-no-comments` skill does.
- A carried script gets a unit test in the repository's `tests/` with a
  negative control, run once `watch.py admit --kind test-nostack` (the
  `kvb-org-organize` skill) prints `grant`; `make test` keeps the chair's
  grant.
- `transcend.py mark` every offered candidate with its verdict.
- Leave the result uncommitted; committing is the `kvb-git-commit-next`
  skill's job.

## Output

| Candidate | Source | Target | Verdict |

Dropped candidates stay with their reason.
