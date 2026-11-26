#!/usr/bin/env node
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
const PLUGINS = {
  "caveman@caveman": true,
  "ponytail@ponytail": true,
};
// Trip-wire: `codebase-memory-mcp install` registers the same server for every agent, Claude Code included; the plugin on top runs it twice.
const RETIRED_PLUGINS = { "codebase-memory@codebase-memory": "codebase-memory" };
const REMINDERS = ["kvb-dream", "kvb-coach"];
const RETIRED = [
  "autotune/hooks/reminder.sh",
  "kvb-skills-tune/hooks/reminder.sh",
  "kvb-skill-tune/hooks/reminder.sh",
];
const RENAMED = {
  "dream/hooks/reminder.sh": "kvb-dream/hooks/reminder.sh",
  "kvb-skills-dream/hooks/reminder.sh": "kvb-dream/hooks/reminder.sh",
  "kvb-skill-dream/hooks/reminder.sh": "kvb-dream/hooks/reminder.sh",
  "democracy/scripts/council.py": "kvb-org-organize/scripts/council.py",
  "democracy/scripts/watch.py": "kvb-org-organize/scripts/watch.py",
  "subagent-model/scripts/log.py": "kvb-org-perform/scripts/log.py",
  "kvb-org-organize/scripts/news.py": "kvb-org-radio/scripts/radio.py",
};

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
for (const [plugin, marketplace] of Object.entries(RETIRED_PLUGINS)) {
  // Trip-wire: this file can be settings.local.json; a deleted key there lets a true in settings.json win, a false overrides it.
  data.enabledPlugins[plugin] = false;
  delete data.extraKnownMarketplaces[marketplace];
}
data.env = data.env || {};
if (!data.env.CLAUDE_CODE_AUTO_COMPACT_WINDOW) data.env.CLAUDE_CODE_AUTO_COMPACT_WINDOW = "300000";
const PYTHON = "/usr/bin/python3 -I";
const ABSOLUTE = { python3: PYTHON, bash: "/usr/bin/bash" };
require("./council-deny").withCouncilDeny(data);

const pluginRepos = new Set(Object.values(MARKETPLACES).map((entry) => entry.source.repo));
const lock = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "skills-lock.json"), "utf8"));
for (const [name, entry] of Object.entries(lock.skills || {})) {
  if (pluginRepos.has(entry.source)) {
    fs.rmSync(path.join(path.dirname(settingsPath), "skills", name), { recursive: true, force: true });
  }
}

data.hooks = data.hooks || {};
const retired = (hook) =>
  typeof hook.command === "string" && RETIRED.some((r) => hook.command.includes(`/skills/${r}`));
for (const [event, entries] of Object.entries(data.hooks)) {
  if (!Array.isArray(entries)) continue;
  data.hooks[event] = entries
    .map((entry) =>
      Array.isArray(entry.hooks) ? { ...entry, hooks: entry.hooks.filter((h) => !retired(h)) } : entry)
    .filter((entry) => !Array.isArray(entry.hooks) || entry.hooks.length > 0);
}
for (const entries of Object.values(data.hooks)) {
  if (!Array.isArray(entries)) continue;
  for (const entry of entries) {
    for (const hook of entry.hooks || []) {
      if (typeof hook.command !== "string") continue;
      for (const [from, to] of Object.entries(RENAMED)) {
        hook.command = hook.command.replace(`/skills/${from}`, `/skills/${to}`);
      }
      if (hook.command.includes("/skills/kvb-")) {
        hook.command = hook.command.replace(/(^|&& )(python3|bash) /, (_, lead, binary) => `${lead}${ABSOLUTE[binary]} `);
      }
    }
  }
}
data.hooks.UserPromptSubmit = data.hooks.UserPromptSubmit || [];
const alreadyRegistered = JSON.stringify(data.hooks.UserPromptSubmit);
for (const skill of REMINDERS) {
  if (alreadyRegistered.includes(`${skill}/hooks/reminder.sh`)) continue;
  const reminder = path.join(path.dirname(settingsPath), "skills", skill, "hooks", "reminder.sh");
  data.hooks.UserPromptSubmit.push({
    hooks: [{ type: "command", command: `${ABSOLUTE.bash} ${JSON.stringify(reminder)}` }],
  });
}

data.hooks.PreToolUse = data.hooks.PreToolUse || [];
if (!JSON.stringify(data.hooks.PreToolUse).includes("kvb-org-organize/scripts/council.py")) {
  const council = path.join(path.dirname(settingsPath), "skills", "kvb-org-organize", "scripts", "council.py");
  data.hooks.PreToolUse.push({
    matcher: "Edit|Write|MultiEdit|NotebookEdit",
    hooks: [{ type: "command", command: `${PYTHON} ${JSON.stringify(council)} gate` }],
  });
}

