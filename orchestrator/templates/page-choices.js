  const CHOICE_ICONS = {post: "bi-envelope", call: "bi-telephone", newsletter: "bi-newspaper", broadcast: "bi-broadcast", "pan-pan": "bi-exclamation-triangle", security: "bi-shield-exclamation", mayday: "bi-life-preserver"};
  const choiceAsk = {to: new Set(), dom: null, names: ""};

  async function requestChoices(cls) {
    const direct = TO_ONE.some(([id]) => id === cls);
    const to = direct ? [...choiceAsk.to].sort((a, b) => a.localeCompare(b)) : ["*"];
    if ((direct && !to.length) || (cls === "mayday" && !confirmMayday())) {
      return;
    }
    const label = `Choice request (${CLASSES[cls]}) to ${direct ? to.join(", ") : "all"}`;
    const signed = await signedProof("/api/choices/sign", {class: cls, to}, label);
    if (!signed) {
      return;
    }
    const result = await sendJson("/api/choices", {class: cls, to, proof: signed.proof});
    if (!result.ok || !result.data) {
      toast(`${label} failed`, fail(result), false);
      return;
    }
    toast(`${label}: ${result.data.ok ? "sent" : "stored, sending failed"}`, [...result.data.ids.map((id) => `kvb-orchestrator msg ${id}`), ...runLines(result.data)], result.data.ok);
    await load();
  }

  function choiceMenu() {
    const picks = h("div", {class: "choice-agents", role: "group", "aria-label": "Post or call to"});
    const count = counter(0);
    const button = ([id, label]) => h("button", {type: "button", class: "btn small", "data-channel": id, ...named(label, `${label}: ask for every open decision as a choice, signed with your passkey. ${CHANNEL_HINTS[id]}`), on: {click: () => requestChoices(id)}},
      icon(CHOICE_ICONS[id]), label);
    const direct = TO_ONE.map(button);
    choiceAsk.dom = {picks, count, direct};
    choiceAsk.names = "";
    return h("details", {class: "menu choice-request", id: "choice-request"},
      h("summary", named("Request choices", "Request choices: every open decision comes back as a choice, signed with your passkey"), icon("bi-ui-checks"), "Request choices", caret()),
      h("div", {class: "menu-box end", role: "group", "aria-label": "Choice requests"},
        h("h3", {}, "Post or call to", count), picks, h("div", {class: "choice-buttons"}, direct),
        h("h3", {}, "To all"), h("div", {class: "choice-buttons"}, TO_ALL.map(button))));
  }

  function syncChoices() {
    choiceAsk.dom.count.textContent = String(choiceAsk.to.size);
    for (const button of choiceAsk.dom.direct) {
      button.disabled = !choiceAsk.to.size;
    }
  }

  function pickChoice(name, on) {
    if (on) {
      choiceAsk.to.add(name);
    } else {
      choiceAsk.to.delete(name);
    }
    syncChoices();
  }

  function drawChoices() {
    const dom = choiceAsk.dom;
    if (!dom || !dom.picks.isConnected) {
      return;
    }
    const names = agentNames();
    for (const name of [...choiceAsk.to]) {
      if (!names.includes(name)) {
        choiceAsk.to.delete(name);
      }
    }
    const sig = JSON.stringify(names);
    if (sig !== choiceAsk.names) {
      choiceAsk.names = sig;
      dom.picks.replaceChildren(...(names.length ? names.map((name) => h("label", {class: "check"},
        h("input", {type: "checkbox", value: name, checked: choiceAsk.to.has(name), on: {change: (event) => pickChoice(name, event.target.checked)}}), name)) : [h("p", {class: "muted"}, "No agent known yet.")]));
    }
    syncChoices();
  }
