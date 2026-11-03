---
name: kvb-git-issue-solve
description: >
  Solve open issues, each in its own worktree, and open one pull request per
  issue. Trigger on /kvb-git-issue-solve [issue...].
---

Every issue gets its own sidetree, its own evidence and its own pull
request, so a red one blocks nothing else.

## Procedure

1. **Candidates**: the issues named, else `gh issue list --state open`. Drop
   what the `kvb-git-issue-close` skill finds already fixed, and what a peer
   already works on: `council.py list` and the `kvb-org-organize` Peer
   protocol; when a peer solves it, only comment on the issue who solves it
   where.
2. **Rank**: issues about a failing default branch first, then the rank of
   the `kvb-org-wsjf` skill; the operator's order wins.
3. **Take** each issue before touching it: label it `in analysis` (`gh issue
   edit <n> --add-label "in analysis"`) and comment once with this session's
   name, the planned branch and the register task. A missing label is
   created once: `gh label create "in analysis" --color FBCA04 --description
   "An agent analyses this issue"`, `gh label create "in progress" --color
   1D76DB --description "An agent works on a fix"`.
4. **Solve** each with the `kvb-org-split` skill: claim `work/issue-<n>`,
   enter it in the `kvb-org-rasci` register (objective: the issue fixed; key
   results: a test that failed before and passes after, the pull request
   open), branch `fix/<scope>/<n>` from the default branch in its own
   worktree, evidence, self-assessment, independent review. Commits go to
   that branch only, never to the default branch; parallel work follows the
   resource chair's grants. With the first change, swap the label: `gh issue
   edit <n> --remove-label "in analysis" --add-label "in progress"`.
5. **Open the pull request** with the `kvb-git-pr-create` skill, closing
   exactly its issue. Below the split bar the proposal becomes a draft pull
   request with the residuals and the evidence that would close them.
6. **Report** per issue, then release its claim and tear its sidetree down
   as `kvb-org-split` describes; the branch stays until the merge. An issue
   dropped or handed on loses its label and gets a comment saying why.

## Output

| Issue | Branch | Confidence | Break risk | PR | State |
