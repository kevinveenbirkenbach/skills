# From scored record to improvements

## Step 3: hypothesize

A pattern (two or more occurrences) or a single expensive failure becomes a
falsifiable hypothesis: *cause → predicted consequence → what would disprove
it*. Drop one-off noise; cut a hypothesis nothing could disprove.

## Step 4: dialectic

Every surviving hypothesis goes through the `kvb-think-dialectic` skill to
~99%. Scale the skeptics to the stakes: one for a memory fact, more for a rule
or code change. Each brief names the exact files, commits or log lines and the
one claim to attack, and caps the answer at ten lines. Survivors become
findings; refuted ones are recorded as discarded **with the refutation**, so
the next dream does not re-derive them.

## Step 5: write memory

In the memory directory of the project concerned: one file per fact, one
pointer line in `MEMORY.md`. Update the file covering a fact instead of adding
a duplicate; delete memories this run disproved. Absolute dates, never
"yesterday". Nothing the repository already records (code structure, git
history, `CLAUDE.md`).

## Step 6: the improvements

- **Code**: the change to the repository's source, tests, config or CI the
  finding calls for.
- **Agent instructions**: the missing or wrong rule in `CLAUDE.md`,
  `AGENTS.md`, the project's skills or contributor docs. Every mistake repeated
  in the window is a candidate: quote the line that failed to prevent it or
  name the absent rule, and propose the exact wording.

Prefer the structural fix (test, check, hook, written rule) that makes the
error impossible over a memory entry that only reminds. Each question carries
the improvement and its evidence.

A finding on a live peer's line goes to it as
`${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/news.py post "<finding>" --to
<name>`; `SendMessage` only when the peer must act or answer.
