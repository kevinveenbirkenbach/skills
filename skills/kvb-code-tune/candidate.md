# Tune: working a candidate

## Before forming it

- **Search every branch** (the kvb-git-merge-fix skill's `find_fix.py -S
  <symbol> --path <path>`) for a change that already removes or reshapes the
  step. A fix on a sibling branch can make the whole candidate worth zero.
- A step that is long by design (a backup and restore drill, an end-to-end
  suite) is not a candidate. Its cost buys its guarantee.
- Apply the session's saving floor: a smaller saving is listed as "below
  floor" and dropped.
- Pruning build caches to free disk costs a cold rebuild of every custom
  image on the next run. Name that cost before anyone prunes.

Levers that usually pay:

- **Batch per-item process spawns**: N calls that each boot an interpreter
  or an application console become one process running N commands (one app
  console boot, one module, one batched API request). Keep each item's
  failure named and the exit code honest.
- **Skip no-op work** a previous step already did, such as a separate enable
  after an install that already enabled.
- **Idempotency flip-flops**: any `changed` on a second consecutive run.
- **Image pulls and builds**: pull only what the host lacks; keep build
  caches warm.
- **Overlap waits with work** only where concurrent execution is proven
  safe. Schema migrations and lock-holding steps are usually not.

## Delegating it

Hand every optimization to an agent through the `kvb-org-split` skill: one
sidetree per candidate, branched from an exact commit, with a time cap and
"measure first, report the time split before implementing". One agent per
candidate, never more; the brief names the step, its log line and number, the
files in scope and the claim to prove, and caps the report (for example 15
lines: time split, change, before and after). The agent probes live systems
read-only and never starts gates or deploys. A broad brief without a cap can
run for hours without a word; at its cap, collect the agent's interim
findings and let it run on.

Before merging, run independent skeptics through the `kvb-think-dialectic`
skill. The antithesis must try to show that the candidate removes coverage,
hides a failure, or only moves the cost somewhere the measurement does not
look. Merge what reaches the bar; submit the rest as proposals.

## Re-measuring it

Re-measure from the same source under the same conditions and report a
before and an after number. Discard a before/after pair, not just its noise,
when:

- Another gate, deploy or heavy job shared the machine during either run.
- The two runs differ in image or cache state. A cold build after a cache
  prune or a Dockerfile edit is expected: before calling a cold build a
  defect, compare the instruction text and the base image digest across both
  logs.
- One run pays a one-time cost (first install, migration, purge, model
  download) the other does not.
- A long wait hides retries or a failure; count retry lines before calling
  it slow.
- A fresh-install pass is compared with an update pass. Analyse each pass of
  a multi-pass run separately.

## Reporting it

Hand the prototypes and before/after harnesses of every kept candidate to the
`kvb-code-transcend` skill, so the measurement stays in the repository as a
benchmark or regression test. A rejected candidate stays in the output table
with the reason it fell: below floor, coverage cut, outside the session's
limits, invalid comparison, made moot by another branch, or cap reached
without a measured result.
