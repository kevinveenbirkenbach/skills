  const COUNTED = {ask: "Asks", review: "Reviews", decision: "Entscheidungen"};

  function ruleRequestBody(item) {
    const rule = item.rule;
    const dry = item.dry_run;
    const pairs = [["Art", RULE_KINDS[rule.kind]], rule.kind === "ask" ? ["Werkzeug (Glob)", rule.tool] : null, ["Muster (Glob)", rule.pattern], rule.kind === "decision" ? null : ["Verzeichnis (Glob)", rule.scope], ["Läuft ab am", absolute.format(stampOf(rule.expires))]];
    return h("div", {class: "rule-request"},
      item.detail ? h("p", {class: "text"}, item.detail) : null,
      meta(pairs.filter(Boolean)),
      h("p", {class: "muted dry-run-count"}, "Trockenlauf: Die Regel hätte ", h("strong", {}, `${dry.matched} von ${dry.total}`), ` ${COUNTED[rule.kind]} der letzten ${dry.days} Tage freigegeben.`),
      h("p", {class: "muted"}, RULE_HINTS[rule.kind]));
  }

  async function acceptRule(item) {
    const label = `Regel: ${short(item.title)}`;
    ui.busy = true;
    const prepared = await sendJson(`/api/rule-requests/${encodeURIComponent(item.id)}/sign`, {});
    const signed = prepared.ok && prepared.data ? await assertion(prepared.data, label) : null;
    if (!prepared.ok || !prepared.data) {
      toast(`${label}: nicht möglich`, fail(prepared), false);
    }
    const result = signed ? await sendJson(`/api/rule-requests/${encodeURIComponent(item.id)}/accept`, {rule: prepared.data.payload, assertion: signed}) : null;
    ui.busy = false;
    if (result) {
      toast(result.ok ? `Angelegt: ${short(item.title)}` : `${label}: nicht angelegt`, result.ok ? [] : fail(result), result.ok);
    }
    await load();
  }
