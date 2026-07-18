---
name: explain
description: >
  Explain code and its interactions. Trigger when the operator asks what a
  piece of code does, how a mechanism works, why components interact the way
  they do, or invokes /explain on a file, function, role, or module.
  Portable across projects.
---

Explain the named code so an engineer who has never seen it can follow it:

1. Read the code and every collaborator it touches (callers, callees,
   templates, configs) before explaining; never explain from the name alone.
2. Lead with the purpose in one sentence, then walk the flow in execution
   order: inputs, transformations, side effects, outputs. Name the real
   files and line references.
3. Make the interactions explicit: which component induces, triggers, or
   consumes which, and where the single source of truth lives. Point out
   trip-wires (non-obvious ordering, escaping, caching, permission edges)
   as part of the flow, not as an appendix.
4. Afterwards ask whether to persist a Mermaid diagram of the explained
   mechanism under a `## Schema` heading in the README.md next to the
   affected code (create the heading if missing, replace its previous
   diagram if present). On approval, keep the diagram to the explained
   scope: components as nodes, induction/data flow as labeled edges.
