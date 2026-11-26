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
      stream.tag = "";
    }
    stream.busy = true;
    try {
      const response = await fetch(`/api/events?${windowQuery()}&${filterQuery()}&after=${stream.last}`, {cache: "no-store", headers: stream.tag ? {"If-None-Match": stream.tag} : {}});
      if (response.status === 304) {
        stream.error = "";
      } else if (response.ok) {
        const tag = response.headers.get("ETag") || "";
        const data = await response.json();
        if (stream.key === key) {
          const seen = new Set(stream.entries.map((entry) => entry.id));
          stream.events = data.events;
          stream.entries = [...stream.entries, ...data.entries.filter((entry) => !seen.has(entry.id))].sort((a, b) => a.ts - b.ts).slice(-STREAM_KEEP);
          stream.last = data.last;
          stream.sessions = data.sessions;
          stream.tag = tag;
          stream.error = "";
        }
      } else {
        stream.error = `${response.status} ${(await response.text()).trim()}`;
      }
    } catch {
      ui.offline = true;
    }
    stream.busy = false;
    drawStream(true);
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
    closePopup();
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
    if (entry.kind === "operator" && entry.ref.check === "decision") {
      return pill("Decision", KIND_TONES.decision);
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
    if (entry.kind === "operator" && ref.answered) {
      return [status("decided"), pill(ref.answered, "ok")];
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
    if (entry.kind === "operator" && entry.ref.check === "decision") {
      return [h("p", {class: "text question"}, revealed(entry.title)), entry.text !== "-" ? h("p", {class: "text reason"}, revealed(entry.text)) : null];
    }
    if (entry.kind === "ask" || entry.kind === "operator") {
      return [entry.kind === "operator" && entry.text !== "-" ? h("p", {class: "text"}, entry.text) : null];
    }
    if (entry.kind === "review") {
      return [entry.text ? h("pre", {class: "notes"}, entry.text) : null];
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

  /**
   * @param {Object} entry a stream entry.
   * @param {Object|null} item its waiting inbox item, or null.
   * @returns {HTMLElement|null} one code box with the entry's command and diff and the item's actions in its foot; a
   * review entry without a waiting item loads its diff on the eye's first click; null for an entry with neither.
   */
  function streamCode(entry, item) {
    const commanded = entry.kind === "ask" || (entry.kind === "operator" && entry.ref.check !== "decision");
    const late = entry.kind === "review" && !item;
    const key = `message:${entry.ts}/${entry.id}`;
    const opened = late && codeOpened(key, "preview");
    const diff = item ? diffBlocks(item) : opened ? diffBlocks({kind: "review", id: entry.ref.id, diff: 0}) : null;
    if (!commanded && !diff && !late) {
      return null;
    }
    const text = entry.kind === "ask" ? entry.text : entry.title;
    const where = entry.kind === "ask" ? entry.ref.cwd : entry.ref.directory;
    const missing = late ? h("p", {class: "muted"}, opened ? "No diff stored for this review." : "The eye loads the diff of this review.") : null;
    return codeBox(key, "preview", [commanded ? h("div", {class: "command", "data-path": where || "-"}, h("code", {}, text)) : null, commanded ? h("span", {class: "muted code-where"}, `in ${dash(where)}`) : null, diff || missing],
      commanded ? text : "", item ? actionsFor(item) : [], late ? drawStream : null);
  }

  function eventRow(entry) {
    const answered = entry.kind === "operator" && entry.ref.answered;
    const item = entry.waiting && !answered ? inboxOf(entry) : null;
    const code = streamCode(entry, item);
    const choice = item ? choiceOf(item, () => {}) : null;
    const alarm = entry.kind === "radio" && (entry.part === "mayday" || entry.part === "pan-pan");
    const renamed = entry.now && entry.now !== entry.agent ? h("span", {title: `now: ${entry.now}`}, agentLink(entry.agent)) : agentLink(entry.agent);
    const who = entry.agent ? renamed : entry.session ? h("strong", {title: entry.session}, entry.session.slice(0, 8)) : null;
    const headline = entry.kind === "transcript" || entry.kind === "ask" || entry.kind === "operator" ? null : h("span", {class: "headline"}, Receipts.headline(entry));
    const blocked = (item && item.blocked) || (entry.kind === "operator" && entry.ref.blocked) || "";
    return h("li", {class: `entry k-${entry.kind}${entry.waiting && !answered ? " waiting" : ""}${alarm ? " alarm" : ""}`, "data-ref": item ? keyOf(item) : null, "data-item": `message:${entry.ts}/${entry.id}`, "data-to": item && item.to ? item.to : null,
      "data-blocked": blocked ? "" : null, "data-answered": answered ? "" : null, title: blocked || null},
      h("div", {class: "msg-meta"}, when(entry.ts), kindPill(entry), extras(entry)),
      h("div", {},
        h("div", {class: "route"}, who, entry.sub ? h("button", {type: "button", class: "linkish muted", on: {click: () => focusSub(entry.session, entry.sub)}}, `› Subagent ${entry.sub.slice(0, 12)}`) : null, entry.kind === "ask" ? h("strong", {}, entry.title) : null, headline),
        entry.kind === "decision" && choice ? choice : [body(entry), choice],
        entry.kind === "radio" ? readerRow(entry.ref) : null,
        blocked ? h("p", {class: "item-blocked"}, icon("bi-slash-circle"), blocked) : null,
        code,
        item && item.job ? consoleOf(item.job) : null,
        item ? feedbackList(keyOf(item)) : null,
        item && !code ? h("div", {class: "line-actions"}, actionsFor(item)) : null));
  }

  /**
   * @param {boolean} [polled] true from a poll: the rows stay when the shown entries, their inbox items and the error
   * are unchanged; any other call redraws them.
   */
  function drawStream(polled) {
    if (!stream.dom || ui.screen !== "stream") {
      return;
    }
    const floor = live() && ui.preset > 0 ? nowSeconds() - ui.preset : -Infinity;
    const rows = [...stream.events, ...stream.entries.filter((entry) => entry.ts >= floor)].sort((a, b) => b.ts - a.ts || (a.id < b.id ? 1 : -1));
    const shown = rows.slice(0, FEED_LIMIT);
    stream.dom.count.textContent = `${rows.length} entries${live() ? " · following live" : ""}`;
    const drawn = JSON.stringify([shown, shown.map((entry) => entry.waiting ? inboxOf(entry) : null), rows.length, stream.error, rows.length ? null : [stream.busy, activeWaiting()]]);
    if (polled === true && drawn === stream.dom.drawn) {
      return;
    }
    stream.dom.drawn = drawn;
    if (stream.error) {
      stream.dom.list.replaceChildren(emptyState("Stream not readable", stream.error));
      return;
    }
    keepTyping(stream.dom.list, () => keepScroll(stream.dom.list, () => stream.dom.list.replaceChildren(rows.length
      ? h("div", {class: "card flush"}, h("ol", {class: "feed"}, shown.map(eventRow)),
        rows.length > shown.length ? h("p", {class: "footnote"}, `${rows.length - shown.length} older entries hidden; narrow down with a filter or the time range.`) : null)
      : emptyState(stream.busy ? "Loading …" : "No entries", activeWaiting() ? "Nothing is waiting for you right now." : "Nothing in the chosen time range and filter."))));
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
    const list = h("div", {"data-panel": "stream"});
    const more = h("details", {class: "menu"}, h("summary", named("Filter", "Filter: kinds, transcript parts, saved views, custom time range"), icon("bi-funnel"), caret()), h("div", {class: "menu-box end"},
      h("h3", {}, "Kinds"), kinds, h("h3", {}, "Transcript parts"), parts, h("h3", {}, "Saved views"), saved, h("h3", {}, "Custom time range"), customRange()));
    stream.dom = {search, count, categories, kinds, parts, saved, focus, list};
    window.setTimeout(() => {
      drawFilters();
      drawStream();
      fetchEvents();
    }, 0);
    return h("div", {}, boxHead("Stream", "filters stream-head", categories, search, more, count), focus, list);
  }
