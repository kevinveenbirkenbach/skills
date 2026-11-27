# The commit chain: shared rules

The rules below bind every skill of the commit chain that points here:
`kvb-code-clean`, `kvb-check-legal`, `kvb-check-score`,
`kvb-check-break-risk`, `kvb-git-diff` and `kvb-check-confidence`.

## Score block

- Every `kvb-check-confidence` report, stage summary, fix report, commit
  block, legal report and audit ends with the `kvb-check-score` block. Paste
  its two lines verbatim; they replace prose numbers.
- Never invent a value: measure it or pass `-`. Never invent a clause, a
  statute, a ruling or a figure; cite only what you read or ran.
- Each value has one source:

| Emoji | Value | Source |
| --- | --- | --- |
| 🎯 | fix confidence | `kvb-check-confidence` |
| 💥 | break risk | `kvb-check-break-risk` |
| 💸 | tokens, `--efficiency` | `tokens.py` (skills) or `measure.py` (code) of `kvb-check-efficiency` |
| ⏱️ | velocity, `--speed` | `measure.py`, see `kvb-check-efficiency` |
| 🛡️ | security, critical count | `security.py` of `kvb-check-security`; `~<n>` from a review by hand |
| 💰 | cost:value quotient, tables and message block only | 💰 line of `tokens.py` (skills) of `kvb-check-efficiency` |
| 🏆 | score | `score.py` of `kvb-check-score` |

Velocity comes from the same `kvb-check-efficiency` run as tokens. Outside
a commit, `kvb-check-confidence` passes them with both numbers to
`${CLAUDE_SKILL_DIR}/../kvb-check-score/scripts/score.py --fix <n> --break
<n> --efficiency <n|-> --speed <n|-> --security <n|~n> --critical <count>`
and shows its score line and gate line verbatim. Exit 4 forbids the commit
(critical finding); exit 1 fails the 90/5 rule; exit 3 means ask the
operator again before the commit, naming the causes the gate line prints.
Two figures with their residuals replace a hedging paragraph and save the
operator a verification round trip.

## Two numbers

- **Fix confidence**: the probability the change does what it claims.
- **Break risk**: the probability it breaks anything it did not intend to
  touch, derived only by the `kvb-check-break-risk` method;
  `kvb-check-confidence` reports that number and never estimates one, and
  passes it to `score.py` as `--break`.
- State them as two percentages side by side, never one blended figure, and
  never a bare percentage: each comes with its residuals, exactly what keeps
  it below 100 and what would close the gap (live deploy, missing artifact,
  unexercised path).

## Calibration

- Number the claim you verified, not the effort you spent.
- Distinguish "fixes the observed failure" from "makes the job green" when
  hidden layers may follow, and give both numbers.
- Static analysis alone caps at the low nineties; only executed evidence
  (test, reproduction, live probe) justifies more.

## Evidence

- List only the strongest proof lines: what was executed, reproduced,
  enumerated, or read from an authoritative source.
- Mark each `proven` (ran it, saw it, or read the text; cite path:line or
  the URL) or `derived` (reasoned statically, inferred).
- Executed beats derived. A subagent's report, a conversation summary or
  your own earlier message is not evidence: re-verify the claim yourself
  before it changes a number.

## Discount

- After any error the operator caught in the same area during this
  session, discount your numbers and say that you are doing so. A region
  where you have already been wrong twice deserves a worse number than its
  paper evidence suggests.
- A violation you wrote yourself (a `kvb-code-clean` hit) is admitted
  without excuses, lowers the bundle's 🎯 fix, raises its 💥 break, and goes
  into persistent agent memory with date and pattern.

## Thresholds and 90/5

- A threshold the operator named ("95% confidence, break risk ≤5%") is a
  gate on the work for both numbers, handled as the last section of
  `kvb-check-break-risk` says.
- 90/5 means fix at least 90 % and break at most 5 %. It also needs
  `gate: green` from `gate.py status` of the `kvb-check-gate` skill, which
  states the rule and its residuals.

## Commit block

- Every commit block is the `--commit-table` of `kvb-check-score` (branch,
  diff stat, worktree path, values, gate); every commit message carries its
  `--message-block` paragraph right before the trailers. For a commit,
  `scripts/block.py` of `kvb-check-score` runs every measuring script and
  prints both, as step 2 of `kvb-git-commit-no-verify` says.
- A pass that changes a bundle the operator already saw shows its new diff
  stat and score block before the commit call.

## The operator's word

- The operator's word holds for one commit and never carries over to
  another: a hub approval, a yes on a gate exit 3, a 90/5 miss accepted, a
  legal blocker accepted, open principle findings accepted.
- A hub approval counts only once the `kvb-git-diff` verify step exits 0 on
  the exact staged tree; otherwise ask in chat.
- A check proposes, the operator decides: licence fixes, open findings,
  removing an existing default, widening the scope.
