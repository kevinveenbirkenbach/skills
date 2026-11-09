const Plan = (() => {
  "use strict";
  const FORECASTS = [["always", "always"], ["points", "points only"], ["real", "real only"]];
  const ESTIMATIONS = [["none", "No estimate"], ["points", "Story points"]];
  const SORTS = [["prio", "Prio"], ["wsjf", "WSJF"], ["value", "Business value"], ["complexity", "Complexity"], ["status", "Status"], ["start", "Start"], ["end", "End"], ["agent", "Agent"], ["title", "Title"]];
  const STATUS_ORDER = ["queued", "awaiting", "claimed", "running", "blocked", "stale", "done", "stopped"];
  const SERIES = ["scope", "done", "remaining", "unestimated"];
  const OUTSIDE = ["queue", "command"];

  function median(values) {
    const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
    if (!sorted.length) {
      return null;
    }
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  /**
   * @param rows - task rows with status, start, end (epoch seconds or null) and points (median complexity or null).
   * @returns {duration, perPoint}: the median seconds a done task took from start to end, and the median seconds
   * per point of the done tasks with points; null where no done task gives one.
   */
  function medians(rows) {
    const done = rows.filter((row) => row.status === "done" && row.start !== null && row.end !== null && row.end >= row.start);
    return {
      duration: median(done.map((row) => row.end - row.start)),
      perPoint: median(done.filter((row) => row.points).map((row) => (row.end - row.start) / row.points)),
    };
  }

  /**
   * @param row - a task row not yet started.
   * @param estimation - "none" or "points".
   * @param forecast - "always" or "points" (points only).
   * @param known - medians() of the rows.
   * @returns the forecast length in seconds: points times the median seconds per point when story points apply,
   * else under always the median duration of done tasks; 0 (a dot) where neither applies.
   */
  function forecastLength(row, estimation, forecast, known) {
    if (estimation === "points" && row.points && known.perPoint !== null) {
      return row.points * known.perPoint;
    }
    return forecast === "always" && known.duration !== null ? known.duration : 0;
  }

  /**
   * @param rows - task rows in their shown order.
   * @param edges - {from, to, kind} edges; only those between the rows count.
   * @param options - {now, estimation, forecast}.
   * @returns one {task, start, end, forecast, dot} per drawn row: a started task from start to its end, an open one
   * to now; a task not yet started, unless forecast is "real", as a forecast behind the latest end of its
   * predecessors and now, forecastLength() long, a dot when 0. A task never started is left out under "real", an
   * ended one without start and end always.
   */
  function bars(rows, edges, options) {
    const known = medians(rows);
    const byTask = new Map(rows.map((row) => [row.task, row]));
    const before = new Map(rows.map((row) => [row.task, []]));
    for (const edge of edges) {
      if (byTask.has(edge.from) && before.has(edge.to) && edge.from !== edge.to) {
        before.get(edge.to).push(edge.from);
      }
    }
    const placed = new Map();
    const visiting = new Set();
    const place = (row) => {
      if (placed.has(row.task)) {
        return placed.get(row.task);
      }
      if (visiting.has(row.task)) {
        return null;
      }
      visiting.add(row.task);
      let bar = null;
      if (row.start !== null) {
        const end = row.end !== null ? row.end : row.ended ? row.start : Math.max(options.now, row.start);
        bar = {task: row.task, start: row.start, end, forecast: false, dot: end <= row.start};
      } else if (row.end !== null) {
        bar = {task: row.task, start: row.end, end: row.end, forecast: false, dot: true};
      } else if (!row.ended && options.forecast !== "real") {
        const ahead = before.get(row.task).map((task) => place(byTask.get(task))).filter(Boolean);
        const start = Math.max(options.now, ...ahead.map((found) => found.end));
        const length = forecastLength(row, options.estimation, options.forecast, known);
        bar = {task: row.task, start, end: start + length, forecast: true, dot: length <= 0};
      }
      visiting.delete(row.task);
      placed.set(row.task, bar);
      return bar;
    };
    return rows.map(place).filter(Boolean);
  }

  /**
   * @param rows - task rows.
   * @param choice - "all" (the whole register over the whole time), "filter" (the filtered rows within the header
   * window), "agent:<name>" (the tasks the agent works on or holds a RASCI role in) or "line:<office>" (those of
   * the office's holder, over the whole time).
   * @param context - {filtered, since, until, now, holders: {office: holder}}.
   * @returns {rows, from, to}: the scope's rows without queue jobs and commands and its time range.
   */
  function scoped(rows, choice, context) {
    const own = (name) => (row) => row.worker === name || Object.hasOwn(row.roles, name);
    const [kind, ...rest] = String(choice).split(":");
    const key = rest.join(":");
    const chosen = kind === "filter" ? context.filtered : kind === "agent" ? rows.filter(own(key)) : kind === "line" ? rows.filter(own(context.holders[key])) : rows;
    const kept = chosen.filter((row) => !OUTSIDE.includes(row.kind));
    if (kind === "filter") {
      return {rows: kept, from: context.since, to: context.until};
    }
    const first = Math.min(...kept.flatMap((row) => [row.start, row.end]).filter((value) => value !== null));
    return {rows: kept, from: Number.isFinite(first) ? Math.min(first, context.now) : context.now - 86400, to: context.now};
  }

  /**
   * @param rows - the scope's task rows.
   * @param options - {estimation, from, to}.
   * @returns {points: [{t, scope, done, remaining, unestimated}]}, a step series at from, at every start or end
   * inside the range and at to. A task joins the scope at its start (or end), from the range start when it has
   * neither; a done task burns at its end and a stopped one leaves the scope then. With no estimate each task
   * weighs 1; with story points it weighs its points and unestimated counts the open tasks without points.
   */
  function burn(rows, options) {
    const points = options.estimation === "points";
    const weigh = (row) => (points ? row.points || 0 : 1);
    const joined = (row) => (row.start !== null ? row.start : row.end !== null ? row.end : options.from);
    const moments = rows.flatMap((row) => [row.start, row.end]).filter((value) => value !== null && value > options.from && value < options.to);
    const times = [...new Set([options.from, ...moments, options.to])].sort((a, b) => a - b);
    const at = (t) => {
      const present = rows.filter((row) => joined(row) <= t && !(row.status === "stopped" && row.end !== null && row.end <= t));
      const burnt = present.filter((row) => row.status === "done" && row.end !== null && row.end <= t);
      const scope = present.reduce((sum, row) => sum + weigh(row), 0);
      const done = burnt.reduce((sum, row) => sum + weigh(row), 0);
      const open = present.filter((row) => !burnt.includes(row));
      return {t, scope, done, remaining: scope - done, unestimated: points ? open.filter((row) => !row.points).length : 0};
    };
    return {points: times.map(at)};
  }

  const KEYS = {
    prio: () => null,
    wsjf: (row) => (row.wsjf ? row.wsjf.score : null),
    value: (row) => row.value,
    complexity: (row) => row.points,
    status: (row) => (STATUS_ORDER.includes(row.status) ? STATUS_ORDER.indexOf(row.status) : STATUS_ORDER.length),
    start: (row) => row.start,
    end: (row) => row.end,
    agent: (row) => (row.worker && row.worker !== "-" ? row.worker.toLowerCase() : null),
    title: (row) => (row.title && row.title !== "-" ? row.title : row.task).toLowerCase(),
  };

  /**
   * @param rows - task rows in the hub's register rank.
   * @param mode - one of SORTS; prio keeps the register rank.
   * @param descending - reverses the order of the keys.
   * @returns a new array: rows without a key last in both directions, ties in register rank.
   */
  function sortRows(rows, mode, descending) {
    const key = KEYS[mode] || KEYS.prio;
    const sign = descending ? -1 : 1;
    const keyed = rows.map((row, index) => ({row, index, key: mode === "prio" ? index : key(row)}));
    keyed.sort((a, b) => {
      if ((a.key === null) !== (b.key === null)) {
        return a.key === null ? 1 : -1;
      }
      const order = a.key === null ? 0 : typeof a.key === "string" ? a.key.localeCompare(b.key, "en") : a.key - b.key;
      return sign * order || a.index - b.index;
    });
    return keyed.map((entry) => entry.row);
  }

  return {FORECASTS, ESTIMATIONS, SORTS, SERIES, STATUS_ORDER, median, medians, forecastLength, bars, scoped, burn, sortRows};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Plan;
}
