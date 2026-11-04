---
name: kvb-org-split
description: >
  Keep agent work in its own worktree until 90% fix confidence and under 5%
  break risk, else a proposal. Trigger when delegating or parallelizing.
---

# Funnel

The main line only receives changes that have earned it. Everything else stays
in a sidetree until it does, or leaves as a proposal.

## The bar

- **Fix confidence of at least 90 %** and **break risk under 5 %**, both
  reported by the `kvb-check-confidence` skill, the break risk derived through
  the `kvb-check-break-risk` skill.
- The operator may set a different bar. Never lower it to make a change fit.

## The stages

1. **Brief.** As few agents as the stakes need, one concern each, on the
   model the `kvb-org-perform` skill picks, entered in the `kvb-org-rasci`
   register as R with `--worker "subagent <type> (<model>)"`. The brief names
   the goal, the exact base commit, the exact files and the claims to prove or
   refute, the scope that may change, the evidence expected back, an answer
   cap (default 15 lines: verdict, evidence, residuals), a time cap (default
   60 minutes) for its interim state, and the limits:
   - no pushes; read-only probes on shared live systems;
   - code explored through the codebase-memory-mcp graph first
     (`search_graph`, `trace_path`, `get_architecture`, `detect_changes`; the
     `kvb-agent-optimize` skill sets it up), grep and read after;
   - light runs (no Docker, about a minute) self-admit with
     `${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/watch.py admit --kind
     test-nostack`; `make test`, gates, deploys and anything with Docker only
     on the grant of the `kvb-org-organize` chair;
   - status that asks nothing goes to
     `${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/news.py post "<text>"`,
     never into a message.
2. **Sidetree.** Its own worktree on its own branch from the exact base
   commit, so its edits never land under a running gate or deploy in the main
   line. Use the host's worktree isolation if any. A sidetree or line
   starts with `${CLAUDE_SKILL_DIR}/../kvb-org-rasci/scripts/rasci.py set
   <task> --branch <own> --base <upstream> --workdir <dir>`.
3. **Evidence.** Targeted tests, a test for the new behaviour, and a negative
   control: the test fails without the change. Numbers come from the same
   source before and after.
4. **Self-assessment.** The agent reports fix confidence and break risk with
   their residuals and commits on its branch. Its parent marks proven key
   results met in the `kvb-org-rasci` register and records
   `--artifact worktree:<path>`.
5. **Independent review.** Before any merge, run the `kvb-think-dialectic`
   skill with skeptics who did not write the change, briefed the same way
   (exact diff and claim, capped answer). A hole returns the change to stage 3.
6. **Merge.** At or above the bar, merge the sidetree branch by the
   repository's commit rules, then re-verify on the main line with the
   project's gate.
7. **Tear down.** Read `teardown.md` next to this file before tearing down a
   merged, proposed or abandoned sidetree.

## When the bar is out of reach

When the deciding evidence is not available to the agent or the change is
inherently riskier, read `proposal.md` next to this file.

## Rules

- At its time cap, ask an agent for its interim findings and let it run on;
  never stop a running agent.
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

Verdict: merged, proposal or abandoned; proposals list what would close their
gap.
