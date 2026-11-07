---
name: kvb-think-explain
description: >
  Explain on request what code does, how a mechanism works or why
  components interact.
---

Explain the named code so an engineer who has never seen it can follow it:

1. Read the code and every collaborator it touches (callers, callees,
   templates, configs) before explaining; never explain from the name alone.
   Explore through the codebase-memory-mcp graph first (`search_graph`,
   `trace_path`, `get_architecture`; the `kvb-agent-optimize` skill sets it
   up), grep and read after.
2. Lead with the purpose in one sentence, then walk the flow in execution
   order: inputs, transformations, side effects, outputs, with real files
   and line references.
3. Make the interactions explicit: which component induces, triggers or
   consumes which, and where the single source of truth lives. Point out
   trip-wires (non-obvious ordering, escaping, caching, permission edges) in
   the flow, not in an appendix.
4. Afterwards ask whether to persist a Mermaid diagram of the explained
   mechanism under a `## Schema` heading in the README.md next to the
   affected code (create the heading if missing, replace its previous
   diagram if present). On approval, keep the diagram to the explained
   scope: components as nodes, induction and data flow as labeled edges.
