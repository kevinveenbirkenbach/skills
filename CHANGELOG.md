# Changelog

## [0.2.0] - 2026-10-31

Added:

- Git: *branch-gc* clears merged branches and worktrees with *pkgmgr*
- Agents: *subagent-model* uses a cheaper model only at 90 % same result
- Agents: *subagent-model* hooks log every spawn and its rated quality

Changed:

- Coordination: never cut a running job or agent short, not even at its cap
- Resources: *watch.py admit* grants test slots only below CPU and RAM limits
- Coordination: a relayer writes an operator rule to shared memory first

Fixed:

- Resources: stop-stage cleanup now skips worktrees where *make* still runs
- Resources: the block hook ignores heavy commands in quotes and heredocs
- Update: *make update* now updates every locked source, not just the first
- Update: *make update* installs for Claude Code only
- CI: *ci-artifacts* signs lint failures by finding, ignores later steps
- Release: *changelog* warns when a workflow on HEAD already failed
- CI: ruff pinned in *pyproject.toml*; local and CI lint now agree

Upgrade notes:

- 0.1.0 was never published (its CI failed); its upgrade notes follow
- Install: restart the agent after *make install* to load skills and hooks
- Resources: *watch.py* needs *~/.config/agents-council/config.json*
- Resources: add *busy_processes* and *load_limits* to that config

## [0.1.0] - 2026-10-30

Added:

- Install: *make install* and *make project* install every locked skill
- Install: enables caveman and ponytail; adds autotune and dream reminders
- Commit: *commit-next* commits a bundle and stages the next one
- Commit: *comments-clean* and *advocate* audit every commit before it lands
- Commit: *confidence* and *break-risk* report measured fix and break numbers
- Coordination: *democracy* elects the first agent to claim work as its owner
- Coordination: *council.py* claims work; a hook blocks edits without a claim
- Coordination: *funnel* keeps agent work in worktrees until it clears 90/5
- Resources: *watch.py* blocks heavy jobs and cleans up before the disk fills
- Cleanup: *cleanup* frees disk space after asking every peer agent
- CI: *triage*, *observe* and *ci-artifacts* with *ci_failures.py* clustering
- CI: *tune* finds speed-ups that never cut logic, coverage or correctness
- Git: *merge-fix* with *find_fix.py* finds a fix on any branch and merges it
- Reasoning: *active-listening* and *dialectic* pin requirements and causes
- Review: *criticize* and *sceptic* give critique hardened by dialectic
- Autonomy: *plan* hands an objective-oriented plan to *robot*
- Quality: *test* runs Makefile targets; *--fix* loops until they are green
- Quality: *refactor*, *no-defaults* and *scope-guard* keep changes lean
- Skills: *autotune*, *autoskill*, *dream* and *essence* improve the skills
- Release: *changelog* writes the pkgmgr release message since the last tag
- Status: *status-matrix* lists everything in flight with its confidence
- Help: *explain* and *help-skills* explain code and the skill set
- Chat: *shortcuts* expands operator tokens such as *sobu* and *socon*
- Security: *medusa* runs the MEDUSA scanner on repos and secret stores
- Docs: the README skill map shows how the skills invoke each other

Upgrade notes:

- Install: restart the agent after *make install* to load skills and hooks
- Resources: *watch.py* needs *~/.config/agents-council/config.json*
