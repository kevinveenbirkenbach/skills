#!/usr/bin/env node
// Enable the caveman and ponytail plugins in a Claude Code settings.json so
// their SessionStart hooks auto-activate both modes, register the autotune
// and dream reminder hooks, the democracy claim gate, the resource watch and the subagent-model log. Merges non-destructively: existing marketplaces,
// plugins and hooks are preserved, unparseable files are left untouched.
"use strict";

const fs = require("fs");
const path = require("path");

const settingsPath = process.argv[2];
if (!settingsPath) {
  console.error("usage: enable-plugins.js <settings.json>");
  process.exit(2);
}

const MARKETPLACES = {
  caveman: { source: { source: "github", repo: "JuliusBrussee/caveman" } },
  ponytail: { source: { source: "github", repo: "DietrichGebert/ponytail" } },
};
const PLUGINS = { "caveman@caveman": true, "ponytail@ponytail": true };
const REMINDERS = ["autotune", "dream"];

let data = {};
if (fs.existsSync(settingsPath)) {
  const raw = fs.readFileSync(settingsPath, "utf8").trim();
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch (err) {
      console.error(`skills: ${settingsPath} is not valid JSON; leaving it untouched (${err.message}).`);
      process.exit(0);
    }
  }
}

data.extraKnownMarketplaces = data.extraKnownMarketplaces || {};
for (const [name, entry] of Object.entries(MARKETPLACES)) {
  if (!data.extraKnownMarketplaces[name]) data.extraKnownMarketplaces[name] = entry;
}
data.enabledPlugins = Object.assign(data.enabledPlugins || {}, PLUGINS);

data.hooks = data.hooks || {};
data.hooks.UserPromptSubmit = data.hooks.UserPromptSubmit || [];
const alreadyRegistered = JSON.stringify(data.hooks.UserPromptSubmit);
for (const skill of REMINDERS) {
  if (alreadyRegistered.includes(`${skill}/hooks/reminder.sh`)) continue;
  const reminder = path.join(path.dirname(settingsPath), "skills", skill, "hooks", "reminder.sh");
  data.hooks.UserPromptSubmit.push({
    hooks: [{ type: "command", command: `bash ${JSON.stringify(reminder)}` }],
  });
}

data.hooks.PreToolUse = data.hooks.PreToolUse || [];
if (!JSON.stringify(data.hooks.PreToolUse).includes("democracy/scripts/council.py")) {
  const council = path.join(path.dirname(settingsPath), "skills", "democracy", "scripts", "council.py");
  data.hooks.PreToolUse.push({
    matcher: "Edit|Write|MultiEdit|NotebookEdit",
    hooks: [{ type: "command", command: `python3 ${JSON.stringify(council)} gate` }],
  });
}

const SCRIPT_HOOKS = [
  ["democracy/scripts/watch.py", "UserPromptSubmit", null, "watch"],
  ["democracy/scripts/watch.py", "PostToolUse", "Bash", "watch"],
  ["democracy/scripts/watch.py", "PreToolUse", "Bash", "block"],
  ["subagent-model/scripts/log.py", "PreToolUse", "Agent|Task", "spawn"],
  ["subagent-model/scripts/log.py", "PostToolUse", "Bash", "persist"],
];
for (const [script, event, matcher, sub] of SCRIPT_HOOKS) {
  data.hooks[event] = data.hooks[event] || [];
  const registered = data.hooks[event].some((entry) =>
    (entry.hooks || []).some((hook) =>
      String(hook.command).includes(script) && String(hook.command).endsWith(` ${sub}`)));
  if (registered) continue;
  const file = path.join(path.dirname(settingsPath), "skills", ...script.split("/"));
  const entry = { hooks: [{ type: "command", command: `python3 ${JSON.stringify(file)} ${sub}` }] };
  data.hooks[event].push(matcher ? { matcher, ...entry } : entry);
}

fs.writeFileSync(settingsPath, JSON.stringify(data, null, 2) + "\n");
console.log(`skills: enabled caveman + ponytail plugins, the ${REMINDERS.join(" + ")} reminders, the democracy claim gate, the resource watch and the subagent-model log in ${settingsPath}`);
