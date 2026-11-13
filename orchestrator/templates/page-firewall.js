  const FIREWALL_LISTS = {"permissions.allow": "Allow", "permissions.ask": "Ask", "permissions.deny": "Deny", "sandbox.filesystem.allowWrite": "Sandbox: write", "sandbox.filesystem.denyRead": "Sandbox: no read", "sandbox.network.allowedDomains": "Sandbox: domain"};
  const LIST_TONES = {allow: "ok", ask: "warn", deny: "bad"};
  const SETTINGS_RESULTS = {done: ["written", "ok"], refused: ["refused", "bad"], failed: ["failed", "bad"]};
  const EVERY_AGENT = "*";
  const TARGET_GONE = "gone";
  const TARGET_PICK = "";
  const SESSION_KEY = /^(?!-)[A-Za-z0-9_-]{1,128}$/;
  const firewall = {data: null, busy: false, staged: {}, dom: null, targets: new Set(), picks: {}};

  const knownAgents = () => Object.keys(people()).filter((key) => key !== HUMAN && SESSION_KEY.test(key)).sort();
  const firewallGroups = () => (firewall.data ? firewall.data.groups : []);
  const settingsFile = (path) => (firewall.data ? firewall.data.files.find((file) => file.path === path) : null);
  const everyAgent = (agents) => !agents || (agents.length === 1 && agents[0] === EVERY_AGENT);
  const groupOf = (agents) => firewallGroups().find((entry) => entry.members.join(",") === [...agents].sort().join(","));
  const firewallPickOf = (key) => (Object.hasOwn(firewall.picks, key) ? firewall.picks[key] : TARGET_PICK);

  function targetLabel(agents) {
    if (everyAgent(agents)) {
      return "all agents";
    }
    const group = groupOf(agents);
    return revealed(group ? `group ${group.name}` : agents.map(labelOf).join(", "));
  }

  const signedMembers = (agents) => agents.map((key) => `${labelOf(key)} (${key})`).join(", ");

  /**
   * @param {string[]} agents the session ids a payload is signed for.
   * @returns {string} the scope the passkey prompt names with every session id the signature covers: for all agents, for group X: A (s1), B (s2), for agent A (s1) or for agents A (s1), B (s2).
   */
  function scopeLabel(agents) {
    if (everyAgent(agents)) {
      return "for all agents";
    }
    const group = groupOf(agents);
    return group ? `for group ${group.name}: ${signedMembers(agents)}` : `for ${agents.length === 1 ? "agent" : "agents"} ${signedMembers(agents)}`;
  }

  /**
   * @param {Object} rule a rule as signed: kinds, tool, pattern, scope, expires in epoch seconds and agents.
   * @returns {string[]} the lines the passkey prompt shows for it: what it grants, in which directory, until when and for which sessions.
   */
  function ruleLines(rule) {
    const end = new Date(rule.expires * 1000).toISOString().slice(0, 16).replace("T", " ");
    const days = (Math.max(rule.expires - nowSeconds(), 0) / DAY).toFixed(1);
    return [`${rule.kinds.join(", ")}${rule.tool ? ` ${rule.tool}` : ""}: ${rule.pattern}`, `in ${rule.scope}`, `until ${end} UTC, in ${days} days`, scopeLabel(Object.hasOwn(rule, "agents") ? rule.agents : [EVERY_AGENT])];
  }

  /**
   * @param {string} label what the operator signs.
   * @param {Object} prepared the hub's offer: payload, the signed rule itself or an approval, and enables, the signed rule an approval turns on.
   * @returns {string} the passkey prompt's text, with every line of ruleLines() for the rule that takes effect, each line through revealed().
   */
  function promptText(label, prepared) {
    const rule = prepared.payload && prepared.payload.kind === "rule" ? prepared.payload : prepared.enables;
    return [label, ...(rule ? ruleLines(rule) : [])].map(revealed).join("\n");
  }

  const targetPill = (agents) => h("span", {class: "pill", "data-tone": "neutral", "data-agents": JSON.stringify(agents === undefined ? [EVERY_AGENT] : agents), title: "Applies to"}, targetLabel(agents));

  function targetOptions(keyed) {
    return [
      ...(keyed ? [h("option", {value: TARGET_PICK, disabled: true}, "Pick a target")] : []),
      h("option", {value: "all"}, "All agents"),
      ...knownAgents().map((key) => h("option", {value: `agent:${key}`}, revealed(`Agent ${labelOf(key)}`))),
      ...firewallGroups().map((group) => h("option", {value: `group:${group.id}`}, revealed(`Group ${group.name}`))),
    ];
  }

  function fillTargets(select) {
    const keyed = "targetKey" in select.dataset;
    const value = keyed ? firewallPickOf(select.dataset.targetKey) : select.value;
    select.replaceChildren(...targetOptions(keyed));
    const gone = value !== TARGET_PICK && ![...select.options].some((option) => option.value === value);
    if (gone) {
      select.append(h("option", {value: TARGET_GONE, disabled: true}, "Target gone: pick again"));
      select.value = TARGET_GONE;
    } else if (value !== TARGET_PICK || keyed) {
      select.value = value;
    }
    const waiting = keyed && value === TARGET_PICK;
    select.setCustomValidity(gone ? "The chosen group or agent is gone: pick the target again" : waiting ? "Pick a target first" : "");
    const scope = select.form || select.parentElement;
    for (const button of scope ? scope.querySelectorAll("[data-sign]") : []) {
      button.disabled = (gone || waiting) && !select.disabled;
    }
  }

  /**
   * @param {string} label the select's accessible name.
   * @param {string|null} key the rule set whose pick the page keeps across redraws, with no default until the operator picks; null for a select that starts on all agents.
   * @returns {HTMLSelectElement} the target select.
   */
  function targetSelect(label, key) {
    const select = h("select", {class: "field", "aria-label": label, "data-target-key": key});
    fillTargets(select);
    select.addEventListener("change", () => {
      if (key !== null) {
        firewall.picks[key] = select.value;
      }
      fillTargets(select);
    });
    firewall.targets.add(select);
    return select;
  }

  /**
   * @param {string} value the target select's value: all, agent:<session>, group:<id> or gone.
   * @returns {string[]|null} the sorted session ids the rule is signed for, ["*"] only for all, null for a gone or unknown target.
   */
  function agentsOf(value) {
    if (value.startsWith("agent:")) {
      return [value.slice("agent:".length)];
    }
    if (value.startsWith("group:")) {
      const group = firewallGroups().find((entry) => entry.id === value.slice("group:".length));
      return group ? group.members : null;
    }
    return value === "all" ? [EVERY_AGENT] : null;
  }

  /**
   * @param {string} kind the rule kind; a review rule always applies to every agent.
   * @param {string} value the target select's value.
   * @returns {string[]|null} the agents to sign; null for a group that is gone, which the hub refuses.
   */
  const ruleAgents = (kind, value) => (kind === "review" ? [EVERY_AGENT] : agentsOf(value));

  async function fetchFirewall() {
    if (firewall.busy) {
      return;
    }
    firewall.busy = true;
    try {
      const response = await fetch("/api/firewall", {cache: "no-store"});
      if (response.ok) {
        firewall.data = await response.json();
      }
    } catch {
      ui.offline = true;
    }
    firewall.busy = false;
    drawFirewall();
  }

  function drawFirewall() {
    const dom = firewall.dom;
    if (!dom || !dom.settings.isConnected) {
      return;
    }
    for (const select of [...firewall.targets]) {
      if (select.isConnected) {
        fillTargets(select);
      } else {
        firewall.targets.delete(select);
      }
    }
    for (const node of document.querySelectorAll("#main [data-agents]")) {
      node.textContent = targetLabel(JSON.parse(node.dataset.agents));
    }
    dom.groups.replaceChildren(groupsCard());
    dom.sets.replaceChildren(setsCard());
    dom.patterns.replaceChildren(patternsCard());
    dom.settings.replaceChildren(settingsCard());
  }

  function firewallSections() {
    firewall.dom = {groups: h("div", {}), sets: h("div", {}), patterns: h("div", {}), settings: h("div", {})};
    window.setTimeout(() => {
      drawFirewall();
      fetchFirewall();
    }, 0);
    return [firewall.dom.settings, firewall.dom.groups, firewall.dom.sets, firewall.dom.patterns];
  }

  async function firewallPost(path, payload, label) {
    const result = await sendJson(path, payload);
    toast(result.ok ? label : `${label}: not possible`, result.ok ? [] : fail(result), result.ok);
    await fetchFirewall();
    return result.ok;
  }

  function groupsCard() {
    const name = h("input", {class: "field", type: "text", placeholder: "builders", "aria-label": "Group name"});
    const members = h("select", {class: "field", multiple: true, size: Math.min(Math.max(knownAgents().length, 2), 6), "aria-label": "Members"}, knownAgents().map((key) => h("option", {value: key}, labelOf(key))));
    const form = h("form", {class: "fw-form", "aria-label": "New agent group"}, h("label", {}, "Name", name), h("label", {}, "Members", members),
      h("button", {type: "submit", class: "btn soft", ...named("Add group", "Add group: name the chosen agents as one rule target")}, icon("bi-people"), "Add group"));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const chosen = [...members.selectedOptions].map((option) => option.value).sort();
      await firewallPost("/api/firewall/groups", {name: name.value.trim(), members: chosen}, "Group added");
    });
    const rows = firewallGroups().map((group) => h("div", {class: "rule-row", "data-group": group.name}, h("strong", {}, revealed(group.name)), h("span", {class: "muted"}, revealed(group.members.map(labelOf).join(", "))), h("span", {class: "spacer"}),
      iconBtn("bi-trash3", "Delete group", "btn small danger", () => firewallPost(`/api/firewall/groups/${encodeURIComponent(group.id)}/delete`, {}, "Group deleted"), `Delete group ${group.name}: rules signed for it keep their agents`)));
    return h("section", {class: "card stack-tight", "aria-label": "Agent groups"}, h("h3", {}, "Agent groups"),
      h("p", {class: "muted"}, "A rule applies to one agent, a group or all agents. A group's members are signed into each rule when you sign it."),
      rows.length ? h("div", {class: "mini"}, rows) : h("p", {class: "muted"}, "No group yet."), form);
  }

  function setsCard() {
    const name = h("input", {class: "field", type: "text", placeholder: "ci", "aria-label": "Set name"});
    const days = h("input", {class: "field", type: "number", min: 1, max: 366, value: 7, "aria-label": "Days"});
    const chosen = h("select", {class: "field", multiple: true, size: Math.min(Math.max(state.rules.length, 2), 6), "aria-label": "Rules"}, state.rules.map((rule) => h("option", {value: rule.id}, `${rule.kind} ${rule.tool} ${rule.pattern}`.replace("  ", " "))));
    const form = h("form", {class: "fw-form", "aria-label": "New rule set"}, h("label", {}, "Name", name), h("label", {}, "Days", days), h("label", {}, "Rules", chosen),
      h("button", {type: "submit", class: "btn soft", ...named("Save set", "Save set: keep the chosen rules as one named rule set")}, icon("bi-collection"), "Save set"));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await firewallPost("/api/firewall/sets", {name: name.value.trim(), days: Number(days.value), rules: [...chosen.selectedOptions].map((option) => option.value)}, "Rule set saved");
    });
    const sets = firewall.data ? firewall.data.sets : [];
    const rows = sets.map((set) => setRow(set));
    return h("section", {class: "card stack-tight", "aria-label": "Rule sets"}, h("h3", {}, "Rule sets"),
      h("p", {class: "muted"}, "Take a set over as a whole for one agent, a group or all agents: each of its rules is signed with your passkey for that target."),
      rows.length ? h("div", {class: "mini"}, rows) : h("p", {class: "muted"}, "No rule set yet."), form);
  }

  function setRow(set) {
    const target = targetSelect(`Take over ${set.name} for`, set.id);
    const take = h("button", {type: "button", class: "btn small soft", "data-sign": "", ...named("Take over", `Take over: sign the ${set.rules.length} rules of ${set.name} for the chosen agents`)}, icon("bi-box-arrow-in-down"), "Take over");
    take.addEventListener("click", async () => {
      take.disabled = true;
      await takeOver(set, agentsOf(target.value));
      fillTargets(target);
    });
    const row = h("div", {class: "rule-row", "data-set": set.name}, h("strong", {}, revealed(set.name)), h("span", {class: "muted"}, `${set.rules.length} rules, ${set.days} days`), h("span", {class: "spacer"}), target, take,
      iconBtn("bi-trash3", "Delete set", "btn small danger", () => firewallPost(`/api/firewall/sets/${encodeURIComponent(set.id)}/delete`, {}, "Rule set deleted"), `Delete set ${set.name}: its signed rules stay`));
    fillTargets(target);
    return row;
  }

  /**
   * @param {Object} set the rule set to take over: name, days and rules.
   * @param {string[]|null} agents the target from agentsOf().
   */
  async function takeOver(set, agents) {
    if (!agents) {
      toast(`${set.name}: not taken over`, ["No target picked, or the picked group or agent is gone"], false);
      return;
    }
    const expires = Math.floor(nowSeconds()) + set.days * DAY;
    let created = 0;
    for (const rule of set.rules) {
      const prepared = await sendJson("/api/rules/sign", {...rule, expires, agents: rule.kind === "review" ? [EVERY_AGENT] : agents});
      const signed = prepared.ok && prepared.data ? await assertion(prepared.data, `Rule set ${set.name}`) : null;
      const result = signed ? await sendJson("/api/rules", {rule: prepared.data.payload, assertion: signed, enabled: true}) : prepared;
      created += signed && result.ok ? 1 : 0;
    }
    toast(`${set.name}: ${created} of ${set.rules.length} rules signed for ${targetLabel(agents)}`, [], created === set.rules.length);
    await load();
  }

  function patternsCard() {
    const patterns = firewall.data ? firewall.data.patterns : [];
    return h("section", {class: "card stack-tight", "aria-label": "Never granted"}, h("h3", {}, "Never granted by a rule"),
      h("p", {class: "muted"}, "An ask rule never grants a command that matches one of these patterns; Claude Code asks instead."),
      h("ul", {class: "mini fw-patterns"}, patterns.map((pattern) => h("li", {}, h("div", {class: "row"}, pill(pattern.label, "bad"), h("code", {}, pattern.pattern))))));
  }

  function stageChange(path, change) {
    const changes = (firewall.staged[path] || []).filter((entry) => !(entry.list === change.list && entry.entry === change.entry));
    firewall.staged[path] = [...changes, change];
    drawFirewall();
  }

  function unstageChange(path, change) {
    firewall.staged[path] = (firewall.staged[path] || []).filter((entry) => entry !== change);
    if (!firewall.staged[path].length) {
      delete firewall.staged[path];
    }
    drawFirewall();
  }

  function entryRow(path, list, entry) {
    const last = list.split(".").pop();
    const tone = Object.hasOwn(LIST_TONES, last) ? LIST_TONES[last] : "neutral";
    const editable = Object.hasOwn(FIREWALL_LISTS, list);
    return h("li", {"data-entry": entry, "data-list": list}, h("div", {class: "row"}, pill(FIREWALL_LISTS[list] || list, tone), h("code", {}, revealed(entry)), h("span", {class: "spacer"}),
      editable ? iconBtn("bi-dash-circle", "Remove", "btn small ghost", () => stageChange(path, {list, op: "remove", entry}), `Remove: stage the removal of ${revealed(entry)} from ${list}`) : null));
  }

  function fileCard(file) {
    const groups = file.groups.map((group) => h("details", {class: "fw-group", open: true, "data-tool": group.tool, "data-prefix": group.prefix},
      h("summary", {}, h("strong", {}, group.tool), group.prefix ? h("code", {}, group.prefix) : null, counter(group.entries.length)),
      h("ul", {class: "mini"}, group.entries.map((entry) => entryRow(file.path, `permissions.${entry.list}`, entry.entry)))));
    const sandbox = file.sandbox.map((entry) => (entry.values
      ? h("details", {class: "fw-group", "data-key": entry.key}, h("summary", {}, h("strong", {}, entry.key), counter(entry.values.length)), h("ul", {class: "mini"}, entry.values.map((value) => entryRow(file.path, entry.key, value))))
      : h("div", {class: "rule-row", "data-key": entry.key}, h("strong", {}, entry.key), h("code", {}, JSON.stringify(entry.value)))));
    const status = file.error ? pill(file.error, "bad") : file.exists ? pill(`sha256 ${file.sha256.slice(0, 12)}`, "neutral") : pill("missing: a change creates it", "warn");
    return h("section", {class: "fw-file", "data-file": file.path, "aria-label": file.path}, h("div", {class: "row"}, h("code", {class: "fw-path"}, file.path), status),
      groups.length ? groups : h("p", {class: "muted"}, "No permission entries."), sandbox.length ? h("h4", {}, "Sandbox") : null, sandbox);
  }

  function addForm(files) {
    const file = h("select", {class: "field", "aria-label": "Settings file"}, files.map((entry) => h("option", {value: entry.path}, entry.path)));
    const list = h("select", {class: "field", "aria-label": "List"}, Object.entries(FIREWALL_LISTS).map(([value, label]) => h("option", {value}, `${label} (${value})`)));
    const entry = h("input", {class: "field", type: "text", placeholder: "Bash(make test:*)", "aria-label": "Entry"});
    const form = h("form", {class: "fw-form", "aria-label": "Stage a settings change"}, h("label", {}, "File", file), h("label", {}, "List", list), h("label", {}, "Entry", entry),
      h("button", {type: "submit", class: "btn soft", ...named("Stage", "Stage: add the entry to the list; nothing is written before you sign")}, icon("bi-plus-lg"), "Stage"));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (entry.value.trim()) {
        stageChange(file.value, {list: list.value, op: "add", entry: entry.value.trim()});
      }
    });
    return form;
  }

  const settingsItems = () => Object.entries(firewall.staged).filter(([file]) => settingsFile(file)).map(([file, changes]) => ({kind: "settings", file, base: settingsFile(file).sha256, changes}));

  function stagedList() {
    const rows = Object.entries(firewall.staged).flatMap(([path, changes]) => changes.map((change) => h("li", {"data-staged": `${change.op} ${change.entry}`}, h("div", {class: "row"},
      pill(change.op === "add" ? "add" : "remove", change.op === "add" ? "ok" : "bad"), h("code", {}, revealed(`${change.list}: ${change.entry}`)), h("span", {class: "muted"}, revealed(path)), h("span", {class: "spacer"}),
      iconBtn("bi-x-circle", "Unstage", "btn small ghost", () => unstageChange(path, change), "Unstage: drop this change")))));
    if (!rows.length) {
      return h("p", {class: "muted"}, "No staged change.");
    }
    const review = h("button", {type: "button", class: "btn primary", ...named("Review and sign", "Review and sign: show the diff, then sign it with your passkey")}, icon("bi-file-diff"), "Review and sign");
    review.addEventListener("click", reviewSettings);
    return h("div", {class: "stack-tight"}, h("ul", {class: "mini", "aria-label": "Staged changes"}, rows), h("div", {class: "actions"}, review));
  }

  function settingsCard() {
    const data = firewall.data;
    if (!data) {
      return h("section", {class: "card"}, h("p", {class: "muted"}, "Loading the settings …"));
    }
    const files = data.files;
    return h("section", {class: "card stack-tight", "aria-label": "Claude settings"}, h("h3", {}, "Claude settings"),
      h("p", {class: "muted"}, "Permissions and sandbox entries of the listed settings files, grouped by tool and prefix as the host read them. A change shows as a diff, is signed with your passkey and is written by the host, never by an agent."),
      data.error ? h("p", {class: "muted"}, data.error) : null,
      files.map(fileCard), files.length ? addForm(files) : null, stagedList());
  }

  function diffLines(text) {
    return h("pre", {class: "fw-diff"}, text.split("\n").map((line) => h("span", {class: line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : null}, `${revealed(line)}\n`)));
  }

  async function reviewSettings() {
    const items = settingsItems();
    const preview = await sendJson("/api/firewall/preview", {items});
    if (!preview.ok || !preview.data) {
      toast("Settings: not possible", fail(preview), false);
      await fetchFirewall();
      return;
    }
    const outcome = h("div", {class: "mini", "aria-live": "polite"});
    const confirm = h("button", {type: "button", class: "btn primary", ...named("Sign and apply", "Sign and apply: hand exactly this diff to the host with your passkey signature")}, icon("bi-pen"), "Sign and apply");
    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      if (!await applySettings(items, outcome)) {
        confirm.disabled = false;
      }
    });
    openSheet("Settings change", [
      h("p", {class: "muted"}, "The host writer checks your signature, refuses a file that changed since and writes exactly this change; it keeps every other key and a backup beside the file."),
      h("div", {class: "stack-tight", "aria-label": "Diff"}, preview.data.diffs.map((entry) => h("div", {"data-diff": entry.file}, h("code", {}, revealed(entry.file)), diffLines(entry.diff)))),
      outcome,
      h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), confirm),
    ], true);
  }

  async function applySettings(items, outcome) {
    const signed = await proofFor(items, "Settings");
    if (signed === null) {
      outcome.replaceChildren(h("p", {class: "muted"}, "Not signed: nothing was handed over."));
      return false;
    }
    const result = await sendJson("/api/firewall/settings", {items, proof: signed.proof});
    if (!result.ok || !result.data) {
      toast("Settings: not possible", fail(result), false);
      outcome.replaceChildren(h("p", {class: "muted"}, `${result.status} ${result.text}`.trim()));
      return false;
    }
    outcome.replaceChildren(h("p", {class: "muted", "data-firewall": result.data.id}, `Signed and handed to the host (job ${result.data.id}); the firewall unit writes now.`));
    followJob(`/api/firewall/settings/${encodeURIComponent(result.data.id)}`, outcome, Date.now(), (data) => {
      const {good, lines} = showJob(data, outcome, "file", SETTINGS_RESULTS);
      toast(`Settings: ${good ? "written" : "not everything written"}`, lines, good);
      if (good) {
        firewall.staged = {};
      }
      fetchFirewall();
    });
    return true;
  }
