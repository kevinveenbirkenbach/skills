  const COUNTED = {ask: "asks", review: "reviews", decision: "decisions"};

  function ruleRequestBody(item) {
    const rule = item.rule;
    const dry = item.dry_run;
    const pairs = [["Kind", RULE_KINDS[rule.kind]], rule.kind === "ask" ? ["Tool (glob)", rule.tool] : null, ["Pattern (glob)", rule.pattern], rule.kind === "decision" ? null : ["Directory (glob)", rule.scope], ["Expires on", absolute.format(stampOf(rule.expires))]];
    return h("div", {class: "rule-request"},
      item.detail ? h("p", {class: "text"}, revealed(item.detail)) : null,
      meta(pairs.filter(Boolean)),
      h("p", {class: "muted dry-run-count"}, "Dry run: the rule would have granted ", h("strong", {}, `${dry.matched} of ${dry.total}`), ` ${COUNTED[rule.kind]} from the last ${dry.days} days.`),
      h("p", {class: "muted"}, RULE_HINTS[rule.kind]));
  }

  async function acceptRule(item) {
    const label = `Rule: ${short(item.title)}`;
    ui.busy = true;
    const prepared = await sendJson(`/api/rule-requests/${encodeURIComponent(item.id)}/sign`, {});
    const signed = prepared.ok && prepared.data ? await assertion(prepared.data, label) : null;
    if (!prepared.ok || !prepared.data) {
      toast(`${label}: not possible`, fail(prepared), false);
    }
    const result = signed ? await sendJson(`/api/rule-requests/${encodeURIComponent(item.id)}/accept`, {rule: prepared.data.payload, assertion: signed}) : null;
    ui.busy = false;
    if (result) {
      toast(result.ok ? `Created: ${short(item.title)}` : `${label}: not created`, result.ok ? [] : fail(result), result.ok);
    }
    await load();
  }
