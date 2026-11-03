---
name: kvb-git-merge-fix
description: >
  Find the commits on any branch that carry a described fix and merge them
  here. Trigger on /kvb-git-merge-fix <description> or a request to bring over
  a fix from another branch.
---

The free text after `/kvb-git-merge-fix` is the fix description, exactly like `/loop`
takes its prompt. Everything after the skill name is the search intent; there is
no other input. If it is missing, ask for it and stop.

## 1. Refuse to work on a dirty tree

`git status --porcelain` must be empty. If it is not, stop and let the operator
commit or open a worktree. Never stash, never `git checkout -- <file>`, never
`git restore --staged`: those discard uncommitted work that other agents in the
same tree may own.

## 2. Fetch everything

```bash
git fetch --all --prune --tags
```

That is the "pull all branches" step. Do not check branches out one by one; all
searching below runs against the fetched refs.

## 3. Turn the description into search terms

Derive from the operator's text: 2-4 keywords for commit messages, plus any
symbol, string, or path the fix must have touched. State the derived terms in
one line so a wrong reading is visible before the search.

## 4. Search every ref

Search by keyword, by literal and by path in one call; they find different
things, and a commit matching any one of them is a hit, so `--path` widens
the search instead of narrowing `--grep`:

```bash
${CLAUDE_SKILL_DIR}/scripts/find_fix.py --grep '<keyword>' -S '<symbol or literal>' --path '<path or glob>'
```

It drops every hit already in HEAD (`in_head` counts them; all in HEAD means
the fix is already in, say so and stop) and prints the rest with their
branches and files. Then read the actual change: `git show --stat <sha>` and
the diff. A matching commit subject is a lead, not evidence, and `-S` also
matches the commit that removed the literal; the diff decides.

## 5. Present the candidates

One table: sha, branch(es), subject, files touched, one line on what the diff
really does. Let the operator pick unless exactly one candidate survives step 4
and its diff plainly is the described fix.

## 6. Bring it over

- One or a few commits, rest of the branch unwanted: `git cherry-pick -x <sha>…`
  (`-x` records the origin).
- The whole branch is wanted: `git merge --no-ff <branch>`.
- Conflicts: resolve them by reading both sides. Never `-X ours`/`-X theirs`,
  never `git checkout --ours/--theirs` wholesale — that silently drops one
  side's fix. Unresolvable → `git cherry-pick --abort` / `git merge --abort`,
  report what conflicted, change nothing else.

## 7. Report

Show `git log --oneline <base>..HEAD` and the resulting diffstat, then apply the
kvb-check-confidence skill: what came over, what did not, what still has to be verified.
Run the project's test or quality gate only when the operator asks for it.

## Rules

- Never push and never force anything; the merge stays local until the operator
  ships it.
- Never rewrite history to make a cherry-pick fit (no rebase of the target
  branch, no amend of foreign commits).
- If the search finds nothing, say so plainly and list the terms tried. Do not
  reimplement the fix under this skill — that is a different task.
