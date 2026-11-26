  const RULE_KINDS = {ask: "Ask: tool + command pattern", review: "Review: branch pattern + gate green", decision: "Decision: take the recommendation"};
  const RULE_HINTS = Glossary.RULE_HINTS;

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

  function rulesScreen() {
    const kind = h("select", {class: "field", "aria-label": "Kind"}, Object.entries(RULE_KINDS).map(([value, label]) => h("option", {value}, label)));
    const target = targetSelect("Applies to", null);
    const targetField = h("label", {}, "Applies to", target);
    const tool = h("input", {class: "field", type: "text", placeholder: "Bash", value: "Bash"});
    const pattern = h("input", {class: "field", type: "text", placeholder: "make test*"});
    const scope = h("input", {class: "field", type: "text", value: "*", placeholder: "/home/…/Repositories/*"});
    const expiry = new Date(Date.now() + 7 * DAY * 1000);
    const expires = h("input", {class: "field", type: "date", value: localInput(expiry.getTime() / 1000).slice(0, 10), required: true});
    const enabled = h("input", {type: "checkbox", checked: true});
    const toolField = h("label", {}, "Tool (glob)", tool);
    const scopeField = h("label", {}, "Directory (glob)", scope);
    const hint = h("p", {class: "muted"});
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
    const form = h("form", {class: "rule-form"}, h("label", {}, "Kind", kind), targetField, toolField, h("label", {}, "Pattern (glob)", pattern), scopeField, h("label", {}, "Expires on", expires), h("label", {class: "check"}, enabled, "active"), h("button", {type: "submit", class: "btn primary", "data-sign": ""}, "Create rule"));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const end = Date.parse(`${expires.value}T23:59:59`) / 1000;
      const fields = {
        kind: kind.value,
        tool: kind.value === "ask" ? tool.value.trim() : "",
        pattern: pattern.value.trim() || (kind.value === "decision" ? "*" : ""),
        scope: kind.value === "decision" ? "*" : scope.value.trim(),
        expires: Number.isFinite(end) ? end : 0,
        agents: ruleAgents(kind.value, target.value),
      };
      const prepared = await sendJson("/api/rules/sign", fields);
      if (!prepared.ok || !prepared.data) {
        toast("Rule not created", fail(prepared), false);
        return;
      }
      const signed = prepared.data.sign ? await assertion(prepared.data, "Rule") : null;
      if (prepared.data.sign && !signed) {
        return;
      }
      const result = await sendJson("/api/rules", {rule: prepared.data.payload, assertion: signed, enabled: enabled.checked});
      toast(result.ok ? "Rule created" : "Rule not created", result.ok ? [] : fail(result), result.ok);
      await load();
    });
    const dom = firewallSections();
    const ruleCard = h("div", {class: "card"}, h("h3", {}, "New hub rule for automatic grants"), hint, form);
    return controlsPage({tools: [dom.tools], rules: [dom.settings, ruleCard, dom.patterns], groups: [dom.groups, dom.sets], schedules: [schedulesPanel()]}, dom.bar);
  }
