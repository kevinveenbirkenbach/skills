  const FIREWALL_LISTS = {"permissions.allow": "Allow", "permissions.ask": "Ask", "permissions.deny": "Deny", "sandbox.filesystem.allowWrite": "Sandbox: write", "sandbox.filesystem.denyRead": "Sandbox: no read", "sandbox.network.allowedDomains": "Sandbox: domain"};
  const LIST_TONES = {allow: "ok", ask: "warn", deny: "bad"};
  const ROW_FILTERS = [["allow", "Allow"], ["ask", "Ask"], ["deny", "Deny"], ["sandbox", "Sandbox"], ["signed", "Signed"]];
  const ACTION_ORDER = ["deny", "ask", "allow", "sandbox", "signed"];
  const ENTRY_HINTS = {
    allow: "Claude Code runs a matching call without asking, so it never reaches the ask ledger.",
    ask: "Claude Code asks before a matching call; the ask reaches the Agent Orchestrator.",
    deny: "Claude Code refuses a matching call, so it never reaches the ask ledger.",
    sandbox: "Bounds what a sandboxed command may write, read or reach.",
  };
  const HUB_SOURCE = "hub";
  const SETTINGS_RESULTS = {done: ["written", "ok"], refused: ["refused", "bad"], failed: ["failed", "bad"]};
  const EVERY_AGENT = "*";
  const TARGET_GONE = "gone";
  const TARGET_PICK = "";
  const SESSION_KEY = /^(?!-)[A-Za-z0-9_-]{1,128}$/;
  const CONTROL_TABS = [["tools", "Tools", "bi-plug"], ["rules", "Rules", "bi-shield-lock"], ["groups", "Groups", "bi-people"], ["schedules", "Schedules", "bi-clock"]];
  const CAPABILITY_WORDS = {deniedMcpServers: ["Unblock server", "Block server"], enabledPlugins: ["Enable plugin", "Disable plugin"], switches: ["Turn on", "Turn off"]};
  const TOOL_HINTS = {
    deniedMcpServers: "Off blocks the server before it loads, in every session and project.",
    enabledPlugins: "Off disables the plugin with its skills, hooks and servers.",
    switches: "Built-in features of Claude Code.",
  };
  const SWITCH_TITLES = {enableArtifact: "Artifacts"};
  const OTHER_OP = {add: "remove", remove: "add"};
  const firewall = {data: null, busy: false, staged: {}, dom: null, targets: new Set(), picks: {}, shown: new Set(ROW_FILTERS.map(([id]) => id)), open: new Set(), tab: CONTROL_TABS[0][0], missing: false};

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
    dom.tools.replaceChildren(toolsCard());
    const count = Object.values(firewall.staged).reduce((sum, changes) => sum + changes.length, 0);
    dom.bar.hidden = !count;
    dom.bar.replaceChildren(...(count ? applyBar(count) : []));
  }

  function firewallSections() {
    firewall.dom = {tools: h("div", {}), groups: h("div", {}), sets: h("div", {}), patterns: h("div", {}), settings: h("div", {}), bar: h("div", {class: "apply-bar", role: "region", "aria-label": "Apply changes", hidden: true})};
    window.setTimeout(() => {
      drawFirewall();
      fetchFirewall();
    }, 0);
    return firewall.dom;
  }

  /**
   * @param {Object} panels per tab of CONTROL_TABS the nodes it shows.
   * @param {HTMLElement} bar the Apply bar every tab shares.
   * @returns {HTMLElement} the Controls screen: title, tab list, one panel per tab, only the chosen one shown, and the bar.
   */
  function controlsPage(panels, bar) {
    if (ui.views.rules === "schedules") {
      firewall.tab = "schedules";
      ui.views.rules = null;
    }
    const views = {};
    const tabs = {};
    const pick = (id) => {
      firewall.tab = id;
      window.history.replaceState(null, "", Nav.hashOf("rules", id === "schedules" ? id : null));
      for (const [key, tab] of Object.entries(tabs)) {
        tab.setAttribute("aria-selected", String(key === id));
        views[key].hidden = key !== id;
      }
    };
    for (const [id, label, glyph] of CONTROL_TABS) {
      tabs[id] = h("button", {type: "button", role: "tab", id: `controls-tab-${id}`, "data-tab": id, "aria-controls": `controls-${id}`, "aria-selected": String(firewall.tab === id), on: {click: () => pick(id)}}, icon(glyph), label);
      views[id] = h("div", {class: "stack", role: "tabpanel", id: `controls-${id}`, "aria-labelledby": `controls-tab-${id}`, hidden: firewall.tab !== id}, panels[id]);
    }
    return h("div", {class: "stack fw-controls"}, boxHead("Controls", "", h("h2", {class: "box-title"}, "Controls"), h("div", {class: "segmented", role: "tablist", "aria-label": "Controls"}, Object.values(tabs))), Object.values(views), bar);
  }

  async function firewallPost(path, payload, label) {
    const result = await sendJson(path, payload);
    toast(result.ok ? label : `${label}: not possible`, result.ok ? [] : fail(result), result.ok);
    await fetchFirewall();
    return result.ok;
  }

  /**
   * @param {string} label the field's name, shown above the chips.
   * @param {Array} items [value, text, leading node or null] per chip.
   * @param {HTMLElement|null} empty what the field shows when items is empty.
   * @returns {Object} {node, chosen}: the field and a reader of the checked values.
   */
  function checkChips(label, items, empty) {
    const boxes = items.map(([value, text, lead]) => ({value, box: h("input", {type: "checkbox", value}), text, lead}));
    const node = h("div", {class: "fw-chips-field"}, h("span", {class: "fw-chips-label"}, label), items.length
      ? h("div", {class: "chips check-chips", role: "group", "aria-label": label}, boxes.map(({box, text, lead}) => h("label", {class: "chip check-chip"}, box, lead, h("span", {}, text))))
      : empty);
    return {node, chosen: () => boxes.filter(({box}) => box.checked).map(({value}) => value)};
  }

  function groupsCard() {
    const name = h("input", {class: "field", type: "text", placeholder: "builders", "aria-label": "Group name"});
    const members = checkChips("Members", knownAgents().map((key) => [key, labelOf(key), face(key, false)]), h("p", {class: "muted"}, "No agent known yet: agents appear once they post or claim work."));
    const form = h("form", {class: "fw-form", "aria-label": "New agent group"}, h("label", {}, "Name", name), members.node,
      h("button", {type: "submit", class: "btn soft", ...named("Add group", "Add group: name the chosen agents as one rule target")}, icon("bi-people"), "Add group"));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await firewallPost("/api/firewall/groups", {name: name.value.trim(), members: members.chosen().sort()}, "Group added");
    });
    const rows = firewallGroups().map((group) => h("div", {class: "rule-row", "data-group": group.name}, h("strong", {}, revealed(group.name)), h("span", {class: "muted"}, revealed(group.members.map(labelOf).join(", "))), h("span", {class: "spacer"}),
      iconBtn("bi-trash3", "Delete group", "btn small danger", () => firewallPost(`/api/firewall/groups/${encodeURIComponent(group.id)}/delete`, {}, "Group deleted"), revealed(`Delete group ${group.name}: rules signed for it keep their agents`))));
    return h("section", {class: "card stack-tight", "aria-label": "Agent groups"}, h("h3", {}, "Agent groups"),
      h("p", {class: "muted"}, "A rule applies to one agent, a group or all agents. A group's members are signed into each rule when you sign it."),
      rows.length ? h("div", {class: "mini"}, rows) : h("p", {class: "muted"}, "No group yet."), form);
  }

  function setsCard() {
    const name = h("input", {class: "field", type: "text", placeholder: "ci", "aria-label": "Set name"});
    const days = h("input", {class: "field", type: "number", min: 1, max: 366, value: 7, "aria-label": "Days"});
    const chosen = checkChips("Rules", state.rules.map((rule) => [rule.id, revealed(`${rule.kind} ${rule.tool} ${rule.pattern}`.replace("  ", " ")), null]),
      h("p", {class: "muted"}, "No rule yet: create one under Rules, New hub rule for automatic grants, then pick it here."));
    const form = h("form", {class: "fw-form", "aria-label": "New rule set"}, h("label", {}, "Name", name), h("label", {}, "Days", days), chosen.node,
      h("button", {type: "submit", class: "btn soft", ...named("Save set", "Save set: keep the chosen rules as one named rule set")}, icon("bi-collection"), "Save set"));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await firewallPost("/api/firewall/sets", {name: name.value.trim(), days: Number(days.value), rules: chosen.chosen()}, "Rule set saved");
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
      iconBtn("bi-trash3", "Delete set", "btn small danger", () => firewallPost(`/api/firewall/sets/${encodeURIComponent(set.id)}/delete`, {}, "Rule set deleted"), revealed(`Delete set ${set.name}: its signed rules stay`)));
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

  /**
   * @param {Object} file a settings file as /api/firewall lists it.
   * @returns {Object[]} one row per permissions entry and sandbox value: filter, action, tone, tool, pattern, list, entry (null for a sandbox value no list holds), hits and never.
   */
  function fileRows(file) {
    const permissions = file.groups.flatMap((group) => group.entries.map((entry) => ({filter: entry.list, action: FIREWALL_LISTS[`permissions.${entry.list}`], tone: LIST_TONES[entry.list], tool: group.tool, pattern: entry.spec, list: `permissions.${entry.list}`, entry: entry.entry, hits: entry.hits, never: entry.never})));
    const sandbox = file.sandbox.flatMap((entry) => {
      const base = {filter: "sandbox", action: FIREWALL_LISTS[entry.key] || "Sandbox", tone: "info", tool: entry.key.replace(/^sandbox\./, ""), list: entry.key, hits: null, never: ""};
      return entry.values ? entry.values.map((value) => ({...base, pattern: value, entry: value})) : [{...base, pattern: JSON.stringify(entry.value), entry: null}];
    });
    return [...permissions, ...sandbox];
  }

  /**
   * @returns {Object[]} one row per stored hub rule, with the hits /api/firewall counted for it; pending until the next fetch counts a new rule.
   */
  function signedRows() {
    const counted = firewall.data.rules;
    return state.rules.map((rule) => ({filter: "signed", action: `Grant ${rule.kind}`, tone: "ok", tool: rule.tool, pattern: rule.pattern, rule, ...(Object.hasOwn(counted, rule.id) ? counted[rule.id] : {hits: null, never: "", pending: true})}));
  }

  const fileStatus = (file) => (file.error ? pill(file.error, "bad") : file.exists ? pill(`sha256 ${file.sha256.slice(0, 12)}`, "neutral") : pill("missing: a change creates it", "warn"));
  const byAction = (one, two) => ACTION_ORDER.indexOf(one.filter) - ACTION_ORDER.indexOf(two.filter);

  function sourceGroups() {
    return [{id: HUB_SOURCE, label: "Hub rules", file: false, status: null, rows: signedRows()}, ...SettingsFiles.listed(firewall.data.files, firewall.missing).shown.map((file) => ({id: file.path, label: file.path, file: true, status: fileStatus(file), rows: fileRows(file)}))];
  }

  function hitsCell(row) {
    if (row.pending) {
      return h("span", {class: "muted", title: "Counted with the next refresh"}, "…");
    }
    if (row.never) {
      return h("span", {class: "muted", title: `The matcher never grants a command that ${row.never}`}, `never granted: ${row.never}`);
    }
    if (row.hits === null) {
      return h("span", {class: "muted", title: "Only asks reach the ledger the hits come from"}, "not seen");
    }
    return row.hits ? h("strong", {}, String(row.hits)) : ["0 ", h("span", {class: "pill", "data-tone": "warn", title: "No ask of the counted days matched this entry"}, "unused")];
  }

  function actionCell(row) {
    const rule = row.rule;
    const action = h("span", {class: "pill", "data-tone": row.tone, title: rule ? RULE_HINTS[rule.kind] : ENTRY_HINTS[row.filter]}, row.action);
    if (!rule) {
      return action;
    }
    const until = `until ${absolute.format(stampOf(rule.expires))}`;
    return [action, rule.expires <= nowSeconds() ? pill("expired", "bad") : null, h("span", {class: "pill", "data-tone": rule.enabled ? "ok" : "neutral", title: until}, rule.enabled ? "active" : "off")];
  }

  function changeCell(group, row) {
    const rule = row.rule;
    if (rule) {
      return [btn(rule.enabled ? "Turn off" : "Turn on", "btn small", () => changeRule(rule, rule.enabled ? "disable" : "enable")), btn("Delete", "btn small danger", () => {
        if (window.confirm("Delete rule?")) {
          changeRule(rule, "delete");
        }
      })];
    }
    const editable = row.entry !== null && Object.hasOwn(FIREWALL_LISTS, row.list);
    return editable ? iconBtn("bi-dash-circle", "Remove", "btn small ghost", () => stageChange(group.id, {list: row.list, op: "remove", entry: row.entry}), `Remove: stage the removal of ${revealed(row.entry)} from ${row.list}`) : null;
  }

  /**
   * @param {Object} group the source the row belongs to: id, label and file, false for the hub rules.
   * @param {Object} row a row of fileRows() or signedRows().
   * @returns {HTMLTableRowElement} the row: action, tool, pattern, scope, source, hits and its change buttons.
   */
  function ruleRow(group, row) {
    const rule = row.rule;
    const pattern = [h("code", {}, revealed(row.pattern)), rule && rule.kind !== "decision" ? h("span", {class: "muted"}, " in ", h("code", {}, rule.scope ? revealed(rule.scope) : "–")) : null];
    const source = rule ? h("span", {class: "muted"}, rule.signed ? "Hub, passkey-signed" : "Hub, unsigned: has no effect") : h("code", {class: "fw-path"}, revealed(group.label));
    return h("tr", {"data-filter": row.filter, "data-list": row.list, "data-entry": row.entry, "data-rule": rule ? rule.id : null, "data-unused": row.hits === 0},
      h("td", {}, actionCell(row)), h("td", {}, row.tool ? h("code", {}, revealed(row.tool)) : "–"), h("td", {}, pattern),
      h("td", {}, rule ? targetPill(rule.agents) : h("span", {class: "muted"}, "file")), h("td", {}, source),
      h("td", {class: "fw-hits"}, hitsCell(row)), h("td", {class: "fw-change"}, changeCell(group, row)));
  }

  function sourceBody(group) {
    const rows = group.rows.filter((row) => firewall.shown.has(row.filter)).sort(byAction);
    if (!rows.length && group.rows.length) {
      return null;
    }
    const open = firewall.open.has(group.id);
    const unused = rows.filter((row) => row.hits === 0).length;
    const fold = h("button", {type: "button", class: "fw-fold", "aria-expanded": String(open), on: {click: () => {
      if (open) {
        firewall.open.delete(group.id);
      } else {
        firewall.open.add(group.id);
      }
      drawFirewall();
    }}}, icon(open ? "bi-chevron-down" : "bi-chevron-right"), group.file ? h("code", {class: "fw-path"}, revealed(group.label)) : h("strong", {}, group.label), counter(rows.length), unused ? pill(`${unused} unused`, "warn") : null);
    return h("tbody", {"data-source": group.id}, h("tr", {class: "fw-source"}, h("th", {colspan: 7, scope: "rowgroup"}, h("div", {class: "row"}, fold, group.status))), open ? rows.map((row) => ruleRow(group, row)) : []);
  }

  function filterChips() {
    return h("div", {class: "chips", role: "group", "aria-label": "Show rules"}, ROW_FILTERS.map(([id, label]) => h("button", {type: "button", class: "chip", "data-filter": id, "aria-pressed": String(firewall.shown.has(id)), on: {click: () => {
      if (firewall.shown.has(id)) {
        firewall.shown.delete(id);
      } else {
        firewall.shown.add(id);
      }
      drawFirewall();
    }}}, label)));
  }

  function ruleTable() {
    const bodies = sourceGroups().map(sourceBody).filter(Boolean);
    if (!bodies.length) {
      return h("p", {class: "muted"}, "No rule matches the chosen chips.");
    }
    const head = h("thead", {}, h("tr", {}, ["Action", "Tool", "Pattern", "Scope", "Source", `Hits (${firewall.data.days} days)`].map((label) => h("th", {scope: "col"}, label)), h("th", {scope: "col", "aria-label": "Change"})));
    return h("div", {class: "fw-table-wrap"}, h("table", {class: "fw-table", "aria-label": "Firewall rules"}, head, bodies));
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

  const turnsOn = (change) => (change.list === "deniedMcpServers") !== (change.op === "add");
  const stagedOf = (path, list, entry) => (firewall.staged[path] || []).find((change) => change.list === list && change.entry === entry);

  /**
   * @param {Object} change a staged change.
   * @returns {Array} its pill and text: on or off with Block server x, Enable plugin y or Turn off Artifacts for a tool, add or remove with list: entry otherwise.
   */
  function stagedWords(change) {
    const words = CAPABILITY_WORDS[change.list];
    if (!words) {
      return [pill(change.op, change.op === "add" ? "ok" : "bad"), `${change.list}: ${change.entry}`];
    }
    const on = turnsOn(change);
    return [pill(on ? "on" : "off", on ? "ok" : "bad"), `${words[on ? 0 : 1]} ${SWITCH_TITLES[change.entry] || change.entry}`];
  }

  function stagedList() {
    return h("ul", {class: "mini", "aria-label": "Staged changes"}, Object.entries(firewall.staged).flatMap(([path, changes]) => changes.map((change) => {
      const [state, words] = stagedWords(change);
      return h("li", {"data-staged": `${change.op} ${change.entry}`}, h("div", {class: "row"}, state, h("code", {}, revealed(words)), h("span", {class: "muted fw-path"}, revealed(path)), settingsFile(path) ? null : pill("file gone: not applied", "bad"), h("span", {class: "spacer"}),
        iconBtn("bi-x-circle", "Unstage", "btn small ghost", () => unstageChange(path, change), "Unstage: drop this change")));
    })));
  }

  /**
   * @param {number} count how many changes are staged, at least one.
   * @returns {HTMLElement[]} the bar's content: the folded list of staged changes, Discard and Apply, which shows the diff of the changes to a listed file and signs it.
   */
  function applyBar(count) {
    const ready = settingsItems().reduce((sum, item) => sum + item.changes.length, 0);
    const apply = h("button", {type: "button", class: "btn primary", "data-apply": "", disabled: !ready, title: "Apply: show the diff of every staged change to a listed file, then sign it with your passkey", on: {click: reviewSettings}}, icon("bi-send-check"), `Apply (${ready})`);
    const discard = iconBtn("bi-arrow-counterclockwise", "Discard", "btn ghost", () => {
      firewall.staged = {};
      drawFirewall();
    }, "Discard: drop every staged change");
    return [h("details", {class: "apply-list"}, h("summary", {}, `${count} staged ${count === 1 ? "change" : "changes"}`), stagedList()), h("span", {class: "spacer"}), discard, apply];
  }

  /**
   * @param {string} path the settings file the tools live in.
   * @param {Object} group a tools group: list, label, off (the op that turns a row off) and rows.
   * @param {Object} row one server, plugin or switch: name, on as the host read it, and overrides, each other settings file that sets it differently as {file, on}.
   * @returns {HTMLElement} the row with a pill per override and a switch that stages the flip, or drops the staged flip to turn it back.
   */
  function toolRow(path, group, row) {
    const staged = stagedOf(path, group.list, row.name);
    const on = staged ? turnsOn(staged) : row.on;
    const title = SWITCH_TITLES[row.name] || row.name;
    const flip = () => (staged ? unstageChange(path, staged) : stageChange(path, {list: group.list, op: row.on ? group.off : OTHER_OP[group.off], entry: row.name}));
    const overrides = row.overrides.map((other) => h("span", {class: "pill", "data-tone": "warn", "data-override": other.file, title: revealed(`${other.file} sets it ${other.on ? "on" : "off"}, which wins in that repository`)},
      `${other.on ? "on" : "off"} in ${revealed(other.file.split("/").slice(-3, -2)[0] || other.file)}`));
    return h("label", {class: "tool-row", "data-tool": row.name, "data-on": String(on), "data-staged": staged ? "" : null},
      h("span", {class: "tool-name"}, revealed(title)), overrides, staged ? pill("staged", "warn") : null, h("span", {class: "spacer"}),
      h("input", {type: "checkbox", role: "switch", class: "switch", checked: on, "aria-label": title, on: {change: flip}}));
  }

  function blockForm(path) {
    const name = h("input", {class: "field", type: "text", placeholder: "plugin:name:server", "aria-label": "Server name"});
    const form = h("form", {class: "tool-add", "aria-label": "Block another MCP server"}, name,
      h("button", {type: "submit", class: "btn soft", ...named("Block", "Block: stage a deny rule for this server name; Apply signs it")}, icon("bi-slash-circle"), "Block"));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (name.value.trim()) {
        stageChange(path, {list: "deniedMcpServers", op: "add", entry: name.value.trim()});
      }
    });
    return form;
  }

  function toolsCard() {
    const data = firewall.data;
    const tools = data ? data.tools : null;
    if (!tools) {
      return h("section", {class: "card"}, h("p", {class: "muted"}, !data ? "Loading the tools …" : data.error ? data.error : "The host view marks no ~/.claude/settings.json yet: the kvb-orchestrator-firewall unit writes it with its next run."));
    }
    const groups = tools.groups.map((group) => h("div", {class: "tool-group", "data-list": group.list}, h("h4", {}, group.label), h("p", {class: "muted"}, TOOL_HINTS[group.list]),
      group.rows.length ? h("div", {class: "tool-rows"}, group.rows.map((row) => toolRow(tools.file, group, row))) : h("p", {class: "muted"}, "None known."),
      group.list === "deniedMcpServers" ? blockForm(tools.file) : null));
    return h("section", {class: "card stack-tight", "aria-label": "Tools"}, h("h3", {}, "Tools"),
      h("p", {class: "muted"}, "What every agent session may load, as ~/.claude/settings.json sets it. A pill names a repository whose settings set it differently, which wins there; a .claude/settings.local.json stays unseen. A switch only stages; Apply shows the diff, you sign it with your passkey and the host writes it. Each session picks it up at its next start."),
      tools.error ? pill(tools.error, "bad") : null, h("div", {class: "tool-groups"}, groups));
  }

  function settingsCard() {
    const data = firewall.data;
    if (!data) {
      return h("section", {class: "card"}, h("p", {class: "muted"}, "Loading the settings …"));
    }
    const files = data.files;
    return h("section", {class: "card stack-tight fw-rules", "aria-label": "Firewall rules"}, h("h3", {}, "Firewall rules"),
      h("p", {class: "muted"}, `Every rule in one table: the hub rules and the permissions and sandbox entries of the listed settings files as the host read them, one folded group per source. Hits count the asks of the last ${data.days} days a rule matches, with the matcher of the rule request dry run; allow, deny and sandbox entries never reach the ask ledger and show not seen. A settings change shows as a diff, is signed with your passkey and is written by the host, never by an agent.`),
      data.error ? h("p", {class: "muted"}, data.error) : null,
      h("div", {class: "row fw-filters"}, filterChips(), missingToggle(SettingsFiles.listed(files, false).missing)), ruleTable(), files.length ? addForm(files) : null);
  }

  function missingToggle(count) {
    if (!count) {
      return null;
    }
    const label = `${firewall.missing ? "hide" : "show"} ${count} missing`;
    return h("button", {type: "button", class: "btn small ghost fw-missing", "aria-pressed": String(firewall.missing),
      ...named(label, `${label}: settings files whose folder does not exist on this host; a change cannot create them`), on: {click: () => {
        firewall.missing = !firewall.missing;
        drawFirewall();
      }}}, icon(firewall.missing ? "bi-eye-slash" : "bi-eye"), label);
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
      h("div", {class: "stack-tight", "aria-label": "Diff"}, preview.data.diffs.map((entry) => h("div", {"data-diff": entry.file}, h("code", {class: "fw-path"}, revealed(entry.file)), diffLines(entry.diff)))),
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
        for (const item of items) {
          delete firewall.staged[item.file];
        }
      }
      fetchFirewall();
    });
    return true;
  }
