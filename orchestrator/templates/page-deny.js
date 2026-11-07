  const DENY_CHANNELS = [["post", true, "sobald sein Zug endet"], ["call", true, "sofort, weckt ihn"], ["newsletter", false, "sobald ihr Zug endet"], ["broadcast", false, "sofort"], ["pan-pan", false, "sofort, dringend"], ["security", false, "sofort, als Sicherheitsmeldung"]];
  const DENY_REASON = 2000;
  const requesterOf = (item) => item.agent || "den anfragenden Agenten";

  function denyNow(item, channel, reason) {
    return submit([{...entryOf(item, "reject", ""), channel, reason}], `Ablehnung (${CLASSES[channel]}): ${short(item.title)}`);
  }

  function denySheet(item) {
    const name = `deny-${keyOf(item)}`;
    const choices = DENY_CHANNELS.map(([id, direct, hint]) => h("label", {class: "deny-channel"},
      h("input", {type: "radio", name, value: id, checked: id === "post"}),
      h("span", {}, h("strong", {}, CLASSES[id]), h("small", {}, `an ${direct ? requesterOf(item) : "alle"}, ${hint}`))));
    const reason = h("textarea", {class: "field", maxlength: DENY_REASON, rows: 3, placeholder: "z. B. erst das Gate grün machen"});
    const confirm = h("button", {type: "button", class: "btn danger"}, icon("bi-x-lg"), "Ablehnen");
    confirm.addEventListener("click", () => {
      const picked = choices.map((label) => label.querySelector("input")).find((input) => input.checked);
      closeSheet();
      denyNow(item, picked.value, reason.value);
    });
    openSheet("Ablehnen", [
      h("div", {class: "who"}, pill(ITEM_LABELS[item.kind], KIND_TONES[item.kind]), item.agent ? person(item.agent) : null),
      h("p", {class: "text"}, item.title),
      h("fieldset", {class: "deny-channels"}, h("legend", {}, "Kanal"), choices),
      h("label", {class: "deny-reason"}, "Grund (optional, der Agent liest ihn mit)", reason),
      h("p", {class: "muted"}, "Der Passkey signiert die Ablehnung samt Kanal und Grund; danach bleiben 3 s zum Rückgängigmachen.",
        " Mayday bleibt dem Operator vorbehalten."),
      h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Abbrechen", "btn ghost", closeSheet), confirm)], false);
    reason.focus();
  }

  function denySplit(item) {
    const main = iconBtn("bi-x-lg", "Ablehnen", "btn small danger", () => denyNow(item, "post", ""), `Ablehnen: per Post an ${requesterOf(item)}, 3 s rückgängig`);
    const more = h("button", {type: "button", class: "btn small danger icon-only", "aria-haspopup": "dialog", ...named("Ablehnen über …", "Ablehnen über einen anderen Kanal oder mit Grund")}, caret());
    more.addEventListener("click", (event) => {
      event.stopPropagation();
      denySheet(item);
    });
    return h("div", {class: "deny-split", role: "group", "aria-label": "Ablehnen"}, main, more);
  }
