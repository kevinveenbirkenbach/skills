  const DENY_CHANNELS = [["post", true, "when its turn ends"], ["call", true, "at once, wakes it"], ["newsletter", false, "when their turn ends"], ["broadcast", false, "at once"], ["pan-pan", false, "at once, urgent"], ["security", false, "at once, as a safety notice"]];
  const DENY_REASON = 2000;
  const requesterOf = (item) => item.to || "nobody (recipient unclear)";

  function denyNow(item, channel, reason) {
    return submit([{...entryOf(item, "reject", ""), channel, reason, to: item.to}], `Denial (${CLASSES[channel]}): ${short(item.title)}`);
  }

  function denySheet(item) {
    const name = `deny-${keyOf(item)}`;
    const choices = DENY_CHANNELS.map(([id, direct, hint]) => h("label", {class: "deny-channel"},
      h("input", {type: "radio", name, value: id, checked: id === "post"}),
      h("span", {}, h("strong", {}, CLASSES[id]), h("small", {}, `to ${direct ? requesterOf(item) : "all"}, ${hint}`))));
    const reason = h("textarea", {class: "field", maxlength: DENY_REASON, rows: 3, placeholder: "e.g. make the gate green first"});
    const confirm = h("button", {type: "button", class: "btn danger"}, icon("bi-x-lg"), "Deny");
    confirm.addEventListener("click", () => {
      const picked = choices.map((label) => label.querySelector("input")).find((input) => input.checked);
      closeSheet();
      denyNow(item, picked.value, reason.value);
    });
    openSheet("Deny", [
      h("div", {class: "who"}, pill(ITEM_LABELS[item.kind], KIND_TONES[item.kind]), item.agent ? person(item.agent) : null),
      h("p", {class: "text"}, item.title),
      h("fieldset", {class: "deny-channels"}, h("legend", {}, "Channel"), choices),
      h("label", {class: "deny-reason"}, "Reason (optional, the agent reads it too)", reason),
      h("p", {class: "muted"}, "The passkey signs the denial with channel, recipient and reason; then 3 s remain to undo it.",
        " Mayday stays reserved for the operator."),
      h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), confirm)], false);
    reason.focus();
  }

  function denySplit(item) {
    const main = iconBtn("bi-x-lg", "Deny", "btn small danger", () => denyNow(item, "post", ""), `Deny: by post to ${requesterOf(item)}, 3 s to undo`);
    const more = h("button", {type: "button", class: "btn small danger icon-only", "aria-haspopup": "dialog", ...named("Deny via …", "Deny via another channel or with a reason")}, caret());
    more.addEventListener("click", (event) => {
      event.stopPropagation();
      denySheet(item);
    });
    return h("div", {class: "deny-split", role: "group", "aria-label": "Deny"}, main, more);
  }
