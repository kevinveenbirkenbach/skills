---
name: kvb-skill-silence
description: >
  Cut the tokens and agent messages the skills of this repository and of the
  skills repo cost. kvb-optimize runs it.
---

Every word in the skill listing, a loaded SKILL.md or a hook's output is paid
on every turn of every session, and every delivered message costs its
recipient a full turn. `kvb-skill-essence` removes dead weight and
duplicates; this skill cuts what still costs.

## Scope and measurement

The skills the current repository owns (`skills/`, its own `.claude/skills/`,
not installed copies) and the skills repository. Measure before changing:

- `scripts/budget.py --repo <skills repo> --top 10`: listing words, the
  longest descriptions, every SKILL.md over the cap.
- Each own SKILL.md's word count, and what each registered hook prints per
  turn (settings files, read-only).
- The window's traffic: the radio store (`radio.py show --all` of the
  `kvb-org-radio` skill; wakes carry `"wake": true` in its `news.jsonl`),
  this session's `SendMessage` calls, and subagent runs
  (`log.py report` of the `kvb-org-perform` skill).
- Context re-read per turn, from the transcripts Claude Code keeps:
  `${CLAUDE_SKILL_DIR}/scripts/context.py --root ~/.claude/projects --days 7
  --threshold 300000 --threshold 500000` (turns, tokens, median, p90,
  compactions, shares above each threshold, per day).

## Levers, in this order

1. **Listing**: a description says what and when, never its own slash
   command; no skill listed twice through a copy and a plugin.
2. **Length**: each SKILL.md at most `SKILL_WORDS` (600) words of
   `scripts/budget.py`, enforced by `tests/test_lock.py`. Details move to a
   side file the skill reads only when it needs them; no rule is cut.
3. **Messages**: every step that sends one is checked against the
   `kvb-org-organize` Peer protocol: status that asks nothing goes to
   `radio.py post`, polling peers becomes reading the council, the register or
   the radio, one batched message per peer, a wake only when the recipient
   must act or answer, no reply to a message that asks nothing, light runs
   admit themselves.
4. **Subagents**: their number follows the stakes, the brief names exact
   files and claims and caps the answer, a cheaper model only by the
   `kvb-org-perform` table.
5. **Exploration**: code questions go to the code graph first (the
   `kvb-agent-optimize` skill), grep and reading after.
6. **Hooks**: a hook prints nothing when nothing changed; a reminder fires
   once per window, not per turn.
7. **Context window**: `make install` sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW`
   to 500000 where it is unset. Propose a new value only with the
   `context.py` series as evidence (tokens saved, compactions, and the
   operator's corrections of agents that lost a detail after one); the
   operator picks and changes it, because the settings are the operator's.
   Never adjust it automatically.

## Confirm and apply

One `AskUserQuestion` batch, or the round of the `kvb-optimize` skill: every
change with its measured cost before and its estimate after. Only what is
picked gets written. A change to another repository's skills becomes a task
for that repository's owner in the `kvb-org-rasci` register, never a write
from here.

## Output

| Repository | Skill or hook | Lever | Before | After |
