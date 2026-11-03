# Unmerged and dirty items

Never part of the apply. One `AskUserQuestion` question per item
(`multiSelect: false`): `Keep (Recommended)` and `Delete`, the description
naming what is lost (the item's `reason`: unique commits, dirty paths). For
each `Delete`, hand the operator `pkgmgr branch purge --branch <name>`: it
asks y/N per item and answers no without a terminal, so it runs only in the
operator's shell.
