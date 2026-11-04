---
name: kvb-think-choice
description: >
  Offer the open decisions as multiple choice and checkboxes. Trigger on
  "auswahl", "offene punkte".
---

The operator decides faster by picking than by reading prose. This skill
collects every decision still open and offers each as a choice with the
recommended option first.

## Step 1: collect

Gather what waits on the operator, never what an agent can decide itself:

- This session's own open questions and staged bundles waiting for a commit
  word.
- `${CLAUDE_SKILL_DIR}/../kvb-org-operator/scripts/operator.py list --json`:
  every row with the check `decision`.
- The `kvb-org-rasci` register (`rasci.py show --wide`): tasks `blocked` on
  the Operator as A or C.

Merge duplicates and drop items a command can settle (those go to
`operator.py run`). Rank by what unblocks most work first.

## Step 2: shape each item

- One question per item, two to four options, the recommended option first
  and marked as such, each with one line on its consequence.
- Independent yes/no items of one kind (which tasks to start, which rows to
  close) become one checkbox question.
- An item whose options need a comparison carries a short preview: the
  command, the diff stat or the score line of each option.

## Step 3: ask

- **Claude Code**: `AskUserQuestion`, at most four questions per call,
  `multiSelect: true` for checkbox questions, `false` otherwise; more items
  follow in the next call.
- **Other runtimes**: print the same items as markdown, numbered questions
  with lettered options and `- [ ]` boxes, and ask for an answer such as
  `1a 2c 3: x, z`.

## Step 4: act

Carry out each answer within its own skill's rules (a commit word through
`kvb-git-commit-next`, a decision row through `operator.py done`). A pick
that needs an action outside the sandbox becomes an `operator.py add` row.
An answer is the operator's word for that item only and never carries over.