const SCRIPT_HOOKS = [
  ["kvb-org-organize/scripts/watch.py", "UserPromptSubmit", null, "watch", {}],
  ["kvb-org-radio/scripts/radio.py", "UserPromptSubmit", null, "hook", {}],
  ["kvb-org-radio/scripts/radio.py", "PostToolBatch", null, "tool", {}],
  ["kvb-org-radio/scripts/radio.py", "Stop", null, "listen", { asyncRewake: true, timeout: 21600 }],
  ["kvb-org-radio/scripts/radio.py", "Stop", null, "mailbox", {}],
  ["kvb-org-radio/scripts/radio.py", "PreToolUse", "Edit|Write|MultiEdit|NotebookEdit", "block", {}],
  ["kvb-org-organize/scripts/hooks.py", "PreToolUse", "Bash", "pre-bash", {}],
  ["kvb-org-organize/scripts/hooks.py", "PostToolUse", "Bash", "post-bash", {}],
  ["kvb-org-perform/scripts/log.py", "PreToolUse", "Agent|Task", "spawn", {}],
  ["kvb-agent-optimize/scripts/graph.py", "PreToolUse", "Read|Edit|Write|MultiEdit|NotebookEdit|Grep|Glob", "hook", { timeout: 30 }],
  ["kvb-org-organize/scripts/account.py", "SessionStart", null, "hook", {}],
];
const DISPATCHED = [
  ["kvb-org-organize/scripts/watch.py", "PostToolUse", "watch"],
  ["kvb-org-organize/scripts/watch.py", "PreToolUse", "block"],
  ["kvb-org-queue/scripts/queue.py", "PreToolUse", "block"],
  ["kvb-org-perform/scripts/log.py", "PostToolUse", "persist"],
];
const ran = (hook, script, sub) => String(hook.command).includes(script) && String(hook.command).endsWith(` ${sub}`);
for (const [script, event, sub] of DISPATCHED) {
  data.hooks[event] = (data.hooks[event] || [])
    .map((entry) => (Array.isArray(entry.hooks) ? { ...entry, hooks: entry.hooks.filter((hook) => !ran(hook, script, sub)) } : entry))
    .filter((entry) => !Array.isArray(entry.hooks) || entry.hooks.length > 0);
}
// Trip-wire: python3 recompiles the script it is started with on every call and caches only imported modules; loading it as __main__ by file path reuses its __pycache__.
const AS_MAIN = `'import importlib.util as u,sys;s=u.spec_from_file_location("__main__",sys.argv[1]);m=u.module_from_spec(s);sys.argv=sys.argv[1:];sys.modules["__main__"]=m;s.loader.exec_module(m)'`;
for (const [script, event, matcher, sub, extra] of SCRIPT_HOOKS) {
  data.hooks[event] = data.hooks[event] || [];
  const file = JSON.stringify(path.join(path.dirname(settingsPath), "skills", ...script.split("/")));
  // Trip-wire: python3 on a missing file exits 2, which blocks every prompt or tool call; the test makes it exit 1.
  const command = `[ -f ${file} ] && ${PYTHON} -c ${AS_MAIN} ${file} ${sub}`;
  const legacy = [`${PYTHON} ${file} ${sub}`, `[ -f ${file} ] && ${PYTHON} ${file} ${sub}`];
  const owner = data.hooks[event].find((entry) => (entry.hooks || []).some((hook) => ran(hook, script, sub)));
  if (owner) {
    const registered = owner.hooks.find((hook) => ran(hook, script, sub));
    if (legacy.includes(registered.command)) registered.command = command;
    if (owner.hooks.length === 1 && matcher) owner.matcher = matcher;
    continue;
  }
  const entry = { hooks: [{ type: "command", command, ...extra }] };
  data.hooks[event].push(matcher ? { matcher, ...entry } : entry);
}

fs.writeFileSync(settingsPath, JSON.stringify(data, null, 2) + "\n");
console.log(`skills: enabled the caveman and ponytail plugins (plugin skill copies dropped from this .claude), the ${REMINDERS.join(" + ")} reminders, the kvb-org-organize claim gate, resource watch and session account hook, the kvb-org-radio hooks, the kvb-org-perform log, the kvb-agent-optimize code graph hook, and one Bash hook dispatcher (radio, watch, queue, graph, log) per event in ${settingsPath}`);
