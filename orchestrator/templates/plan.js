const Plan = (() => {
  "use strict";
  const FORECASTS = [["always", "always"], ["points", "points only"], ["real", "real only"]];
  const ESTIMATIONS = [["none", "No estimate"], ["points", "Story points"]];
  const TRENDS = [["off", "off"], ["regression", "linear regression"], ["velocity", "velocity"]];
  const SORTS = [["prio", "Prio"], ["wsjf", "WSJF"], ["value", "Business value"], ["complexity", "Complexity"], ["status", "Status"], ["start", "Start"], ["end", "End"], ["agent", "Agent"], ["title", "Title"]];
  const STATUS_ORDER = ["queued", "awaiting", "claimed", "running", "blocked", "stale", "done", "stopped"];
  const SERIES = ["scope", "done", "remaining", "unestimated"];
  const TRENDED = ["scope", "done", "remaining"];
  const OUTSIDE = ["queue", "command"];
  const DAY = 86400;
  const STALE_DAYS = 3;

  const stale = (row, now) => !row.ended && typeof row.updated === "number" && now - row.updated >= STALE_DAYS * DAY;

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
   * @param rows - task rows.
   * @param edges - {from, to, kind} edges; only those between the rows count.
   * @param settle - (row, ahead) => value or null, where ahead() lists the settled values of the row's
   * predecessors; a predecessor still being settled (a cycle) and a null value are left out.
   * @returns a Map from task to its settled value, each row settled once, in row order.
   */
  function settled(rows, edges, settle) {
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
      const value = settle(row, () => before.get(row.task).map((task) => place(byTask.get(task))).filter(Boolean));
      visiting.delete(row.task);
      placed.set(row.task, value);
      return value;
    };
    rows.forEach(place);
    return placed;
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
    const placed = settled(rows, edges, (row, ahead) => {
      if (row.start !== null) {
        const end = row.end !== null ? row.end : row.ended ? row.start : Math.max(options.now, row.start);
        return {task: row.task, start: row.start, end, forecast: false, dot: end <= row.start};
      }
      if (row.end !== null) {
        return {task: row.task, start: row.end, end: row.end, forecast: false, dot: true};
      }
      if (row.ended || options.forecast === "real") {
        return null;
      }
      const start = Math.max(options.now, ...ahead().map((found) => found.end));
      const length = forecastLength(row, options.estimation, options.forecast, known);
      return {task: row.task, start, end: start + length, forecast: true, dot: length <= 0};
    });
    return rows.map((row) => placed.get(row.task)).filter(Boolean);
  }

  /**
   * @param rows - task rows.
   * @param edges - {from, to, kind} edges; only those between the rows count.
   * @param options - {now, estimation}.
   * @returns a Map from task to {start, eta, forecast}: an ended task's end (null without one); else its start, or
   * for a task not yet started the latest of now and its predecessors' ETAs, plus forecastLength() under "always".
   */
  function etas(rows, edges, options) {
    const known = medians(rows);
    return settled(rows, edges, (row, ahead) => {
      if (row.ended) {
        return {start: row.start, eta: row.end, forecast: false};
      }
      const start = row.start !== null ? row.start : Math.max(options.now, ...ahead().map((found) => found.eta).filter((eta) => eta !== null));
      return {start, eta: start + forecastLength(row, options.estimation, "always", known), forecast: true};
    });
  }

  /**
   * @param rows - task rows.
   * @param choice - "all" (the whole register over the whole time), "filter" (the filtered rows within the header
   * window), "agent:<name>" (the tasks the agent works on or holds a RASCI role in) or "line:<office>" (those of
   * the office's holder, over the whole time).
   * @param context - {filtered, since, until, now, holders: {office: holder}}.
   * @returns {rows, stale, from, to}: the scope's rows without queue jobs, operator commands and stale tasks, the
   * stale ones apart, and its time range.
   */
  function scoped(rows, choice, context) {
    const own = (name) => (row) => row.worker === name || Object.hasOwn(row.roles, name);
    const [kind, ...rest] = String(choice).split(":");
    const key = rest.join(":");
    const chosen = kind === "filter" ? context.filtered : kind === "agent" ? rows.filter(own(key)) : kind === "line" ? rows.filter(own(context.holders[key])) : rows;
    const inside = chosen.filter((row) => !OUTSIDE.includes(row.kind));
    const kept = inside.filter((row) => !stale(row, context.now));
    const apart = inside.filter((row) => stale(row, context.now));
    if (kind === "filter") {
      return {rows: kept, stale: apart, from: context.since, to: context.until};
    }
    const first = Math.min(...kept.flatMap((row) => [row.start, row.end]).filter((value) => value !== null));
    return {rows: kept, stale: apart, from: Number.isFinite(first) ? Math.min(first, context.now) : context.now - 86400, to: context.now};
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
    const moments = rows.flatMap((row) => [row.start, row.end]).filter((value) => value !== null && value > options.from && value < options.to);
    const times = [...new Set([options.from, ...moments, options.to])].sort((a, b) => a - b);
    const at = (t) => {
      const present = rows.filter((row) => joinedAt(row, options.from) <= t && !(row.status === "stopped" && row.end !== null && row.end <= t));
      const burnt = present.filter((row) => row.status === "done" && row.end !== null && row.end <= t);
      const scope = present.reduce((sum, row) => sum + weigh(row), 0);
      const done = burnt.reduce((sum, row) => sum + weigh(row), 0);
      const open = present.filter((row) => !burnt.includes(row));
      return {t, scope, done, remaining: scope - done, unestimated: points ? open.filter((row) => !row.points).length : 0};
    };
    return {points: times.map(at)};
  }

  const joinedAt = (row, from) => (row.start !== null ? row.start : row.end !== null ? row.end : from);

  /**
   * @param rows - the scope's task rows.
   * @param points - burn() points of the rows.
   * @param from - the range start burn() was given.
   * @returns per point {started, ended, joined}: the tasks whose start, end or, without a start, entry into the
   * scope falls after the previous point and up to this one; the first point takes everything up to it.
   */
  function steps(rows, points, from) {
    return points.map((point, index) => {
      const after = index ? points[index - 1].t : -Infinity;
      const within = (t) => t !== null && t > after && t <= point.t;
      const tasks = (test) => rows.filter(test).map((row) => row.task);
      return {
        started: tasks((row) => within(row.start)),
        ended: tasks((row) => within(row.end)),
        joined: tasks((row) => row.start === null && within(joinedAt(row, from))),
      };
    });
  }

  const LAST_SECOND = 8.64e12;
  const reachable = (t) => (t !== null && Number.isFinite(t) && Math.abs(t) <= LAST_SECOND ? t : null);

  function leastSquares(pairs) {
    const mean = (values) => values.reduce((sum, value) => sum + value, 0) / values.length;
    const t0 = mean(pairs.map(([t]) => t));
    const y0 = mean(pairs.map(([, y]) => y));
    const spread = pairs.reduce((sum, [t]) => sum + (t - t0) ** 2, 0);
    return spread > 0 ? {t0, y0, slope: pairs.reduce((sum, [t, y]) => sum + (t - t0) * (y - y0), 0) / spread} : null;
  }

  function velocity(points, name, start) {
    const last = points[points.length - 1];
    const before = points.filter((point) => point.t <= start).pop();
    return {t0: last.t, y0: last[name], slope: (last[name] - before[name]) / (last.t - start)};
  }

  /**
   * @param points - burn() points, in time order.
   * @param choice - {mode: "off", "regression" or "velocity", days: N for velocity}.
   * @returns null when off or with fewer than two distinct times, else {start, lines, forecast}: per series of
   * TRENDED a line {t0, y0, slope}, its value y0 + slope * (t - t0) with slope per second, fitted by least squares
   * over every point (regression, drawn from the first point) or through the last point and the value at
   * max(first point, last point - N days), the mean rate of those days (velocity, drawn from there). The forecast
   * is where the remaining line reaches 0, which by linearity is where done meets scope; null when it never falls
   * or falls only after LAST_SECOND, the last second a Date can hold.
   */
  function trend(points, choice) {
    if (choice.mode === "off" || points.length < 2) {
      return null;
    }
    const last = points[points.length - 1];
    const start = choice.mode === "velocity" ? Math.max(points[0].t, last.t - choice.days * DAY) : points[0].t;
    const lines = Object.fromEntries(TRENDED.map((name) => [name, choice.mode === "velocity" ? (start < last.t ? velocity(points, name, start) : null) : leastSquares(points.map((point) => [point.t, point[name]]))]));
    if (TRENDED.some((name) => lines[name] === null)) {
      return null;
    }
    const rest = lines.remaining;
    const reached = rest.slope < 0 ? rest.t0 - rest.y0 / rest.slope : null;
    return {start, lines, forecast: reachable(reached)};
  }

  const lineAt = (line, t) => line.y0 + line.slope * (t - line.t0);

  /**
   * @param points - burn() points, in time order.
   * @param found - trend() of the points, or null.
   * @returns {fixed, growing}: the finish at fixed scope, where the done trend reaches the last scope (the last point
   * when nothing remains, never before it), and the finish at growing scope, where the done trend meets the scope
   * trend (trend()'s forecast); each null when never reached, both null without a trend.
   */
  function finishes(points, found) {
    if (!found) {
      return {fixed: null, growing: null};
    }
    const last = points[points.length - 1];
    const done = found.lines.done;
    const fixed = last.remaining <= 0 ? last.t : done.slope > 0 ? Math.max(last.t, done.t0 + (last.scope - done.y0) / done.slope) : null;
    return {fixed: reachable(fixed), growing: found.forecast};
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

  return {FORECASTS, ESTIMATIONS, TRENDS, SORTS, SERIES, TRENDED, STATUS_ORDER, STALE_DAYS, median, medians, forecastLength, bars, etas, stale, scoped, burn, steps, trend, finishes, lineAt, sortRows};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Plan;
}
