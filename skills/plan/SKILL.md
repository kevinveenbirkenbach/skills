---
name: plan
description: >
  Turn a request into an objective-oriented plan and hand it to the robot skill
  for autonomous execution. Trigger on /plan or when the operator asks for a
  plan, a breakdown, or a strategy for a task before any work starts. Portable
  across projects.
---

Produce a plan whose every item is an outcome with a check, then execute it
autonomously. A plan that lists activities instead of objectives cannot be
verified, and an unverifiable plan cannot be handed to a robot.

## Procedure

1. **Interview first.** Open every plan with the `active-listening` skill: ask
   until scope, constraints, success criteria, and the operator-only facts are
   all pinned, then reflect the understanding back. This is the only point in
   the run where questions are allowed, so leave nothing open here.
2. **Pin the objective.** State the end state in one sentence, as a condition
   that is either true or false, never as an activity. Name the command or
   observation that proves it.
3. **Inspect before decomposing.** Read the code, config, tests, and history the
   objective touches. Every plan item must rest on something you have seen, not
   on an assumption about how the project works.
4. **Decompose into sub-objectives.** Each item gets: the outcome it reaches,
   the verification that proves it, and the items it depends on. Split an item
   whenever it needs more than one verification. Order by dependency and mark
   the items that are independent, so they can run in parallel.
5. **Resolve the open decisions now.** Any root cause, design choice, or
   trade-off the plan rests on gets settled before execution, escalating to the
   `dialectic` skill where being wrong is expensive. The robot does not ask, so
   an unresolved decision becomes a guess at runtime.
6. **Record the plan as a todo list.** Write the sub-objectives into the
   harness's own todo tracking, one entry per item, phrased as the outcome. Keep
   a plan file only when the operator asks for one.
7. **Present it and wait.** Show the objective, the ordered sub-objectives with
   their verifications, what is deliberately out of scope, and the assumptions
   the plan rests on. Stop here: the plan is the deliverable of this step.
8. **Implement it statically, in full.** On the operator's go, write every code,
   config, test, and doc change the plan calls for, across all sub-objectives,
   before running anything that needs live infrastructure. Verify statically:
   read the diff, run the linters, the unit tests, and whatever dry-run or
   syntax check the project offers. This step ends only when the whole plan
   exists on disk, with no sub-objective left unwritten.
9. **Then iterate under `robot`.** With the static implementation complete,
   invoke the `robot` skill with the objective as its goal for the dynamic part:
   run, deploy, observe, fix, repeat until every verification passes. It drives
   the loop without check-ins, verifies each outcome instead of assuming it, and
   reports the items that fall outside its clearance for the operator to run.

## Rules

- One objective per item, in outcome form: "endpoint returns 200 for an expired
  token", not "fix the auth middleware".
- No item without a verification. If you cannot name what proves it, the item is
  still a wish, not a plan.
- Plan only what the request covers. Speculative future-proofing, refactors
  nobody asked for, and abstractions with one caller belong in the out-of-scope
  list, not in the plan.
- Static before dynamic: never start the robot loop on a half-written plan. A
  deploy that fails on code you had not written yet costs a full cycle and
  proves nothing.
- Re-plan on contradicted evidence: when execution disproves an assumption the
  plan rests on, revise the plan instead of forcing the original steps through.
- Cite `file:line` for every claim about the current state of the code.
