  const RULE_KINDS = {ask: "Ask: tool + command pattern", review: "Review: branch pattern + gate green", decision: "Decision: take the recommendation"};
  const RULE_HINTS = Glossary.RULE_HINTS;
  const RULE_GROUPS = [["ask", "Ask"], ["review", "Review"], ["decision", "Decision"]];
  const RECORD_WORDS = {ask: "asks", review: "reviews", decision: "decisions"};
  const EXPIRY_WARN_DAYS = 2;
  const DRAFT_DELAY = 300;
  const rulesView = {open: {}};

  /**
   * @param {Object} rule the stored rule to turn on again, which widens what agents may do.
   * @returns {Promise<Object|null>} the hub's answer, null when the operator did not sign.
   */
  async function turnOn(rule) {
    const signed = await proofFor([{kind: "enable", rule: rule.id}], "Turn on rule");
    return signed ? sendJson(`/api/rules/${encodeURIComponent(rule.id)}/enable`, {proof: signed.proof}) : null;
  }

  /**
   * @param {Object} rule the stored rule.
   * @param {string} verb enable, disable or delete.
   */
  async function changeRule(rule, verb) {
    const result = verb === "enable" ? await turnOn(rule) : await send(`/api/rules/${encodeURIComponent(rule.id)}/${verb}`, "", "application/json");
    if (result && !result.ok) {
      toast("Rule not changed", fail(result), false);
    }
    await load();
  }

  /**
   * @param {string} id the key rulesView keeps the section's open state under across redraws.
   * @param {boolean} fallback whether the section starts open before the operator toggles it.
   * @param {Array} head the summary's nodes.
   * @param {HTMLElement} body what the section folds.
   * @returns {HTMLDetailsElement} the collapsible section.
   */
  function foldSection(id, fallback, head, body) {
    const open = Object.hasOwn(rulesView.open, id) ? rulesView.open[id] : fallback;
    const section = h("details", {class: "rule-fold", "data-fold": id, open}, h("summary", {title: "Show or hide"}, icon("bi-chevron-right", "rule-fold-mark"), head), body);
    section.addEventListener("toggle", () => {
      rulesView.open[id] = section.open;
    });
    return section;
  }

  /**
   * @param {Object} rule a stored rule with expires in epoch seconds.
   * @returns {HTMLElement} the chip with the days left, red under EXPIRY_WARN_DAYS days and once expired.
   */
  function expiryChip(rule) {
    const days = (rule.expires - nowSeconds()) / DAY;
    const whole = Math.floor(days);
    const text = days <= 0 ? "expired" : whole < 1 ? "under a day left" : `${whole} ${whole === 1 ? "day" : "days"} left`;
    return h("span", {class: "pill", "data-tone": days < EXPIRY_WARN_DAYS ? "bad" : "neutral", "data-expiry": "", title: `until ${absolute.format(stampOf(rule.expires))}`}, text);
  }

  /**
   * @param {Object} counted matched and of, as the hub counts a rule or a draft.
   * @param {string} kind the rule kind, which names the records counted.
   * @returns {string} N of the last M asks, reviews or decisions.
   */
  const matchWords = (counted, kind) => `${counted.matched} of the last ${counted.of} ${RECORD_WORDS[kind]}`;

  function ruleSwitch(rule) {
    return h("input", {type: "checkbox", role: "switch", class: "switch", checked: rule.enabled, "aria-label": revealed(`Rule ${rule.pattern}: on`), on: {change: async (event) => {
      await changeRule(rule, rule.enabled ? "disable" : "enable");
      event.target.checked = rule.enabled;
    }}});
  }

  /**
   * @param {Object} rule a stored rule of state.rules.
   * @returns {HTMLLIElement} the row: switch, tool for an ask rule, pattern, directory, applies-to, expiry chip, match count and delete.
   */
  function hubRuleRow(rule) {
    const remove = () => {
      if (window.confirm("Delete rule?")) {
        changeRule(rule, "delete");
      }
    };
    return h("li", {class: "hub-rule", "data-rule": rule.id, "data-kind": rule.kind, "data-on": String(rule.enabled)},
      ruleSwitch(rule), rule.kind === "ask" ? h("code", {class: "hub-rule-tool", title: "Tool"}, revealed(rule.tool)) : null,
      h("code", {class: "hub-rule-pattern", title: "Pattern"}, revealed(rule.pattern)), h("code", {class: "hub-rule-scope", title: "Directory"}, revealed(rule.scope)),
      targetPill(rule.agents), rule.signed ? null : pill("unsigned: has no effect", "warn"), expiryChip(rule),
      h("span", {class: "hub-rule-count", "data-matched": rule.matched, title: "Counted with the matcher that applies the rule, on or off, expired or not"}, matchWords(rule, rule.kind)),
      h("span", {class: "spacer"}), iconBtn("bi-trash3", "Delete rule", "btn small danger", remove, revealed(`Delete rule ${rule.pattern}`)));
  }

  function ruleGroups() {
    return RULE_GROUPS.map(([kind, label]) => {
      const rows = state.rules.filter((rule) => rule.kind === kind);
      const body = rows.length ? h("ul", {class: "hub-rules"}, rows.map(hubRuleRow)) : h("p", {class: "muted"}, `No ${label.toLowerCase()} rule yet.`);
      return foldSection(kind, true, [h("strong", {}, label), counter(rows.length)], body);
    });
  }

  function rulesList() {
    const add = h("button", {type: "button", class: "btn primary", "data-new-rule": "", ...named("New rule", "New rule: draft a rule and sign it with your passkey"), on: {click: openRuleSheet}}, icon("bi-plus-lg"), "New rule");
    return h("section", {class: "card stack-tight hub-rule-list", "aria-label": "Hub rules"}, h("div", {class: "row"}, h("h3", {}, "Hub rules"), h("span", {class: "spacer"}), add),
      h("p", {class: "muted"}, "Rules the hub applies by itself once your passkey signed them. Each counts how many of the last asks, reviews or decisions of its kind it would have granted."), ruleGroups());
  }

  /**
   * @param {Function} read returns the draft as POST /api/rules/match takes it.
   * @param {HTMLElement} out where the live count shows.
   * @returns {Function} what schedules a count DRAFT_DELAY ms after the last change; only the newest answer shows.
   */
  function draftCounter(read, out) {
    let timer = 0;
    let ticket = 0;
    return () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(async () => {
        ticket += 1;
        const mine = ticket;
        const fields = read();
        const result = await sendJson("/api/rules/match", fields);
        if (mine === ticket) {
          out.dataset.matched = result.ok && result.data ? String(result.data.matched) : "";
          out.textContent = result.ok && result.data ? `Would grant ${matchWords(result.data, fields.kind)}` : `Not counted: ${result.text}`.trim();
        }
      }, DRAFT_DELAY);
    };
  }

  /**
   * @param {Object} fields the draft as ruleDraft() reads it.
   * @param {boolean} enabled whether the rule starts on.
   * @returns {Promise<boolean>} whether the hub stored the signed rule.
   */
  async function createRule(fields, enabled) {
    const prepared = await sendJson("/api/rules/sign", fields);
    if (!prepared.ok || !prepared.data) {
      toast("Rule not created", fail(prepared), false);
      return false;
    }
    const signed = prepared.data.sign ? await assertion(prepared.data, "Rule") : null;
    if (prepared.data.sign && !signed) {
      return false;
    }
    const result = await sendJson("/api/rules", {rule: prepared.data.payload, assertion: signed, enabled});
    toast(result.ok ? "Rule created" : "Rule not created", result.ok ? [] : fail(result), result.ok);
    return result.ok;
  }

  function ruleForm() {
    const kind = h("select", {class: "field", "aria-label": "Kind"}, Object.entries(RULE_KINDS).map(([value, label]) => h("option", {value}, label)));
    const target = targetSelect("Applies to", null);
    const targetField = h("label", {}, "Applies to", target);
    const tool = h("input", {class: "field", type: "text", placeholder: "Bash", value: "Bash"});
    const pattern = h("input", {class: "field", type: "text", placeholder: "make test*", "aria-label": "Pattern"});
    const scope = h("input", {class: "field", type: "text", value: "*", placeholder: "/home/…/Repositories/*"});
    const expiry = new Date(Date.now() + 7 * DAY * 1000);
    const expires = h("input", {class: "field", type: "date", value: localInput(expiry.getTime() / 1000).slice(0, 10), required: true});
    const enabled = h("input", {type: "checkbox", checked: true});
    const toolField = h("label", {}, "Tool (glob)", tool);
    const scopeField = h("label", {}, "Directory (glob)", scope);
    const hint = h("p", {class: "muted"});
    const live = h("p", {class: "muted", "data-live-count": "", "aria-live": "polite"}, "Counting …");
    const sync = () => {
      toolField.hidden = kind.value !== "ask";
      scopeField.hidden = kind.value === "decision";
      targetField.hidden = kind.value === "review";
      target.disabled = targetField.hidden;
      fillTargets(target);
      pattern.placeholder = {ask: "make test*", review: "feature/*", decision: "* (agent pattern)"}[kind.value];
      hint.textContent = RULE_HINTS[kind.value];
    };
    kind.addEventListener("change", sync);
    sync();
    const read = () => {
      const end = Date.parse(`${expires.value}T23:59:59`) / 1000;
      return {
        kind: kind.value,
        tool: kind.value === "ask" ? tool.value.trim() : "",
        pattern: pattern.value.trim() || (kind.value === "decision" ? "*" : ""),
        scope: kind.value === "decision" ? "*" : scope.value.trim(),
        expires: Number.isFinite(end) ? end : 0,
        agents: ruleAgents(kind.value, target.value),
      };
    };
    const form = h("form", {class: "rule-form", "aria-label": "New rule"}, h("label", {}, "Kind", kind), targetField, toolField, h("label", {}, "Pattern (glob)", pattern), scopeField, h("label", {}, "Expires on", expires), h("label", {class: "check"}, enabled, "active"), h("button", {type: "submit", class: "btn primary", "data-sign": ""}, "Create rule"));
    const recount = draftCounter(read, live);
    form.addEventListener("input", recount);
    form.addEventListener("change", recount);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (await createRule(read(), enabled.checked)) {
        closeSheet();
      }
      await load();
    });
    recount();
    return [hint, live, form];
  }

  function openRuleSheet() {
    openSheet("New rule", ruleForm(), false);
  }

  function rulesScreen() {
    const dom = firewallSections();
    const below = [["settings", "Settings files", dom.settings], ["patterns", "Never granted", dom.patterns], ["groups", "Agent groups", dom.groups], ["sets", "Rule sets", dom.sets]];
    return controlsPage({tools: [dom.tools], rules: [rulesList(), ...below.map(([id, label, node]) => foldSection(id, false, [h("strong", {}, label)], node))], schedules: [schedulesPanel()], queue: [queuePanel()]}, dom.bar);
  }
