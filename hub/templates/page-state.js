  function stored(key, fallback) {
    try {
      const text = window.localStorage.getItem(key);
      return text === null ? fallback : JSON.parse(text);
    } catch {
      return fallback;
    }
  }

  function keep(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch {
      return false;
    }
  }

  function validViews(value) {
    const names = new Set(KINDS.map(([id]) => id));
    if (!Array.isArray(value)) {
      return [];
    }
    return value.filter((view) => view && typeof view.name === "string" && view.name && Array.isArray(view.kinds) && view.kinds.length && view.kinds.every((name) => names.has(name)))
      .map((view) => ({name: view.name.slice(0, 60), kinds: view.kinds, waiting: view.waiting === true, q: typeof view.q === "string" ? view.q : "", agent: typeof view.agent === "string" ? view.agent : ""}));
  }

  let state = JSON.parse(document.getElementById("state").textContent);
  const ui = {screen: "stream", graph: "orbit", preset: DAY, from: null, to: null, asOf: null, playing: false, busy: false, offline: false, agent: null, order: null, draft: "", node: null, cursor: 0, selected: new Set(), snoozed: false, review: null, file: 0};
  const filter = {view: "fuer-dich", saved: "", kinds: new Set(state.views["fuer-dich"].kinds), waiting: true, q: "", agent: "", session: "", sub: "", parts: new Set(PARTS.map(([id]) => id))};
  const stream = {key: null, events: [], entries: [], last: 0, sessions: {}, busy: false, again: false, dom: null, error: ""};
  const tree = {data: null, busy: false, q: "", open: new Set(), dom: null};
  const palette = {items: [], index: 0, input: null, list: null, plan: null, box: null};
  const known = {inbox: null, alarms: null, radio: null, batches: new Set()};
  const motion = {current: new Map(), from: new Map(), target: new Map(), start: 0, duration: 0, frame: 0, asOf: undefined};
  const drawn = {screen: "", sig: ""};
  const files = new Map();
  const pageMedia = new Set(state.media);
  const sky = {canvas: document.getElementById("sky"), stars: Ambience.stars(320, 7), mode: "", frame: 0};
  const music = {gain: null, filter: null, drone: [], timer: 0, tension: 0, ducked: 0};
  const radio = {element: null, url: "", level: 0, timer: 0, playing: false, waiting: false};
  const speech = {pending: [], busy: false, warned: 0};
  const mic = {recorder: null, held: false, busy: false, timer: 0};
  const space = {
    views: {graph: {...state.settings.space.graph}, sky: {...state.settings.space.sky}}, glides: {graph: null, sky: null}, edits: 0, saved: 0, timer: 0,
    scene: null, sceneCursor: null, cam: null, frame: 0, look: false, compass: null, subs: new Map(), loading: false, version: 0,
    cursor: {from: 0, to: null, start: 0}, style: null, styleKey: "", trackAsked: 0,
  };
  let userViews = validViews(stored(STORE.views, []));
  let settings = state.settings;
  let settingsSig = JSON.stringify(settings);
  let drawerDom = null;
  let timeDom = null;
  let graphDom = null;
  let reviewDom = null;
  let replay = 0;
  let positions = new Map();
  let inboxSig = "";
  let audio = null;
  let searchTimer = 0;
