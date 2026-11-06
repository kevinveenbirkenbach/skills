.PHONY: install project test update budget hub-install hub-check hub-pin hub-runner hub-hook watch-check

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

# Count skill description words against the listing budget: make budget [INDEX=1]
budget:
	@python3 scripts/budget.py --repo . --top 5 $(if $(INDEX),--index)

# Install, build and start only the kvb-hub, without touching the installed skills.
hub-install:
	@bash scripts/hub.sh install

# Check the installed kvb-hub: image, container, logs, HTTP, pinned keys, hook, runner, disk.
hub-check:
	@bash scripts/hub.sh check

# Param: CREDENTIAL the blob the hub's "Passkey registrieren" shows: make hub-pin CREDENTIAL=<blob>
hub-pin:
	@bash scripts/hub.sh pin "$(CREDENTIAL)"

# Install, enable and restart the kvb-hub runner user service.
hub-runner:
	@bash scripts/hub.sh runner

# Register the kvb-hub PermissionRequest hook in ~/.claude/settings.json.
hub-hook:
	@bash scripts/hub.sh hook

# Show whether the agents-council watch hook is stuck.
watch-check:
	@bash scripts/watch-check.sh
