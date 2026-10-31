# skills 🧠

[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub%20Sponsors-blue?logo=github)](https://github.com/sponsors/kevinveenbirkenbach) [![Patreon](https://img.shields.io/badge/Support-Patreon-orange?logo=patreon)](https://www.patreon.com/c/kevinveenbirkenbach) [![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20Coffee-Funding-yellow?logo=buymeacoffee)](https://buymeacoffee.com/kevinveenbirkenbach) [![PayPal](https://img.shields.io/badge/Donate-PayPal-blue?logo=paypal)](https://s.veen.world/paypaldonate)

The agent skill collection of Kevin Veen-Birkenbach.
Every skill is pinned in `skills-lock.json` for reproducible installs.
First-party skills live under `skills/` and are layered on top of the locked ones at install time.
Compatible with Claude Code, Codex, Gemini CLI, Cursor, Copilot, Windsurf, Cline, and other agents.

## Skill map 🗺️

How the first-party skills work together. A solid arrow means the skill invokes or relies on the other one; a dotted arrow means it fires automatically. Every skill that reports a result closes with the `confidence` block; those arrows are left out. The locked third-party skills (caveman, ponytail, archify) are not drawn.

```mermaid
flowchart LR
  subgraph triggers [Triggers]
    commit_req([commit request])
    stage_req([staging or fix ready])
    edit_hook([edit in a git worktree])
    reminders([reminder hooks])
    code_task([code task])
    spawn([subagent spawn])
  end
  subgraph commit [Commit]
    commit_next[commit-next]
    commit_no_verify[commit-no-verify]
    comments_clean[comments-clean]
    advocate[advocate]
    confidence[confidence]
    break_risk[break-risk]
    explain[explain]
  end
  subgraph coordination [Coordination]
    democracy[democracy]
    coordinate[coordinate]
    funnel[funnel]
    cleanup[cleanup]
    subagent_model[subagent-model]
  end
  subgraph ci [CI]
    observe[observe]
    triage[triage]
    ci_artifacts[ci-artifacts]
    tune[tune]
    merge_fix[merge-fix]
  end
  subgraph reasoning [Reasoning]
    active_listening[active-listening]
    dialectic[dialectic]
    criticize[criticize]
    sceptic[sceptic]
    auto_feature[auto-feature]
  end
  subgraph autonomy [Autonomy]
    plan[plan]
    robot[robot]
  end
  subgraph self_improvement [Self-improvement]
    dream[dream]
    autotune[autotune]
    autoskill[autoskill]
    essence[essence]
    shortcuts[shortcuts]
  end
  subgraph quality [Quality]
    test[test]
    refactor[refactor]
    no_defaults[no-defaults]
    scope_guard[scope-guard]
  end
  subgraph standalone [Standalone]
    changelog[changelog]
    help_skills[help-skills]
    status_matrix[status-matrix]
    medusa[medusa]
  end

  commit_req -.-> commit_next
  commit_req -.-> commit_no_verify
  stage_req -.-> confidence
  edit_hook -. council gate .-> democracy
  reminders -.-> dream
  reminders -.-> autotune
  code_task -.-> no_defaults
  code_task -.-> scope_guard
  spawn -.-> subagent_model

  commit_next --> merge_fix
  commit_next --> commit_no_verify
  commit_next --> explain
  commit_next --> dialectic
  commit_no_verify --> comments_clean
  commit_no_verify --> advocate
  advocate --> dialectic
  confidence --> break_risk
  confidence -. objective .-> autotune

  coordinate --> democracy
  cleanup --> democracy
  funnel --> democracy
  funnel --> dialectic
  funnel --> subagent_model
  dialectic --> subagent_model
  democracy --> merge_fix

  observe --> triage
  observe --> ci_artifacts
  triage --> ci_artifacts
  triage --> democracy
  triage --> dialectic
  triage --> funnel
  triage --> tune
  tune --> democracy
  tune --> funnel
  tune --> merge_fix
  tune --> dialectic

  dialectic --> active_listening
  criticize --> dialectic
  criticize --> active_listening
  sceptic --> dialectic
  sceptic --> no_defaults
  auto_feature --> sceptic
  auto_feature --> active_listening

  plan --> robot
  plan --> active_listening
  robot --> dialectic

  dream --> dialectic
  dream --> autotune
  dream --> autoskill
  autoskill --> autotune
  autoskill --> shortcuts
  autotune --> essence

  test --> triage
  test --> dialectic
  test --> no_defaults
  test --> comments_clean
  refactor --> comments_clean
```

## Requirements 📦

- Node.js (provides `npx skills`).
- `jq` (only required for `make update`).

## Installation 🚀

Install the skills globally into your home (`~/.agents/skills` and `~/.claude/skills`):

```bash
make install
```

Copy the skills into a specific project (`<repo>/.agents/skills` and `<repo>/.claude/skills`):

```bash
make project TARGET=/path/to/repo
```

Both commands also patch the target's `.claude/settings.local.json` — the machine-local, untracked file, so a project's reviewed `.claude/settings.json` is never rewritten by an install: the caveman and ponytail plugins are enabled so their modes auto-activate on session start, and two reminder hooks are registered — `autotune` points you at `/autotune` at most once an hour, `dream` points you at `/dream` at most once every twelve hours per repository (stamped in that repository's git dir). A PreToolUse gate from the `democracy` skill blocks edits to files in a git worktree until the session holds a claim (`skills/democracy/scripts/council.py`), and its resource watch (`skills/democracy/scripts/watch.py`) measures disk, Docker and caches, cleans up low-risk data and blocks new heavy jobs before the disk runs out; it stays inactive until `~/.config/agents-council/config.json` exists. Two hooks of the `subagent-model` skill (`skills/subagent-model/scripts/log.py`) log every Agent spawn with its task class, model and effort, and store the quality feedback a sandboxed session prints, in `~/.local/state/agents-council/subagent-model.jsonl`. Existing settings are preserved.

Restart your agent afterwards so it loads the new skills.

## Maintenance 🔧

Refresh every skill to its latest version and rewrite `skills-lock.json`:

```bash
make update
```

Validate `skills-lock.json` and shellcheck the scripts (also run by CI on every push and after every update):

```bash
make test
```

## Related Tools 🧰

This collection is part of a wider toolset for managing IT and infrastructure:

- [alias](https://github.com/kevinveenbirkenbach/alias) — shell aliases for common commands.
- [package-manager](https://github.com/kevinveenbirkenbach/package-manager) — `pkgmgr`, a single command to install and manage these repositories.
- [infinito-nexus](https://github.com/kevinveenbirkenbach/infinito-nexus) — automation platform for self-hosted infrastructure.

## License 📜

MIT License, Copyright (c) 2026 Kevin Veen-Birkenbach.

## Author 👤

Kevin Veen-Birkenbach [kevin@veen.world](mailto:kevin@veen.world)

## Thanks 🙏

Thanks to the [#ai:infinito.nexus](https://matrix.to/#/%23ai:infinito.nexus) community, and especially to [Paulinhx](https://github.com/Paulinhx) for the inspiration.

## Donation ❤️

If these tools help you, consider supporting their development:

- [GitHub Sponsors](https://github.com/sponsors/kevinveenbirkenbach)
- [Patreon](https://www.patreon.com/c/kevinveenbirkenbach)
- [Buy Me a Coffee](https://buymeacoffee.com/kevinveenbirkenbach)
- [PayPal](https://s.veen.world/paypaldonate)
- Bitcoin: [bc1qle7j8m9kvny2h2q3jzsnc64s4f5zme5re23pzc2lc2d7hhasc4dqachflp](bitcoin:bc1qle7j8m9kvny2h2q3jzsnc64s4f5zme5re23pzc2lc2d7hhasc4dqachflp?message=%E2%9D%A4%EF%B8%8F%20Help%20Build%20the%20Future%20-%20Donation%20to%20Kevin%20Veen-Birkenbach.)
