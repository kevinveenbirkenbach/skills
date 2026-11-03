---
name: kvb-git-issue-close
description: >
  Close finished issues, of one pull request or the whole repository, each
  verified and confirmed.
---

Closing an issue is outward-facing: nothing is closed or edited before the
operator confirms the list, and every closed issue names the pull request or
commit that fixed it.

## Step 1: candidates

- **A pull request named** (or the current branch's, `gh pr view --json
  number`): `${CLAUDE_SKILL_DIR}/scripts/issues.py` lists every issue it
  references: closing keywords and mentions in the body and the commits, a
  trailing number in the branch name, and the issues GitHub already links.

  ```bash
  gh pr view <pr> --json number,body,headRefName,commits,closingIssuesReferences | issues.py --repo <owner/name>
  ```

- **No pull request**: every open issue of the repository. After `git fetch`,
  `${CLAUDE_SKILL_DIR}/scripts/done.py` lists the default-branch commits that
  reference each one:

  ```bash
  gh issue list --state open --limit 1000 --json number | done.py --repo <owner/name> --git-dir . --ref origin/<default>
  ```

  An open issue no commit references can still be fixed: search the default
  branch by its description with the kvb-git-merge-fix skill's `find_fix.py`.

## Step 2: verify

Per candidate, `gh issue view <n> --json state,title,body,comments` (with
`--repo` for a foreign one); skip a closed issue. Judge it `fixed`, `partly`
or `unrelated` against the diff, with evidence: the change addressing each
point of the issue and the test or CI run proving it. Only `fixed` goes on;
`partly` gets a progress comment instead.

## Step 3: confirm

`AskUserQuestion` with `multiSelect: true`, one option per `fixed` issue, the
evidence in its description, nothing preselected.

## Step 4: close

Where the fix lives decides how:

- **On the default branch**: `gh issue close <n> --reason completed
  --comment "Fixed by #<pr> (<sha>)."`, or the commit alone when no pull
  request carried it.
- **In an open pull request, or merged into another branch**: add one
  `Closes #<n>` line per issue to the pull request body (`gh pr edit <pr>
  --body-file <file>`, keeping the existing body), so the merge into the
  default branch closes them; never close them early.

## Output

| Issue | Verdict | Evidence | Action |
