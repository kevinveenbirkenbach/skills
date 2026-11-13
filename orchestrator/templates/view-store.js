const ViewStore = (() => {
  "use strict";
  const ROUTE = "/api/view";
  const DELAY = 250;
  const TRIES = 3;
  const ID_LIMIT = 200;
  const HASHED = 8;
  const ESCAPE = /[^A-Za-z0-9./-]/gu;
  const LEAF = /^[A-Za-z]{1,32}\.[A-Za-z]{1,32}$/u;
  const HEADERS = {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"};
  const store = {doc: null, saved: null, flight: new Map(), pending: new Map(), listeners: [], timer: 0, chain: Promise.resolve(), waiting: [], error: "", leaving: false};
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const related = (one, other) => one === "" || other === "" || one === other || one.startsWith(`${other}.`) || other.startsWith(`${one}.`);

  function slot(path, doc) {
    const keys = String(path).split(".");
    let parent = null;
    let node = doc;
    for (const key of keys) {
      if (node === null || typeof node !== "object" || Array.isArray(node) || !Object.hasOwn(node, key)) {
        throw new Error(`unknown view path ${path}`);
      }
      parent = node;
      node = node[key];
    }
    return {parent, key: keys[keys.length - 1], value: node};
  }

  const fold = (changes, base) => changes.reduce((value, change) => clone(change(clone(value))), base);

  function rebuild() {
    const next = clone(store.saved);
    for (const [path, entry] of store.flight) {
      const found = slot(path, next);
      found.parent[found.key] = clone(entry.value);
    }
    for (const [path, changes] of store.pending) {
      const found = slot(path, next);
      found.parent[found.key] = fold(changes, found.value);
    }
    store.doc = next;
  }

  function notify(path) {
    for (const entry of [...store.listeners]) {
      if (related(entry.path, path)) {
        entry.callback(get(entry.path));
      }
    }
  }

  /**
   * @param doc - the whole view document the hub served.
   */
  function start(doc) {
    store.saved = clone(doc);
    store.flight = new Map();
    store.pending = new Map();
    rebuild();
    notify("");
  }

  function current() {
    if (store.doc === null) {
      start(JSON.parse(document.getElementById("view").textContent));
    }
    return store.doc;
  }

  /**
   * @param path - a dotted key of the view document, such as resources.hidden.
   * @returns a copy of its value as this page shows it, its own unsent changes included.
   */
  const get = (path) => clone(slot(path, current()).value);

  function adopt(doc) {
    store.saved = clone(doc);
    rebuild();
    notify("");
  }

  async function send(body, keepalive) {
    try {
      const response = await fetch(ROUTE, {method: "PATCH", headers: HEADERS, body: JSON.stringify(body), cache: "no-store", keepalive});
      if (response.ok || response.status === 409) {
        return {status: response.ok ? 200 : 409, data: await response.json()};
      }
      return {status: response.status, error: (await response.text()).trim() || String(response.status)};
    } catch (error) {
      return {status: 0, error: String(error && error.message ? error.message : error)};
    }
  }

  function takeOff() {
    const body = {set: {}, expect: {}};
    for (const [path, changes] of store.pending) {
      const base = slot(path, store.saved).value;
      const value = fold(changes, base);
      store.flight.set(path, {changes, value});
      body.set[path] = value;
      body.expect[path] = base;
    }
    store.pending = new Map();
    return body;
  }

  function land() {
    const back = new Map([...store.flight].map(([path, entry]) => [path, [...entry.changes, ...(store.pending.get(path) || [])]]));
    store.flight = new Map();
    for (const [path, changes] of store.pending) {
      if (!back.has(path)) {
        back.set(path, changes);
      }
    }
    store.pending = back;
  }

  async function flush() {
    const waiting = store.waiting.splice(0);
    let stored = true;
    for (let attempt = 1; store.pending.size; attempt += 1) {
      const answer = await send(takeOff(), false);
      if (answer.status === 200) {
        store.flight = new Map();
        store.error = "";
        adopt(answer.data);
        break;
      }
      if (answer.status === 409 && attempt < TRIES) {
        land();
        adopt(answer.data.view);
        continue;
      }
      store.error = answer.status === 409 ? `another browser kept changing ${answer.data.paths.join(", ")}; try again` : answer.error;
      store.flight = new Map();
      adopt(answer.status === 409 ? answer.data.view : store.saved);
      stored = false;
      break;
    }
    waiting.forEach((resolve) => resolve(stored));
  }

  function leave() {
    clearTimeout(store.timer);
    store.timer = 0;
    if (!store.pending.size) {
      return;
    }
    const body = {set: {}, expect: {}};
    for (const [path, changes] of store.pending) {
      const base = store.flight.has(path) ? store.flight.get(path).value : slot(path, store.saved).value;
      body.set[path] = fold(changes, base);
      body.expect[path] = base;
    }
    store.pending = new Map();
    const waiting = store.waiting.splice(0);
    send(body, true).then((answer) => {
      if (answer.status === 200) {
        adopt(answer.data);
      }
      waiting.forEach((resolve) => resolve(answer.status === 200));
    });
  }

  /**
   * @param path - a section.key of the view document, such as home.pins.
   * @param change - a function from the key's current value to its new one; when another browser changed the key
   * meanwhile, the hub refuses the write and the page runs change again on the stored value, up to three times.
   * @returns a promise of true once the hub stored the change, false when it refused it; the page then shows the
   * stored value again and error() says why.
   */
  function update(path, change) {
    if (!LEAF.test(String(path))) {
      throw new Error(`a view path to change must be section.key, not ${path}`);
    }
    slot(path, current());
    store.pending.set(path, [...(store.pending.get(path) || []), change]);
    rebuild();
    notify(path);
    if (!store.leaving && typeof addEventListener === "function") {
      store.leaving = true;
      addEventListener("pagehide", leave);
    }
    clearTimeout(store.timer);
    store.timer = setTimeout(() => {
      store.timer = 0;
      store.chain = store.chain.then(flush);
    }, DELAY);
    return new Promise((resolve) => store.waiting.push(resolve));
  }

  /**
   * @param path - a section.key of the view document that holds a scalar; a list path throws, it changes through
   * update() only.
   * @param value - its new value, replacing whatever another browser stored there.
   * @returns the promise update() returns.
   */
  function set(path, value) {
    if (Array.isArray(slot(path, current()).value)) {
      throw new Error(`a list view path changes through update(), not set(): ${path}`);
    }
    return update(path, () => clone(value));
  }

  async function restore(event) {
    if (!event.persisted) {
      return;
    }
    try {
      const response = await fetch(ROUTE, {method: "GET", cache: "no-store"});
      if (response.ok) {
        adopt(await response.json());
      }
    } catch (error) {
      store.error = String(error && error.message ? error.message : error);
    }
  }

  if (typeof addEventListener === "function") {
    addEventListener("pageshow", restore);
  }

  /**
   * @param path - a dotted key of the view document.
   * @param callback - called with the key's new value whenever it, a key inside it or one around it changes.
   * @returns a function that stops the calls.
   */
  function on(path, callback) {
    slot(path, current());
    const entry = {path: String(path), callback};
    store.listeners.push(entry);
    return () => {
      store.listeners = store.listeners.filter((item) => item !== entry);
    };
  }

  function hash(text) {
    let value = 0x811c9dc5;
    for (const char of text) {
      value = Math.imul(value ^ char.codePointAt(0), 0x01000193) >>> 0;
    }
    return value.toString(16).padStart(HASHED, "0");
  }

  /**
   * @param parts - the names that make one series, such as its kind and its name.
   * @returns an id of the view document's grammar: every part with each character outside A-Z, a-z, 0-9 and ./-
   * written as _<hex>_, joined by ":", and cut to 200 characters with a hash of the whole when longer.
   */
  function id(...parts) {
    const text = parts.map((part) => String(part).replace(ESCAPE, (char) => `_${char.codePointAt(0).toString(16)}_`)).join(":");
    return text.length <= ID_LIMIT ? text : `${text.slice(0, ID_LIMIT - HASHED - 1)}:${hash(text)}`;
  }

  return {ROUTE, DELAY, TRIES, start, get, set, update, on, id, error: () => store.error};
})();
if (typeof module === "object" && module.exports) {
  module.exports = ViewStore;
}
