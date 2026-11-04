---
name: kvb-org-rasci
description: >
  RASCI/OKR register of tasks: roles, key results, worker, status.
  Trigger on "rasci", "raci", "zuständigkeiten".
---

The register is the single point of truth of the organisation: every agent
records here what it works on, and claims, queue, handover and reports run
over it. `${CLAUDE_SKILL_DIR}/scripts/rasci.py` keeps it in
`<council root>/rasci.json`. A `kvb-org-organize` claim enters its task by
itself (holder as R and A, `running`, start, workdir, branch); its release
sets `done` and the end, or `stopped` while a key result is still open.

```bash
rasci.py set <task> --title <t> --objective <o> --description <d> --prio <n> --status queued|running|blocked|done|stopped --worker "<agent | subagent <type> (<model>)>" --workdir <dir> --branch <b> --base <upstream branch> --artifact <kind>:<ref> --tool <script or command> [--start <iso>] [--end <iso>] [--drop-artifact <a>] [--drop-tool <t>]
rasci.py kr <task> add "<measurable result>" | met <n> | open <n> | rm <n>
rasci.py role <task> "<party>" <letters>
rasci.py get <task>
rasci.py rm <task>
rasci.py show [--all]
rasci.py show --wide [--all]
rasci.py artifacts [--ended] [--task <task>]
rasci.py estimate <task> "<party>" --value <fib> --complexity <fib>
rasci.py wsjf [--all]
rasci.py tools
rasci.py agents
rasci.py order "<agent>,<agent>,..."
```

## Objective and key results

The objective says what the task is for; its key results are the measurable
outcomes that prove it reached (a test green, a run passing, a release
published). `done` is refused while one is open; a task ended short of them is
`stopped`. `show --wide` puts both in the OKR column as
`<objective> (<met>/<all> KR)`.

## Roles

- **R Responsible**: does the task: the claim holder, or the subagent it runs.
- **A Accountable**: exactly one; takes the final decision and carries the
  overall responsibility. The claim holder, unless the operator decides.
- **S Supportive**: actively helps carry it out: a peer's fix, the chair's
  grant, a stack or runner.
- **C Consulted**: asked for input before acting: line representatives,
  lineage owners, the operator on a pending decision.
- **I Informed**: kept up to date on progress or result, without a say.

`-` clears a party; the operator is the party `Operator`.

## Rules

- On start, `set` title, objective, description, priority and worker, `kr
  add` every key result, and `role` every party beyond R and A; on each
  change, update the status. The worker is the one session or subagent
  executing the task right now.
- Artifacts share this table and follow the `kvb-org-artefacts` skill:
  record each one when it appears, drop it once deleted. Add every script or
  tool the task ran (`--tool`): `tools` ranks them for `kvb-dream`.
- Priority is the rank of the `kvb-org-wsjf` skill: an operator's pin
  (`--prio`) first, then WSJF from the estimates the chair collects; `show`
  prints the rank as Prio and the score as WSJF.
- Write only your own rows; another session's task belongs to that session.
  The one exception is `order`, the operator's pick through the
  `kvb-org-priority` skill.
- Read `show` (Prio, WSJF, Task, Status, Worker, A; cells cut short) or
  `get` instead of asking a peer what it works on. `show --wide` adds OKR,
  Artifacts, Start, End and every RASCI letter.
- When invoked, print `show --wide` unchanged; its `gaps:` line names tasks
  without exactly one A, without R, or open without a key result. `hotfix/`
  and `operator/` rows are records, not work tasks: `gaps:`, `wsjf` and
  `artifacts` skip them. `get` prints one task in full, key results numbered.
