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
  function denyNow(item, channel, reason, to) {
    return submit([{...entryOf(item, "reject", ""), channel, reason, to: DIRECT_DENY.has(channel) ? to : item.to}], `Denial (${CLASSES[channel]}): ${short(item.title)}`);
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

  function denySheet(item) {
    const name = `deny-${keyOf(item)}`;
    const recipient = h("select", {class: "field"}, h("option", {value: ""}, "Pick the agent to tell"),
      denyRecipients(item).map((agent) => h("option", {value: agent, selected: agent === item.to}, revealed(agent))));
    const confirm = h("button", {type: "button", class: "btn danger"}, icon("bi-x-lg"), "Deny");
    const hints = [];
    const picked = () => choices.map((label) => label.querySelector("input")).find((input) => input.checked);
    const paintDeny = () => {
      hints.forEach(([small, direct, hint]) => {
        small.textContent = `to ${direct ? revealed(recipient.value) || "nobody yet: pick a recipient" : "all"}, ${hint}`;
      });
      confirm.disabled = DIRECT_DENY.has(picked().value) && !recipient.value;
    };
    const choices = DENY_CHANNELS.map(([id, direct, hint]) => {
      const small = h("small", {});
      hints.push([small, direct, hint]);
      return h("label", {class: "deny-channel"},
        h("input", {type: "radio", name, value: id, checked: id === "call", on: {change: paintDeny}}),
        h("span", {}, h("strong", {}, CLASSES[id]), small));
    });
    recipient.addEventListener("change", paintDeny);
    const reason = h("textarea", {class: "field", maxlength: DENY_REASON, rows: 3, placeholder: "e.g. make the gate green first"});
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
      h("p", {class: "muted"}, "The passkey signs the denial with channel, recipient and reason; then 3 s remain to undo it.",
        " Mayday stays reserved for the operator."),
      h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), confirm)], false);
    reason.focus();
  }

  function denySplit(item) {
    const main = iconBtn("bi-x-lg", "Deny", "btn small danger", () => denyNow(item, "post", "", item.to), item.to ? `Deny: by post to ${revealed(item.to)}, 3 s to undo` : "Deny: the card names no agent; pick one under Deny via …");
    main.disabled = !item.to;
    const more = h("button", {type: "button", class: "btn small danger icon-only", "aria-haspopup": "dialog", ...named("Deny via …", "Deny via another channel or with a reason")}, caret());
    more.addEventListener("click", (event) => {
      event.stopPropagation();
      denySheet(item);
    });
    return h("div", {class: "deny-split", role: "group", "aria-label": "Deny"}, main, more);
  }
