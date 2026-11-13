#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const COUNCIL_DENY = ["Edit(~/.claude/agents-council/**)", "Edit(~/.local/state/agents-council/**)"];

function withCouncilDeny(data) {
  data.permissions = data.permissions || {};
  data.permissions.deny = [...new Set([...(data.permissions.deny || []), ...COUNCIL_DENY])];
  return data;
}

module.exports = { COUNCIL_DENY, withCouncilDeny };

function resolved(settingsPath) {
  let link;
  try {
    link = fs.lstatSync(settingsPath).isSymbolicLink();
  } catch (err) {
    if (err.code === "ENOENT") return settingsPath;
    throw err;
  }
  if (!link) return settingsPath;
  if (fs.existsSync(settingsPath)) return fs.realpathSync(settingsPath);
  return path.resolve(path.dirname(settingsPath), fs.readlinkSync(settingsPath));
}

function main(settingsPath) {
  if (!settingsPath) {
    console.error("usage: council-deny.js <settings.json>");
    return 2;
  }
  const target = resolved(settingsPath);
  let data = {};
  let mode = 0o600;
  if (fs.existsSync(target)) {
    mode = fs.statSync(target).mode & 0o777;
    const raw = fs.readFileSync(target, "utf8").trim();
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch (err) {
        console.error(`skills: ${settingsPath} is not valid JSON; leaving it untouched (${err.message}).`);
        return 1;
      }
    }
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    console.error(`skills: ${settingsPath} holds no JSON object; leaving it untouched.`);
    return 1;
  }
  const temporary = `${target}.${process.pid}`;
  try {
    fs.writeFileSync(temporary, JSON.stringify(withCouncilDeny(data), null, 2) + "\n", { mode, flag: "wx" });
    fs.chmodSync(temporary, mode);
    fs.renameSync(temporary, target);
  } catch (err) {
    fs.rmSync(temporary, { force: true });
    throw err;
  }
  console.log(`skills: Edit and Write on ${COUNCIL_DENY.length} council paths denied in ${settingsPath}`);
  return 0;
}

if (require.main === module) process.exit(main(process.argv[2]));
