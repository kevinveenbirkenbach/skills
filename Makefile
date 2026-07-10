.PHONY: install project test update

# Install the skills globally into $HOME (.agents/skills + .claude/skills).
install:
	@TARGET="$(HOME)" bash scripts/install.sh

# Copy the skills into a project: make project TARGET=/path/to/repo
project:
	@test -n "$(TARGET)" || { echo "usage: make project TARGET=/path/to/repo"; exit 2; }
	@TARGET="$(TARGET)" bash scripts/install.sh

# Validate skills-lock.json and shellcheck the scripts.
test:
	@python3 -m unittest discover -s tests -v
	@if command -v shellcheck >/dev/null; then shellcheck scripts/*.sh; else echo "shellcheck not installed - skipped"; fi

# Update all skills to their latest versions and refresh skills-lock.json.
update:
	@bash scripts/update.sh
