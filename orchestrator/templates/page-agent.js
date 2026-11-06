  function history(key) {
    const known = (people()[key] || {names: [nameOf(key)]}).names;
    const radio = state.radio.filter((row) => row.source === key || row.targets.includes(key)).map((row) => ({ts: row.ts, mine: row.from === HUMAN, who: row.from, text: row.text}));
    const sent = state.messages.filter((message) => known.includes(message.to) || message.to === "*").map((message) => ({ts: message.created_ts, mine: true, who: HUMAN, text: message.upload ? `${message.text}\n📎 ${message.upload}` : message.text, id: message.id}));
    const hubIds = new Set(sent.map((entry) => entry.id));
    const relayed = radio.filter((entry) => !(entry.who === HUMAN && [...hubIds].some((id) => entry.text.includes(`[kvb-orchestrator msg ${id}]`))));
    return [...relayed, ...sent].sort((a, b) => a.ts - b.ts).slice(-80);
  }

  function drawDrawer() {
    if (!drawerDom) {
      return;
    }
    const node = state.graph.nodes.find((entry) => entry.id === ui.agent);
    const tasks = node ? node.tasks : [];
    const claims = node ? node.claims : [];
    drawerDom.info.replaceChildren(
      h("h3", {}, "Aufgaben", counter(tasks.length)),
      tasks.length ? h("ul", {class: "mini"}, tasks.map((task) => h("li", {},
        h("div", {class: "row"}, h("code", {}, task.task), status(task.status)),
        h("span", {}, dash(task.title)),
        h("span", {class: "roles"}, [task.worker ? "Worker" : "", task.letters ? `Rollen ${task.letters}` : ""].filter(Boolean).join(" · "))))) : h("p", {class: "muted"}, "Keine offenen Aufgaben."),
      h("h3", {}, "Claims", counter(claims.length)),
      claims.length ? h("ul", {class: "mini"}, claims.map((claim) => h("li", {},
        h("div", {class: "row"}, h("code", {}, claim.office), claim.beat === null ? null : h("span", {class: "muted"}, "Puls ", when(claim.beat))),
        h("span", {}, dash(claim.work)),
        h("span", {class: "muted"}, `${dash(claim.runtime)} · seit ${dash(claim.since)}`)))) : h("p", {class: "muted"}, "Keine Claims."));
    const rows = history(ui.agent);
    drawerDom.history.replaceChildren(rows.length
      ? h("div", {}, rows.map((row) => h("div", {class: `bubble ${row.mine ? "mine" : "theirs"}`}, h("span", {class: "muted"}, `${row.who} · `, when(row.ts)), row.text)))
      : h("p", {class: "muted"}, "Kein Verlauf im gewählten Zeitraum."));
  }

  async function loadSubagents(key, holder, life) {
    if (!SESSION_ID.test(key)) {
      holder.replaceChildren(h("p", {class: "muted"}, "Keine Session bekannt."));
      return;
    }
    let data = null;
    try {
      const response = await fetch(`/api/subagents?session=${encodeURIComponent(key)}`, {cache: "no-store"});
      data = response.ok ? await response.json() : null;
    } catch {
      data = null;
    }
    if (!data) {
      holder.replaceChildren(h("p", {class: "muted"}, "Subagenten nicht lesbar."));
      return;
    }
    life.textContent = stamp(data);
    const rows = data.subagents.map((row) => ({...row, session: key})).sort((a, b) => a.started - b.started);
    holder.replaceChildren(rows.length ? h("ul", {class: "mini"}, rows.map((row) => {
      const item = h("li", {},
        h("div", {class: "row"}, h("button", {type: "button", class: "linkish", title: "Transkript im Stream zeigen", on: {click: () => focusSub(row.session, row.id)}}, `${row.type}: ${row.description}`), row.finished ? pill("fertig", "neutral") : pill("läuft", "ok")),
        h("span", {class: "muted"}, `Tiefe ${row.depth} · `, when(row.started), stamp(row) ? ` · ${stamp(row)}` : ""));
      item.style.marginLeft = `${(row.depth - 1) * 18}px`;
      return item;
    })) : h("p", {class: "muted"}, "Keine Subagenten."));
  }

  async function deliver(text, file, cls) {
    let upload = "";
    if (file) {
      if (file.size > UPLOAD_LIMIT) {
        toast("Datei zu groß", [`${file.name}: höchstens 50 MiB`], false);
        return false;
      }
      const stored = await send(`/api/uploads?name=${encodeURIComponent(file.name)}`, file, "application/octet-stream");
      if (!stored.ok || !stored.data) {
        toast("Upload fehlgeschlagen", [`${stored.status} ${stored.text}`.trim()], false);
        return false;
      }
      upload = stored.data.id;
    }
    return message(nameOf(ui.agent), text, upload, cls);
  }

  async function message(to, text, upload, cls) {
    const label = TO_ONE.find(([id]) => id === cls)[1];
    const result = await sendJson("/api/messages", {to, text, upload, class: cls});
    if (!result.ok || !result.data) {
      toast(`${label} an ${to} fehlgeschlagen`, [`${result.status} ${result.text}`.trim()], false);
      return false;
    }
    toast(`${label} an ${to}: ${result.data.ok ? "gesendet" : "gespeichert, Senden fehlgeschlagen"}`, [`kvb-orchestrator msg ${result.data.id}`, ...runLines(result.data)], result.data.ok);
    await load();
    return true;
  }

  function openAgent(who) {
    const drawer = document.getElementById("drawer");
    const key = agentKey(who);
    const name = nameOf(key);
    ui.agent = key;
    const text = h("textarea", {"aria-label": `Nachricht an ${name}`, placeholder: `Nachricht an ${name} …`});
    const file = h("input", {type: "file", class: "field", "aria-label": "Datei anhängen"});
    const button = h("button", {type: "submit", class: "btn primary"}, "Senden");
    const classes = choice("to-one", TO_ONE, "post");
    const form = h("form", {class: "drawer-form"}, text, file, classes,
      h("p", {class: "muted"}, "Post kommt am Ende des Zuges an, Call sofort mit Lesebestätigung; prüfbar mit operator_message."),
      h("div", {class: "actions"}, h("span", {class: "spacer"}), micButton(text), button));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!text.value.trim()) {
        return;
      }
      button.disabled = true;
      if (await deliver(text.value, file.files[0] || null, picked(classes))) {
        text.value = "";
        file.value = "";
      }
      button.disabled = false;
    });
    const info = h("div", {});
    const subs = h("div", {}, h("p", {class: "muted"}, "Lade Subagenten …"));
    const log = h("div", {"aria-live": "polite"});
    const life = h("span", {class: "muted"});
    const former = (people()[key] || {names: []}).names.filter((entry) => entry !== name);
    drawer.replaceChildren(
      h("div", {class: "drawer-head"}, face(name, true), life, h("div", {}, h("h2", {class: "panel-title"}, name), h("span", {class: "muted"}, former.length ? `Agent · früher ${former.join(", ")}` : "Agent")), h("span", {class: "spacer"}),
        h("button", {type: "button", class: "btn small ghost", "aria-label": "Schließen", on: {click: closeAgent}}, "×")),
      h("div", {class: "drawer-body"}, info, h("h3", {}, "Subagenten"), subs, h("h3", {}, "Verlauf"), log),
      form);
    drawer.hidden = false;
    drawerDom = {info, history: log};
    drawDrawer();
    loadSubagents(key, subs, life);
    text.focus();
  }

  function closeAgent() {
    document.getElementById("drawer").hidden = true;
    drawerDom = null;
    ui.agent = null;
  }

  function agentNames() {
    const names = new Set([...state.graph.nodes.filter((node) => node.kind === "session" || node.kind === "chair").map((node) => nameOf(node.id)), ...state.priority]);
    return [...names].sort((a, b) => a.localeCompare(b));
  }
