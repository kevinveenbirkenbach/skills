# skills 🧠

[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub%20Sponsors-blue?logo=github)](https://github.com/sponsors/kevinveenbirkenbach) [![Patreon](https://img.shields.io/badge/Support-Patreon-orange?logo=patreon)](https://www.patreon.com/c/kevinveenbirkenbach) [![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20Coffee-Funding-yellow?logo=buymeacoffee)](https://buymeacoffee.com/kevinveenbirkenbach) [![PayPal](https://img.shields.io/badge/Donate-PayPal-blue?logo=paypal)](https://s.veen.world/paypaldonate)

The agent skill collection of Kevin Veen-Birkenbach.
Every skill is pinned in `skills-lock.json` for reproducible installs.
First-party skills live under `skills/` and are layered on top of the locked ones at install time.
Compatible with Claude Code, Codex, Gemini CLI, Cursor, Copilot, Windsurf, Cline, and other agents.

## Requirements 📦

- Node.js (provides `npx skills`).
- `jq` (only required for `make update`).

## Installation 🚀

Install the skills globally into your home (`~/.agents/skills` and `~/.claude/skills`):

```bash
make install
```

Copy the skills into a specific project (`<repo>/.agents/skills` and `<repo>/.claude/skills`):

```bash
make project TARGET=/path/to/repo
```

Both commands also enable the caveman and ponytail plugins in the target's `.claude/settings.json` so their modes auto-activate on session start; existing settings are preserved.

Restart your agent afterwards so it loads the new skills.

## Maintenance 🔧

Refresh every skill to its latest version and rewrite `skills-lock.json`:

```bash
make update
```

Validate `skills-lock.json` and shellcheck the scripts (also run by CI on every push and after every update):

```bash
make test
```

## Related Tools 🧰

This collection is part of a wider toolset for managing IT and infrastructure:

- [alias](https://github.com/kevinveenbirkenbach/alias) — shell aliases for common commands.
- [package-manager](https://github.com/kevinveenbirkenbach/package-manager) — `pkgmgr`, a single command to install and manage these repositories.
- [infinito-nexus](https://github.com/kevinveenbirkenbach/infinito-nexus) — automation platform for self-hosted infrastructure.

## License 📜

MIT License, Copyright (c) 2026 Kevin Veen-Birkenbach.

## Author 👤

Kevin Veen-Birkenbach [kevin@veen.world](mailto:kevin@veen.world)

## Thanks 🙏

Thanks to the [#ai:infinito.nexus](https://matrix.to/#/%23ai:infinito.nexus) community, and especially to [Paulinhx](https://github.com/Paulinhx) for the inspiration.

## Donation ❤️

If these tools help you, consider supporting their development:

- [GitHub Sponsors](https://github.com/sponsors/kevinveenbirkenbach)
- [Patreon](https://www.patreon.com/c/kevinveenbirkenbach)
- [Buy Me a Coffee](https://buymeacoffee.com/kevinveenbirkenbach)
- [PayPal](https://s.veen.world/paypaldonate)
- Bitcoin: [bc1qle7j8m9kvny2h2q3jzsnc64s4f5zme5re23pzc2lc2d7hhasc4dqachflp](bitcoin:bc1qle7j8m9kvny2h2q3jzsnc64s4f5zme5re23pzc2lc2d7hhasc4dqachflp?message=%E2%9D%A4%EF%B8%8F%20Help%20Build%20the%20Future%20-%20Donation%20to%20Kevin%20Veen-Birkenbach.)
