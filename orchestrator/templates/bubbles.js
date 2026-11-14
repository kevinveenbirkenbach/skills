const Bubbles = (() => {
  "use strict";
  const SCALES = [1, 0.8, 0.65];
  const SMALLEST = 0.5;
  const PACE = 180;
  const SHORTEST = 1.5;
  const QUIET_SCALE = 0.8;
  const QUIET_CAP = 3;
  const QUIET_WAIT = 30;

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

  /**
   * @param {object|null} head the row that sounds or loads now.
   * @param {Array<object>} pending the rows of the speech queue, in order.
   * @param {Array<object>} [quiet] the silent bubbles on screen, rows that are not read aloud.
   * @returns {Array<object>} who, item and scale of one bubble per agent: the speech queue first, by its position, then the silent bubbles of agents the queue leaves free.
   */
  function plan(head, pending, quiet) {
    const queue = head ? [head, ...pending] : pending;
    const shift = head ? 0 : 1;
    const seen = new Set();
    const once = (item, size) => {
      if (seen.has(item.who)) {
        return [];
      }
      seen.add(item.who);
      return [{who: item.who, item, scale: size}];
    };
    return [...queue.flatMap((item, index) => once(item, scale(index + shift))), ...(quiet || []).flatMap((item) => once(item, QUIET_SCALE))];
  }

  /**
   * @param {Array<object>} showing the silent bubbles on screen now.
   * @param {Array<object>} waiting the silent bubbles that wait, oldest first.
   * @param {Set<string>} taken the agents a speech bubble shows now.
   * @returns {object} start: the waiting bubbles that start now, oldest first, so that at most QUIET_CAP show and no agent shows two; waiting: the rest, still waiting.
   */
  function admit(showing, waiting, taken) {
    const busy = new Set([...taken, ...showing.map((item) => item.who)]);
    const start = [];
    const rest = [];
    for (const item of waiting) {
      if (showing.length + start.length < QUIET_CAP && !busy.has(item.who)) {
        busy.add(item.who);
        start.push(item);
      } else {
        rest.push(item);
      }
    }
    return {start, waiting: rest};
  }

  /**
   * @param {Array<object>} waiting the silent bubbles that wait, oldest first.
   * @param {object} item the silent bubble of a row that arrived live.
   * @returns {Array<object>} the waiting bubbles with the item last, at most QUIET_WAIT, the oldest dropped first.
   */
  function queued(waiting, item) {
    return [...waiting, item].slice(-QUIET_WAIT);
  }

  return {SCALES, SMALLEST, PACE, SHORTEST, QUIET_SCALE, QUIET_CAP, QUIET_WAIT, scale, words, reading, reveals, shown, picked, plan, admit, queued};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Bubbles;
}
