  function paletteItems() {
    return [
      ...Nav.TABS.flatMap(([id, label], index) => [{label: `View: ${label}`, hint: String(index + 1), run: () => go(id, null)}, ...(Nav.SUBS[id] || []).map(([sub, name]) => ({label: `View: ${label} › ${name}`, hint: Nav.hashOf(sub, null), run: () => go(sub, null)}))]),
      ...["agents", "artifacts", "tasks"].flatMap((screen) => Nav.viewsOf(screen).map(([id, name]) => ({label: `${Nav.TABS.find(([tab]) => tab === screen)[1]}: ${name}`, hint: Nav.hashOf(screen, id), run: () => go(screen, id)}))),
      ...Object.entries(state.views).map(([id, view]) => ({label: `Stream: ${view.label}`, hint: "Category", run: () => useView(id)})),
      ...userViews.map((view) => ({label: `Stream: ${view.name}`, hint: "saved view", run: () => useSaved(view)})),
      ...agentNames().map((name) => ({label: `${avatar(name)} ${name}`, hint: "Agent", run: () => openAgent(name)})),
      {label: "Radio to all …", hint: "Newsletter, Broadcast, Pan-Pan, Security, Mayday", run: openToAll},
      ...ACTIONS.map(([id, label]) => ({label, hint: id === "clear-mayday" ? "Mayday" : "Day/Night", run: () => confirmAct(id)})),
      {label: "Priority …", hint: "agent order in the hierarchy", run: openAgentOrder},
      {label: "Firewall …", hint: "automatic grants", run: () => go("rules", null)},
      {label: "Settings …", hint: "Ambience, location, colors, music, tones, read radio aloud, internet radio", run: settingsSheet},
      {label: settings.music.on ? "Music off" : "Music on", hint: "Ambience", run: toggleMusic},
      {label: space.look ? "Leave the sky" : "Look at the sky", hint: "h", run: () => skyLook(!space.look)},
      {label: "Toggle control room", hint: "Ambience", run: toggleLeitstand},
      {label: "Enable notifications", hint: "Ambience", run: askNotify},
      {label: "Keyboard shortcuts", hint: "?", run: helpSheet},
    ];
  }

  function drawPalette() {
    if (palette.plan) {
      return;
    }
    const raw = palette.input.value.trim();
    const q = raw.toLowerCase();
    const items = paletteItems().filter((item) => !q || item.label.toLowerCase().includes(q) || item.hint.toLowerCase().includes(q));
    if (raw) {
      items.push(state.llm
        ? {label: `AI command: “${raw}”`, hint: "Tab", keep: true, run: () => askModel(raw)}
        : {label: "AI command is off", hint: "set KVB_ORCHESTRATOR_LLM_URL and KVB_ORCHESTRATOR_LLM_MODEL in orchestrator/.env", keep: true, run: () => toast("AI command is off", ["Set KVB_ORCHESTRATOR_LLM_URL, KVB_ORCHESTRATOR_LLM_MODEL and KVB_ORCHESTRATOR_LLM_KEY_FILE in orchestrator/.env and reinstall."], false)});
    }
    palette.items = items;
    palette.index = Math.min(palette.index, Math.max(items.length - 1, 0));
    palette.list.replaceChildren(...items.map((item, index) => h("li", {role: "option", "aria-selected": String(index === palette.index), on: {
      click: () => runPalette(index),
      mousemove: () => {
        if (palette.index !== index) {
          palette.index = index;
          drawPalette();
        }
      },
    }}, h("span", {}, item.label), h("span", {class: "muted"}, item.hint))));
    const current = palette.list.children[palette.index];
    if (current) {
      current.scrollIntoView({block: "nearest"});
    }
  }

  function runPalette(index) {
    const item = palette.items[index];
    if (!item) {
      return;
    }
    if (!item.keep) {
      closePalette();
    }
    item.run();
  }

  async function askModel(text) {
    palette.plan = {actions: [], rejected: [], busy: true};
    palette.list.replaceChildren(h("li", {}, h("span", {class: "muted"}, "Asking the model … (only the command, ids and titles leave the hub)")));
    const result = await sendJson("/api/nl", {text});
    if (!palette.plan) {
      return;
    }
    if (!result.ok || !result.data) {
      palette.plan = null;
      palette.list.replaceChildren(h("li", {}, h("span", {}, `AI command failed: ${result.status} ${result.text}`.trim())));
      return;
    }
    palette.plan = result.data;
    const actions = result.data.actions.map((action) => h("pre", {}, action.summary));
    const rejected = result.data.rejected.map((entry) => h("p", {class: "muted"}, `discarded: ${entry.reason} · ${entry.action}`));
    palette.list.replaceChildren(h("li", {class: "palette-plan"},
      actions.length ? actions : h("p", {class: "muted"}, "The model proposed no valid action."),
      rejected,
      h("p", {class: "muted"}, actions.length ? "Enter runs exactly these actions · Esc cancels" : "Esc closes")));
  }

  async function executePlan(plan) {
    for (const action of plan.actions) {
      const args = action.args;
      if (action.name === "approve" || action.name === "reject" || action.name === "choose") {
        await submit(args.items, action.summary.split("\n")[0]);
      } else if (action.name === "snooze" || action.name === "pin") {
        for (const key of args.keys) {
          const item = state.inbox.find((entry) => entry.kind === key.kind && entry.id === key.id);
          if (item) {
            await mark(item, action.name === "snooze" ? nowSeconds() + args.hours * 3600 : item.until, action.name === "pin" ? true : item.pinned);
          }
        }
      } else if (action.name === "view") {
        useView(args.name);
      } else if (action.name === "open") {
        go(args.view, null);
      } else if (action.name === "message") {
        await message(args.to, args.text, "", "post");
      } else if (action.name === "filter") {
        filter.q = args.q;
        if (ui.screen === "stream" && stream.dom) {
          stream.dom.search.value = args.q;
          refilter();
        } else {
          go("stream", null);
        }
      }
    }
  }

  function openPalette() {
    const box = document.getElementById("palette");
    palette.input = h("input", {type: "text", placeholder: "View, agent, action, or a command in words …", "aria-label": "Command", role: "combobox", "aria-expanded": "true"});
    palette.list = h("ul", {class: "palette-list", role: "listbox"});
    palette.index = 0;
    palette.plan = null;
    palette.input.addEventListener("input", () => {
      palette.index = 0;
      palette.plan = null;
      drawPalette();
    });
    palette.input.addEventListener("keydown", (event) => {
      if (palette.plan && event.key === "Enter") {
        event.preventDefault();
        const plan = palette.plan;
        if (!plan.busy && plan.actions.length) {
          closePalette();
          executePlan(plan);
        }
      } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const size = Math.max(palette.items.length, 1);
        palette.index = (palette.index + (event.key === "ArrowDown" ? 1 : size - 1)) % size;
        drawPalette();
      } else if (event.key === "Tab" && palette.input.value.trim() && !palette.plan) {
        event.preventDefault();
        palette.index = palette.items.length - 1;
        runPalette(palette.index);
      } else if (event.key === "Enter") {
        event.preventDefault();
        runPalette(palette.index);
      }
    });
    box.replaceChildren(h("div", {class: "palette-box", role: "dialog", "aria-label": "Commands"}, h("div", {class: "palette-row"}, palette.input, micButton(palette.input)), palette.list));
    box.hidden = false;
    drawPalette();
    palette.input.focus();
  }

  function closePalette() {
    document.getElementById("palette").hidden = true;
    palette.plan = null;
  }
