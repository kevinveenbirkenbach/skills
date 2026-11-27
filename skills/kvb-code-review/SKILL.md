---
name: kvb-code-review
description: >
  Review a change against every repo standard, Quality check and harness
  review skill, with skeptics, memory and a push stamp. Trigger before a push.
---

Read-only: the review never edits, stages, commits or pushes. Its script is
`${CLAUDE_SKILL_DIR}/scripts/review.py`; every
step passes `--repo <root>` and, from step 2 on, `--target <spec>`.

## Step 1: target

Run `review.py target --repo <root>`, then ask one `AskUserQuestion` with
the four targets, the detected one first and marked `(Recommended)`:

1. **Staged changes** (`staged`).
2. **Pull request** (`pr <n>`; HEAD must be its head).
3. **Branch against the default branch** (`branch <main|master>`).
4. **Commit range** (`range <a>..<b>`; `range <upstream>..HEAD` is what a
   push sends).

## Step 2: plan from memory

`review.py plan --target <spec> --harness <name> ...` with one `--harness`
per read-only review skill the harness lists (Claude Code: `code-review`,
`security-review`); a harness that lists none gets no `--harness`, and the
verdict says `harness: none`. A lens or finding whose key the memory holds
is never run or judged again: only `run` statuses and missing files go on.

## Step 3: lenses in parallel

Start everything of this step in one message:

- **Scripts**: `review.py run --target <spec> --task <register task>
  [--measure "<command>"]` in the background; `--measure` only when the
  change touches runnable code. Heavy lenses wait in `queue.py hold`.
- **Judging lenses** (`standards`, `legal`) with missing files: one subagent
  each, its brief exactly what `review.py brief --lens <name>` prints, on
  the model the `kvb-org-perform` skill picks; its JSON answer goes to a
  scratch file and into `review.py record --lens <name> --findings <file>`.
- **Harness skills**: each listed one, read-only on the same target (never
  `--fix` or `--comment`), its findings written as the same JSON array and
  recorded with `--lens harness:<name> --harness <name>`.

## Step 4: skeptics

`review.py plan` lists every finding with the roles it still needs. In one
message: one skeptic subagent per lens for all its findings (role `lens`)
and one more per critical or high finding (role `blocker`); each gets only
the finding, its hunk and the cited section, defaults to `refuted` on a
concrete hole, and answers `[{"key", "role", "verdict":
"confirmed|refuted", "evidence"}]` for `review.py judge --verdicts <file>`.

## Step 5: verdict

Show `review.py verdict --target <spec> --harness ...` verbatim: the table
`| Severity | Lens | File:line | Finding | Skeptic | Evidence |`, every
lens with its `kvb-check-*` skill and status, the standards read, skipped
and unreviewed lenses, `verdict: clean|blocked|pending`.
Clean means no confirmed critical or high finding. Below it the commit score
block of `kvb-check-score/scripts/block.py`, its break risk and confidence
judged by the `kvb-check-break-risk` and `kvb-check-confidence` methods.

## Step 6: stamp

When the target is everything the push sends and the tracked tree is clean,
`review.py stamp --target <spec> --harness ...` records the verdict for
`HEAD^{tree}`; `review.py status` prints it. A new tree voids it; a
signing-only rewrite keeps it. The pre-bash hook of `kvb-org-organize`
refuses every push row (`--check pushed:<dir>`, or a `--command` running
`git push`, `gipsn` or `git-sign-push` in `--dir`) while that directory
lacks a clean stamp or a waiver.

## Step 7: waiver

Only when the operator wants this push despite the verdict:
`review.py question` prints the question, options and recommended option
for the hub's `decision_request` (your agent name); once `decision_wait`
returns `message` and `answer`, `review.py waive --message <message>
--answer <answer> --agent <name>` records it after the hub's
`operator_message` matches. Never type a waiver for the operator.
