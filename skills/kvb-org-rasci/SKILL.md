---
name: kvb-org-rasci
description: >
  RASCI/OKR register of tasks: roles, key results, worker, status.
  Trigger on "rasci", "raci", "zuständigkeiten".
---

The register is the organisation's single point of truth: every agent
records what it works on. `${CLAUDE_SKILL_DIR}/scripts/rasci.py` keeps it in
`<council root>/rasci.json`. A `kvb-org-organize` claim enters its task by
itself (holder as R and A, `running`, start, workdir, branch); its release
sets `done` and the end, or `stopped` while a key result is still open.

```bash
rasci.py set <task> --title <t> --objective <o> --description <d> --prio <n> --status queued|running|blocked|done|stopped --worker "<agent | subagent <type> (<model>)>" --workdir <dir> --branch <b> --base <upstream branch> --artifact <kind>:<ref> --tool <script or command> --after <task> [--start <iso>] [--end <iso>] [--drop-artifact <a>] [--drop-tool <t>] [--drop-after <task>]
rasci.py kr <task> add "<measurable result>" | met <n> | open <n> | rm <n>
rasci.py role <task> "<party>" <letters>
rasci.py get <task>
rasci.py rm <task>
rasci.py keep <task>
rasci.py prune --since <epoch> <task>...
rasci.py show [--wide] [--all] [--gaps]
rasci.py artifacts [--ended] [--task <task>] [--worker <text>]
rasci.py estimate <task> "<party>" --value <fib> --complexity <fib>
rasci.py estimate <task> Operator --value <fib>
rasci.py wsjf [--all]
rasci.py tools
rasci.py agents
rasci.py agents order "<agent>,<agent>,..."
```

## Objective and key results

The objective says what the task is for; its key results are the measurable
outcomes that prove it reached (a test green, a run passing, a release
published). `done` is refused while one is open; a task ended short of them is
`stopped`. `show --wide` puts both in the OKR column as
`<objective> (<met>/<all> KR)`.

## Roles

- **R Responsible**: does the task: the claim holder, or the subagent it runs.
- **A Accountable**: exactly one; takes the final decision. The claim
  holder, unless the operator decides.
- **S Supportive**: helps carry it out: a fix, a grant, a runner.
- **C Consulted**: asked before acting, e.g. the operator on a decision.
- **I Informed**: kept informed, without a say.

`-` clears a party; the operator is the party `Operator`.

## Rules

- On start, `set` title, objective, description, priority and worker, `kr
  add` every key result, and `role` every party beyond R and A; update the
  status on each change.
- Artifacts follow the `kvb-org-artefacts` skill:
  record each one when it appears, drop it once deleted. Add every script or
  tool the task ran (`--tool`): `tools` ranks them for `kvb-dream`.
- Priority is the rank of the `kvb-org-wsjf` skill: an operator's pin
  (`--prio`) first, then WSJF from the estimates the chair collects; `show`
  prints the rank as Prio and the score as WSJF; the agent order of
  `kvb-org-priority` only breaks ties. The Operator's business value, also
  recorded alone, replaces the median.
- `--after <task>` records that a task follows another (a Gantt arrow);
  an unknown task and a cycle are refused.
- Write only your own rows.
- Until a hub prune's Sécurité deadline, `keep` (or any change) holds a
  listed task open; the rest end `stopped`.
- Read `show` or `get` instead of asking a peer what it works on; `--wide`
  adds OKR, artifacts, times and every letter. Both cap at the top 30 open
  tasks; `--all` lists every task. Tasks ended over 7 days ago move to
  `rasci-archive.json`; `get` and `--all` still read it, and a command
  naming one brings it back.
- When invoked, summarize `show --wide` (counts per status, top tasks, the
  `gaps:` count; `show --gaps` lists each: shown tasks without exactly one
  A, without R, or open without a key result), never reprint it. `hotfix/`
  and `operator/` rows are records: `gaps:`, `wsjf` and `artifacts` skip
  them. `get` prints one task in full, key results numbered.
