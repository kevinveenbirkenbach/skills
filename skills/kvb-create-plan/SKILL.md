---
name: kvb-create-plan
description: >
  Turn a request into an objective-oriented plan for kvb-org-robot.
  Trigger on a plan, breakdown or strategy request before work starts.
---

Produce a plan whose every item is an outcome with a check, then execute it
autonomously. A plan of activities instead of objectives cannot be verified,
and an unverifiable plan cannot be handed to a robot.

## Procedure

1. **Interview first.** Open every plan with the `kvb-think-listen` skill: ask
   until scope, constraints, success criteria and the operator-only facts are
   pinned, then reflect the understanding back. This is the only point in the
   run where questions are allowed, so leave nothing open.
2. **Pin the objective.** The end state in one sentence, as a condition that
   is true or false, never an activity, with the command or observation that
   proves it.
3. **Inspect before decomposing.** Read the code, config, tests and history
   the objective touches; every item rests on something you have seen, not on
   an assumption. Explore the code through the codebase-memory-mcp graph
   first (`search_graph`, `trace_path`, `get_architecture`, `detect_changes`;
   the `kvb-agent-optimize` skill sets it up), grep and read after.
4. **Decompose into sub-objectives.** Each item gets its outcome, the
   verification that proves it, and the items it depends on. Split an item
   that needs more than one verification. Order by dependency and mark the
   independent items, so they can run in parallel.
5. **Resolve the open decisions now.** Every root cause, design choice or
   trade-off the plan rests on is settled before execution, through the
   `kvb-think-dialectic` skill where being wrong is expensive. The robot does
   not ask, so an unresolved decision becomes a guess at runtime.
6. **Record the plan in the register.** The objective goes into the
   `kvb-org-rasci` register with each sub-objective's verification as a key
   result; mirror the sub-objectives into the harness's todo tracking, one
   entry per item, phrased as the outcome. A plan file only when the operator
   asks for one.
7. **Present it and wait.** Show the objective, the ordered sub-objectives
   with their verifications, what is deliberately out of scope, and the
   assumptions the plan rests on. Stop: the plan is this step's deliverable.
8. **Implement it statically, in full.** On the operator's go, write every
   code, config, test and doc change the plan calls for, across all
   sub-objectives, before running anything that needs live infrastructure.
   Verify statically: read the diff, run the linters, the unit tests, and any
   dry-run or syntax check the project offers. The step ends only when the
   whole plan exists on disk.
9. **Then iterate under `kvb-org-robot`.** Invoke the `kvb-org-robot` skill
   with the objective as its goal for the dynamic part: run, deploy, observe,
   fix, repeat until every verification passes. It drives the loop without
   check-ins, verifies each outcome, and reports the items outside its
   clearance for the operator to run.

## Rules

- One objective per item, in outcome form: "endpoint returns 200 for an
  expired token", not "fix the auth middleware".
- No item without a verification; an item nothing proves is a wish.
- Plan only what the request covers. Speculative future-proofing, refactors
  nobody asked for, and abstractions with one caller go to the out-of-scope
  list.
- Static before dynamic: never start the robot loop on a half-written plan; a
  deploy failing on code not yet written costs a full cycle and proves
  nothing.
- Re-plan on contradicted evidence: when execution disproves an assumption,
  revise the plan instead of forcing the original steps through.
- Cite `file:line` for every claim about the current state of the code.
