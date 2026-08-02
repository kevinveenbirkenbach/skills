#!/usr/bin/env node
// Enable the caveman and ponytail plugins in a Claude Code settings.json so
// their SessionStart hooks auto-activate both modes, and register the autotune
// and dream reminder hooks. Merges non-destructively: existing marketplaces,
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

fs.writeFileSync(settingsPath, JSON.stringify(data, null, 2) + "\n");
console.log(`skills: enabled caveman + ponytail plugins and the ${REMINDERS.join(" + ")} reminders in ${settingsPath}`);
