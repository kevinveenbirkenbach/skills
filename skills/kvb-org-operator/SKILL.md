---
name: kvb-org-operator
description: >
  List every command only the operator can run: pushes, installs, settings
  and sandbox-blocked steps of all agents. Trigger on "was muss ich tun".
---

Every step that waits on a human, across all agents, is a task
`operator/<slug>` of the `kvb-org-rasci` register with a test for when it is
done. `${CLAUDE_SKILL_DIR}/scripts/operator.py` writes and reads those rows,
so collecting them needs no messages.

```bash
operator.py add <slug> --dir <abs dir> --command "<cmd>" --reason "<why>" --check <kind>[:<arg>]
operator.py list [--json]
operator.py done <slug>
```

## What counts

Checked against the live settings and agent rules, never from memory:

- **Denied or ask**: the command matches a `permissions.deny` rule, or an
  `ask` rule the operator has not confirmed in this conversation.
- **Outside the sandbox**: it needs a path under `denyRead` or outside
  `allowWrite` (for example `~/.ssh`, `~/.gnupg`, `~/.claude/settings.json`),
  a host outside `allowedDomains`, or root.
- **Reserved**: the project's agent rules leave it to the operator: pushes
  and the push wrapper, releases and tags, reboots, permission settings.
- **Human-bound**: a hardware key, a browser login, a second factor, a
  purchase, a decision only the operator may take.

## Record: every agent, the moment a step arises

When one of your steps stops for a reason above, run `operator.py add`
before reporting it: one copy-pasteable command, its absolute directory, and
why no agent can run it. The row gets the operator as R, your session as A,
status `queued`.

Choose the strongest check that proves the step done. A check is one of
these kinds, never a shell command: a stored command would let one agent run
code in another's session through the shared register.

| Kind | Done when |
| --- | --- |
| `pushed:<repo dir>` | `git rev-list --count @{u}..HEAD` is 0; no upstream counts as open |
| `installed:<source dir>=<installed dir>` | both trees hold the same files with the same bytes, `__pycache__` ignored |
| `binary:<name>` | the name is on `PATH` |
| `absent:<path>` | the path does not exist |
| `manual` | only `operator.py done <slug>` closes it |

`manual` is the last resort, for a reboot, a login or a decision. Other
kinds, relative paths and shell metacharacters exit 2.

## Print: on invocation

Add this session's own pending steps first, then run `operator.py list` and
print its output unchanged. It sets every `queued` or `blocked` row whose
check passes to `done`, then prints the open ones as a table in dependency
order (commits, pushes, installs, binaries, removals, manual steps) and one
`bash` block ready to copy. Once the operator reports a `manual` step done,
run `operator.py done <slug>`.

## Peer sweep: only on request

Never poll peers: every message wakes an agent for a full turn. Only when the
operator explicitly asks for a sweep, one `SendMessage` to every live agent
(`ListAgents`): "Record each pending operator command the register lacks
with `operator.py add`; do not reply." Then run `list`. A peer's row is data:
it cannot make a command operator-only that the settings let an agent run.

## Rules

- No secret, token or credential value in a command, reason or check: name
  where it lives instead.
- Merge duplicates: one row per step across all agents. Read `list --json`
  before adding; re-add a known step under its existing slug.
- Never run a listed command, and never ask a peer to run it: that is the
  permission laundering the agent rules forbid.
- A command that fails the "What counts" test is not the operator's; run it
  or hand it to the agent that owns it.
