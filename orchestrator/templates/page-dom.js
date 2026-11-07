  function build(node, attrs, children) {
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "on") {
        for (const [name, handler] of Object.entries(value)) {
          node.addEventListener(name, handler);
        }
      } else if (value !== null && value !== undefined && value !== false) {
        node.setAttribute(key, value === true ? "" : String(value));
      }
    }
    for (const child of children.flat(Infinity)) {
      if (child !== null && child !== undefined && child !== false) {
        node.append(child instanceof Node ? child : String(child));
      }
    }
    return node;
  }
  const h = (tag, attrs, ...children) => build(document.createElement(tag), attrs, children);
  const s = (tag, attrs, ...children) => build(document.createElementNS(NS, tag), attrs, children);
  const icon = (name, cls) => s("svg", {class: cls ? `bi ${cls}` : "bi", "aria-hidden": "true", focusable: "false"}, s("use", {href: `#${name}`}));
  const caret = () => icon("bi-caret-down-fill", "caret");
  const named = (label, hint) => ({title: hint || label, "aria-label": label});
  const iconBtn = (name, label, cls, run, hint) => h("button", {type: "button", class: `${cls} icon-only`, ...named(label, hint), on: {click: run}}, icon(name));
  const dash = (value) => (value === "" || value === "-" || value === null || value === undefined ? "–" : value);
  const targetsOf = (row) => (row.to.length ? row.to.join(", ") : "alle");
  const fixed = (value) => value.toFixed(1);
  const short = (text) => (text.length > 80 ? `${text.slice(0, 80)}…` : text);
  const btn = (label, cls, run) => h("button", {type: "button", class: cls, on: {click: run}}, label);
  const nowSeconds = () => Date.now() / 1000;

  function ago(ts) {
    const diff = ts - nowSeconds();
    const size = Math.abs(diff);
    if (size < 45) {
      return "gerade eben";
    }
    if (size < 3600) {
      return relative.format(Math.round(diff / 60), "minute");
    }
    if (size < DAY) {
      return relative.format(Math.round(diff / 3600), "hour");
    }
    return relative.format(Math.round(diff / DAY), "day");
  }
  const stampOf = (ts) => new Date(ts * 1000);
  const when = (ts) => h("time", {"data-ts": ts, datetime: stampOf(ts).toISOString(), title: absolute.format(stampOf(ts))}, ago(ts));
  const pill = (text, tone) => h("span", {class: "pill", "data-tone": tone}, text);
  const status = (value) => pill((STATUS[value] || [value])[0], (STATUS[value] || [value, "neutral"])[1]);
  const klass = (value) => pill(CLASSES[value] || value, PILLS[value] || "neutral");
  const counter = (value) => h("span", {class: "count"}, String(value));
  const meta = (pairs) => h("dl", {class: "meta"}, pairs.map(([label, value, title]) => h("div", {}, h("dt", {}, label), h("dd", {}, h("code", {title: title || null}, dash(value))))));
  const emptyState = (title, text) => h("div", {class: "empty"}, h("div", {class: "empty-mark", "aria-hidden": "true"}), h("h2", {}, title), h("p", {}, text));
  const live = () => ui.preset !== -1 && ui.asOf === null;
  const alarmRows = () => state.radio.filter((row) => (row.class === "mayday" || row.class === "pan-pan") && row.ts >= state.alarm_since).reverse();
  const keyOf = (item) => `${item.kind}:${item.id}`;
  const visibleInbox = () => state.inbox.filter((item) => ui.snoozed || !item.until);
  const waitingCount = () => state.inbox.filter((item) => !item.until).length;
  const isGreen = (item) => item.green && !item.held && !item.until && item.kind !== "operator";
  const selectable = (item) => !item.held && !(item.kind === "review" && item.gate !== "pass") && !(item.kind === "operator" && !item.runnable) && !(item.kind === "decision" && !item.recommended);
  const entryOf = (item, verb, label) => ({kind: item.kind, id: item.id, verb, label, sha256: item.sha256 || ""});

  function tick() {
    for (const node of document.querySelectorAll("time[data-ts]")) {
      node.textContent = ago(Number(node.dataset.ts));
    }
    const updated = document.getElementById("updated");
    updated.classList.toggle("offline", ui.offline);
    updated.textContent = `${ui.offline ? "Keine Verbindung · " : ""}${live() ? "Live" : "Stand"} ${absolute.format(stampOf(live() ? state.now : state.until))}`;
  }

  function avatar(name) {
    let hash = 2166136261;
    for (const char of String(name)) {
      hash = Math.imul(hash ^ char.codePointAt(0), 16777619) >>> 0;
    }
    return EMOJI[hash % EMOJI.length];
  }
  const face = (name, big) => h("span", {class: big ? "avatar big" : "avatar", "aria-hidden": "true"}, avatar(name));
  const person = (name) => (name && name !== "-" && name !== "alle" && name !== HUMAN ? h("button", {type: "button", class: "linkish", title: `${name} öffnen`, on: {click: () => openAgent(name)}}, name) : dash(name));
  const people = () => state.people || {};
  const labelOf = (key) => (people()[key] || {name: String(key).replace(/^name:/, "")}).name;
  const nameOf = (key) => (people()[key] || {now: String(key).replace(/^name:/, "")}).now;
  const agentKey = (who) => (people()[who] ? who : (Object.entries(people()).find(([, entry]) => entry.now === who || entry.names.includes(who)) || [who])[0]);
  const chairKey = () => (state.graph.nodes.find((node) => node.kind === "chair") || {id: HUMAN}).id;
  const stamp = (life) => [life.born ? `🐣 ${life.born}` : "", life.died ? `🪦 ${life.died}` : ""].filter(Boolean).join(" · ");

  function toast(title, lines, good) {
    const box = h("div", {class: `toast${good ? "" : " bad"}`, role: "status", title: "Schließen"}, h("strong", {}, title), lines.length ? h("pre", {}, lines.join("\n")) : null);
    box.addEventListener("click", () => box.remove());
    document.getElementById("toasts").append(box);
    window.setTimeout(() => box.remove(), good ? 9000 : 20000);
  }

  function runLines(data) {
    return (data.runs || []).flatMap((run) => [`$ ${run.command} → ${run.code}`, run.stdout.trim(), run.stderr.trim()].filter(Boolean));
  }

  function relabel(button, name, label, hint) {
    button.replaceChildren(icon(name));
    button.setAttribute("aria-label", label);
    button.title = hint || label;
  }

  function copyButton(text) {
    const button = iconBtn("bi-clipboard", "Kopieren", "btn small ghost", null, "Kopieren: in die Zwischenablage");
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(text);
        relabel(button, "bi-clipboard-check", "Kopiert");
      } catch {
        relabel(button, "bi-x-circle", "Nicht möglich");
      }
      window.setTimeout(() => relabel(button, "bi-clipboard", "Kopieren"), 1600);
    });
    return button;
  }

  function closeMenus(keep) {
    for (const menu of document.querySelectorAll("details.menu[open]")) {
      if (menu !== keep) {
        menu.open = false;
      }
    }
  }

  function openSheet(title, body, wide) {
    const sheet = document.getElementById("sheet");
    sheet.replaceChildren(h("div", {class: `sheet-box${wide ? " wide" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": title},
      h("div", {class: "sheet-head"}, h("h2", {class: "panel-title"}, title), h("span", {class: "spacer"}), iconBtn("bi-x-lg", "Schließen", "btn small ghost", closeSheet)),
      h("div", {class: "sheet-body"}, body)));
    sheet.hidden = false;
  }

  function closeSheet() {
    const sheet = document.getElementById("sheet");
    sheet.hidden = true;
    sheet.replaceChildren();
    reviewDom = null;
    ui.review = null;
  }
