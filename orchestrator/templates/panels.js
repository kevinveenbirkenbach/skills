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
  const ZOOM = {min: 50, max: 200, step: 10, base: 100};
  const HOSTS = "[data-panel], [data-item]";
  const TOO_LONG = "the id runs past 200 characters";
  const panels = new Map();
  const items = new Map();
  const captures = new Map();

  const keyOf = (pin) => `${pin.kind}:${pin.id}`;
  const span = (value) => Number.isInteger(value) && value >= 1 && value <= SPAN;
  const clamp = (value) => Math.min(Math.max(Math.round(value), 1), SPAN);
  const plain = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);
  const keysOf = (pin) => Object.keys(pin).sort().join(",");

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

  function fnv(text, seed) {
    let value = seed;
    for (const char of text) {
      value = Math.imul(value ^ char.codePointAt(0), 0x01000193) >>> 0;
    }
    return value.toString(16).padStart(8, "0");
  }

  /**
   * @param text - any text, such as the canonical form of a pin's view.
   * @returns 16 hex characters, two FNV-1a hashes of the text with different offsets.
   */
  const digest = (text) => `${fnv(text, 0x811c9dc5)}${fnv(text, 0x01000193)}`;

  function valid(pin) {
    return plain(pin) && ["h,id,kind,w", "h,id,kind,view,w"].includes(keysOf(pin)) && (!Object.hasOwn(pin, "view") || plain(pin.view))
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
    return pins.filter((pin) => valid(pin) && !seen.has(keyOf(pin)) && Boolean(seen.add(keyOf(pin)))).slice(0, MAX)
      .map(({kind, id, w, h, view}) => (view ? {kind, id, w, h, view} : {kind, id, w, h}));
  }

  /**
   * @param id - the panel id, the value of the source element's data-panel.
   * @param title - the tile title.
   * @param render - (size) => Node, size being {w, h} in grid cells.
   * @param group - optional name of a group of which Home holds one pin at most, such as the 3D views.
   * @param size - optional [w, h] in grid cells a new pin of the panel gets; SIZES.panel when left out.
   */
  function panel(id, title, render, group, size) {
    panels.set(id, {title, render, group: group || "", size: size || SIZES.panel});
  }

  /**
   * @param kind - the item kind, the part of data-item before the first colon.
   * @param title - the tile title, or (id, view) => title.
   * @param render - (size, id, view) => Node, or null once the item no longer exists; view is the pin's stored view,
   * undefined for a pin without one.
   */
  function item(kind, title, render) {
    items.set(kind, {title, render, group: ""});
  }

  /**
   * @param id - the data-panel of a source element whose star pins a bookmark of what it shows instead of itself.
   * @param take - (element) => {kind, id, view, refused}: the item pin the star makes now, such as a chart with the
   * series switched on at this moment; the star shows that pin's pressed state, or stays disabled with refused as its
   * reason while refused is a non-empty text.
   */
  function capture(id, take) {
    captures.set(id, take);
  }

  function lookup(kind, id, view) {
    const entry = kind === PANEL ? panels.get(id) : items.get(kind);
    if (!entry) {
      return null;
    }
    const name = kind === PANEL ? id : raw(id);
    return {kind, id, group: entry.group, title: typeof entry.title === "function" ? entry.title(name, view) : entry.title, render: (size) => entry.render(size, name, view)};
  }

  /**
   * @param element - a source element with data-panel or data-item.
   * @returns {kind, id, view, refused} of the pin its "Pin to Home" makes now, or null for a data-item without a kind; refused
   * names why no pin is possible, such as an id past 200 characters, and id is null then unless a capture gave one.
   */
  function targetOf(element) {
    if (element.hasAttribute("data-panel")) {
      const id = element.getAttribute("data-panel");
      return captures.has(id) ? captures.get(id)(element) : {kind: PANEL, id};
    }
    const value = element.getAttribute("data-item") || "";
    const cut = value.indexOf(":");
    if (cut < 1) {
      return null;
    }
    const id = token(value.slice(cut + 1));
    return id ? {kind: value.slice(0, cut), id} : {kind: value.slice(0, cut), id: null, refused: TOO_LONG};
  }

  const has = (pins, kind, id) => pins.some((pin) => pin.kind === kind && pin.id === id);
  const groupOf = (pin) => (lookup(pin.kind, pin.id) || {group: ""}).group;

  /**
   * @param view - optional plain object the new pin stores, such as the chart selection of a metric bookmark.
   * @returns {pins, refused, holder}: pins unchanged when the pin is already there or refused; refused is "" when the
   * pin is there, "full" at 64 pins and "group" when holder, a pin of the same single-instance group, is on Home.
   */
  function add(pins, kind, id, view) {
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
    const [w, h] = kind === PANEL ? (panels.get(id) || {size: SIZES.panel}).size : SIZES.item;
    return {pins: [...pins, plain(view) ? {kind, id, w, h, view} : {kind, id, w, h}], refused: "", holder: null};
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

  /**
   * @param zooms - the view store's home.zoom: pin key to percent; a pin without one shows at ZOOM.base.
   * @param key - the tile's pin key.
   * @param step - +1 zooms in, -1 out, 0 resets.
   * @returns the new map: the tile at ZOOM.step percent more or less, held in ZOOM.min to ZOOM.max, left out at the base.
   */
  function zoomBy(zooms, key, step) {
    const now = Object.hasOwn(zooms, key) ? zooms[key] : ZOOM.base;
    const next = step === 0 ? ZOOM.base : Math.min(ZOOM.max, Math.max(ZOOM.min, now + step * ZOOM.step));
    const rest = Object.fromEntries(Object.entries(zooms).filter(([name]) => name !== key));
    return next === ZOOM.base ? rest : {...rest, [key]: next};
  }

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

  /**
   * @param root - the element whose subtree carries the marked source elements.
   * @param marks - [[selector, panel id], ...]: source elements whose page carries no data-panel of its own, tagged so
   * that the context menu's "Pin to Home" finds them.
   * @returns mark(): tags the marks again.
   */
  function decorate(root, marks) {
    const mark = () => marks.forEach(([selector, id]) => root.querySelectorAll(selector).forEach((element) => element.hasAttribute("data-panel") || element.setAttribute("data-panel", id)));
    mark();
    new MutationObserver(mark).observe(root, {childList: true, subtree: true});
    return mark;
  }

  return {
    MAX, SPAN, PANEL, ID, HOSTS, keyOf, token, raw, digest, valid, validLayout, clean, panel, item, capture, lookup, targetOf, has, add, remove, firstOfGroup,
    place, move, resize, placeKey, moveKey, resizeKey, resizeBy, stretch, ZOOM, zoomBy, memory, store, decorate,
  };
})();
if (typeof module === "object" && module.exports) {
  module.exports = Panels;
}
