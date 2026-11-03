---
name: kvb-git-close-issues
description: >
  Close the issues a pull request fixes, each verified and confirmed.
  Trigger on /kvb-git-close-issues [pr].
---

Closing an issue is outward-facing: nothing is closed or edited before the
operator confirms the list, and every closed issue names the pull request
and commit that fixed it.

## Step 1: candidates

The pull request named after the command, else the one of the current
branch (`gh pr view --json number`). `${CLAUDE_SKILL_DIR}/scripts/issues.py`
lists every issue it references, from closing keywords and mentions in the
body and the commits, a trailing number in the branch name, and the issues
GitHub already links:

```bash
gh pr view <pr> --json body,headRefName,commits,closingIssuesReferences | issues.py
```

## Step 2: verify

Per candidate, `gh issue view <n> --json state,title,body,comments` (with
`--repo` for a foreign one); a closed issue is skipped. Judge it `fixed`,
`partly` or `unrelated` against the pull request's diff, with evidence: the
change that addresses each point of the issue and the test or CI run that
proves it. Only `fixed` goes on; `partly` gets a progress comment instead.

## Step 3: confirm

`AskUserQuestion` with `multiSelect: true`, one option per `fixed` issue,
the evidence in its description, nothing preselected.

## Step 4: close

Where the fix lives decides how:

- **Merged into the default branch**: `gh issue close <n> --reason completed
  --comment "Fixed by #<pr> (<sha>)."`.
- **Open, or merged into another branch**: add one `Closes #<n>` line per
  issue to the pull request body (`gh pr edit <pr> --body-file <file>`,
  keeping the existing body), so the merge into the default branch closes
  them; never close them early.

## Output

| Issue | Verdict | Evidence | Action |
