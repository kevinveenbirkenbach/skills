  const RULE_KINDS = {ask: "Ask: tool + command pattern", review: "Review: branch pattern + gate green", decision: "Decision: take the recommendation"};
  const RULE_HINTS = {
    ask: "Grants matching asks in matching directories, never a command with a warning (rm -r, push, --force, sudo, pipes into a shell …). The passkey signs the rule once; the hook checks signature and pattern itself.",
    review: "Grants reviews of matching branches and worktrees, only when their gate is green. The passkey signs the rule once; the commit skill checks signature and pattern itself.",
    decision: "Takes the recommended option in decisions of matching agents. The passkey signs the rule once; the decisions themselves stay unsigned.",
  };

  function rulesScreen() {
    const kind = h("select", {class: "field", "aria-label": "Kind"}, Object.entries(RULE_KINDS).map(([value, label]) => h("option", {value}, label)));
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
      pattern.placeholder = {ask: "make test*", review: "feature/*", decision: "* (agent pattern)"}[kind.value];
      hint.textContent = RULE_HINTS[kind.value];
    };
    kind.addEventListener("change", sync);
    sync();
    const form = h("form", {class: "rule-form"}, h("label", {}, "Kind", kind), toolField, h("label", {}, "Pattern (glob)", pattern), scopeField, h("label", {}, "Expires on", expires), h("label", {class: "check"}, enabled, "active"), h("button", {type: "submit", class: "btn primary"}, "Create rule"));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const end = Date.parse(`${expires.value}T23:59:59`) / 1000;
      const fields = {
        kind: kind.value,
        tool: kind.value === "ask" ? tool.value.trim() : "",
        pattern: pattern.value.trim() || (kind.value === "decision" ? "*" : ""),
        scope: kind.value === "decision" ? "*" : scope.value.trim(),
        expires: Number.isFinite(end) ? end : 0,
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
    const change = async (rule, verb) => {
      const result = await send(`/api/rules/${encodeURIComponent(rule.id)}/${verb}`, "", "application/json");
      if (!result.ok) {
        toast("Rule not changed", [`${result.status} ${result.text}`.trim()], false);
      }
      await load();
    };
    const now = nowSeconds();
    const list = state.rules.length ? h("div", {class: "mini"}, state.rules.map((rule) => h("div", {class: "rule-row"},
      pill(rule.kind, KIND_TONES[rule.kind]),
      rule.tool ? h("code", {}, rule.tool) : null,
      h("code", {}, rule.pattern),
      rule.kind === "decision" ? null : h("code", {title: "Directory"}, rule.scope || "–"),
      pill(rule.signed ? "signed" : "unsigned: has no effect", rule.signed ? "ok" : "bad"),
      rule.expires <= now ? pill("expired", "bad") : h("span", {class: "muted"}, `until ${absolute.format(stampOf(rule.expires))}`),
      rule.enabled ? pill("active", "ok") : pill("off", "neutral"),
      h("span", {class: "spacer"}),
      btn(rule.enabled ? "Turn off" : "Turn on", "btn small", () => change(rule, rule.enabled ? "disable" : "enable")),
      btn("Delete", "btn small danger", () => {
        if (window.confirm("Delete rule?")) {
          change(rule, "delete");
        }
      })))) : h("p", {class: "muted"}, "No rule yet. Every automatic grant shows up in the stream and can be undone for 3 s.");
    return h("div", {class: "stack"}, h("h2", {class: "title"}, "Firewall rules for automatic grants"), list, h("div", {class: "card"}, hint, form));
  }
