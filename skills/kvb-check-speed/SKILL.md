---
name: kvb-check-speed
description: >
  Wall-clock speed of changed code versus its base commit.
---

Its ⏱️ velocity is the share of its base's wall-clock time a change needs:
under 100 % it is faster, over 100 % slower. It has no script of its own: one run
of the `kvb-check-efficiency` measurement yields both values.

```bash
python3 ${CLAUDE_SKILL_DIR}/../kvb-check-efficiency/scripts/measure.py --base <ref> -- <command...>
```

Its `⏱️ velocity <p> % (wall <b>→<a> s)` compares wall seconds at `<ref>` and
in the working tree: one run each, or the mean of 5 each when a value
exceeds 100. The command, the runs, the `queue.py hold` wrapper for heavy
commands and the exit codes are those of the `kvb-check-efficiency` skill;
pasting its whole line reports both values at once.

- **Skills have no speed**: only their tokens count. Pass `--speed -` to
  `kvb-check-score`, which shows `–`.
- **Code without a runnable path** (configuration, templates no command
  renders) has no speed either: `--speed -`, and say why.
- **Other load**: wall time follows host load. Above 30 % other load the
  script falls back to the CPU-time ratio and marks the estimate:
  `⏱️ velocity ~<p> % (cpu <b>→<a> s)`, ending in
  `(estimated: other load <x> %)`. Report the run you
  made; never rerun to pick the best result.
