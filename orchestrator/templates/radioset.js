const RadioSet = (() => {
  "use strict";
  const KEY = "kvb-orchestrator.radio";
  const MODES = ["auto", "quiet", "silence"];
  const TONES = ["mayday", "review", "direct", "radio"];
  const CLASSES = ["post", "call", "newsletter", "broadcast", "mayday", "pan-pan", "security"];
  const TO_ALL = new Set(["newsletter", "broadcast", "mayday", "pan-pan", "security"]);
  const TABS = ["sent", "received", "all"];
  const CHIPS = ["class", "from", "to", "agent"];
  const TEXT_LIMIT = 200;
  const MUTED_LIMIT = 200;
  const BURST = {seconds: 0.6, frequency: 1800, q: 0.9};
  const MARK = /\[kvb-orchestrator msg ([0-9a-f]{16})\]/;
  const DEFAULTS = {
    mode: "auto",
    sounds: {mayday: {on: true, volume: 0.9}, review: {on: true, volume: 0.6}, direct: {on: true, volume: 0.5}, radio: {on: false, volume: 0.25}},
    squelch: 1,
    classes: ["mayday", "pan-pan", "security"],
    muted: [],
    log: {tab: "received", chips: {class: "", from: "", to: "", agent: ""}, q: ""},
  };

  const level = (value, fallback) => (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1 ? value : fallback);
  const short = (value) => typeof value === "string" && value.length <= TEXT_LIMIT;
  const object = (value) => (value && typeof value === "object" && !Array.isArray(value) ? value : {});

  function tone(raw, fallback) {
    const entry = object(raw);
    return {on: typeof entry.on === "boolean" ? entry.on : fallback.on, volume: level(entry.volume, fallback.volume)};
  }

  function log(raw) {
    const entry = object(raw);
    const chips = object(entry.chips);
    return {
      tab: TABS.includes(entry.tab) ? entry.tab : DEFAULTS.log.tab,
      chips: Object.fromEntries(CHIPS.map((name) => [name, short(chips[name]) ? chips[name] : ""])),
      q: short(entry.q) ? entry.q : "",
    };
  }

  /**
   * @param {object|null} stored the radio set this browser kept, or null.
   * @returns {object} the radio set with every unknown or broken field at its default; MAYDAY always stays read aloud.
   */
  function valid(stored) {
    const raw = object(stored);
    const sounds = object(raw.sounds);
    const classes = Array.isArray(raw.classes) ? raw.classes : DEFAULTS.classes;
    const muted = Array.isArray(raw.muted) ? raw.muted.filter((key) => typeof key === "string" && key && key.length <= TEXT_LIMIT) : [];
    return {
      mode: MODES.includes(raw.mode) ? raw.mode : DEFAULTS.mode,
      sounds: Object.fromEntries(TONES.map((name) => [name, tone(sounds[name], DEFAULTS.sounds[name])])),
      squelch: level(raw.squelch, DEFAULTS.squelch),
      classes: CLASSES.filter((name) => name === "mayday" || classes.includes(name)),
      muted: [...new Set(muted)].sort().slice(0, MUTED_LIMIT),
      log: log(raw.log),
    };
  }

  function picked(row, set) {
    return row.class === "mayday" || (set.classes.includes(row.class) && !set.muted.includes(row.source));
  }

  /**
   * @param {object} row a radio row of the state with word, rest and voice.
   * @param {object} set the radio set.
   * @param {Object<string, boolean>} live tts and open: whether the hub speaks at all and whether its CPU gate is open.
   * @returns {Array<{kind: string, text: (string|undefined)}>} what plays, in order: the procedure word line in every mode, then the spoken rest in Auto below the threshold, else the noise burst, nothing more in Silence.
   */
  function plan(row, set, live) {
    if (!picked(row, set)) {
      return [];
    }
    const word = live.tts && row.voice && row.word ? [{kind: "word", text: row.word}] : [];
    if (set.mode === "silence") {
      return word;
    }
    const spoken = set.mode === "auto" && live.tts && live.open && row.voice && row.rest;
    return [...word, spoken ? {kind: "speech", text: row.rest} : {kind: "burst"}];
  }

  /**
   * @param {number} loudness the tone's volume times the squelch.
   * @returns {Object<string, number>} seconds, frequency, q and gain of the band-passed white noise of the squelch tail.
   */
  function burst(loudness) {
    return {...BURST, gain: loudness};
  }

  function toAll(row) {
    return TO_ALL.has(row.class) || !row.to.length;
  }

  /**
   * @param {object} row a radio row.
   * @param {Array<object>} messages the hub's message ledger of the state.
   * @returns {object|null} the ledger message the row relays; null for a row no message of this hub sent, whatever its sender name.
   */
  function ledgerOf(row, messages) {
    const found = MARK.exec(row.text);
    return found ? messages.find((message) => message.id === found[1]) || null : null;
  }

  function sentRows(messages, human) {
    return messages.map((message) => ({ts: message.created_ts, from: human, to: message.to === "*" ? [] : [message.to], class: message.class || "post", text: message.text, voice: message.voice, sent: true, readers: message.readers, acks: message.acks}));
  }

  function tabRows(rows, tab, human, messages) {
    if (tab === "sent") {
      return sentRows(messages, human);
    }
    return rows.filter((row) => tab === "all" || toAll(row) || row.to.includes(human));
  }

  function matches(row, entry) {
    const {chips, q} = entry;
    const words = q.trim().toLowerCase();
    return (!chips.class || row.class === chips.class)
      && (!chips.from || row.from === chips.from)
      && (!chips.to || row.to.includes(chips.to))
      && (!chips.agent || row.from === chips.agent || row.to.includes(chips.agent))
      && (!words || [row.text, row.from, ...row.to].join("\n").toLowerCase().includes(words));
  }

  /**
   * @param {Array<object>} rows the radio rows of the state.
   * @param {object} entry the log part of the radio set: tab, chips and q.
   * @param {string} human the operator's name.
   * @param {Array<object>} messages the hub's message ledger; Sent lists it, not radio rows that only claim the operator's name.
   * @returns {Array<object>} the rows of the tab that every chip and the search match, newest first.
   */
  function logRows(rows, entry, human, messages) {
    return tabRows(rows, entry.tab, human, messages).filter((row) => matches(row, entry)).sort((a, b) => b.ts - a.ts);
  }

  function counts(rows, human, messages) {
    return Object.fromEntries(TABS.map((tab) => [tab, tabRows(rows, tab, human, messages).length]));
  }

  function choices(rows) {
    const sorted = (values) => [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
    const names = rows.flatMap((row) => [row.from, ...row.to]);
    return {
      class: CLASSES.filter((name) => rows.some((row) => row.class === name)).concat(sorted(rows.map((row) => row.class)).filter((name) => !CLASSES.includes(name))),
      from: sorted(rows.map((row) => row.from)),
      to: sorted(rows.flatMap((row) => row.to)),
      agent: sorted(names),
    };
  }

  function cleared(entry) {
    return {...entry, chips: Object.fromEntries(CHIPS.map((name) => [name, ""])), q: ""};
  }

  return {KEY, MODES, TONES, CLASSES, TABS, CHIPS, DEFAULTS, valid, picked, plan, burst, toAll, ledgerOf, logRows, counts, choices, cleared};
})();
if (typeof module === "object" && module.exports) {
  module.exports = RadioSet;
}
