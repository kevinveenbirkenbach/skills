---
name: kvb-ci-track
description: >
  Track runs, PR checks, alerts, issues; wake on new failures.
---

`${CLAUDE_SKILL_DIR}/scripts/track.py` keeps one JSON file per target in the
shared council directory, so every agent sees what was already reported and
triaged. Its docstring holds the full contract.

```bash
track.py add run <owner/repo> <run id> [--rules <file>]
track.py add pr <owner/repo> <number> [--rules <file>]
track.py add alerts <owner/repo> --codeql --secrets
track.py add issues <owner/repo> [--label <name> ...]
track.py poll <target> [<target> ...]
track.py wait <target> [<target> ...] --interval <s> --timeout <s>
track.py ack <fingerprint> --verdict '<root cause or fix>'
```

## Watch

1. `add` prints the target id. Pass `--rules` the repository's own rules
   file when it has one: failing-line regexes such as Ansible's `fatal:` with
   its last `TASK`, or Playwright's `✘ <spec>:<line>:<col>` with its first
   `Error:`.
2. Start `wait` as a background task (Claude Code: `run_in_background`;
   elsewhere the runtime's equivalent), the interval matched to how fast the
   target changes: about 300 s for a running matrix, 1800 s for alerts or
   issues. Its end is the wake-up; never `/loop`, cron or a shell loop over
   `poll`.
3. On its end, read the exit code:
   - **10**: each printed line is one new cluster: fingerprint, target,
     label, job count, failing line and any matching hotfix. Triage it with
     the `kvb-ci-triage` skill, then start `wait` again.
   - **20**: every target terminal, every cluster acked: the watch is done.
   - **30**: every target terminal, a cluster still unacked: finish its
     triage and ack it.
   - **3**: gh failed (auth, network, a broken rules file); the reason is on
     stderr. **0**: timeout, nothing new: start `wait` again.

## Ack

Once a cluster has its verdict (fixed, flake proven transient, fixed by a
later commit), `ack` it. The ack silences that fingerprint in every target,
so the same failure in the next run stays quiet. Never ack a cluster just to
quiet it; an ack without a verdict is refused.

## Rules

- One line per new cluster; alerts carry the rule id or secret type and
  path:line, never a secret value. Every line is masked, but treat it like a
  log line: quote it, never widen it with the raw log.
- The failing line is a lead. The log and artifacts (`kvb-ci-artifacts`)
  stay the evidence.
- A hotfix hint lists every repository's hotfixes; confirm it with
  `hotfix.py match --repo <worktree>` before you sync.
