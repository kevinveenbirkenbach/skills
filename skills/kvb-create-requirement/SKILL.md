---
name: kvb-create-requirement
description: >
  Write a requirement: user story, decisions, Mermaid approach, acceptance
  criteria, tests. Trigger on "requirement schreiben" or a kvb-think-gaps
  pick.
---

Writes requirements, never implementations. Nothing touches disk before the
operator picks `Write it`.

## Step 1: context

Ask the operator for the context first, in one open question: what should
change, for whom, and why now. A candidate handed over by the
`kvb-think-gaps` skill already carries it. Read what the answer points to
(code, issues, logs, existing requirements) before the next step.

## Step 2: listen

Run the `kvb-think-listen` skill until scope, constraints, the definition of
done and every operator-only decision are fixed. Its answers become the
Decisions section.

## Step 3: brainstorm

Run the `kvb-think-brainstorm` skill on the approach. The operator's pick
becomes a decision; each rejected option stays there with its reason.

## Step 4: draft

Location, filename and numbering follow the project's existing requirement
documents; read them first, and ask when there are none. One feature per
document: a title that needs "and" is two requirements. Sections in this
order:

1. `# <number> - <title>`
2. `## User Story`: "As a <role>, I want <capability>, so that <benefit>."
3. `## Decisions (operator-confirmed <YYYY-MM-DD>; do not re-litigate)`:
   numbered, a bold keyword first, rejected alternatives with their reason.
4. `## Approach`: one Mermaid `flowchart TD` over the whole procedure, one
   `subgraph` per phase with an emoji title and an emoji in every node:

   ```mermaid
   flowchart TD
       subgraph P["🧭 0 · Preparation"]
           P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
           P2 -- "✏️ corrections" --> P1
       end
       P2 -- "🤖 yes" --> A1
       subgraph A["🛠️ A · Implementation"]
           A1["🧩 Change"] --> A2{"🧪 Tests green?"}
           A2 -- "🔴 no: fix" --> A1
           A2 -- "🟢 yes" --> AF{"💬 Operator feedback?"}
           AF -- "✏️ changes" --> A1
       end
       AF -- "👍 fits" --> D1["🏁 Review, commit with operator OK, hand-over"]
   ```

   Every verifiable stage gets its test loop and an operator feedback
   checkpoint; a user-visible change shows screenshots at that checkpoint.
5. `## Acceptance Criteria`: grouped under `###` per area. Each item is a
   `- [ ]` that one check proves or disproves on its own: a command, a
   `file:line`, a test name, an observable state. No "should", no "works
   well".
6. `### Tests`, the last group: `Unit`, `Integration` and `E2E`, each with
   its criteria. A level that cannot apply stays with `n/a: <reason>`.

## Step 5: confirm and write

Show the full draft, then `AskUserQuestion`: `Write it` / `Revise it` /
`Discard`. Revise loops back to the step the correction touches. Write only
on `Write it`; lint the file with the project's markdown linter, a light run
that self-admits with
`${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/watch.py admit --kind
test-nostack`; a lint through `make` or Docker runs through `queue.py hold`
(the `kvb-org-queue` skill).

## Step 6: hand over

Stop after writing. Offer in one line to run the `kvb-create-plan` skill,
which hands the plan to the `kvb-org-robot` skill; never start the
implementation without the operator's yes.
