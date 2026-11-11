const Bubbles = (() => {
  "use strict";
  const SCALES = [1, 0.8, 0.65];
  const SMALLEST = 0.5;
  const PACE = 180;
  const SHORTEST = 1.5;

  function scale(position) {
    return SCALES[position] ?? SMALLEST;
  }

  function words(text) {
    return String(text || "").split(/\s+/).filter(Boolean);
  }

  function reading(count) {
    return Math.max(SHORTEST, (count * 60) / PACE);
  }

  function reveals(count, duration) {
    return Array.from({length: count}, (_, index) => (index / count) * duration);
  }

  function shown(count, duration, elapsed) {
    return reveals(count, duration).filter((at) => at <= elapsed).length;
  }

  function picked(row, speech) {
    return row.class === "mayday" || speech.classes.includes(row.class);
  }

  function plan(head, pending) {
    const queue = head ? [head, ...pending] : pending;
    const shift = head ? 0 : 1;
    const seen = new Set();
    return queue.flatMap((item, index) => {
      if (seen.has(item.who)) {
        return [];
      }
      seen.add(item.who);
      return [{who: item.who, item, scale: scale(index + shift)}];
    });
  }

  return {SCALES, SMALLEST, PACE, SHORTEST, scale, words, reading, reveals, shown, picked, plan};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Bubbles;
}
