# Changelog

## [0.3.0] - 2026-11-03

Breaking:

- Skills: every skill is now *kvb-category-name*; the old names are gone
- Skills: the category *skills* is now *skill*, e.g. *kvb-skill-tune*
- Skills: *kvb-create-feature* is now *kvb-think-gaps*
- Skills: *kvb-skill-dream* is now *kvb-dream*
- Skills: *kvb-skills-shortcuts* and tokens such as *sobu* are gone

Added:

- Org: *kvb-org-rasci* keeps one RASCI/OKR register of every agent task
- Org: *kvb-org-artefacts* tracks images, volumes and worktrees per task
- Org: *kvb-org-wsjf* ranks the register by WSJF from Fibonacci estimates
- Org: *kvb-org-operator* lists every command only the operator can run
- Commit: commit skills show worktree, branch, confidence and risk first
- Transcend: *kvb-transcend* carries session scripts and tests into repos
- Requirements: *kvb-create-requirement* with user story, Mermaid and tests
- Think: *kvb-think-brainstorm* scores options from seven fixed lenses
- Skills: *kvb-skill-compile* turns deterministic steps into scripts
- Skills: *kvb-skill-cleanup* deletes legacy skills that renames left behind
- Dream: *kvb-optimize* runs all nine optimization skills in one pass
- Dream: a GNOME notification recommends */kvb-dream* daily at 17:00
- Coach: *kvb-coach* suggests the next step for mind, body, food and tasks
- Coach: *kvb-coach-meditation* plays alpha-wave music with fractals
- Coach: a short coach note at the first prompt of every full hour

Changed:

- Dream: covers every repository and session, then optimizes and cleans up
- Dream: one hint per agent every 12 h replaces the tune and dream hints
- Tune: *kvb-code-tune* always checks language, framework and recursion
- Cleanup: worktrees are listed by size and integration line
- Coordination: hotfix gates take the next free test slot
- Coordination: an agent may end its own job after 60 min without progress

Upgrade notes:

- Install: run *make install* and restart the agent to load the new names
- Install: run *make install-skills* in each project to drop old copies
- Install: */kvb-skill-cleanup* lists any legacy skill left behind
- Install: the global install enables the *kvb-dream-notify.timer* unit
- Settings: remove *autotune* and *dream* hooks from *~/.claude/settings.json*

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
