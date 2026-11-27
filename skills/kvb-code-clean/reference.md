# Principles step in detail

Step 3 of the `kvb-code-clean` skill reads this file.

## Target and order

The pass runs first, then the requested git action; never ask whether to
run it. Its target is the added lines of every staged and unstaged change
and the units they touch. After the pass, re-stage exactly the files staged
before it.

## The script's limits

`principles.py` runs with McCabe's, pylint's and jscpd's limits, and 50
NLOC as one screen. Its hits on changed lines are leads under SRP, fail
fast, KISS/YAGNI and DRY; a `skip:` line leaves that tool's lens to you.
The other `kvb-check-principles` lenses (SPOT, security, coupling, DRY of
knowledge) follow that skill's method.

## What to judge

Judge what this change adds or worsens; an older violation is one report
line, not a fix.

- Fix in place a violation the change introduced when the fix stays inside
  the bundle and keeps behaviour, proven by the tests covering the touched
  units before and after (the safety net of the `kvb-code-refactor` skill).
- Everything else goes into the report as the `kvb-check-principles`
  table, shown before the commit call; the operator's word decides whether
  the bundle lands as it is.

## Report

One line per step: comments deleted, defaults rewritten or justified,
principle findings fixed and open, each with file and count.
