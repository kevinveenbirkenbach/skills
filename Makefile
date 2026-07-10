.PHONY: install project test update

# Install the skills globally into $HOME (.agents/skills + .claude/skills).
install:
	@TARGET="$(HOME)" bash scripts/install.sh

# Copy the skills into a project: make project TARGET=/path/to/repo
project:
	@test -n "$(TARGET)" || { echo "usage: make project TARGET=/path/to/repo"; exit 2; }
	@TARGET="$(TARGET)" bash scripts/install.sh

# Validate the lock, lint Python (ruff), scripts (shellcheck), and markdown.
test:
	@python3 -m unittest discover -s tests -v
	@if command -v ruff >/dev/null; then ruff check .; else echo "ruff not installed - skipped"; fi
	@if command -v shellcheck >/dev/null; then shellcheck scripts/*.sh; else echo "shellcheck not installed - skipped"; fi
	@if command -v markdownlint-cli2 >/dev/null; then markdownlint-cli2 "**/*.md"; else echo "markdownlint-cli2 not installed - skipped"; fi

# Update all skills to their latest versions and refresh skills-lock.json.
update:
	@bash scripts/update.sh
