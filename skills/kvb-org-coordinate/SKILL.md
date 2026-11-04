---
name: kvb-org-coordinate
description: >
  Coordinate a failure or fix with agents on related branches through
  merges: claim, ask, report. Trigger when a fix touches code other
  branches share.
---

Run the `kvb-org-organize` skill's **Peer protocol**, its `lineage.md`
included, for the failure or fix at hand. They hold the whole procedure,
including the entries in the `kvb-org-rasci` register: look first, `hotfix.py
match` of the `kvb-git-hotfix` skill included; ask by `radio.py send direct
--to <name> --wake`; report by `radio.py post` (both `kvb-org-radio`). A
hotfix is recorded with `hotfix.py add` and `update`, never reported by
message or radio post. This skill only keeps its command working.
