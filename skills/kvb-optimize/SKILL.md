---
name: kvb-optimize
description: >
  Run every optimization skill in one pass with one round of questions.
  Trigger on /kvb-optimize; kvb-dream runs it.
---

Collector for the optimization skills, so one pass needs one evidence
collection and one round of questions. Evidence handed over by the
`kvb-dream` skill is used as is; standalone, collect it once from the
current session and repository and hand the same set to every skill.

## Order

Each runs its own inventory and keeps its own confirmation step; an empty
inventory is skipped with one line.

1. `kvb-skill-cleanup`: delete the legacy skills first, so nothing below
   optimizes a dead copy.
2. `kvb-transcend`: carry scripts, tests and skills out of scratchpads and
   agent homes into the skills repository or the current repository.
3. `kvb-skill-auto`: turn the operator's repetitions into skills.
4. `kvb-skill-tune`: turn frictions into new or sharper skills.
5. `kvb-skill-compile`: turn deterministic skill steps into scripts.
6. `kvb-skill-essence`: compact skills and memory.
7. `kvb-code-refactor`: bring the uncommitted changes up to the project's
   standards.
8. `kvb-code-tune`: optimize the hot paths the evidence measured.
9. `kvb-agent-optimize`: index every repository in scope as a code graph
   and tighten its agent instructions.
10. `kvb-think-gaps`: find the missing work and hand each pick to
    `kvb-create-requirement`.

## Questions

Collect the candidates of all skills first, then run one `kvb-think-listen`
round and put every skill's own confirmation questions into one batch,
grouped by skill. Each skill writes only what was picked for it.

## Output

| Skill | Candidates | Picked | Written | Skipped with reason |

Tests and lints of the written changes run once at the end, on the resource
chair's grant (the `kvb-org-organize` skill); nothing is committed.
