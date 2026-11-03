# Run behind HEAD

A CI run is a snapshot of one commit, and the branch has moved since. Scope
the job set down **before** enumerating, clustering or spawning anything:
every job investigated against stale code is work thrown away, and a fix
proposed there risks reverting someone else's.

Two cheap discriminators, without opening an artifact:

- `git diff --name-only <run-sha>..HEAD -- <source dir> | cut -d/ -f2 | sort -u`
  shows which components already moved.
- A grep of the saved job logs for the literal error signature of each cause
  already fixed in that range.

What survives both is the job set the procedure applies to; say how many jobs
you dropped and why. The run cannot contain a fix that landed after it, so
looking only at its commit can only ever confirm the failure.
