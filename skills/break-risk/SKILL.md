---
name: break-risk
description: >
  Derive the break-risk percentage from measurement instead of feel. Called by
  the `confidence` skill every time it reports, and usable alone whenever the
  operator asks "what could this break?" or names a break-risk threshold.
  Portable across projects.
---

Break risk is the probability the change breaks something it did not intend to
touch. It is not the inverse of fix confidence, and it is not a mood. Derive it
by answering the questions below; a number produced without them is a guess
wearing a percent sign.

## The consumer question, first and always

Enumerate every consumer of every thing the change alters, before naming a
number. A written caveat never licenses a low number; an enumeration does.

- Search the **committed** state, not just the working tree. A symbol that looks
  unused in your branch may still be called from a file you have not opened
  (`git grep <symbol> HEAD`). Removing a function with zero external callers is
  a different risk class from removing one with nine.
- Enumerate consumers of the **output**, not only of the code: who reads the
  variable, renders the template, parses the emitted block, imports the
  constant.
- Say the count out loud. "Two consumers, both inside this change set" is
  evidence. "I don't think anything else uses it" is not.

## Measure the delta at the surface that matters

Compare what the old code **actually produced** against what the new code
produces, at the point where the difference becomes observable: rendered output,
emitted config, returned set, wire bytes.

The trap this defeats: reasoning about what the old code *looks like* it did. A
sweep that appeared to forward sixteen ports forwarded **zero** in production,
because the flag it gated on was unrendered template text. Had the delta been
argued from the source rather than measured, the risk would have been sized
against a behaviour that never existed.

Extract the old implementation from version control and run it on today's
inputs. If `DROPPED` is empty, nothing can regress; say so and move on.

## Classify every finding as live or latent

For each way the change could break something, decide which it is and say so:

- **Live**: a shipped configuration, inventory, variant or default reaches it.
- **Latent**: reachable only under a configuration nobody ships today.

Both belong in the report. Only live findings drive the number up materially. A
latent finding with a named trigger is worth more to the operator than a vague
worry, and it is honest about why the number is not zero.

## Walk the deployment matrix

A change verified in one mode is unverified in the others. Enumerate the axes
the project actually has, and state the verdict per cell rather than averaging
them away. Typical axes: deployment mode, node role, topology, distro,
filesystem, single versus multi host.

Two numbers for two modes beats one blended number that is wrong in both.

## Weigh the failure mode, not only the probability

A low-probability failure that **fails open** can outrank a likely one that
fails closed. Ask what the world looks like when the change misbehaves:

- Fails closed and loud: the service refuses to start, a gate goes red, a
  request errors. Cheap to detect, bounded blast radius.
- Fails open and silent: a port stays reachable, a check passes vacuously, a
  credential keeps working, traffic is forwarded to an unintended place.

Say which one applies. When a design choice is between an unverifiable control
over an exposure and not creating the exposure, prefer the second and say why.

## Evidence rules

- Executed beats derived. Run it, render it, read the output.
- A subagent's report, a conversation summary, or your own earlier message is
  **not** evidence. Re-verify the claim yourself before it changes a number.
- Negative control before claiming a check works: make the thing it should
  catch, watch it fail, restore. A check never observed failing is not known to
  work.
- The same applies to a check you did not write. Citing an existing lint, test
  or gate as the reason a change is safe means reading its pattern, not its
  docstring, and watching it fail on the case you are trusting it to catch. A
  green gate whose rule never matched your case is silence, not a pass.
- After a context compaction, rebuild attributions from the source; conclusions
  survive compaction, the evidence under them does not.

## Producing the number

State it as a percentage next to fix confidence, never blended, and always with
its residuals. Anchor roughly:

- **Under 5%**: consumers enumerated, delta measured at the surface, every axis
  of the matrix covered by executed evidence, failure mode closed.
- **5 to 15%**: measured, but one axis or one layer rests on reasoning — no live
  run, a mode not exercised, a runtime the render cannot prove.
- **15 to 40%**: a real behaviour change whose consumers are enumerated but
  whose effect is unmeasured, or a latent finding with a plausible trigger.
- **Above 40%**: a known live defect, an unenumerated consumer set, or a
  fail-open exposure without a verified control. Fix it rather than report it.

Discount yourself after any error the operator caught in the same area during
this session, and say that you are doing so. A region where you have already
been wrong twice deserves a worse number than its paper evidence suggests.

## When the operator names a threshold

A named threshold is a gate on the work, not a field in the report. Missing it
is a work item: name the cheapest evidence that would close the gap, go get it,
re-measure. Report a miss only when the evidence is genuinely out of reach, and
name which piece.
