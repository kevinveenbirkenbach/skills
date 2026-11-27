# Hub approval in detail

The `kvb-git-diff` skill reads this file for its placeholders, fallbacks and
the approval's lifetime.

## Placeholders

- `<repo>`: the repository's name.
- `<branch>`: the branch with every `/` as `-`.
- `<base>`: the branch's base.
- `<table>`: a file under `/tmp` holding the `kvb-check-score` commit table.
- `<pages>`, `<approvals>`: the directories
  `${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/councilroot.py dir pages`
  and `... dir approvals` print, in the council root the hub reads.
- `<id>`: the review id `approval.py request` returns.
- `<gate>`: `pass` or `fail` from step 2; step 4 passes the same value.
- `<agent>`: your agent name, which inline feedback is posted to.

## The request

The request ships the staged diff; every file MEDUSA's secret rules or an
armour line flag goes by stat only, so the hub shows it on the card. Only a
`pass` review can be approved in bulk or by a rule. Chat links do not open
for this operator, so the `url` goes out as plain text. Without the script
or port 8737, the MCP tool `review_request` takes the same fields without
the diff.

## Verify and lifetime

- Step 4 verifies the operator's pinned passkey signature; any exit but 0
  means no commit, and the printed reason goes to the operator.
- Sandboxed without port 8737: save `review_wait`'s answer under `/tmp` and
  add `--record <file>` to the verify call.
- `superseded`: a newer request for the same worktree and branch replaced
  the review.
- A review's approval holds two hours.
- A `kvb-org-operator` commit row chaining these steps runs only once every
  review is approved: `operator.py run` skips it until then, and its hub
  card offers `Approve n and run`.
