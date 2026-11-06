  function rulesScreen() {
    const kind = h("select", {class: "field", "aria-label": "Art"}, h("option", {value: "ask"}, "Ask: Werkzeug + Befehlsmuster"), h("option", {value: "review"}, "Review: Branch-Muster + Gate grün"), h("option", {value: "decision"}, "Entscheidung: Empfehlung nehmen"));
    const tool = h("input", {class: "field", type: "text", placeholder: "Bash", value: "Bash"});
    const pattern = h("input", {class: "field", type: "text", placeholder: "make test*"});
    const scope = h("input", {class: "field", type: "text", value: "*", placeholder: "/home/…/Repositories/*"});
    const expiry = new Date(Date.now() + 7 * DAY * 1000);
    const expires = h("input", {class: "field", type: "date", value: localInput(expiry.getTime() / 1000).slice(0, 10), required: true});
    const enabled = h("input", {type: "checkbox", checked: true});
    const toolField = h("label", {}, "Werkzeug (Glob)", tool);
    const scopeField = h("label", {}, "Verzeichnis (Glob)", scope);
    const hint = h("p", {class: "muted"});
    const sync = () => {
      toolField.hidden = kind.value !== "ask";
      scopeField.hidden = kind.value === "decision";
      pattern.placeholder = {ask: "make test*", review: "feature/*", decision: "* (Agent-Muster)"}[kind.value];
      hint.textContent = {
        ask: "Gibt passende Asks in passenden Verzeichnissen frei, nie einen Befehl mit Warnung (rm -r, push, --force, sudo, Pipe in eine Shell …). Der Passkey signiert die Regel einmal; der Hook prüft Signatur und Muster selbst.",
        review: "Gibt Reviews passender Branches und Worktrees frei, nur wenn ihr Gate grün ist. Der Passkey signiert die Regel einmal; der Commit-Skill prüft Signatur und Muster selbst.",
        decision: "Nimmt bei Entscheidungen passender Agenten die empfohlene Option; Entscheidungen bleiben unsigniert.",
      }[kind.value];
    };
    kind.addEventListener("change", sync);
    sync();
    const form = h("form", {class: "rule-form"}, h("label", {}, "Art", kind), toolField, h("label", {}, "Muster (Glob)", pattern), scopeField, h("label", {}, "Läuft ab am", expires), h("label", {class: "check"}, enabled, "aktiv"), h("button", {type: "submit", class: "btn primary"}, "Regel anlegen"));
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
        toast("Regel nicht angelegt", fail(prepared), false);
        return;
      }
      const signed = prepared.data.sign ? await assertion(prepared.data, "Regel") : null;
      if (prepared.data.sign && !signed) {
        return;
      }
      const result = await sendJson("/api/rules", {rule: prepared.data.payload, assertion: signed, enabled: enabled.checked});
      toast(result.ok ? "Regel angelegt" : "Regel nicht angelegt", result.ok ? [] : fail(result), result.ok);
      await load();
    });
    const change = async (rule, verb) => {
      const result = await send(`/api/rules/${encodeURIComponent(rule.id)}/${verb}`, "", "application/json");
      if (!result.ok) {
        toast("Regel nicht geändert", [`${result.status} ${result.text}`.trim()], false);
      }
      await load();
    };
    const now = nowSeconds();
    const list = state.rules.length ? h("div", {class: "mini"}, state.rules.map((rule) => h("div", {class: "rule-row"},
      pill(rule.kind, KIND_TONES[rule.kind]),
      rule.tool ? h("code", {}, rule.tool) : null,
      h("code", {}, rule.pattern),
      rule.kind === "decision" ? null : h("code", {title: "Verzeichnis"}, rule.scope || "–"),
      rule.kind === "decision" ? null : pill(rule.signed ? "signiert" : "unsigniert: wirkt nicht", rule.signed ? "ok" : "bad"),
      rule.expires <= now ? pill("abgelaufen", "bad") : h("span", {class: "muted"}, `bis ${absolute.format(stampOf(rule.expires))}`),
      rule.enabled ? pill("aktiv", "ok") : pill("aus", "neutral"),
      h("span", {class: "spacer"}),
      btn(rule.enabled ? "Ausschalten" : "Einschalten", "btn small", () => change(rule, rule.enabled ? "disable" : "enable")),
      btn("Löschen", "btn small danger", () => {
        if (window.confirm("Regel löschen?")) {
          change(rule, "delete");
        }
      })))) : h("p", {class: "muted"}, "Noch keine Regel. Jede automatische Freigabe erscheint im Stream und lässt sich 3 s lang rückgängig machen.");
    return h("div", {class: "stack"}, h("h2", {class: "title"}, "Regeln für automatische Freigaben"), list, h("div", {class: "card"}, hint, form));
  }
