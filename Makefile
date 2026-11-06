.PHONY: install project test update budget orchestrator-install orchestrator-check orchestrator-pin orchestrator-runner orchestrator-hook watch-check

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

# Migrate, install, build and start only the Agent Orchestrator, without touching the installed skills.
orchestrator-install:
	@bash scripts/orchestrator.sh install

# Check the installed Agent Orchestrator: image, container, logs, HTTP, pinned keys, hook, runner, disk.
orchestrator-check:
	@bash scripts/orchestrator.sh check

# Param: CREDENTIAL the blob "Passkey registrieren" shows: make orchestrator-pin CREDENTIAL=<blob>
orchestrator-pin:
	@bash scripts/orchestrator.sh pin "$(CREDENTIAL)"

# Install, enable and restart the Agent Orchestrator runner user service.
orchestrator-runner:
	@bash scripts/orchestrator.sh runner

# Register the Agent Orchestrator PermissionRequest hook in ~/.claude/settings.json.
orchestrator-hook:
	@bash scripts/orchestrator.sh hook

# Show whether the agents-council watch hook is stuck.
watch-check:
	@bash scripts/watch-check.sh
