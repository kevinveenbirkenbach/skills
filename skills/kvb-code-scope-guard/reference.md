# Scope guard in detail

The `kvb-code-scope-guard` skill reads this file for each rule's reason and
edge cases. A problem you noticed behind the request is not an invitation to
solve it.

1. **Scaffolding**: a migration you run once needs a throwaway script, not a
   CLI subcommand that ships forever. Do the thing, then delete the
   scaffolding.
2. **`git add`**: the operator's tree carries their own edits and their
   local config, and sweeping those into your bundle makes them undo your
   work by hand.
3. **Adjacent defects**: fixing one quietly puts an unreviewed change in
   someone else's commit.
4. **Hand-overs**: an instruction to hand something over is complete on its
   own. Print the artifact in the shape asked for: do not optimize, reorder
   or deduplicate it, do not wrap it in a command that consumes it, and do
   not append commentary, next steps, confidence blocks or offers. A
   narrowing qualifier ("just the line") re-shapes the earlier request;
   re-emit narrower without re-deriving the content. A problem with the
   artifact is worth one sentence before it, never a rewrite of it.
