# Succession

- A piece of work or a cluster ends with its result, a proposal, or an
  abandoned attempt, posted to the radio for the peers who heard the claim.
  The holder then runs `council.py release <office>`, and the next agent that
  starts the work is elected afresh.
- A representative or the chair that ends hands its office to the next-oldest
  live representative (by claim time) and posts it to the radio.
- Chair handover is explicit: the outgoing chair sends the incoming chair the
  queue and the running grants
  (`${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py send call --to
  <name>`: it must confirm), posts the new holder to the radio, and
  keeps allocating until the incoming chair confirms. Two allocators never
  run at once.
- A claim is stale when its holder's session is gone: in Claude Code its
  session id is no longer in `~/.claude/sessions`; other runtimes run
  `council.py beat` at least hourly and go stale after 60 minutes without one.
  `claim` then exits 4. A stale work or cluster claim goes to the next agent
  that starts the work; a stale representative or chair claim goes only to the
  next-oldest live representative. The successor runs
  `council.py takeover <office> --work "..."` and posts the succession to the
  radio; everyone else leaves it alone.
- After a restart or reboot, run `council.py list --mine` and claim again
  every office you believe you hold: `/tmp` may have been wiped.
