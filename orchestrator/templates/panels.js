const Panels = (() => {
  "use strict";
  const MAX = 64;
  const SPAN = 12;
  const ID_MAX = 200;
  const ID = /^[A-Za-z0-9:_./-]{1,200}$/;
  const KIND = /^[A-Za-z0-9:_./-]{1,32}$/;
  const ESCAPE = /[^A-Za-z0-9./-]/gu;
  const ESCAPED = /_([0-9a-f]+)_/g;
  const PANEL = "panel";
  const SIZES = {panel: [6, 4], item: [4, 3]};
  const HOSTS = "[data-panel], [data-item]";
  const XHTML = "http://www.w3.org/1999/xhtml";
  const SVG = "http://www.w3.org/2000/svg";
  const panels = new Map();
  const items = new Map();
  const placed = new WeakMap();

  const keyOf = (pin) => `${pin.kind}:${pin.id}`;
  const span = (value) => Number.isInteger(value) && value >= 1 && value <= SPAN;
  const clamp = (value) => Math.min(Math.max(Math.round(value), 1), SPAN);

  /**
   * @param raw - an item's own id, any text.
   * @returns the pin id in the view store grammar of ViewStore.id: each character outside A-Z, a-z, 0-9 and ./- as
   * _<hex>_; null when that runs past 200 characters, as such an id would lose its way back to the item.
   */
  function token(raw) {
    const text = String(raw).replace(ESCAPE, (char) => `_${char.codePointAt(0).toString(16)}_`);
    return text.length <= ID_MAX ? text : null;
  }

  const raw = (id) => id.replace(ESCAPED, (_, hex) => String.fromCodePoint(parseInt(hex, 16)));

  function valid(pin) {
    return Boolean(pin) && typeof pin === "object" && !Array.isArray(pin) && Object.keys(pin).sort().join(",") === "h,id,kind,w"
      && typeof pin.kind === "string" && KIND.test(pin.kind) && typeof pin.id === "string" && ID.test(pin.id) && span(pin.w) && span(pin.h);
  }

  function validLayout(pins) {
    return Array.isArray(pins) && pins.length <= MAX && pins.every(valid) && new Set(pins.map(keyOf)).size === pins.length;
  }

  function clean(pins) {
    if (!Array.isArray(pins)) {
      return [];
    }
    const seen = new Set();
    return pins.filter((pin) => valid(pin) && !seen.has(keyOf(pin)) && Boolean(seen.add(keyOf(pin)))).slice(0, MAX).map(({kind, id, w, h}) => ({kind, id, w, h}));
  }

  /**
   * @param id - the panel id, the value of the source element's data-panel.
   * @param title - the tile title.
   * @param render - (size) => Node, size being {w, h} in grid cells.
   * @param group - optional name of a group of which Home holds one pin at most, such as the 3D views.
   */
  function panel(id, title, render, group) {
    panels.set(id, {title, render, group: group || ""});
  }

  /**
   * @param kind - the item kind, the part of data-item before the first colon.
   * @param title - the tile title, or (id) => title.
   * @param render - (size, id) => Node, or null once the item no longer exists.
   */
  function item(kind, title, render) {
    items.set(kind, {title, render, group: ""});
  }

  function lookup(kind, id) {
    const entry = kind === PANEL ? panels.get(id) : items.get(kind);
    if (!entry) {
      return null;
    }
    const plain = kind === PANEL ? id : raw(id);
    return {kind, id, group: entry.group, title: typeof entry.title === "function" ? entry.title(plain) : entry.title, render: (size) => entry.render(size, plain)};
  }

  function targetOf(element) {
    if (element.hasAttribute("data-panel")) {
      return {kind: PANEL, id: element.getAttribute("data-panel")};
    }
    const value = element.getAttribute("data-item") || "";
    const cut = value.indexOf(":");
    return cut > 0 ? {kind: value.slice(0, cut), id: token(value.slice(cut + 1))} : null;
  }

  const has = (pins, kind, id) => pins.some((pin) => pin.kind === kind && pin.id === id);
  const groupOf = (pin) => (lookup(pin.kind, pin.id) || {group: ""}).group;

  /**
   * @returns {pins, refused, holder}: pins unchanged when the pin is already there or refused; refused is "" when the
   * pin is there, "full" at 64 pins and "group" when holder, a pin of the same single-instance group, is on Home.
   */
  function add(pins, kind, id) {
    if (has(pins, kind, id)) {
      return {pins, refused: "", holder: null};
    }
    if (pins.length >= MAX) {
      return {pins, refused: "full", holder: null};
    }
    const group = groupOf({kind, id});
    const holder = group ? pins.find((pin) => groupOf(pin) === group) || null : null;
    if (holder) {
      return {pins, refused: "group", holder};
    }
    const [w, h] = kind === PANEL ? SIZES.panel : SIZES.item;
    return {pins: [...pins, {kind, id, w, h}], refused: "", holder: null};
  }

  const firstOfGroup = (pins, pin) => !groupOf(pin) || pins.find((other) => groupOf(other) === groupOf(pin)) === pin;

  const remove = (pins, kind, id) => pins.filter((pin) => !(pin.kind === kind && pin.id === id));
  const indexOf = (pins, key) => pins.findIndex((pin) => keyOf(pin) === key);

  function place(pins, from, to) {
    if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || from >= pins.length || to < 0 || to >= pins.length || from === to) {
      return pins;
    }
    const next = [...pins];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    return next;
  }

  const move = (pins, index, step) => (index < 0 ? pins : place(pins, index, Math.min(Math.max(index + step, 0), pins.length - 1)));
  const resize = (pins, index, w, h) => pins.map((pin, at) => (at === index ? {...pin, w: clamp(w), h: clamp(h)} : pin));
  const placeKey = (pins, from, to) => place(pins, indexOf(pins, from), indexOf(pins, to));
  const moveKey = (pins, key, step) => move(pins, indexOf(pins, key), step);
  const resizeKey = (pins, key, w, h) => resize(pins, indexOf(pins, key), w, h);

  function resizeBy(pins, key, dw, dh) {
    const pin = pins[indexOf(pins, key)];
    return pin ? resize(pins, indexOf(pins, key), pin.w + dw, pin.h + dh) : pins;
  }

  /**
   * @param start - the tile's {w, h} when the gesture began.
   * @param dx - the pointer's horizontal travel in px.
   * @param dy - the pointer's vertical travel in px.
   * @param column - one column plus its gap in px.
   * @param row - one row plus its gap in px.
   * @returns the new {w, h}, each rounded to whole cells and held in 1 to 12.
   */
  function stretch(start, dx, dy, column, row) {
    return {w: clamp(start.w + dx / column), h: clamp(start.h + dy / row)};
  }

  function memory() {
    const values = new Map();
    const listeners = new Map();
    return {
      get: (path) => values.get(path),
      update: (path, change) => {
        const value = change(values.get(path));
        values.set(path, value);
        (listeners.get(path) || []).forEach((listen) => listen(value));
        return Promise.resolve(true);
      },
      on: (path, listen) => listeners.set(path, [...(listeners.get(path) || []), listen]),
    };
  }

  /**
   * @param backend - an object with get(path), update(path, change) and on(path, cb), as ViewStore offers; get and
   * on may throw for a path the store does not know, update re-runs change on the stored list after a conflict.
   * @param path - the view store path of the pins.
   * @returns {read, change, watch, error}: read() gives the cleaned pins, change(fn) hands fn, a pure function from
   * the stored pins to the new ones, to backend.update and gives a promise of its true or false, refused before the
   * store when fn makes an invalid layout of the shown pins; watch(cb) calls cb with the cleaned pins on every change
   * and error() gives the store's reason for its last refusal.
   */
  function store(backend, path) {
    const read = () => {
      try {
        return clean(backend.get(path));
      } catch {
        return [];
      }
    };
    return {
      read,
      change: (fn) => {
        if (!validLayout(fn(read()))) {
          return Promise.reject(new Error("invalid layout"));
        }
        return new Promise((resolve) => resolve(backend.update(path, (stored) => {
          const before = clean(stored);
          const after = fn(before);
          return validLayout(after) ? after : before;
        })));
      },
      watch: (listen) => {
        try {
          backend.on(path, (value) => listen(clean(value)));
          return true;
        } catch {
          return false;
        }
      },
      error: () => (typeof backend.error === "function" ? backend.error() : ""),
    };
  }

  function glyph(name) {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("class", "bi");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const use = document.createElementNS(SVG, "use");
    use.setAttribute("href", `#${name}`);
    svg.append(use);
    return svg;
  }

  function paint(button, on, title) {
    const label = on ? "Unpin from Home" : "Pin to Home";
    if (button.getAttribute("aria-pressed") !== String(on)) {
      button.setAttribute("aria-pressed", String(on));
      button.replaceChildren(glyph(on ? "bi-star-fill" : "bi-star"));
    }
    if (button.getAttribute("aria-label") !== label) {
      button.setAttribute("aria-label", label);
    }
    const hint = `${label}: ${title}`;
    if (button.getAttribute("title") !== hint) {
      button.setAttribute("title", hint);
    }
  }

  function slotOf(element) {
    const own = [...element.querySelectorAll("[data-star-slot]")].find((slot) => slot.closest(HOSTS) === element);
    if (own) {
      return own;
    }
    const found = [...element.children].find((child) => child.classList.contains("star-row"));
    if (found) {
      return found;
    }
    const row = document.createElement("div");
    row.setAttribute("class", "star-row");
    element.prepend(row);
    return row;
  }

  function button(element, options, enabled) {
    const made = document.createElement("button");
    made.setAttribute("type", "button");
    made.setAttribute("class", "star btn small ghost icon-only");
    if (!enabled) {
      made.setAttribute("disabled", "");
      made.setAttribute("aria-label", "Pin to Home");
      made.setAttribute("title", "Pin to Home: not possible, the id runs past 200 characters");
      made.append(glyph("bi-star"));
      return made;
    }
    made.addEventListener("pointerdown", (event) => event.stopPropagation());
    made.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const now = targetOf(element);
      const entry = now && now.id ? lookup(now.kind, now.id) : null;
      if (entry) {
        options.press(now.kind, now.id, entry.title);
      }
    });
    return made;
  }

  function star(element, options) {
    if (element.namespaceURI !== XHTML) {
      return;
    }
    const target = targetOf(element);
    const entry = target && target.id ? lookup(target.kind, target.id) : null;
    if (!target || (target.id && !entry)) {
      return;
    }
    let made = placed.get(element);
    if (!made || !element.contains(made)) {
      made = button(element, options, Boolean(entry));
      placed.set(element, made);
      slotOf(element).append(made);
    }
    if (entry) {
      paint(made, options.pinned(target.kind, target.id), entry.title);
    }
  }

  /**
   * @param root - the element whose subtree gets a star on every element with data-panel or data-item; the star goes
   * into the element's own data-star-slot descendant, else into a star row the element gets as its first child.
   * @param options - {pinned(kind, id) => boolean, press(kind, id, title), marks: [[selector, panel id], ...]}, marks
   * naming source elements whose page carries no data-panel of its own.
   * @returns mark(): tags the marks, stars what lacks one and repaints the pressed state of all.
   */
  function decorate(root, options) {
    const marks = options.marks || [];
    const mark = () => {
      marks.forEach(([selector, id]) => root.querySelectorAll(selector).forEach((element) => element.hasAttribute("data-panel") || element.setAttribute("data-panel", id)));
      root.querySelectorAll(HOSTS).forEach((element) => star(element, options));
    };
    mark();
    new MutationObserver(mark).observe(root, {childList: true, subtree: true});
    return mark;
  }

  return {
    MAX, SPAN, PANEL, ID, HOSTS, keyOf, token, raw, valid, validLayout, clean, panel, item, lookup, targetOf, has, add, remove, firstOfGroup,
    place, move, resize, placeKey, moveKey, resizeKey, resizeBy, stretch, memory, store, decorate,
  };
})();
if (typeof module === "object" && module.exports) {
  module.exports = Panels;
}
