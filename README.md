# skills 🧠

Reproducible agent skill collection, pinned in `skills-lock.json`.
Works for Claude Code, Codex, Gemini CLI, Cursor, Copilot, Windsurf, Cline, and more.

Homepage: [github.com/kevinveenbirkenbach/skills](https://github.com/kevinveenbirkenbach/skills)

## Usage 🚀

- `make install` installs the skills globally into your home (`~/.agents/skills` and `~/.claude/skills`).
- `make project TARGET=/path/to/repo` copies the skills into a project (`<repo>/.agents/skills` and `<repo>/.claude/skills`).
- `make update` refreshes every skill to its latest version and rewrites `skills-lock.json`.
- `make test` validates `skills-lock.json` and shellchecks the scripts; CI runs it on every push and after every update.

Node.js is REQUIRED (`npx skills`); `make update` additionally needs `jq`.
Restart your agent after installing so it loads the new skills.

## Author 👤

Kevin Veen-Birkenbach [kevin@veen.world](mailto:kevin@veen.world)
