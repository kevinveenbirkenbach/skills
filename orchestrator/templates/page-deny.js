  const DENY_CHANNELS = [["post", true, "when its turn ends"], ["call", true, "at once, wakes it"], ["newsletter", false, "when their turn ends"], ["broadcast", false, "at once"], ["pan-pan", false, "at once, urgent"], ["security", false, "at once, as a safety notice"]];
  const DENY_REASON = 2000;
  const DIRECT_DENY = new Set(DENY_CHANNELS.filter(([, direct]) => direct).map(([id]) => id));
  const denyRecipients = (item) => [...new Set([item.to, ...state.claims.map((claim) => claim.agent)].filter((agent) => agent && agent !== HUMAN))].sort();

  /**
   * @param {Object} item the denied inbox item.
   * @param {string} channel the radio class.
   * @param {string} reason the operator's reason, possibly empty.
   * @param {string} to the agent a direct channel tells; a class to all keeps the item's requester.
   */
  async function denyNow(item, channel, reason, to) {
    const denied = await submit([{...entryOf(item, "reject", ""), channel, reason, to: DIRECT_DENY.has(channel) ? to : item.to}], `Denial (${CLASSES[channel]}): ${short(item.title)}`);
    if (denied && lineNotes(keyOf(item))) {
      setLineMarks(keyOf(item), []);
    }
    return denied;
  }

  /**
   * @param {HTMLTextAreaElement} field the field the chips fill.
   * @param {string[]} texts the earlier texts, newest first.
   * @param {string} label the accessible name of the chip group.
   * @returns {Node|null} the texts as chips: a press puts its text into the field, which stays editable; null without
   * texts.
   */
  function presetChips(field, texts, label) {
    if (!texts.length) {
      return null;
    }
    return h("div", {class: "chips reason-chips", role: "group", "aria-label": label}, texts.map((text) => {
      const chip = h("button", {type: "button", class: "chip", title: text}, short(text));
      chip.addEventListener("click", () => {
        field.value = text;
        field.focus();
      });
      return chip;
    }));
  }

  const reasonChips = (field) => presetChips(field, state.reasons, "Recent reasons");
  const NO_RECIPIENT = "Pick the agent to tell: a post or call needs a recipient";
  const NO_AGENT = "No agent to tell: the item names no recipient; pick one under Deny via …";
  let whyOffCount = 0;

  /**
   * @param {HTMLButtonElement} button a button that may be disabled.
   * @returns {root, set}: root wraps the button and carries its tooltip, because a disabled
   * button fires no hover in Chrome; set(why, hint) disables the button and names why while why is not empty, else
   * enables it and names the action hint; aria-describedby gives keyboard users the same text.
   */
  function whyOff(button) {
    whyOffCount += 1;
    const note = h("span", {id: `why-off-${whyOffCount}`, hidden: true});
    const root = h("span", {class: "why-off"}, button, note);
    button.setAttribute("aria-describedby", note.id);
    const set = (why, hint) => {
      button.disabled = Boolean(why);
      root.title = why || hint;
      note.textContent = why || hint;
    };
    return {root, set};
  }

  function denySheet(item) {
    const name = `deny-${keyOf(item)}`;
    const recipient = h("select", {class: "field"}, h("option", {value: ""}, "Pick the agent to tell"),
      denyRecipients(item).map((agent) => h("option", {value: agent, selected: agent === item.to}, revealed(agent))));
    const confirm = h("button", {type: "button", class: "btn danger"}, icon("bi-x-lg"), "Deny");
    const gate = whyOff(confirm);
    const hints = [];
    const picked = () => choices.map((label) => label.querySelector("input")).find((input) => input.checked);
    const paintDeny = () => {
      hints.forEach(([small, direct, hint]) => {
        small.textContent = `to ${direct ? revealed(recipient.value) || "nobody yet: pick a recipient" : "all"}, ${hint}`;
      });
      gate.set(DIRECT_DENY.has(picked().value) && !recipient.value ? NO_RECIPIENT : "", `Deny: ${CLASSES[picked().value]} ${DIRECT_DENY.has(picked().value) ? `to ${revealed(recipient.value)}` : "to all"}, signed by your passkey`);
    };
    const choices = DENY_CHANNELS.map(([id, direct, hint]) => {
      const small = h("small", {});
      hints.push([small, direct, hint]);
      return h("label", {class: "deny-channel"},
        h("input", {type: "radio", name, value: id, checked: id === "call", on: {change: paintDeny}}),
        h("span", {}, h("strong", {}, CLASSES[id]), small));
    });
    recipient.addEventListener("change", paintDeny);
    const reason = h("textarea", {class: "field", maxlength: DENY_REASON, rows: 3, placeholder: "e.g. make the gate green first", "data-skills": item.repo || ""});
    reason.value = lineNotes(keyOf(item)).slice(0, DENY_REASON);
    confirm.addEventListener("click", () => {
      const channel = picked().value;
      closeSheet();
      denyNow(item, channel, reason.value, recipient.value);
    });
    paintDeny();
    openSheet("Deny", [
      h("div", {class: "who"}, pill(ITEM_LABELS[item.kind], KIND_TONES[item.kind]), item.agent ? person(item.agent) : null),
      h("p", {class: "text"}, item.title),
      h("fieldset", {class: "deny-channels"}, h("legend", {}, "Channel"), choices),
      h("label", {class: "deny-recipient"}, "Recipient of a post or call", recipient),
      reasonChips(reason),
      h("label", {class: "deny-reason"}, "Reason (optional, the agent reads it too)", reason),
      h("p", {class: "muted"}, `The passkey signs the denial with channel, recipient and reason; then ${undoWords()}.`,
        " Mayday stays reserved for the operator."),
      h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), gate.root)], false);
    reason.focus();
  }

  function denySplit(item) {
    const hint = `Deny: by post to ${revealed(item.to)}, then ${undoWords()}; with line comments it opens Deny via … with them as the reason`;
    const main = iconBtn("bi-x-lg", "Deny", "btn small danger", () => (lineNotes(keyOf(item)) ? denySheet(item) : denyNow(item, "post", "", item.to)), item.to ? hint : NO_AGENT);
    const gate = whyOff(main);
    gate.set(item.to ? "" : NO_AGENT, hint);
    const more = h("button", {type: "button", class: "btn small danger icon-only", "aria-haspopup": "dialog", ...named("Deny via …", "Deny via another channel or with a reason")}, caret());
    more.addEventListener("click", (event) => {
      event.stopPropagation();
      denySheet(item);
    });
    return h("div", {class: "deny-split", role: "group", "aria-label": "Deny"}, gate.root, more);
  }

  /**
   * @param {Object} item a Yes/No choice or decision row.
   * @param {string} no its No label.
   * @param {Function} answer sends the label it is given.
   */
  function declineSheet(item, no, answer) {
    const words = h("textarea", {class: "field", rows: 4, maxlength: OTHER_LIMIT, "aria-label": "Comment", "data-skills": ""});
    const confirm = h("button", {type: "button", class: "btn danger"}, icon("bi-x-lg"), revealed(no));
    confirm.addEventListener("click", () => {
      closeSheet();
      answer(Answers.declined(no, words.value, OTHER_LIMIT));
    });
    openSheet(`${revealed(no)}: ${short(item.title)}`, [h("p", {class: "muted"}, `Optional: what to do instead; it goes with the answer ${revealed(no)} on one line.`), reasonChips(words), words,
      h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), confirm)], false);
    words.focus();
  }

  /**
   * @param {Object} item a Yes/No choice or decision row.
   * @param {Function} answer sends the label it is given: chooseOne() for a choice, answerPick() for a row.
   * @returns {HTMLElement[]} the grant button answering Yes and the decline button answering No with an optional comment.
   */
  function yesNoButtons(item, answer) {
    const {yes, no} = Answers.pair(item);
    return [
      h("button", {type: "button", class: "btn small primary", disabled: ui.busy, ...named(revealed(yes), `${revealed(yes)}: answer ${short(item.title)}`), on: {click: () => answer(yes)}}, icon("bi-check-lg"), revealed(yes)),
      h("button", {type: "button", class: "btn small danger", disabled: ui.busy, ...named(revealed(no), `${revealed(no)}: answer it, with an optional comment on what to do instead`), on: {click: () => declineSheet(item, no, answer)}}, icon("bi-x-lg"), revealed(no)),
    ];
  }
