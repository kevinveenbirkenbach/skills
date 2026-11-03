---
name: kvb-code-transcend
description: >
  Carry the session's ad-hoc tests and scripts into the current repo.
---

The test the agent ran from its scratchpad, the probe that proved a cause, the
benchmark behind an optimization: they protected this session's work and
nothing after it. This skill moves them into the repository the agent works
in (`git rev-parse --show-toplevel`), in that repository's own form. It
changes nothing before the operator confirms.

## Step 1: inventory

Read-only:

- **Tests and scripts outside the repo**: `transcend.py scan` of the
  `kvb-transcend` skill lists them in the own and peers' scratchpads and
  skips what was already decided and has not changed; peer candidates follow
  that skill's consent step. Add the `python -c` checks and negative controls
  this session ran inline.
- **Probes and reproductions** that proved a root cause or a fix.
- **Measurements**: prototypes and before/after harnesses of the
  `kvb-code-tune` skill.
- **Repeated commands** a make target or script of the repository could own.
- **Untracked helpers** the agent left inside the repository.

One line each: `candidate -> source -> what it guards`.

## Step 2: classify

Read the repository's rules first (AGENTS.md, CONTRIBUTING, the Makefile, the
test layout). Per candidate one target in that repository's form: a test in
its test tree and framework, a make target, a script under its scripts
directory, a CI step, or drop. No new framework, dependency or language
without the operator. A kept optimization keeps its measurement as a
benchmark or regression test.

## Step 3: listen and confirm

Run the `kvb-think-listen` skill on the open points: target path, framework,
which repository line owns the file. Then `AskUserQuestion`: one
`multiSelect` with the candidates, nothing preselected, and per pick a
single-select `Write it` / `Revise it` / `Discard` with the drafted diff.

## Step 4: write

- Write only the confirmed files, path-scoped; a peer's line goes to its
  owner through the `kvb-org-coordinate` skill.
- Every carried test fails without the code it guards: show the negative
  control once.
- Run the carried tests as a light run (no Docker, about a minute) after
  `${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/watch.py admit --kind
  test-nostack`; `make test`, gates and anything with Docker only on the
  resource chair's grant (the `kvb-org-organize` skill). Leave the result
  uncommitted for the `kvb-git-commit-next` skill.
- `transcend.py mark` every offered candidate with its verdict.

## Output

| Candidate | Source | Target in the repo | Verdict |

Dropped candidates stay with their reason.
