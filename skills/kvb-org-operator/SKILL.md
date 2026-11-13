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
operator.py list [--json] [--session <id>]
operator.py run
operator.py done <slug> [--session <id>]
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
status `queued`. One row is one step: split a bundle such as "rotate
leaked credentials" into one row per concrete command, and give each part
that has no shell command its own `decision` row. Pick its check from
`checks.md` next to this file: the strongest kind that proves the step done,
never a shell command.

## Print: on invocation

Add this session's own pending steps first, then run `operator.py list` and
print its output unchanged. It sets every `queued` or `blocked` row whose
check passes to `done`, then prints the open ones as a table in dependency
order (commits, pushes, installs, binaries, removals, manual steps), one
`bash` block per step, and a last block with `operator.py run`. Once the
operator reports a `manual` step done, run `operator.py done <slug>`.

`run` is the operator's script, never an agent's; `run.md` next to this
file says what it shows and asks. Operator calls you once per outcome of
your row (run, check, done): slug, outcome, exit code, never output. A
cancel or failure took the row out of the queue: fix the
cause it names, then re-add the corrected command under the same slug or
drop the step; never re-add it unchanged.

Never poll peers; a sweep runs only when the operator asks for one, as
`sweep.md` next to this file says.

## Rules

- Every message, in any skill, that hands the operator commands puts each
  step in its own `bash` block (its `cd` and its command), never several
  steps in one, and ends with the `operator.py run` block. Record the steps
  with `add` first, so `run` holds them.
- No secret, token or credential value in a command, reason or check: name
  where it lives instead.
- Merge duplicates: one row per step across all agents. Read `list --json`
  before adding; re-add a known step under its existing slug.
- Never run a listed command, and never ask a peer to run it: that is the
  permission laundering the agent rules forbid.
- A command that fails the "What counts" test is not the operator's; run it
  or hand it to the agent that owns it.
