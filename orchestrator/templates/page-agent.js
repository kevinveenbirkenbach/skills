  function history(key) {
    const known = (people()[key] || {names: [nameOf(key)]}).names;
    const radio = state.radio.filter((row) => row.source === key || row.targets.includes(key)).map((row) => ({ts: row.ts, mine: row.from === HUMAN, who: row.from, text: row.text}));
    const sent = state.messages.filter((message) => known.includes(message.to) || message.to === "*").map((message) => ({ts: message.created_ts, mine: true, who: HUMAN, text: message.upload ? `${message.text}\n📎 ${message.upload}` : message.text, id: message.id, voice: message.voice}));
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
      h("h3", {}, "Tasks", counter(tasks.length)),
      tasks.length ? h("ul", {class: "mini"}, tasks.map((task) => h("li", {},
        h("div", {class: "row"}, h("code", {}, task.task), status(task.status)),
        h("span", {}, dash(task.title)),
        h("span", {class: "roles"}, [task.worker ? "Worker" : "", task.letters ? `Roles ${task.letters}` : ""].filter(Boolean).join(" · "))))) : h("p", {class: "muted"}, "No open tasks."),
      h("h3", {}, "Claims", counter(claims.length)),
      claims.length ? h("ul", {class: "mini"}, claims.map((claim) => h("li", {},
        h("div", {class: "row"}, h("code", {}, claim.office), claim.beat === null ? null : h("span", {class: "muted"}, "Pulse ", when(claim.beat))),
        h("span", {}, dash(claim.work)),
        h("span", {class: "muted"}, `${dash(claim.runtime)} · since ${dash(claim.since)}`)))) : h("p", {class: "muted"}, "No claims."));
    const rows = history(ui.agent);
    drawerDom.history.replaceChildren(rows.length
      ? h("div", {}, rows.map((row) => h("div", {class: `bubble ${row.mine ? "mine" : "theirs"}`}, h("span", {class: "muted"}, `${row.who} · `, when(row.ts)), row.text, voiceReplay(row.voice))))
      : h("p", {class: "muted"}, "No history in the chosen time range."));
  }

  async function loadSubagents(key, holder, life) {
    if (!SESSION_ID.test(key)) {
      holder.replaceChildren(h("p", {class: "muted"}, "No session known."));
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
      holder.replaceChildren(h("p", {class: "muted"}, "Subagents unreadable."));
      return;
    }
    life.textContent = stamp(data);
    const rows = data.subagents.map((row) => ({...row, session: key})).sort((a, b) => a.started - b.started);
    holder.replaceChildren(rows.length ? h("ul", {class: "mini"}, rows.map((row) => {
      const item = h("li", {},
        h("div", {class: "row"}, h("button", {type: "button", class: "linkish", title: "Show transcript in the stream", on: {click: () => focusSub(row.session, row.id)}}, `${row.type}: ${row.description}`), row.finished ? pill("finished", "neutral") : pill("running", "ok")),
        h("span", {class: "muted"}, `Depth ${row.depth} · `, when(row.started), stamp(row) ? ` · ${stamp(row)}` : ""));
      item.style.marginLeft = `${(row.depth - 1) * 18}px`;
      return item;
    })) : h("p", {class: "muted"}, "No subagents."));
  }

  async function deliver(text, file, cls) {
    let upload = "";
    if (file) {
      if (file.size > UPLOAD_LIMIT) {
        toast("File too large", [`${file.name}: at most 50 MiB`], false);
        return false;
      }
      const stored = await send(`/api/uploads?name=${encodeURIComponent(file.name)}`, file, "application/octet-stream");
      if (!stored.ok || !stored.data) {
        toast("Upload failed", [`${stored.status} ${stored.text}`.trim()], false);
        return false;
      }
      upload = stored.data.id;
    }
    return message(nameOf(ui.agent), text, upload, cls);
  }

  function message(to, text, upload, cls) {
    return radioSend({to, text, upload, cls, voice: ""});
  }

  function openAgent(who) {
    const drawer = document.getElementById("drawer");
    const key = agentKey(who);
    const name = nameOf(key);
    ui.agent = key;
    const text = h("textarea", {"aria-label": `Message to ${name}`, placeholder: `Message to ${name} …`});
    const file = h("input", {type: "file", class: "field", "aria-label": "Attach file"});
    const button = h("button", {type: "submit", class: "btn primary icon-only", ...named("Send")}, icon("bi-send"));
    const classes = choice("to-one", TO_ONE, "post");
    const form = h("form", {class: "drawer-form"}, text, file, classes,
      h("p", {class: "muted"}, "Post arrives at the end of the turn, Call at once with a read receipt; your passkey signs, verifiable with operator_message."),
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
    const subs = h("div", {}, h("p", {class: "muted"}, "Loading subagents …"));
    const log = h("div", {"aria-live": "polite"});
    const life = h("span", {class: "muted"});
    const former = (people()[key] || {names: []}).names.filter((entry) => entry !== name);
    drawer.replaceChildren(
      h("div", {class: "drawer-head"}, face(name, true), life, h("div", {}, h("h2", {class: "panel-title"}, name), h("span", {class: "muted"}, former.length ? `Agent · formerly ${former.join(", ")}` : "Agent")), h("span", {class: "spacer"}),
        iconBtn("bi-x-lg", "Close", "btn small ghost", closeAgent)),
      h("div", {class: "drawer-body"}, info, h("h3", {}, "Subagents"), subs, h("h3", {}, "History"), log),
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
    const names = new Set([...state.graph.nodes.filter((node) => node.kind === "session" || node.kind === "chair").map((node) => nameOf(node.id)), ...state.agent_order]);
    return [...names].sort((a, b) => a.localeCompare(b));
  }
