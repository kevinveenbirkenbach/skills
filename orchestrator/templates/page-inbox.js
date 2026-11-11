  async function submit(entries, label) {
    ui.busy = true;
    const signed = await proofFor(entries, label);
    if (signed === null) {
      ui.busy = false;
      await load();
      return false;
    }
    const result = await sendJson("/api/inbox/approve", {items: entries, proof: signed.proof});
    ui.busy = false;
    if (!result.ok || !result.data) {
      toast(`${label}: not possible`, fail(result), false);
      await load();
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
    if (item.kind === "rule") {
      return acceptRule(item);
    }
    if (item.kind === "decision") {
      if (!item.recommended) {
        openItem(item);
        return null;
      }
      return submit([entryOf(item, "approve", item.recommended)], `Choice: ${item.recommended}`);
    }
    return submit([entryOf(item, "approve", "")], `${item.kind === "operator" ? "Run" : "Grant"}: ${short(item.title)}`);
  }

  const rejectOne = (item) => submit([entryOf(item, "reject", "")], `Denial: ${short(item.title)}`);
  const chooseOne = (item, label) => submit([entryOf(item, "approve", label)], `Choice: ${label}`);

  const denialOf = (item) => (item.deniable ? {...entryOf(item, "reject", ""), channel: "post", reason: "", to: item.to} : item.kind === "review" ? entryOf(item, "reject", "") : null);
  const pickable = (item) => !item.held && (selectable(item) || denialOf(item) !== null);

  function bulk(items, label, deny) {
    const usable = items.filter(deny ? (item) => denialOf(item) !== null : selectable);
    if (!usable.length) {
      toast(`${label}: nothing to ${deny ? "deny" : "grant"}`, [], false);
      return;
    }
    const rows = usable.map((item) => h("li", {},
      h("div", {class: "row"}, pill(ITEM_LABELS[item.kind], KIND_TONES[item.kind]), item.kind === "decision" && !deny ? h("span", {class: "muted"}, `→ ${item.recommended}`) : null),
      h("strong", {}, item.title),
      item.kind === "operator" ? h("div", {class: "command"}, h("code", {}, item.command)) : null,
      item.kind === "operator" ? h("span", {class: "muted"}, `in ${item.directory}`) : null,
      item.kind === "ask" ? h("div", {class: "command"}, h("code", {}, item.command)) : null));
    const confirm = h("button", {type: "button", class: deny ? "btn danger" : "btn primary"}, `${deny ? "Deny" : "Grant"} ${usable.length}`);
    confirm.addEventListener("click", () => {
      closeSheet();
      submit(usable.map((item) => (deny ? denialOf(item) : entryOf(item, "approve", item.kind === "decision" ? item.recommended : ""))), `${label}: ${usable.length} entries`);
    });
    const note = deny
      ? "Every entry and every full command that gets denied; each requester gets its denial by post. After the click the passkey signs the whole selection once; then 3 s remain to undo."
      : "Every entry and every full command that gets granted. After the click the passkey signs the whole selection once; then 3 s remain to undo.";
    openSheet(label, [h("p", {class: "muted"}, note), h("ul", {class: "mini"}, rows), h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), confirm)], false);
    confirm.focus();
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
    if (item.kind === "review") {
      buttons.push(iconBtn("bi-check-lg", "Grant", "btn small primary", () => approveOne(item)), iconBtn("bi-x-lg", "Deny", "btn small danger", () => rejectOne(item)));
    } else if (item.kind === "ask") {
      buttons.push(iconBtn("bi-check-lg", "Grant", "btn small primary", () => approveOne(item)));
    } else if (item.kind === "decision" && item.recommended) {
      buttons.push(h("button", {type: "button", class: "btn small primary", ...named(`Recommendation: ${item.recommended}`), on: {click: () => approveOne(item)}}, icon("bi-check-lg"), item.recommended));
    } else if (item.kind === "operator" && item.runnable) {
      buttons.push(iconBtn("bi-play-fill", "Run", "btn small primary", () => approveOne(item)));
    } else if (item.kind === "rule") {
      buttons.push(h("button", {type: "button", class: "btn small primary", ...named("Accept", "Accept: the passkey signs exactly this rule, then it applies"), on: {click: () => approveOne(item)}}, icon("bi-shield-check"), "Accept"));
    }
    if (item.deniable) {
      buttons.push(denySplit(item));
    }
    if (item.job && !jobOpen(item.job)) {
      buttons.push(iconBtn("bi-x-circle", "Close", "btn small ghost", () => dismissJob(item.job), "Close: hide the console; a done row disappears with it"));
    }
    return buttons;
  }

  function inboxItem(item, index) {
    const red = item.kind === "review" && item.gate !== "pass";
    const classes = ["item", isGreen(item) ? "green" : "", red ? "red" : "", item.held ? "held" : "", index === ui.cursor ? "cursor" : ""].filter(Boolean).join(" ");
    const box = h("input", {type: "checkbox", "aria-label": `Select ${item.title}`, checked: ui.selected.has(keyOf(item)), disabled: !pickable(item), on: {change: () => toggle(item, true)}});
    return h("li", {class: classes, "data-index": index},
      box,
      h("div", {},
        h("div", {class: "head-row"},
          pill(ITEM_LABELS[item.kind], KIND_TONES[item.kind]),
          item.kind === "review" ? pill(item.gate === "pass" ? "Gate green" : "Gate red", item.gate === "pass" ? "ok" : "bad") : null,
          item.warnings.map((warning) => pill(warning, "bad")),
          item.pinned ? pill("pinned", "violet") : null,
          item.until ? pill(`until ${absolute.format(stampOf(item.until))}`, "neutral") : null,
          h("span", {class: "spacer"}), when(item.ts)),
        h("button", {type: "button", class: "linkish", title: "Open", on: {click: () => openItem(item)}}, item.title),
        item.agent ? h("div", {class: "muted"}, "from ", person(item.agent)) : null,
        item.kind === "review" ? h("div", {class: "muted"}, item.detail, item.score ? ` · ${item.score}` : "") : null,
        item.kind === "operator" && item.title !== item.command ? h("div", {class: "command"}, h("code", {}, item.command)) : null,
        item.kind === "operator" ? h("div", {class: "muted"}, `in ${dash(item.directory)}`, item.detail && item.detail !== "-" ? ` · ${item.detail}` : "") : null,
        item.job ? consoleOf(item.job) : null,
        item.kind === "rule" ? ruleRequestBody(item) : null,
        item.kind === "ask" ? h("div", {class: "muted"}, `in ${dash(item.directory)}`) : null,
        item.kind === "decision" ? h("div", {class: "options"}, item.options.map((option) => h("button", {
          type: "button", class: `option${option.label === item.recommended ? " recommended" : ""}`, title: `${option.label}: your passkey signs this answer, a post to ${item.agent}`, disabled: item.held, on: {click: () => chooseOne(item, option.label)},
        }, h("strong", {}, option.label), option.description ? h("span", {}, option.description) : null))) : null),
      h("div", {class: "item-actions"},
        actionsFor(item),
        item.kind === "operator" ? copyButton(item.command) : null,
        h("span", {class: "spacer"}),
        iconBtn("bi-hourglass-split", "1 h", "btn small ghost", () => mark(item, nowSeconds() + 3600, item.pinned), "1 h: snooze for one hour"),
        iconBtn("bi-sunrise", "tomorrow", "btn small ghost", () => mark(item, tomorrow(), item.pinned), "tomorrow: snooze until 8 am tomorrow"),
        item.until ? iconBtn("bi-alarm", "wake", "btn small ghost", () => mark(item, 0, item.pinned), "wake: show again") : null,
        iconBtn(item.pinned ? "bi-pin-angle-fill" : "bi-pin-angle", item.pinned ? "unpin" : "pin", "btn small ghost", () => mark(item, item.until, !item.pinned))));
  }

  function inboxScreen() {
    inboxDom = h("div", {class: "inbox"});
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
    const sig = JSON.stringify([items.map(withoutOutput), [...ui.selected], ui.cursor, ui.snoozed, ui.busy, Math.floor(nowSeconds() / 60)]);
    if (sig === inboxSig) {
      repaintConsoles(items);
      return;
    }
    inboxSig = sig;
    const green = items.filter(isGreen);
    const chosen = items.filter((item) => ui.selected.has(keyOf(item)));
    const hidden = state.inbox.length - waitingCount();
    const snoozed = h("input", {type: "checkbox", checked: ui.snoozed, on: {change: (event) => {
      ui.snoozed = event.target.checked;
      drawInbox();
    }}});
    const deniable = chosen.filter((item) => denialOf(item) !== null);
    const grantable = chosen.filter(selectable);
    const choose = h("button", {type: "button", class: "btn small soft", ...named(`Grant selection (${grantable.length})`), disabled: !grantable.length || ui.busy, on: {click: () => bulk(chosen, "Grant selection", false)}}, icon("bi-check2-square"), String(grantable.length));
    const deny = h("button", {type: "button", class: "btn small danger", ...named(`Deny selection (${deniable.length})`, `Deny selection (${deniable.length}): each requester gets its denial by post, one passkey signature, 3 s to undo`), disabled: !deniable.length || ui.busy, on: {click: () => bulk(chosen, "Deny selection", true)}}, icon("bi-x-square"), String(deniable.length));
    const all = h("button", {type: "button", class: "btn small primary", ...named(`Grant all green (${green.length})`), disabled: !green.length || ui.busy, on: {click: () => bulk(green, "Grant all green", false)}}, icon("bi-check2-all"), String(green.length));
    inboxDom.replaceChildren(
      h("div", {class: "inbox-head"}, h("h2", {class: "group-title"}, "Inbox", counter(waitingCount())), h("span", {class: "spacer"}),
        hidden ? h("label", {class: "check"}, snoozed, `${hidden} snoozed`) : null),
      h("div", {class: "inbox-actions"}, choose, deny, all),
      onLocalhost() ? "" : h("p", {class: "muted"}, "The passkey signs grants only under ", localLink()),
      items.length ? h("ol", {class: "inbox-list"}, items.map(inboxItem)) : emptyState("All done", "Nothing is waiting for you right now."));
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
      h("p", {class: "text"}, item.title),
      item.command ? h("div", {class: "command"}, h("code", {}, item.command), copyButton(item.command)) : null,
      item.kind === "rule" ? ruleRequestBody(item) : null,
      meta([["Directory", item.directory], ["Warnings", item.warnings.join(", ")], ["Id", item.id]]),
      item.kind === "decision" ? h("div", {class: "options"}, item.options.map((option) => h("button", {
        type: "button", class: `option${option.label === item.recommended ? " recommended" : ""}`, disabled: item.held, on: {click: () => {
          closeSheet();
          chooseOne(item, option.label);
        }},
      }, h("strong", {}, option.label), option.description ? h("span", {}, option.description) : null))) : null,
      h("div", {class: "actions"}, h("span", {class: "spacer"}), actionsFor(item).map((node) => {
        node.addEventListener("click", closeSheet);
        return node;
      })),
    ];
    openSheet(ITEM_LABELS[item.kind], body, false);
  }
