  let inboxDoneOpen = false;
  const GONE_NOTICE = "already done or removed elsewhere";
  const doneItem = (item) => Boolean(item.held || (item.job && !jobOpen(item.job)));

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

  const sending = new Set();

  async function submit(entries, label) {
    const keys = entries.map(keyOf);
    keys.forEach((key) => sending.add(key));
    drawInbox();
    try {
      return await sendBatch(entries, label, keys);
    } finally {
      keys.forEach((key) => sending.delete(key));
      drawInbox();
    }
  }

  async function sendBatch(entries, label, keys) {
    ui.busy = true;
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

  /**
   * @returns {string} what happens after a signature with the undo window the operator set: "3 s remain to undo",
   * or "it takes effect at once" for 0.
   */
  const undoWords = () => (settings.undo > 0 ? `${settings.undo} s remain to undo` : "it takes effect at once");

  function undoToast(batch, label) {
    if (!(batch.due > nowSeconds())) {
      toast(label, ["Done: no undo window is set."], true);
      load();
      return;
    }
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
    return withGrantNotes(item, submit([entryOf(item, "approve", "")], `${item.kind === "operator" ? "Run" : "Grant"}: ${short(item.title)}`));
  }

  /**
   * @param {Object} item the granted inbox item.
   * @param {Promise<boolean>|boolean} granted whether its grant went through.
   * @returns {Promise<boolean>} granted; once it holds, the item's line comments go to its requester as one post and
   * are forgotten.
   */
  async function withGrantNotes(item, granted) {
    const done = await granted;
    const notes = lineNotes(keyOf(item));
    if (!done || !notes) {
      return done;
    }
    if (!item.to) {
      toast("Line comments kept", ["The card names no agent to post them to."], false);
    } else if (await radioSend({to: item.to, text: `Granted: ${item.title}. Notes:\n${notes}`, upload: "", cls: "post", voice: ""})) {
      setLineMarks(keyOf(item), []);
    }
    return done;
  }

  const chooseOne = (item, label) => (picking(item) ? collectPick(item, label) : submit([entryOf(item, "approve", label)], `Choice: ${shownPick(label)}`));
  const answerPick = (item, label) => (picking(item) ? collectPick(item, label) : answerRow(item, label));
  const grantSolo = (item) => (item.kind === "rule" ? acceptRule(item) : withGrantNotes(item, submit([entryOf(item, "approve", "")], `Grant: ${short(item.title)}`)));
  const asked = (item) => item.kind === "operator" && item.check === "decision";

  async function answerRow(item, answer) {
    if (!item.agent) {
      toast("Answer: no agent to send it to", ["The row names no adding agent; answer in its session."], false);
      return;
    }
    if (await submit([entryOf(item, "approve", answer)], `Answer: ${shownPick(answer)}`)) {
      forgetDraft(item.id);
    }
  }

  const signsFor = (item) => `${item.agent} gets this answer as a call once your passkey signs it`;

  /**
   * @param {Object} item an inbox item.
   * @param {Function} after called before a picked answer is sent.
   * @returns {HTMLElement|Array|null} the choiceDialog() of a decision or a decision row with named options, with its recipient line for a row; only
   * that line for a Yes/No row and null for a permission ask or a Yes/No decision, which booleanActions() answers; null for every other item.
   */
  const choiceOf = (item, after) => {
    if (Answers.boolean(item)) {
      return asked(item) ? answerTo(item) : null;
    }
    if (item.kind === "decision") {
      return choiceDialog(item, {pick: (label) => { after(); chooseOne(item, label); }, toggled: new Set(), chosen: ui.selected.has(keyOf(item)) ? grantLabel(item) : "", locked: item.held, hint: signsFor(item), group: "", other: OTHER_PROMPT});
    }
    const shown = ui.selected.has(keyOf(item)) ? grantLabel(item) : "";
    return asked(item) ? [answerTo(item), choiceDialog(item, {pick: (label) => { after(); answerPick(item, label); }, toggled: new Set(), chosen: shown, locked: item.held, hint: signsFor(item), group: "", other: OTHER_PROMPT})] : null;
  };

  /**
   * @param {Object} item a decision row of the register.
   * @returns {HTMLElement} who receives the answer: the row's first agent with role A, which any agent can set, so the operator sees it before signing.
   */
  const UNASSIGNED = "No agent holds role A on this row: answer in its session.";
  const answerTo = (item) => h("p", {class: "muted answer-to"}, item.agent ? ["Your answer goes to ", h("strong", {}, revealed(item.agent)), " as a passkey-signed call that wakes it at once, with the row id and your answer only."] : UNASSIGNED);

  const deniable = (item) => item.deniable || item.kind === "review";
  const withNotes = (item, reason) => [reason, lineNotes(keyOf(item))].filter(Boolean).join(LINE_JOIN).slice(0, DENY_REASON);
  const denialOf = (item, reason) => ({...entryOf(item, "reject", ""), channel: lineNotes(keyOf(item)) ? "call" : "post", reason: withNotes(item, reason), to: item.to});
  const pickable = (item) => !item.held && (collectable(item) || deniable(item));

  const unsettled = (item) => item.reviews.filter((review) => review.status !== "approved");

  /**
   * @param {Object[]} items the entries to grant.
   * @returns {Object[]} items after the pending reviews that their commit rows verify and that are not among them yet.
   */
  function withReviews(items) {
    const keys = new Set(items.map(keyOf));
    const linked = new Set(items.flatMap((item) => unsettled(item).map((review) => review.id)));
    return [...state.inbox.filter((entry) => entry.kind === "review" && linked.has(entry.id) && !entry.held && !keys.has(keyOf(entry))), ...items];
  }

  const denyNote = () => `Every entry and every full command that gets denied; each requester gets its denial and the reason by post. After the click ${undoWords()}, and one passkey signature covers the whole selection.`;

  function grantNote(alone, batched) {
    const solos = alone ? ` Each rule and each red-gate review first asks its own signature, one after the other (${alone}).` : "";
    const rest = batched ? ` ${alone ? "Then the" : "The"} passkey signs the rest once, commit rows settling after the reviews they verify.` : "";
    return `Every entry and every full command that gets granted.${solos}${rest} After each signature ${undoWords()}.`;
  }

  function bulk(items, label, deny) {
    const usable = items.filter(deny ? deniable : batchable);
    const alone = deny ? [] : items.filter(solo);
    if (!usable.length && !alone.length) {
      toast(`${label}: nothing to ${deny ? "deny" : "grant"}`, [], false);
      return;
    }
    const labels = new Map([...usable, ...alone].map((item) => [keyOf(item), deny ? "" : grantLabel(item)]));
    const rows = [...usable, ...alone].map((item) => h("li", {},
      h("div", {class: "row"}, pill(ITEM_LABELS[item.kind], KIND_TONES[item.kind]), labels.get(keyOf(item)) ? h("span", {class: "muted"}, revealed(`→ ${shownPick(labels.get(keyOf(item)))}`)) : null),
      h("strong", {}, revealed(item.title)),
      item.kind === "operator" ? h("div", {class: "command"}, h("code", {}, revealed(item.command))) : null,
      item.kind === "operator" ? h("span", {class: "muted"}, revealed(`in ${item.directory}`)) : null,
      item.kind === "ask" ? h("div", {class: "command"}, h("code", {}, revealed(item.command))) : null));
    const confirm = h("button", {type: "button", class: deny ? "btn danger" : "btn primary"}, `${deny ? "Deny" : "Grant"} ${usable.length + alone.length}`);
    const reason = deny ? h("textarea", {class: "field", maxlength: DENY_REASON, rows: 3, placeholder: "e.g. make the gate green first", "data-skills": ""}) : null;
    confirm.addEventListener("click", async () => {
      closeSheet();
      for (const item of alone) {
        if (!(await grantSolo(item))) {
          return;
        }
      }
      if (usable.length && (await submit(usable.map((item) => (deny ? denialOf(item, reason.value) : entryOf(item, "approve", labels.get(keyOf(item))))), `${label}: ${usable.length} entries`))) {
        for (const item of usable) {
          if (deny && lineNotes(keyOf(item))) {
            setLineMarks(keyOf(item), []);
          } else if (!deny) {
            await withGrantNotes(item, true);
          }
        }
      }
    });
    openSheet(label, [h("p", {class: "muted"}, deny ? denyNote() : grantNote(alone.length, usable.length)), h("ul", {class: "mini"}, rows), ...(deny ? [reasonChips(reason), h("label", {class: "deny-reason"}, "Reason (optional, every requester reads it)", reason)] : []),
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
    const grantable = chosen.filter(collectable);
    return {
      chosen,
      grant: h("button", {type: "button", class: "btn small primary", ...named(`Grant selection (${grantable.length})`), disabled: !grantable.length || ui.busy, on: {click: () => bulk(withReviews(chosen), "Grant selection", false)}}, icon("bi-check2-square"), `Grant ${grantable.length}`),
      deny: h("button", {type: "button", class: "menu-item danger", ...named(`Deny selection (${denials.length})`, `Deny selection (${denials.length}): each requester gets its denial and an optional reason by post, one passkey signature, then ${undoWords()}`), disabled: !denials.length || ui.busy, on: {click: () => bulk(chosen, "Deny selection", true)}}, icon("bi-x-square"), `Deny ${denials.length}`),
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

  function toggle(item) {
    if (!item || !pickable(item)) {
      return;
    }
    const key = keyOf(item);
    flip(key);
    ui.cursor = Math.max(visibleInbox().findIndex((entry) => keyOf(entry) === key), 0);
    drawInbox();
    drawGrant();
  }

  function reviewsPill(item) {
    if (!item.reviews.length) {
      return null;
    }
    const waiting = unsettled(item).length;
    return pill(`reviews ${item.reviews.length - waiting}/${item.reviews.length} approved`, waiting ? "neutral" : "ok");
  }

  function runButton(item) {
    const waiting = unsettled(item);
    if (!waiting.length) {
      return iconBtn("bi-play-fill", "Run", "btn small primary", () => approveOne(item));
    }
    const stuck = waiting.some((review) => review.status !== "pending");
    const why = stuck
      ? "A review its commit verifies is rejected or unknown to this hub: the run would fail at its verify step"
      : `Approve the ${waiting.length} reviews its commit verifies, then run it: each red-gate review asks its own signature, the rest goes with the row in one`;
    return h("button", {type: "button", class: "btn small primary", ...named(`Approve ${waiting.length} and run`, why), disabled: stuck || ui.busy, on: {click: () => (collecting(item) ? collect(item) : bulk(withReviews([item]), "Approve and run", false))}}, icon("bi-play-fill"), `Approve ${waiting.length} and run`);
  }

  const blockedButton = (glyph, word, reason) => h("button", {type: "button", class: "btn small", disabled: true, "data-blocked": "", ...named(word, `${word}: not possible now. ${reason}`)}, icon(glyph), word);

  function actionsFor(item) {
    if (item.held) {
      return [h("span", {class: "muted"}, "takes effect …")];
    }
    const buttons = [];
    const grant = (button) => buttons.push(grantPress(button, item));
    if (item.kind === "review") {
      grant(iconBtn("bi-check-lg", "Grant", "btn small primary", () => approveOne(item)));
      buttons.push(denySplit(item));
    } else if (item.kind === "ask") {
      grant(iconBtn("bi-check-lg", "Grant", "btn small primary", () => approveOne(item), "Grant: allow this one call"));
    } else if (Answers.pair(item)) {
      buttons.push(...yesNoButtons(item, (label) => (asked(item) ? answerPick(item, label) : chooseOne(item, label))));
    } else if (item.kind === "decision" && item.recommended) {
      grant(h("button", {type: "button", class: "btn small primary", ...named(revealed(`Recommendation: ${shownPick(item.recommended)}`)), on: {click: () => approveOne(item)}}, icon("bi-check-lg"), revealed(shownPick(item.recommended))));
    } else if (item.kind === "operator" && item.runnable) {
      grant(runButton(item));
    } else if (item.kind === "operator" && item.blocked) {
      buttons.push(blockedButton("bi-play-fill", "Run", item.blocked));
    } else if (item.kind === "rule") {
      grant(h("button", {type: "button", class: "btn small primary", ...named("Accept", "Accept: the passkey signs exactly this rule, then it applies"), on: {click: () => approveOne(item)}}, icon("bi-shield-check"), "Accept"));
    }
    if (item.deniable) {
      buttons.push(denySplit(item));
    } else if (item.kind === "operator" && item.blocked) {
      buttons.push(blockedButton("bi-x-lg", "Deny", item.blocked));
    }
    if (item.job && !jobOpen(item.job)) {
      buttons.push(iconBtn("bi-x-circle", "Close", "btn small ghost", () => dismissJob(item.job), "Close: hide the console; a done row disappears with it"));
    }
    return buttons;
  }

  function inboxHeadline(item) {
    return h("button", {type: "button", class: "linkish headline", title: "Open", on: {click: () => openItem(item)}}, revealed(item.kind === "operator" ? item.id : item.kind === "ask" ? item.title.split(": ")[0] : item.title));
  }

  /**
   * @param {Object} item an inbox item.
   * @returns {string} what the item waits for once it was clicked: the passkey, the undo window, or the Grant of a
   * Select pick; "" for an item nobody clicked yet.
   */
  function waitOf(item) {
    const to = item.agent ? ` to ${item.agent}` : "";
    if (sending.has(keyOf(item))) {
      return `Clicked: the hub stores the answer and sends it${to} once your passkey signs it`;
    }
    if (item.held) {
      return `Signed: waits out the undo window of a few seconds, then the hub delivers it${to} and the card closes`;
    }
    if (grantMode() === GRANT_SELECT && ui.selected.has(keyOf(item))) {
      const label = chosenLabel(item);
      return `${label === undefined ? "Selected" : `Picked "${shownPick(label)}"`}: Select mode collects it until you press Grant selection at the top; pick it again to take it back`;
    }
    return "";
  }

  /**
   * @param {Object} item an inbox item.
   * @param {Array} actions its Grant and Deny nodes.
   * @returns {HTMLElement|null} one code box with the item's command and diff and the actions in its foot, or null for an
   * item with neither.
   */
  function itemCode(item, actions) {
    const commanded = item.kind === "ask" || (item.kind === "operator" && !asked(item));
    const command = commanded ? h("div", {class: "command", "data-path": item.directory || "-"}, h("code", {}, revealed(item.command))) : null;
    const where = commanded ? h("span", {class: "muted code-where"}, revealed(`in ${dash(item.directory)}`)) : null;
    const diff = diffBlocks(item);
    return command || diff ? codeBox(keyOf(item), "preview", [command, where, diff], commanded ? item.command : "", actions, null) : null;
  }

  function inboxItem(item, index) {
    const red = item.kind === "review" && item.gate !== "pass";
    const wait = waitOf(item);
    const actions = actionsFor(item);
    const code = itemCode(item, actions);
    const classes = ["item", "entry", `k-${item.kind}`, "waiting", isGreen(item) ? "green" : "", red ? "red" : "", item.held ? "held" : "", wait ? "pending" : "", index === ui.cursor ? "cursor" : ""].filter(Boolean).join(" ");
    const done = doneItem(item);
    const selected = grantMode() === GRANT_SELECT ? String(ui.selected.has(keyOf(item))) : null;
    return h("li", {class: classes, "data-index": index, "data-ref": keyOf(item), "data-to": item.to || null, "data-blocked": item.blocked ? "" : null, "data-done": done ? "" : null, "aria-selected": selected, "aria-busy": wait ? "true" : null, title: item.blocked || wait || null},
      h("div", {class: "msg-meta"},
        when(item.ts),
        wait ? h("span", {class: "wait-spin", role: "status", "aria-label": wait, title: wait}) : null,
        done ? pill("done", "ok") : null,
        asked(item) ? pill("Decision", KIND_TONES.decision) : pill(ITEM_LABELS[item.kind], KIND_TONES[item.kind]),
        item.kind === "review" ? pill(item.gate === "pass" ? "Gate green" : "Gate red", item.gate === "pass" ? "ok" : "bad") : null,
        reviewsPill(item),
        item.warnings.map((warning) => pill(warning, "bad")),
        item.pinned ? pill("pinned", "violet") : null,
        item.until ? pill(`until ${absolute.format(stampOf(item.until))}`, "neutral") : null),
      h("div", {class: "entry-body"},
        h("div", {class: "route"},
          inboxHeadline(item),
          item.agent ? agentLink(item.agent) : null),
        item.kind === "review" ? h("div", {class: "muted"}, revealed(item.detail), item.score ? revealed(` · ${item.score}`) : "") : null,
        asked(item) ? h("p", {class: "text question"}, revealed(item.title)) : null,
        item.kind === "operator" && item.detail && item.detail !== "-" ? h("p", {class: "text reason"}, revealed(item.detail)) : null,
        item.blocked ? h("p", {class: "item-blocked"}, icon("bi-slash-circle"), item.blocked) : null,
        code,
        item.job ? consoleOf(item.job) : null,
        item.kind === "rule" ? ruleRequestBody(item) : null,
        choiceOf(item, () => {}),
        feedbackList(keyOf(item))),
      h("div", {class: "item-actions line-actions"},
        code ? null : actions,
        h("span", {class: "spacer"}),
        iconBtn("bi-hourglass-split", "1 h", "btn small ghost", () => mark(item, nowSeconds() + 3600, item.pinned), "1 h: snooze for one hour"),
        iconBtn("bi-sunrise", "tomorrow", "btn small ghost", () => mark(item, tomorrow(), item.pinned), "tomorrow: snooze until 8 am tomorrow"),
        item.until ? iconBtn("bi-alarm", "wake", "btn small ghost", () => mark(item, 0, item.pinned), "wake: show again") : null,
        iconBtn(item.pinned ? "bi-pin-angle-fill" : "bi-pin-angle", item.pinned ? "unpin" : "pin", "btn small ghost", () => mark(item, item.until, !item.pinned))));
  }

  function inboxScreen() {
    inboxDom = h("div", {class: "inbox", "data-panel": "tasks/operator"});
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
    const sig = JSON.stringify([mode, items.map(withoutOutput), [...ui.selected], [...choices], [...sending], ui.cursor, ui.snoozed, ui.busy, Math.floor(nowSeconds() / 60), diffView.version, state.messages.map((message) => message.id)]);
    if (sig === inboxSig) {
      repaintConsoles(items);
      return;
    }
    inboxSig = sig;
    const hidden = openInbox().length - waitingCount();
    const snoozed = h("input", {type: "checkbox", checked: ui.snoozed, on: {change: (event) => {
      ui.snoozed = event.target.checked;
      drawInbox();
    }}});
    keepTyping(inboxDom, () => inboxDom.replaceChildren(
      h("div", {class: "inbox-head"}, h("h2", {class: "group-title"}, "Waits on Operator", counter(waitingCount())), h("span", {class: "spacer"}),
        hidden ? h("label", {class: "check"}, snoozed, `${hidden} snoozed`) : null),
      onLocalhost() ? "" : h("p", {class: "muted"}, "The passkey signs grants only under ", localLink()),
      ...inboxRows(items)));
    settleConsoles(items);
  }

  /**
   * @param {Object[]} items the visible inbox items in cursor order.
   * @returns {Array} the open rows, then the done rows (signed within their undo window, or their job ended) under a
   * Done (n) fold at the end, closed until the operator opens it.
   */
  function inboxRows(items) {
    const rows = items.map((item, index) => [item, index]);
    const live = rows.filter(([item]) => !doneItem(item));
    const done = rows.filter(([item]) => doneItem(item));
    const fold = done.length ? h("details", {class: "inbox-done", open: inboxDoneOpen, on: {toggle: (event) => {
      inboxDoneOpen = event.currentTarget.open;
    }}}, h("summary", {}, `Done (${done.length})`), h("ol", {class: "inbox-list"}, done.map(([item, index]) => inboxItem(item, index)))) : null;
    return [live.length ? h("ol", {class: "inbox-list"}, live.map(([item, index]) => inboxItem(item, index))) : emptyState("All done", "Nothing is waiting for you right now."), fold].filter(Boolean);
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
      h("div", {class: "who"}, pill(ITEM_LABELS[item.kind], KIND_TONES[item.kind]), item.agent ? agentLink(item.agent) : null, when(item.ts)),
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
