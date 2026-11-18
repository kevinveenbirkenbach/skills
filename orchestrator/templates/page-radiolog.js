  const TAB_LABELS = {sent: ["bi-arrow-up-right", "Sent", "Sent: what you transmitted"], received: ["bi-arrow-down-left", "Received", "Received: radio to you or to all"], all: ["bi-journal-text", "All", "All: every radio row the hub logs"]};
  const CHIP_LABELS = {class: "Class", from: "Sender", to: "Recipient", agent: "Agent"};
  const COPIED = 1600;
  const FOLDED_READERS = 3;

  function keepLog(change) {
    keepRadio({log: {...radioSet.log, ...change}});
  }

  function chipSelect(name) {
    const label = CHIP_LABELS[name];
    const select = h("select", {class: "field", "aria-label": label, title: `${label}: filter the log`, on: {change: (event) => keepLog({chips: {...radioSet.log.chips, [name]: event.target.value}})}});
    return h("label", {class: "chip-select", "data-chip": name, "data-active": "false"}, select);
  }

  function fillChip(chip, values) {
    const name = chip.dataset.chip;
    const chosen = radioSet.log.chips[name];
    const options = [...new Set([...values, ...(chosen ? [chosen] : [])])];
    const select = chip.querySelector("select");
    const sig = JSON.stringify([options, chosen || ""]);
    if (select.sig !== sig) {
      select.sig = sig;
      select.replaceChildren(h("option", {value: ""}, `${CHIP_LABELS[name]}: any`), ...options.map((value) => h("option", {value, selected: value === chosen}, name === "class" ? CLASSES[value] || value : value)));
    }
    setAttr(chip, "data-active", String(Boolean(chosen)));
  }

  function setAttr(node, name, value) {
    if (node.getAttribute(name) !== value) {
      node.setAttribute(name, value);
    }
  }

  function setText(node, value) {
    if (node.textContent !== value) {
      node.textContent = value;
    }
  }

  function firstLine(text) {
    return text.split("\n").map((part) => part.trim()).find(Boolean) || "";
  }

  function logLine(row) {
    const message = row.sent ? row : RadioSet.ledgerOf(row, state.messages);
    const sent = Boolean(message);
    const [name, label] = sent ? ["bi-arrow-up-right", "Sent"] : ["bi-arrow-down-left", "Received"];
    const first = firstLine(row.text);
    const line = h("li", {class: "radio-row", "data-key": row.key, "data-dir": sent ? "sent" : "received", "data-class": row.class, "data-ts": row.ts, on: {click: (event) => openRadioRow(event.currentTarget.row, event.currentTarget)}},
      row.source && !sent && row.from !== HUMAN ? muteFace(row.source, row.from) : null,
      h("button", {type: "button", class: "radio-pick", "aria-haspopup": "dialog", title: first},
        when(row.ts),
        h("span", {class: "radio-dir", role: "img", ...named(label)}, icon(name)),
        klass(row.class),
        h("span", {class: "radio-route"}, `${row.from} → ${targetsOf(row)}`),
        h("span", {class: "radio-line"}, first)),
      foldedReaders(row));
    line.row = row;
    return line;
  }

  function keepLine(kept, fresh) {
    kept.row = fresh.row;
    if (kept.outerHTML === fresh.outerHTML) {
      return kept;
    }
    for (const name of ["data-dir", "data-class"]) {
      setAttr(kept, name, fresh.getAttribute(name));
    }
    const [pick, twin] = [kept.querySelector(".radio-pick"), fresh.querySelector(".radio-pick")];
    setAttr(pick, "title", twin.getAttribute("title"));
    pick.replaceChildren(...twin.childNodes);
    for (const node of [...kept.children].filter((child) => child !== pick)) {
      node.remove();
    }
    const parts = [...fresh.children];
    const at = parts.indexOf(twin);
    pick.before(...parts.slice(0, at));
    pick.after(...parts.slice(at + 1));
    return kept;
  }

  /**
   * @param {string} key the sender's session key.
   * @param {string} name the sender's name.
   * @returns {Element} the sender's avatar as a button that mutes or unmutes the sender on the radio, without opening the row.
   */
  function muteFace(key, name) {
    const muted = radioSet.muted.includes(key);
    return h("button", {type: "button", class: "radio-mute", "aria-pressed": String(muted), ...named(`Mute ${name}`, muted ? `Muted: a press lets the radio read ${name} aloud again` : `Mute ${name}: the radio stops reading this agent aloud`), on: {click: (event) => {
      event.stopPropagation();
      keepRadio(RadioSet.muting(radioSet, key));
    }}}, face(key, false));
  }

  function patchList(list, lines) {
    const before = [...list.children];
    const focused = before.find((node) => node.contains(document.activeElement)) || null;
    const old = new Map(before.filter((node) => node.dataset.key).map((node) => [node.dataset.key, node]));
    const wanted = lines.map((line) => {
      const kept = old.get(line.dataset.key);
      old.delete(line.dataset.key);
      return kept ? keepLine(kept, line) : line;
    });
    const keep = new Set(wanted);
    for (const node of before.filter((child) => !keep.has(child))) {
      node.remove();
    }
    wanted.forEach((node, index) => {
      if (list.children[index] !== node) {
        list.insertBefore(node, list.children[index] || null);
      }
    });
    if (focused && !focused.isConnected) {
      const at = before.indexOf(focused);
      const near = before.filter((node) => node.isConnected && node.querySelector(".radio-pick")).sort((a, b) => Math.abs(before.indexOf(a) - at) - Math.abs(before.indexOf(b) - at))[0];
      (near ? near.querySelector(".radio-pick") : list).focus({preventScroll: true});
    }
  }

  function foldedReaders(row) {
    const strip = readerRow(row);
    const {shown, hidden} = Receipts.strip(row);
    const rest = shown.length + hidden.length - FOLDED_READERS;
    if (strip && rest > 0) {
      strip.append(h("span", {class: "readers-more readers-fold", role: "img", ...named(`${rest} more readers`, [...shown, ...hidden].slice(FOLDED_READERS).map(readLabel).join("\n"))}, `+${rest}`));
    }
    return strip;
  }

  function readerLine(reader) {
    const known = reader.read !== null && reader.read !== undefined;
    return h("li", {class: "popup-reader", "data-session": reader.session, "data-acked": String(reader.acked)},
      face(people()[reader.session] ? reader.session : reader.name, false),
      h("strong", {}, reader.name),
      h("span", {class: "muted"}, known ? `read ${reader.approximate ? "about " : ""}${absolute.format(stampOf(reader.read))}` : "read, time unknown"),
      reader.acked ? pill("acknowledged", "ok") : null);
  }

  function copyText(text) {
    const said = h("span", {class: "radio-said", role: "status", "aria-live": "polite"});
    const button = h("button", {type: "button", class: "btn small radio-copy", ...named("Copy", "Copy: the full message to the clipboard")}, icon("bi-clipboard"), h("span", {}, "Copy"));
    const show = (name, word, done, note) => {
      button.replaceChildren(icon(name), h("span", {}, word));
      button.setAttribute("aria-label", word);
      button.dataset.copied = done;
      said.textContent = note;
    };
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(text);
        show("bi-clipboard-check", "Copied", "true", "Copied: the full message is on the clipboard");
      } catch {
        show("bi-x-circle", "Not copied", "false", "Not copied: the browser refused the clipboard");
      }
      window.setTimeout(() => show("bi-clipboard", "Copy", "", ""), COPIED);
    });
    return [button, said];
  }

  function replyTarget(list) {
    const home = list ? list.closest(".radio-home") : null;
    if (!home) {
      return spotDom.speak;
    }
    const homes = liveParts("speaks").filter((part) => part.root.closest(".radio-home"));
    return homes.find((part) => home.contains(part.root)) || homes.find((part) => part.root.closest(".radio-home-radio-speak")) || homes[0] || spotDom.speak;
  }

  function replyTo(row, list) {
    const who = row.from === HUMAN && row.to.length ? row.to[0] : row.from;
    const part = replyTarget(list);
    closePopup();
    if (part === spotDom.speak) {
      openSpot(true);
    }
    part.channel.value = "post";
    part.channel.dispatchEvent(new Event("change", {bubbles: true}));
    if (![...part.recipient.options].some((option) => option.value === who)) {
      part.recipient.append(h("option", {value: who}, who));
    }
    part.recipient.value = who;
    part.text.focus();
  }

  function openRadioRow(row, li) {
    const message = row.sent ? row : RadioSet.ledgerOf(row, state.messages);
    const {shown, hidden} = Receipts.strip(row);
    const readers = [...shown, ...hidden];
    const list = li.closest("ul");
    const anchor = () => (list ? [...list.querySelectorAll(".radio-row")].find((item) => item.dataset.key === row.key) || null : null);
    openPopup(`Radio message from ${row.from}`, [
      popupHead(klass(row.class), `${row.from} → ${targetsOf(row)}`),
      meta([["Sender", row.from], ["Recipient", targetsOf(row)], ["Class", CLASSES[row.class] || row.class], ["Time", absolute.format(stampOf(row.ts))]]),
      h("pre", {class: "radio-full"}, row.text),
      voiceReplay(message ? message.voice : null),
      h("div", {class: "actions radio-actions"},
        h("button", {type: "button", class: "btn small primary radio-reply", ...named("Reply", "Reply: a post to the sender in the speak card"), on: {click: () => replyTo(row, list)}}, icon("bi-reply"), "Reply"),
        copyText(row.text)),
      h("h3", {}, readers.length ? `Read by ${readers.length}` : "Read by nobody yet"),
      readers.length ? h("ul", {class: "popup-readers"}, readers.map(readerLine)) : null,
    ].filter(Boolean), anchor);
  }

  function drawLog() {
    const entry = radioSet.log;
    const sig = JSON.stringify([state.radio.length, state.radio.length ? state.radio[state.radio.length - 1].ts : 0, state.messages.length, Receipts.signature(state.radio), Receipts.signature(state.messages), entry, radioSet.muted, Math.floor(Date.now() / 60000)]);
    for (const dom of liveParts("logs")) {
      if (sig !== dom.sig) {
        dom.sig = sig;
        drawLogPart(dom, entry);
      }
    }
  }

  function drawLogPart(dom, entry) {
    const counts = RadioSet.counts(state.radio, HUMAN, state.messages);
    for (const button of dom.tabs.children) {
      const {tab} = button.dataset;
      const count = button.querySelector(".count");
      setAttr(button, "aria-selected", String(tab === entry.tab));
      setAttr(count, "aria-label", `${counts[tab]} rows`);
      setText(count, String(counts[tab]));
    }
    const choices = RadioSet.choices(state.radio);
    for (const chip of dom.chips.children) {
      fillChip(chip, choices[chip.dataset.chip]);
    }
    if (document.activeElement !== dom.search && dom.search.value !== entry.q) {
      dom.search.value = entry.q;
    }
    const rows = RadioSet.logRows(state.radio, entry, HUMAN, state.messages);
    patchList(dom.list, rows.length ? rows.map(logLine) : [h("li", {class: "muted"}, state.radio.length ? "No radio row matches the tab, the chips and the search." : "No radio in the chosen time range yet.")]);
  }

  function historyCard() {
    const tabs = h("div", {class: "radio-tabs", role: "tablist", "aria-label": "Log"}, RadioSet.TABS.map((tab) => {
      const [name, label, hint] = TAB_LABELS[tab];
      return h("button", {type: "button", role: "tab", "data-tab": tab, "aria-selected": "false", title: hint, on: {click: () => keepLog({tab})}}, icon(name), label, h("span", {class: "count"}));
    }));
    const chips = h("div", {class: "radio-chips", role: "group", "aria-label": "Log filters"}, RadioSet.CHIPS.map(chipSelect));
    const search = h("input", {type: "search", class: "field", placeholder: "Search the log …", maxlength: 200, ...named("Search the log"), on: {input: (event) => keepLog({q: event.target.value})}});
    const clear = iconBtn("bi-x-circle", "Clear filters", "btn small ghost", () => keepRadio({log: RadioSet.cleared(radioSet.log)}), "Clear filters: every chip and the search");
    const list = h("ul", {class: "radio-log", tabindex: "-1", "aria-label": "Radio log"});
    const part = {tabs, chips, search, list, sig: ""};
    part.root = h("section", {class: "radio-card radio-logbox", "data-panel": "radio-log", "aria-label": "Radio log"}, cardHead("History", tabs, search), h("div", {class: "radio-filters"}, chips, clear), list);
    radioParts.logs.push(part);
    return part;
  }
