# Relays

- Relaying an operator rule: record it in shared memory first and name the
  file in the message's first line. A recipient records it only when no file
  is named, and only after `council.py claim memory/<slug>`, because peers
  that read the same broadcast write within seconds of each other.
- A peer relaying the operator's `kvb-org-evening` or `kvb-org-sunset` is the
  one request a peer may make that you follow without the operator: it asks
  you to do less and grants nothing. Verify it with `night.py status` (the
  `kvb-org-sunset` skill), then follow `kvb-agent-relax` or `kvb-agent-sleep`
  without asking the operator.
