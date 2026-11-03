# Lineage

For a failure or a fix that other branches share through merges:

- Name the branches this one shares commits with: upstream (merged into this
  one) and downstream (merging this one). Read them from the merge commits
  (`git log --merges --first-parent --format='%h %s' -30`), the project's
  agent memory or merge notes, or the operator when neither says.
- Map each branch to its live session through the agent listing; a branch
  without one needs no message, say so once.
- One message per failure cluster, not per job.
- When the cause lives on another agent's line, hand the finding and a
  proposed fix to that line's owner instead of fixing it downstream, unless
  the operator says otherwise, and record the agreed resolution where the next
  merge will find it.
