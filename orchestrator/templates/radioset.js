const RadioSet = (() => {
  "use strict";
  const KEY = "kvb-orchestrator.radio";
  const MODES = ["auto", "quiet", "silence", "morse", "gibberlink"];
  const FALLBACKS = ["gibberlink", "morse", "burst"];
  const KEYED = ["morse", "gibberlink"];
  const FRAME = {bytes: 140, prefix: 8, key: 64};
  const TONES = ["mayday", "review", "direct", "radio"];
  const CLASSES = ["post", "call", "newsletter", "broadcast", "mayday", "pan-pan", "security"];
  const TO_ALL = new Set(["newsletter", "broadcast", "mayday", "pan-pan", "security"]);
  const TABS = ["sent", "received", "all"];
  const CHIPS = ["class", "from", "to", "agent"];
  const TEXT_LIMIT = 200;
  const MUTED_LIMIT = 200;
  const BURST = {seconds: 0.6, frequency: 1800, q: 0.9};
  const MARK = /\[kvb-orchestrator msg ([0-9a-f]{16})\]/;
  const MARKS = new RegExp(MARK.source, "g");
  const GATE = {min: 0, max: 100, step: 10};
  const PROSIGNS = {
    mayday: {sign: "SOS", joined: true, called: false},
    "pan-pan": {sign: "PAN PAN", joined: false, called: false},
    security: {sign: "SECURITE", joined: false, called: false},
    broadcast: {sign: "CQ", joined: false, called: false},
    newsletter: {sign: "CQ", joined: false, called: false},
    call: {sign: "", joined: false, called: true},
    post: {sign: "KA", joined: true, called: false},
  };
  const DEFAULTS = {
    mode: "auto",
    fallback: "gibberlink",
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
      fallback: FALLBACKS.includes(raw.fallback) ? raw.fallback : DEFAULTS.fallback,
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
   * @param {object} row a radio row of the state with class, called, speaker, pitch and text.
   * @returns {object} the whole row keyed in Morse as kind "morse", sign, joined, text and pitch: the class prosign, or the called stations of a call, then DE with the sender's clear name and the full text without the hub's message mark, in the sender's pitch.
   */
  function morse(row) {
    const {sign, joined, called} = PROSIGNS[row.class];
    return {kind: "morse", sign: called ? row.called.join(" ") : sign, joined, text: `DE ${row.speaker} ${row.text.replace(MARKS, " ")}`, pitch: row.pitch};
  }

  const utf8 = (char) => {
    const point = char.codePointAt(0);
    return point < 0x80 ? 1 : point < 0x800 ? 2 : point < 0x10000 ? 3 : 4;
  };

  function fitting(chars, at, room) {
    let end = at;
    for (let left = room; end < chars.length && utf8(chars[end]) <= left; end += 1) {
      left -= utf8(chars[end]);
    }
    return end;
  }

  function split(key, chars, count) {
    const own = Array.from(key);
    const full = own.slice(0, fitting(own, 0, FRAME.key)).join("");
    const prefix = own.slice(0, FRAME.prefix).join("");
    const out = [];
    let at = 0;
    do {
      const head = `${out.length ? prefix : full} ${out.length + 1}/${count} `;
      const end = fitting(chars, at, FRAME.bytes - Array.from(head).reduce((sum, char) => sum + utf8(char), 0));
      out.push(head + chars.slice(at, end).join(""));
      at = end;
    } while (at < chars.length);
    return out;
  }

  /**
   * @param {string} key the sender's session key, the row's source; its first 64 bytes head frame 1.
   * @param {string} text the message without the hub's mark.
   * @returns {Array<string>} the frames of at most 140 UTF-8 bytes, each split between characters: frame 1 the key, `1/m` and text, every later frame the key's first 8 characters, `n/m` and text.
   */
  function frames(key, text) {
    const chars = Array.from(text);
    for (let count = 1; ;) {
      const out = split(key, chars, count);
      if (out.length === count) {
        return out;
      }
      count = out.length;
    }
  }

  /**
   * @param {object} row a radio row with source, text, protocol and pan.
   * @returns {object} the whole row as kind "gibberlink": its frames, the sender's ggwave protocol and its stereo position.
   */
  function gibberlink(row) {
    return {kind: "gibberlink", frames: frames(row.source, row.text.replace(MARKS, "").trim()), protocol: row.protocol, pan: row.pan};
  }

  const STAND_INS = {gibberlink, morse, burst: () => ({kind: "burst"})};

  /**
   * @param {object} row a radio row of the state.
   * @param {object} set the radio set.
   * @returns {object} the step its fallback pick plays where speech cannot: Gibberlink frames, Morse keying or the burst.
   */
  function standIn(row, set) {
    return STAND_INS[set.fallback](row);
  }

  /**
   * @param {object} row a radio row of the state with word, rest, voice, the Morse and the Gibberlink fields.
   * @param {object} set the radio set.
   * @param {Object<string, boolean>} live tts and open: whether the hub speaks at all and whether its CPU gate is open.
   * @returns {Array<{kind: string, text: (string|undefined)}>} what plays, in order: in Morse the whole row keyed once; else the procedure word line in every mode, then in Gibberlink the frames of the whole row, in Auto below the threshold the spoken rest, else the fallback pick, nothing more in Silence.
   */
  function plan(row, set, live) {
    if (!picked(row, set)) {
      return [];
    }
    if (set.mode === "morse") {
      return [morse(row)];
    }
    const word = live.tts && row.voice && row.word ? [{kind: "word", text: row.word}] : [];
    if (set.mode === "silence") {
      return word;
    }
    if (set.mode === "gibberlink") {
      return [...word, gibberlink(row)];
    }
    const spoken = set.mode === "auto" && live.tts && live.open && row.voice && row.rest;
    return [...word, spoken ? {kind: "speech", text: row.rest} : standIn(row, set)];
  }

  /**
   * @param {number} loudness the tone's volume times the squelch.
   * @returns {Object<string, number>} seconds, frequency, q and gain of the band-passed white noise of the squelch tail.
   */
  function burst(loudness) {
    return {...BURST, gain: loudness};
  }

  /**
   * @param {number} threshold the speech threshold in percent.
   * @returns {string} the threshold as the radio labels it: always at the top of the range, never at its bottom, else the CPU percent speech stays below.
   */
  function gateLabel(threshold) {
    if (threshold >= GATE.max) {
      return "always";
    }
    return threshold <= GATE.min ? "never" : `speak while CPU < ${threshold} %`;
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
    return messages.map((message) => ({ts: message.created_ts, from: human, to: message.to === "*" ? [] : [message.to], class: message.class || "post", text: message.text, voice: message.voice, sent: true, id: message.id, readers: message.readers, acks: message.acks}));
  }

  /**
   * @param {Array<object>} rows radio rows in arrival order, or sent rows of the ledger.
   * @returns {Array<object>} copies of the rows, each with a key unique in the list and stable while rows arrive: the ledger id of a sent row, else time, sender and the occurrence index among rows of the same time and sender.
   */
  function keyed(rows) {
    const seen = new Map();
    return rows.map((row) => {
      const base = row.sent ? `sent ${row.id}` : `${row.ts} ${row.from}`;
      const index = seen.get(base) || 0;
      seen.set(base, index + 1);
      return {...row, key: `${base} ${index}`};
    });
  }

  function tabRows(rows, tab, human, messages) {
    if (tab === "sent") {
      return keyed(sentRows(messages, human));
    }
    return keyed(rows).filter((row) => tab === "all" || toAll(row) || row.to.includes(human));
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
   * @returns {Array<object>} keyed copies of the rows of the tab that every chip and the search match, newest first.
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

  return {KEY, MODES, FALLBACKS, KEYED, FRAME, TONES, CLASSES, TABS, CHIPS, DEFAULTS, GATE, PROSIGNS, valid, picked, frames, standIn, plan, burst, gateLabel, toAll, ledgerOf, logRows, counts, choices, cleared};
})();
if (typeof module === "object" && module.exports) {
  module.exports = RadioSet;
}
