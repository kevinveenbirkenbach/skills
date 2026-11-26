#!/usr/bin/env node
"use strict";

const { edit } = require("./council-deny");

const GRAPH = /(^|\/)codebase-memory-mcp$/;
const NARROWED = { PreToolUse: "Grep|Glob" };
const DROPPED = { PostToolUse: "Read" };

const graphOnly = (entry) =>
  Array.isArray(entry.hooks) && entry.hooks.length > 0 && entry.hooks.every((hook) => GRAPH.test(String(hook.command || "").trim()));

/**
 * Narrow the hooks `codebase-memory-mcp install` registers.
 * @param {object} data settings; a PreToolUse entry running only the graph binary matches NARROWED, its PostToolUse
 *   Read entry goes, and of graph-only entries with one event and matcher the first stays, since every install adds
 *   its own entry again.
 * @returns {object} data, changed in place.
 */
function narrowGraphHooks(data) {
  const hooks = data.hooks || {};
  for (const [event, entries] of Object.entries(hooks)) {
    if (!Array.isArray(entries)) continue;
    const seen = new Set();
    hooks[event] = entries.filter((entry) => {
      if (!graphOnly(entry)) return true;
      if (NARROWED[event]) entry.matcher = NARROWED[event];
      if (DROPPED[event] === entry.matcher) return false;
      const key = String(entry.matcher);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  return data;
}

module.exports = { narrowGraphHooks };

if (require.main === module) {
  const settingsPath = process.argv[2];
  if (!settingsPath) {
    console.error("usage: graph-hooks.js <settings.json>");
    process.exit(2);
  }
  const code = edit(settingsPath, narrowGraphHooks);
  if (code === 0) console.log(`skills: the codebase-memory-mcp hooks in ${settingsPath} run on ${NARROWED.PreToolUse} only, none after Read`);
  process.exit(code);
}
