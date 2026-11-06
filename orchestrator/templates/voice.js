const Voice = (() => {
  "use strict";
  const RANKS = {mayday: 0, "pan-pan": 1, security: 2};
  const ALARMS = new Set(["mayday", "pan-pan"]);
  const ROUTINE = 3;

  function toneOf(row, human) {
    if (ALARMS.has(row.class)) {
      return "mayday";
    }
    return row.class === "security" || row.to.includes(human) ? "direct" : "radio";
  }

  function loudness(tone, settings) {
    if (tone !== "mayday") {
      return settings.sounds[tone].volume;
    }
    return Math.max(...Object.values(settings.sounds).map((sound) => sound.volume), settings.music.volume);
  }

  function speakable(row, speech) {
    if (!speech.on || !row.speech || !row.voice) {
      return false;
    }
    return row.class === "mayday" || (speech.classes.includes(row.class) && !speech.muted.includes(row.source));
  }

  function rank(item) {
    return Object.hasOwn(RANKS, item.cls) ? RANKS[item.cls] : ROUTINE;
  }

  function enqueue(pending, item, limit) {
    const at = pending.findIndex((other) => rank(other) > rank(item));
    const next = at < 0 ? [...pending, item] : [...pending.slice(0, at), item, ...pending.slice(at)];
    return next.slice(0, limit);
  }

  function frames(duration, rate, seconds) {
    return Math.max(Math.min(Math.ceil(duration * rate), rate * seconds), 0);
  }

  function wav(samples, rate) {
    const size = samples.length * 2;
    const buffer = new ArrayBuffer(44 + size);
    const view = new DataView(buffer);
    const text = (offset, value) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)));
    text(0, "RIFF");
    view.setUint32(4, 36 + size, true);
    text(8, "WAVE");
    text(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, rate, true);
    view.setUint32(28, rate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    text(36, "data");
    view.setUint32(40, size, true);
    samples.forEach((sample, index) => {
      const level = Math.max(-1, Math.min(1, sample));
      view.setInt16(44 + index * 2, level < 0 ? level * 0x8000 : level * 0x7fff, true);
    });
    return buffer;
  }

  return {toneOf, loudness, speakable, enqueue, frames, wav};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Voice;
}
