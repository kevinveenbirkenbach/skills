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

  /**
   * @param {Object} item a rule request.
   * @param {string} label the toast and passkey prompt label.
   * @returns {Promise<Object|null>} the accept body with the rule and its passkey assertion, null when the server refused or the operator cancelled.
   */
  async function signRule(item, label) {
    const prepared = await sendJson(`/api/rule-requests/${encodeURIComponent(item.id)}/sign`, {});
    if (!prepared.ok || !prepared.data) {
      if (!closeGone(prepared, [keyOf(item)], label)) {
        toast(`${label}: not possible`, fail(prepared), false);
      }
      return null;
    }
    const signed = await assertion(prepared.data, label);
    return signed ? {rule: prepared.data.payload, assertion: signed} : null;
  }

  /**
   * @param {Object} item a rule request.
   * @returns {Promise<boolean>} whether the rule was created.
   */
  async function acceptRule(item) {
    const label = `Rule: ${short(item.title)}`;
    ui.busy = true;
    const body = await signRule(item, label);
    const result = body ? await sendJson(`/api/rule-requests/${encodeURIComponent(item.id)}/accept`, body) : null;
    ui.busy = false;
    if (result && !closeGone(result, [keyOf(item)], label)) {
      toast(result.ok ? `Created: ${short(item.title)}` : `${label}: not created`, result.ok ? [] : fail(result), result.ok);
    }
    await load();
    return Boolean(result && result.ok);
  }
