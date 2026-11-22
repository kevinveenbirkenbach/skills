  let inboxSlot = null;
  const GONE_NOTICE = "already done or removed elsewhere";

  function closeGone(result, keys, label) {
    if (result.status !== 404 || !keys.length) {
      return false;
    }
    state.inbox = state.inbox.filter((item) => !keys.includes(keyOf(item)));
    toast(`${label}: ${GONE_NOTICE}`, [], true);
    render(false);
    drawStream();
    return true;
  }

  async function reloadGone(missing, keys, label) {
    await load();
    if (missing === null) {
      return;
    }
    const left = new Set(state.inbox.map(keyOf));
    if (keys.some((key) => !left.has(key))) {
      toast(`${label}: ${GONE_NOTICE}`, [], true);
    } else {
      toast(`${label}: not possible`, fail(missing), false);
    }
  }

  async function submit(entries, label) {
    ui.busy = true;
    const keys = entries.map(keyOf);
    let missing = null;
    const gone = (result) => {
      if (keys.length > 1 && result.status === 404) {
        missing = result;
        return true;
      }
      return closeGone(result, keys, label);
    };
    const signed = await proofFor(entries, label, gone);
    if (signed === null) {
      ui.busy = false;
      await reloadGone(missing, keys, label);
      return false;
    }
    const result = await sendJson("/api/inbox/approve", {items: entries, proof: signed.proof});
    ui.busy = false;
    if (!result.ok || !result.data) {
      if (!gone(result)) {
        toast(`${label}: not possible`, fail(result), false);
      }
      await reloadGone(missing, keys, label);
      return false;
    }
    known.batches.add(result.data.id);
    ui.selected.clear();
    undoToast(result.data, label);
    await load();
    return true;
  }

  function undoToast(batch, label) {
    const left = h("span", {class: "muted"});
    const button = h("button", {type: "button", class: "btn small", ...named("Undo")}, icon("bi-arrow-counterclockwise"), "Undo");
    const box = h("div", {class: "toast wait", role: "status"}, h("strong", {}, label), h("div", {class: "undo-row"}, left, h("span", {class: "spacer"}), button));
    let timer = 0;
    const count = () => {
      const rest = Math.ceil(batch.due - nowSeconds());
      if (rest <= 0) {
        window.clearInterval(timer);
        box.remove();
        load();
        return;
      }
      left.textContent = `takes effect in ${rest} s`;
    };
    timer = window.setInterval(count, 250);
    button.addEventListener("click", async () => {
      window.clearInterval(timer);
      button.disabled = true;
      const result = await send(`/api/inbox/undo/${encodeURIComponent(batch.id)}`, "", "application/json");
      box.remove();
      toast(result.ok ? `Undone: ${label}` : "Too late: already in effect", result.ok ? [] : [`${result.status} ${result.text}`.trim()], result.ok);
      await load();
    });
    document.getElementById("toasts").append(box);
    count();
  }

  function approveOne(item) {
    if (collecting(item)) {
      collect(item);
      return null;
    }
    if (item.kind === "rule") {
      return acceptRule(item);
    }
    if (item.kind === "decision") {
      if (!item.recommended) {
        openItem(item);
        return null;
      }
      return submit([entryOf(item, "approve", item.recommended)], `Choice: ${shownPick(item.recommended)}`);
    }
    return submit([entryOf(item, "approve", "")], `${item.kind === "operator" ? "Run" : "Grant"}: ${short(item.title)}`);
  }

  const chooseOne = (item, label) => submit([entryOf(item, "approve", label)], `Choice: ${shownPick(label)}`);
  const asked = (item) => item.kind === "operator" && item.check === "decision";
  const answers = new Map();
  const answerOf = (item) => answers.get(keyOf(item)) || item.answered || "";

  async function answerRow(item, answer) {
    if (!item.agent) {
      toast("Answer: no agent to send it to", ["The row names no adding agent; answer in its session."], false);
      return;
    }
    if (await radioSend({to: item.agent, text: `Decision ${item.id}\nAnswer: ${answer}`, cls: "post", upload: "", voice: ""})) {
      answers.set(keyOf(item), answer);
      drawInbox();
    }
  }

  const signsFor = (item) => `your passkey signs this answer, a post to ${item.agent}`;

  /**
   * @param {Object} item a permission ask.
   * @param {string} answer the picked label, or the typed text.
   * @param {boolean} typed whether answer is typed text, which always denies with it as the reason.
   */
  const answerAsk = (item, answer, typed) => (!typed && answer === ALLOW ? approveOne(item) : denyNow(item, "post", typed ? answer : ""));

  /**
   * @param {Object} item an inbox item.
   * @param {Function} after called before a picked answer is sent.
   * @returns {HTMLElement|Array|null} the choiceDialog() of a decision, a decision row or a permission ask, with its recipient line for a row; null for every other item.
   */
  const choiceOf = (item, after) => {
    if (item.kind === "decision") {
      return choiceDialog(item, {pick: (label) => { after(); chooseOne(item, label); }, toggled: new Set(), chosen: "", locked: item.held, hint: signsFor(item), group: "", other: OTHER_PROMPT});
    }
    if (item.kind === "ask") {
      return choiceDialog(askDialog(item.id), {pick: (answer, typed) => { after(); answerAsk(item, answer, typed); }, toggled: new Set(), chosen: ui.selected.has(keyOf(item)) ? ALLOW : "", locked: item.held, hint: `your passkey signs it, the answer goes to ${item.to || "its session"}`, group: "", other: TELL});
    }
    const told = answerOf(item);
    return asked(item) ? [answerTo(item), choiceDialog(item, {pick: (label) => { after(); answerRow(item, label); }, toggled: new Set(), chosen: told, locked: item.held || Boolean(told), hint: signsFor(item), group: "", other: OTHER_PROMPT})] : null;
  };

  /**
   * @param {Object} item a decision row of the register.
   * @returns {HTMLElement} who receives the answer: the row's first agent with role A, which any agent can set, so the operator sees it before signing.
   */
  const answerTo = (item) => h("p", {class: "muted answer-to"}, item.agent ? ["Your answer goes to ", h("strong", {}, revealed(item.agent)), " as a passkey-signed post, with the row id and your answer only."] : "No agent holds role A on this row: answer in its session.");

  const deniable = (item) => item.deniable || item.kind === "review";
  const denialOf = (item, reason) => ({...entryOf(item, "reject", ""), channel: "post", reason, to: item.to});
  const pickable = (item) => !item.held && (selectable(item) || deniable(item));

  function bulk(items, label, deny) {
    const usable = items.filter(deny ? deniable : selectable);
    if (!usable.length) {
      toast(`${label}: nothing to ${deny ? "deny" : "grant"}`, [], false);
      return;
    }
    const rows = usable.map((item) => h("li", {},
      h("div", {class: "row"}, pill(ITEM_LABELS[item.kind], KIND_TONES[item.kind]), item.kind === "decision" && !deny ? h("span", {class: "muted"}, revealed(`→ ${shownPick(item.recommended)}`)) : null),
      h("strong", {}, revealed(item.title)),
      item.kind === "operator" ? h("div", {class: "command"}, h("code", {}, revealed(item.command))) : null,
      item.kind === "operator" ? h("span", {class: "muted"}, revealed(`in ${item.directory}`)) : null,
      item.kind === "ask" ? h("div", {class: "command"}, h("code", {}, revealed(item.command))) : null));
    const confirm = h("button", {type: "button", class: deny ? "btn danger" : "btn primary"}, `${deny ? "Deny" : "Grant"} ${usable.length}`);
    const reason = deny ? h("textarea", {class: "field", maxlength: DENY_REASON, rows: 3, placeholder: "e.g. make the gate green first"}) : null;
    confirm.addEventListener("click", () => {
      closeSheet();
      submit(usable.map((item) => (deny ? denialOf(item, reason.value) : entryOf(item, "approve", item.kind === "decision" ? item.recommended : ""))), `${label}: ${usable.length} entries`);
    });
    const note = deny
      ? "Every entry and every full command that gets denied; each requester gets its denial and the reason by post. After the click the passkey signs the whole selection once; then 3 s remain to undo."
      : "Every entry and every full command that gets granted. After the click the passkey signs the whole selection once; then 3 s remain to undo.";
    openSheet(label, [h("p", {class: "muted"}, note), h("ul", {class: "mini"}, rows), ...(deny ? [reasonChips(reason), h("label", {class: "deny-reason"}, "Reason (optional, every requester reads it)", reason)] : []),
      h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), confirm)], false);
    (reason || confirm).focus();
  }

  /**
   * @returns {object} the picked items as chosen, and the grant, deny and grant-all-green controls of the Grant menu.
   */
  function selectionActions(items) {
    const green = items.filter(isGreen);
    const chosen = items.filter((item) => ui.selected.has(keyOf(item)));
    const denials = chosen.filter(deniable);
    const grantable = chosen.filter(selectable);
    return {
      chosen,
      grant: h("button", {type: "button", class: "btn small primary", ...named(`Grant selection (${grantable.length})`), disabled: !grantable.length || ui.busy, on: {click: () => bulk(chosen, "Grant selection", false)}}, icon("bi-check2-square"), `Grant ${grantable.length}`),
      deny: h("button", {type: "button", class: "menu-item danger", ...named(`Deny selection (${denials.length})`, `Deny selection (${denials.length}): each requester gets its denial and an optional reason by post, one passkey signature, 3 s to undo`), disabled: !denials.length || ui.busy, on: {click: () => bulk(chosen, "Deny selection", true)}}, icon("bi-x-square"), `Deny ${denials.length}`),
      green: h("button", {type: "button", class: "menu-item", ...named(`Grant all green (${green.length})`), disabled: !green.length || ui.busy, on: {click: () => bulk(green, "Grant all green", false)}}, icon("bi-check2-all"), `Grant all green ${green.length}`),
    };
  }

  async function mark(item, until, pinned) {
    const result = await sendJson("/api/inbox/mark", {kind: item.kind, id: item.id, until, pinned});
    if (!result.ok) {
      toast("Marking failed", [`${result.status} ${result.text}`.trim()], false);
    }
    await load();
  }

  function tomorrow() {
    const date = new Date();
    date.setDate(date.getDate() + 1);
    date.setHours(8, 0, 0, 0);
    return date.getTime() / 1000;
  }

  function toggle(item, refocus) {
    if (!item || !pickable(item)) {
      return;
    }
    const key = keyOf(item);
    if (ui.selected.has(key)) {
      ui.selected.delete(key);
    } else {
      ui.selected.add(key);
    }
    ui.cursor = Math.max(visibleInbox().findIndex((entry) => keyOf(entry) === key), 0);
    drawInbox();
    drawGrant();
    const box = inboxDom.querySelector(`.item[data-index="${ui.cursor}"] > input[type="checkbox"]`);
    if (refocus && box) {
      box.focus({preventScroll: true});
    }
  }

  function actionsFor(item) {
    if (item.held) {
      return [h("span", {class: "muted"}, "takes effect …")];
    }
    const buttons = [];
    const grant = (button) => buttons.push(grantPress(button, item));
    if (item.kind === "review") {
      grant(iconBtn("bi-check-lg", "Grant", "btn small primary", () => approveOne(item)));
      buttons.push(denySplit(item));
    } else if (item.kind === "decision" && item.recommended) {
      grant(h("button", {type: "button", class: "btn small primary", ...named(revealed(`Recommendation: ${shownPick(item.recommended)}`)), on: {click: () => approveOne(item)}}, icon("bi-check-lg"), revealed(shownPick(item.recommended))));
    } else if (item.kind === "operator" && item.runnable) {
      grant(iconBtn("bi-play-fill", "Run", "btn small primary", () => approveOne(item)));
    } else if (item.kind === "rule") {
      grant(h("button", {type: "button", class: "btn small primary", ...named("Accept", "Accept: the passkey signs exactly this rule, then it applies"), on: {click: () => approveOne(item)}}, icon("bi-shield-check"), "Accept"));
    }
    if (item.deniable) {
      buttons.push(denySplit(item));
    }
    if (item.job && !jobOpen(item.job)) {
      buttons.push(iconBtn("bi-x-circle", "Close", "btn small ghost", () => dismissJob(item.job), "Close: hide the console; a done row disappears with it"));
    }
    return buttons;
  }

  function inboxHeadline(item) {
    return h("button", {type: "button", class: "linkish headline", title: "Open", on: {click: () => openItem(item)}}, revealed(item.kind === "operator" ? item.id : item.kind === "ask" ? item.title.split(": ")[0] : item.title));
  }

  function inboxItem(item, index) {
    const red = item.kind === "review" && item.gate !== "pass";
    const commanded = item.kind === "ask" || (item.kind === "operator" && !asked(item));
    const classes = ["item", "entry", `k-${item.kind}`, "waiting", isGreen(item) ? "green" : "", red ? "red" : "", item.held ? "held" : "", index === ui.cursor ? "cursor" : ""].filter(Boolean).join(" ");
    const box = h("input", {type: "checkbox", "aria-label": `Select ${item.title}`, checked: ui.selected.has(keyOf(item)), disabled: !pickable(item), on: {change: () => toggle(item, true)}});
    return h("li", {class: classes, "data-index": index, "data-ref": keyOf(item), "data-to": item.to || null},
      box,
      h("div", {class: "msg-meta"},
        when(item.ts),
        asked(item) ? pill("Decision", KIND_TONES.decision) : pill(ITEM_LABELS[item.kind], KIND_TONES[item.kind]),
        answerOf(item) ? pill(revealed(`answered: ${answerOf(item)}`), "ok") : null,
        item.kind === "review" ? pill(item.gate === "pass" ? "Gate green" : "Gate red", item.gate === "pass" ? "ok" : "bad") : null,
        item.warnings.map((warning) => pill(warning, "bad")),
        item.pinned ? pill("pinned", "violet") : null,
        item.until ? pill(`until ${absolute.format(stampOf(item.until))}`, "neutral") : null),
      h("div", {class: "entry-body"},
        h("div", {class: "route"},
          inboxHeadline(item),
          item.agent ? [face(item.agent, false), person(item.agent)] : null),
        item.kind === "review" ? h("div", {class: "muted"}, revealed(item.detail), item.score ? revealed(` · ${item.score}`) : "") : null,
        commanded ? h("div", {class: "command", "data-path": item.directory || "-"}, h("code", {}, revealed(item.command)), copyButton(item.command)) : null,
        commanded ? h("span", {class: "muted"}, revealed(`in ${dash(item.directory)}`)) : null,
        asked(item) ? h("p", {class: "text question"}, revealed(item.title)) : null,
        item.kind === "operator" && item.detail && item.detail !== "-" ? h("p", {class: "text reason"}, revealed(item.detail)) : null,
        diffBlocks(item),
        item.job ? consoleOf(item.job) : null,
        item.kind === "rule" ? ruleRequestBody(item) : null,
        choiceOf(item, () => {}),
        feedbackList(keyOf(item))),
      h("div", {class: "item-actions line-actions"},
        actionsFor(item),
        h("span", {class: "spacer"}),
        iconBtn("bi-hourglass-split", "1 h", "btn small ghost", () => mark(item, nowSeconds() + 3600, item.pinned), "1 h: snooze for one hour"),
        iconBtn("bi-sunrise", "tomorrow", "btn small ghost", () => mark(item, tomorrow(), item.pinned), "tomorrow: snooze until 8 am tomorrow"),
        item.until ? iconBtn("bi-alarm", "wake", "btn small ghost", () => mark(item, 0, item.pinned), "wake: show again") : null,
        iconBtn(item.pinned ? "bi-pin-angle-fill" : "bi-pin-angle", item.pinned ? "unpin" : "pin", "btn small ghost", () => mark(item, item.until, !item.pinned))));
  }

  function inboxScreen() {
    inboxDom = h("div", {class: "inbox", "data-panel": "tasks/operator"});
    inboxSlot = h("span", {"data-star-slot": ""});
    return inboxDom;
  }

  function drawInbox() {
    if (!inboxDom) {
      return;
    }
    const items = visibleInbox();
    ui.cursor = Math.min(ui.cursor, Math.max(items.length - 1, 0));
    const present = new Set(items.map(keyOf));
    for (const key of [...ui.selected]) {
      if (!present.has(key)) {
        ui.selected.delete(key);
      }
    }
    const mode = grantMode();
    const sig = JSON.stringify([mode, items.map(withoutOutput), [...ui.selected], [...answers], ui.cursor, ui.snoozed, ui.busy, Math.floor(nowSeconds() / 60), diffView.version, state.messages.map((message) => message.id)]);
    if (sig === inboxSig) {
      repaintConsoles(items);
      return;
    }
    inboxSig = sig;
    const hidden = state.inbox.length - waitingCount();
    const snoozed = h("input", {type: "checkbox", checked: ui.snoozed, on: {change: (event) => {
      ui.snoozed = event.target.checked;
      drawInbox();
    }}});
    Panels.keepFocus(inboxSlot, () => inboxDom.replaceChildren(
      h("div", {class: "inbox-head"}, h("h2", {class: "group-title"}, "Waits on Operator", counter(waitingCount())), h("span", {class: "spacer"}),
        hidden ? h("label", {class: "check"}, snoozed, `${hidden} snoozed`) : null, inboxSlot),
      onLocalhost() ? "" : h("p", {class: "muted"}, "The passkey signs grants only under ", localLink()),
      items.length ? h("ol", {class: "inbox-list"}, items.map(inboxItem)) : emptyState("All done", "Nothing is waiting for you right now.")));
    settleConsoles(items);
    const current = inboxDom.querySelector(`.item[data-index="${ui.cursor}"]`);
    if (current && document.activeElement === document.body) {
      current.scrollIntoView({block: "nearest"});
    }
  }

  function openItem(item) {
    if (!item) {
      return;
    }
    if (item.kind === "review") {
      reviewSheet(item.id);
      return;
    }
    const body = [
      h("div", {class: "who"}, pill(ITEM_LABELS[item.kind], KIND_TONES[item.kind]), item.agent ? face(item.agent, false) : null, item.agent ? person(item.agent) : null, when(item.ts)),
      h("p", {class: "text"}, revealed(item.title)),
      item.command && !asked(item) ? h("div", {class: "command"}, h("code", {}, revealed(item.command)), copyButton(item.command)) : null,
      asked(item) && item.detail && item.detail !== "-" ? h("p", {class: "text reason"}, revealed(item.detail)) : null,
      item.kind === "rule" ? ruleRequestBody(item) : null,
      meta([["Directory", item.directory], ["Warnings", item.warnings.join(", ")], ["Id", item.id]]),
      choiceOf(item, closeSheet),
      h("div", {class: "actions"}, h("span", {class: "spacer"}), actionsFor(item).map((node) => {
        node.addEventListener("click", closeSheet);
        return node;
      })),
    ];
    openSheet(ITEM_LABELS[item.kind], body, false);
  }
