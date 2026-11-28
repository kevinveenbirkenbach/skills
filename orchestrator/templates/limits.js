const Limits = (() => {
  "use strict";
  const METRICS = ["cpu", "ram", "swap", "disk", "psi"];
  const LEVELS = ["lower", "upper", "stop", "mayday"];
  const TARGETED = ["cpu", "ram"];
  const NAMES = {cpu: "CPU", ram: "RAM", swap: "Swap", disk: "Disk", psi: "PSI"};
  const LEVEL_NAMES = {lower: "lower", upper: "upper", stop: "STOP", mayday: "MAYDAY"};
  const ORDER = "lower < upper < STOP < MAYDAY";
  const SHOWN = [...LEVELS, "target"];
  const SHOWN_NAMES = {...LEVEL_NAMES, target: "target"};
  const MEANINGS = {
    lower: "the floor of the band: while CPU and RAM sit below it the queue starts the next job, and the live target climbs 2 points per poll while memory pressure stays calm",
    upper: "the queue starts no job whose footprint would lift the load above it; for RAM, swap, PSI and disk the watch warns above it, and a load above it drops the live target",
    stop: "above it the live guard holds every new job and the watch calls stop; for disk it is the floor below which the queue starts nothing",
    mayday: "the last alarm: above it the watch raises MAYDAY, for disk the critical alarm",
    target: "the live AIMD target between lower and upper, read only: the queue admits a job only while the load plus its footprint stays within it; it climbs 2 points per calm poll and drops to the middle of lower and itself on overload, rising PSI or swap-out",
  };
  const percent =(value) => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100;
  const plain = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);
  const exactly = (value, keys) => plain(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));

  /**
   * @param limits - a limits object as the page would save it.
   * @returns why it is no limits object, the same rules as kvb-org-organize limits.py problem(): exactly METRICS, each
   * with exactly LEVELS, every value a percent from 0 to 100, lower < upper < STOP < MAYDAY; null when it is one.
   */
  function problem(limits) {
    if (!exactly(limits, METRICS)) {
      return `the limits are no object of exactly ${METRICS.join(", ")}`;
    }
    for (const metric of METRICS) {
      const levels = limits[metric];
      if (!exactly(levels, LEVELS)) {
        return `${NAMES[metric]} holds not exactly ${LEVELS.join(", ")}`;
      }
      const values = LEVELS.map((level) => levels[level]);
      if (!values.every(percent)) {
        return `${NAMES[metric]} holds a value that is no percent from 0 to 100`;
      }
      if (!values.every((value, index) => index === 0 || values[index - 1] < value)) {
        return `${NAMES[metric]} breaks ${ORDER}: ${values.join(" / ")} %`;
      }
    }
    return null;
  }

  /**
   * @param next - valid limits the page would save.
   * @param held - the limits in force, null while the queue config applies.
   * @returns every value of next above the one in force as {metric, level, from, to}, from null while none is in
   * force: a higher lower or upper admits more load, a higher STOP or MAYDAY raises an alarm threshold, so each needs
   * the passkey; an empty list means every value stays or tightens.
   */
  function loosened(next, held) {
    return METRICS.flatMap((metric) => LEVELS.map((level) => ({metric, level, from: held ? held[metric][level] : null, to: next[metric][level]})))
      .filter((change) => change.from === null || change.to > change.from);
  }

  /**
   * @param limits - valid limits.
   * @param metric - one of METRICS.
   * @param level - one of LEVELS.
   * @param value - the new value.
   * @returns a copy of limits with only that value changed.
   */
  function withValue(limits, metric, level, value) {
    return {...limits, [metric]: {...limits[metric], [level]: value}};
  }

  /**
   * @param limits - the limits in force, or null.
   * @param profiles - {name: limits} of the hub.
   * @returns the name of the profile holding exactly these values, null for none.
   */
  function profileOf(limits, profiles) {
    if (!limits) {
      return null;
    }
    const found = Object.entries(profiles).find(([, values]) => METRICS.every((metric) => LEVELS.every((level) => values[metric][level] === limits[metric][level])));
    return found ? found[0] : null;
  }

  /**
   * @param change - one entry of loosened().
   * @returns it as words, like `CPU upper 90 → 95 %`.
   */
  function said(change) {
    return `${NAMES[change.metric]} ${LEVEL_NAMES[change.level]} ${change.from === null ? "unset" : change.from} → ${change.to} %`;
  }

  /**
   * @param level - one of SHOWN.
   * @returns what the level means and does, led by its name, for the tooltips of its lines, its menu entry and its
   * matrix column.
   */
  function meaning(level) {
    return `${SHOWN_NAMES[level]}: ${MEANINGS[level]}`;
  }

  /**
   * @param y - a y in the chart's coordinates.
   * @param top - the y of 100 %.
   * @param bottom - the y of 0 %.
   * @returns the whole percent from 0 to 100 at y, the inverse of pixelOf(); a y beyond either edge gives that edge.
   */
  function valueAt(y, top, bottom) {
    return Math.min(100, Math.max(0, Math.round((1 - (y - top) / (bottom - top)) * 100)));
  }

  /**
   * @param value - a percent.
   * @param top - the y of 100 %.
   * @param bottom - the y of 0 %.
   * @returns the y of value on the chart.
   */
  function pixelOf(value, top, bottom) {
    return top + (1 - value / 100) * (bottom - top);
  }

  /**
   * @param base - valid limits the staged values apply to.
   * @param staged - {"<metric>.<level>": value} of the moved lines.
   * @returns a copy of base with every staged value in place.
   */
  function applied(base, staged) {
    return Object.entries(staged).reduce((limits, [key, value]) => {
      const [metric, level] = key.split(".");
      return withValue(limits, metric, level, value);
    }, base);
  }

  /**
   * @param next - limits with the staged values in place.
   * @param staged - {"<metric>.<level>": value} of the moved lines.
   * @returns the first order break of next as {metric, level, words}, level the staged line of the broken pair (its
   * upper one when neither or both are staged) and words naming it; a staged value that is no percent breaks first;
   * null without a break.
   */
  function orderBreak(next, staged) {
    for (const metric of METRICS) {
      const bad = LEVELS.find((level) => Object.hasOwn(staged, `${metric}.${level}`) && !percent(next[metric][level]));
      if (bad) {
        return {metric, level: bad, words: `${NAMES[metric]} ${LEVEL_NAMES[bad]} is no percent from 0 to 100`};
      }
    }
    for (const metric of METRICS) {
      const values = LEVELS.map((level) => next[metric][level]);
      const index = values.findIndex((value, at) => at > 0 && !(values[at - 1] < value));
      if (index > 0) {
        const [low, high] = [LEVELS[index - 1], LEVELS[index]];
        const level = !Object.hasOwn(staged, `${metric}.${high}`) && Object.hasOwn(staged, `${metric}.${low}`) ? low : high;
        const words = level === low ? `must stay below ${LEVEL_NAMES[high]} ${values[index]} %` : `must stay above ${LEVEL_NAMES[low]} ${values[index - 1]} %`;
        return {metric, level, words: `${NAMES[metric]} ${LEVEL_NAMES[level]} ${next[metric][level]} % breaks ${ORDER}: it ${words}`};
      }
    }
    return null;
  }

  /**
   * @param base - valid limits the lines show: those in force, or a profile while none is.
   * @param held - the limits in force, null while the queue config applies.
   * @param staged - {"<metric>.<level>": value} of the moved lines.
   * @returns {next, changes, loose, broken}: next the limits Save would send; changes every staged value apart from
   * base as {metric, level, from, to, kind}, kind tighter for a lower value and looser for a higher one; loose
   * loosened() of next against held, so one passkey signature covers the whole batch once it is not empty; broken
   * orderBreak(), which blocks Save.
   */
  function review(base, held, staged) {
    const next = applied(base, staged);
    const changes = METRICS.flatMap((metric) => LEVELS.filter((level) => Object.hasOwn(staged, `${metric}.${level}`) && staged[`${metric}.${level}`] !== base[metric][level])
      .map((level) => ({metric, level, from: base[metric][level], to: next[metric][level], kind: next[metric][level] < base[metric][level] ? "tighter" : "looser"})));
    const broken = orderBreak(next, staged);
    return {next, changes, loose: broken ? [] : loosened(next, held), broken};
  }

  return {METRICS, LEVELS, TARGETED, NAMES, LEVEL_NAMES, ORDER, SHOWN, SHOWN_NAMES, problem, loosened, withValue, profileOf, said, meaning, valueAt, pixelOf, applied, review};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Limits;
}
