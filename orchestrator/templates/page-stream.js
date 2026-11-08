  async function fetchEvents() {
    if (stream.busy) {
      stream.again = true;
      return;
    }
    const key = `${windowKey()}&${filterQuery()}`;
    if (stream.key !== key) {
      stream.key = key;
      stream.events = [];
      stream.entries = [];
      stream.last = 0;
    }
    stream.busy = true;
    try {
      const response = await fetch(`/api/events?${windowQuery()}&${filterQuery()}&after=${stream.last}`, {cache: "no-store"});
      if (response.ok) {
        const data = await response.json();
        if (stream.key === key) {
          const seen = new Set(stream.entries.map((entry) => entry.id));
          stream.events = data.events;
          stream.entries = [...stream.entries, ...data.entries.filter((entry) => !seen.has(entry.id))].sort((a, b) => a.ts - b.ts).slice(-STREAM_KEEP);
          stream.last = data.last;
          stream.sessions = data.sessions;
          stream.error = "";
        }
      } else {
        stream.error = `${response.status} ${(await response.text()).trim()}`;
      }
    } catch {
      ui.offline = true;
    }
    stream.busy = false;
    drawStream();
    if (stream.again) {
      stream.again = false;
      fetchEvents();
    }
  }

  async function expand(entry, holder, button) {
    button.disabled = true;
    const response = await fetch(`/api/stream/${entry.ref.entry}`, {cache: "no-store"});
    if (response.ok) {
      const data = await response.json();
      entry.text = data.text;
      entry.ref.truncated = false;
      holder.textContent = data.text;
      button.remove();
    } else {
      button.textContent = "No longer available";
    }
  }

  function focusSub(session, sub) {
    filter.view = "";
    filter.saved = "";
    filter.kinds = new Set(["transcript"]);
    filter.waiting = false;
    filter.session = session;
    filter.sub = sub;
    closeAgent();
    if (ui.screen === "stream" && stream.dom) {
      refilter();
    } else {
      go("stream", null);
    }
  }

  function inboxOf(entry) {
    const id = entry.kind === "operator" ? entry.ref.task : entry.ref.id;
    return state.inbox.find((item) => item.kind === entry.kind && item.id === id) || null;
  }

  function kindPill(entry) {
    if (entry.kind === "radio") {
      return klass(entry.part);
    }
    if (entry.kind === "transcript") {
      return pill((PARTS.find(([id]) => id === entry.part) || [entry.part, entry.part])[1], PART_TONES[entry.part] || "neutral");
    }
    return pill((KINDS.find(([id]) => id === entry.kind) || [entry.kind, entry.kind])[1], KIND_TONES[entry.kind] || "neutral");
  }

  function extras(entry) {
    const ref = entry.ref;
    if (entry.kind === "review") {
      return [status(ref.status), ref.gate ? pill(ref.gate === "pass" ? "Gate green" : "Gate red", ref.gate === "pass" ? "ok" : "bad") : null];
    }
    if (entry.kind === "ask") {
      return [status(ref.status), ...ref.warnings.map((warning) => pill(warning, "bad"))];
    }
    if (entry.kind === "decision") {
      return [status(ref.status), ref.choice ? pill(ref.choice, "ok") : null];
    }
    if (entry.kind === "cron") {
      return [pill(ref.active ? "active" : "inactive", ref.active ? "ok" : "neutral")];
    }
    if (entry.kind === "run" || entry.kind === "operator" || entry.kind === "register") {
      return [ref.status ? status(ref.status) : null];
    }
    return [];
  }

  function body(entry) {
    if (entry.kind === "transcript") {
      const text = h("pre", {}, entry.text);
      const more = entry.ref.truncated ? h("button", {type: "button", class: "btn small ghost"}, "Show full text") : null;
      if (more) {
        more.addEventListener("click", () => expand(entry, text, more));
      }
      return [text, more];
    }
    if (entry.kind === "ask" || entry.kind === "operator") {
      const where = entry.kind === "ask" ? entry.ref.cwd : entry.ref.directory;
      return [h("div", {class: "command"}, h("code", {}, entry.kind === "ask" ? entry.text : entry.title), copyButton(entry.kind === "ask" ? entry.text : entry.title)), h("span", {class: "muted"}, `in ${dash(where)}`), entry.kind === "operator" && entry.text !== "-" ? h("p", {class: "text"}, entry.text) : null];
    }
    if (entry.kind === "review") {
      return [entry.text ? h("pre", {class: "notes"}, entry.text) : null, h("div", {class: "line-actions"}, iconBtn("bi-eye", "View diff", "btn small soft", () => reviewSheet(entry.ref.id)))];
    }
    if (entry.kind === "cron") {
      const ref = entry.ref;
      const ended = ref.deleted ? [" · ended ", when(ref.deleted)] : [];
      return [entry.text ? h("pre", {}, entry.text) : null, h("span", {class: "muted"}, "created ", when(ref.created), ended)];
    }
    if (entry.kind === "run") {
      return [entry.text ? h("pre", {}, entry.text) : null];
    }
    return [entry.text ? h("p", {class: "text"}, entry.text) : null];
  }

  function eventRow(entry) {
    const item = entry.waiting ? inboxOf(entry) : null;
    const alarm = entry.kind === "radio" && (entry.part === "mayday" || entry.part === "pan-pan");
    const renamed = entry.now && entry.now !== entry.agent ? h("span", {title: `now: ${entry.now}`}, person(entry.agent)) : person(entry.agent);
    const who = entry.agent ? [face(entry.agent, false), renamed] : entry.session ? h("strong", {title: entry.session}, entry.session.slice(0, 8)) : null;
    const headline = entry.kind === "transcript" || entry.kind === "ask" || entry.kind === "operator" ? null : h("span", {class: "headline"}, entry.title);
    return h("li", {class: `entry k-${entry.kind}${entry.waiting ? " waiting" : ""}${alarm ? " alarm" : ""}`},
      h("div", {class: "msg-meta"}, when(entry.ts), kindPill(entry), extras(entry)),
      h("div", {},
        h("div", {class: "route"}, who, entry.sub ? h("button", {type: "button", class: "linkish muted", on: {click: () => focusSub(entry.session, entry.sub)}}, `› Subagent ${entry.sub.slice(0, 12)}`) : null, entry.kind === "ask" ? h("strong", {}, entry.title) : null, headline),
        body(entry),
        item ? h("div", {class: "line-actions"}, actionsFor(item)) : null));
  }

  function drawStream() {
    if (!stream.dom || ui.screen !== "stream") {
      return;
    }
    const floor = live() && ui.preset > 0 ? nowSeconds() - ui.preset : -Infinity;
    const rows = [...stream.events, ...stream.entries.filter((entry) => entry.ts >= floor)].sort((a, b) => b.ts - a.ts || (a.id < b.id ? 1 : -1));
    const shown = rows.slice(0, FEED_LIMIT);
    stream.dom.count.textContent = `${rows.length} entries${live() ? " · following live" : ""}`;
    if (stream.error) {
      stream.dom.list.replaceChildren(emptyState("Stream not readable", stream.error));
      return;
    }
    stream.dom.list.replaceChildren(rows.length
      ? h("div", {class: "card flush"}, h("ol", {class: "feed"}, shown.map(eventRow)),
        rows.length > shown.length ? h("p", {class: "footnote"}, `${rows.length - shown.length} older entries hidden; narrow down with a filter or the time range.`) : null)
      : emptyState(stream.busy ? "Loading …" : "No entries", activeWaiting() ? "Nothing is waiting for you right now." : "Nothing in the chosen time range and filter."));
  }

  function streamScreen() {
    const search = h("input", {type: "search", placeholder: "Search … agent:Name kind:radio since:2h (/)", value: filter.q, "aria-label": "Search the stream: words, agent:, kind: and since:", on: {input: (event) => {
      filter.q = event.target.value;
      filter.saved = "";
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(fetchEvents, 300);
    }}});
    const count = h("span", {class: "muted"});
    const categories = h("div", {class: "chips", role: "group", "aria-label": "Categories"});
    const kinds = h("div", {class: "chips", role: "group", "aria-label": "Kinds"});
    const parts = h("div", {class: "chips", role: "group", "aria-label": "Transcript parts"});
    const saved = h("div", {class: "chips", role: "group", "aria-label": "Saved views"});
    const focus = h("div", {class: "chips"});
    const list = h("div", {});
    const more = h("details", {class: "menu"}, h("summary", named("Filter", "Filter: kinds, transcript parts, saved views, custom time range"), icon("bi-funnel"), caret()), h("div", {class: "menu-box end"},
      h("h3", {}, "Kinds"), kinds, h("h3", {}, "Transcript parts"), parts, h("h3", {}, "Saved views"), saved, h("h3", {}, "Custom time range"), customRange()));
    stream.dom = {search, count, categories, kinds, parts, saved, focus, list};
    window.setTimeout(() => {
      drawFilters();
      drawStream();
      fetchEvents();
    }, 0);
    return h("div", {}, h("div", {class: "filters"}, categories, search, more, count), focus, list);
  }
