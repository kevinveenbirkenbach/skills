const Kanban = (() => {
  "use strict";
  const {BEAT_S, MARKS, span, head, marks} = typeof KanbanMarks === "object" ? KanbanMarks : require("./kanban-marks.js");
  const COLUMNS = [["queued", "Waiting"], ["running", "Running"], ["done", "Done"]];
  const LANES = [["p1", "P1"], ["p2", "P2"], ["p3", "P3"], ["p4", "P4+"], ["unpinned", "Unpinned"]];
  const PINS = {p1: 1, p2: 2, p3: 3};
  const FREE_FROM = 4;
  const OFF = ["command"];
  const DAY = 86400;
  const MINUTE = 60;
  const REFUSED = ["failed", "refused"];
  const QUEUE = "queue/";
  const RUNNING = "run";
  const QUEUE_LAYERS = [["line", "Queue line", "k-queue-line"], ["jobs", "Queue jobs", "k-queue-jobs"]];

  const onBoard = (row) => !OFF.includes(row.kind);
  const laneOf = (prio) => (prio === null ? "unpinned" : prio >= FREE_FROM ? "p4" : `p${Math.max(prio, 1)}`);
  const labelOf = (row) => (row.status === "blocked" || row.status === "stopped" ? row.status : null);
  const old = (row, now) => columnOf(row) === "done" && row.end !== null && now - row.end > DAY;
  const score = (row) => (row.wsjf ? row.wsjf.score : null);

  /**
   * @param row - a task row.
   * @returns "done" for done and stopped, "running" for running and for blocked once started, else "queued".
   */
  function columnOf(row) {
    if (row.status === "done" || row.status === "stopped") {
      return "done";
    }
    return row.status === "running" || (row.status === "blocked" && row.start !== null) ? "running" : "queued";
  }

  function ranked(a, b) {
    const pins = (a.prio === null) - (b.prio === null) || (a.prio || 0) - (b.prio || 0);
    const scores = (score(a) === null) - (score(b) === null) || (score(b) || 0) - (score(a) || 0);
    return pins || scores || a.task.localeCompare(b.task, "en");
  }

  /**
   * @param rows - the task rows to place, staged changes applied.
   * @param options - {now, old: true shows Done cards that ended more than 24 h ago}.
   * @returns {lanes, hidden}: per lane of LANES {id, label, count, cells: {column: rows}}, each cell in pin then WSJF
   * order (WSJF rank alone in Unpinned), and the count of hidden old Done cards. Operator commands are never placed;
   * a pin below 1 counts as P1.
   */
  function board(rows, options) {
    const placed = rows.filter(onBoard);
    const hidden = options.old ? [] : placed.filter((row) => old(row, options.now));
    const shown = placed.filter((row) => !hidden.includes(row)).sort(ranked);
    const lanes = LANES.map(([id, label]) => {
      const own = shown.filter((row) => laneOf(row.prio) === id);
      return {id, label, count: own.length, cells: Object.fromEntries(COLUMNS.map(([column]) => [column, own.filter((row) => columnOf(row) === column)]))};
    });
    return {lanes, hidden: hidden.length};
  }

  /**
   * @param rows - every task row, staged changes applied.
   * @param task - the task that moves into P4+.
   * @returns the lowest pin from 4 no other open task holds.
   */
  function freePin(rows, task) {
    const held = new Set(rows.filter((row) => row.task !== task && !row.ended && row.prio !== null).map((row) => row.prio));
    let pin = FREE_FROM;
    while (held.has(pin)) {
      pin += 1;
    }
    return pin;
  }

  const slotOf = (target) => (target.after ? `after:${target.after}` : target.drop ? `after:${target.drop}` : target.lane ? "prio" : "status");
  const slotOfArgv = (argv) => (argv[2] === "--after" || argv[2] === "--drop-after" ? `after:${argv[3]}` : argv[2] === "--status" ? "status" : "prio");

  /**
   * @param row - the hub's row of the moved card.
   * @param target - {column}, {status}, {lane}, {after: the task it follows} or {drop: the task it no longer follows}.
   * @param rows - every task row, staged changes applied, for the free pin.
   * @returns the rasci.py argv of the move against the hub's row, or null when the row already reads so.
   */
  function move(row, target, rows) {
    if (target.column) {
      return columnOf(row) === target.column ? null : ["set", row.task, "--status", target.column];
    }
    if (target.status) {
      return row.status === target.status ? null : ["set", row.task, "--status", target.status];
    }
    if (target.lane) {
      if (laneOf(row.prio) === target.lane) {
        return null;
      }
      return target.lane === "unpinned" ? ["set", row.task, "--unpin"] : ["set", row.task, "--prio", String(PINS[target.lane] || freePin(rows, row.task))];
    }
    if (target.after) {
      return target.after === row.task || row.after.includes(target.after) ? null : ["set", row.task, "--after", target.after];
    }
    return target.drop && row.after.includes(target.drop) ? ["set", row.task, "--drop-after", target.drop] : null;
  }

  /**
   * @param staged - the staged changes, each {task, argv}.
   * @param row - the hub's row of the moved card.
   * @param target - as move() takes it.
   * @param rows - every task row, staged changes applied.
   * @returns the new staged list: the move replaces an earlier one of the same task and kind (status, pin, or one
   * dependency), and a move back to the hub's state leaves only the drop of that earlier one.
   */
  function stage(staged, row, target, rows) {
    const slot = slotOf(target);
    const kept = staged.filter((change) => !(change.task === row.task && slotOfArgv(change.argv) === slot));
    const argv = move(row, target, rows);
    return argv ? [...kept, {task: row.task, argv}] : kept;
  }

  /**
   * @param rows - the hub's task rows.
   * @param staged - the staged changes.
   * @returns the rows as they read once the staged changes are applied, a changed row with pending, the argv
   * staged for it; the others unchanged.
   */
  function pending(rows, staged) {
    return rows.map((row) => {
      const own = staged.filter((change) => change.task === row.task);
      if (!own.length) {
        return row;
      }
      const next = {...row, after: [...row.after], pending: own.map((change) => change.argv)};
      for (const {argv} of own) {
        const [, , flag, value] = argv;
        if (flag === "--status") {
          Object.assign(next, {status: value, ended: value === "done" || value === "stopped", end: null});
        } else if (flag === "--prio") {
          next.prio = Number(value);
        } else if (flag === "--unpin") {
          next.prio = null;
        } else if (flag === "--after") {
          next.after.push(value);
        } else {
          next.after = next.after.filter((task) => task !== value);
        }
      }
      return next;
    });
  }

  /**
   * @param rows - the shown cards' rows, staged changes applied.
   * @param line - the hub's queue_line: tasks holding a live queue entry, in grant order.
   * @returns {arrows, queue}: one {from, to} per after dependency between two shown cards, and the shown tasks of the
   * queue line in its order.
   */
  function lines(rows, line) {
    const shown = new Set(rows.map((row) => row.task));
    const arrows = rows.flatMap((row) => row.after.filter((task) => task !== row.task && shown.has(task)).map((from) => ({from, to: row.task})));
    return {arrows, queue: line.filter((task) => shown.has(task))};
  }

  /**
   * @param jobs - the hub's jobs.
   * @param task - a card's task.
   * @returns {failed, applied, total} over the task's changes in its newest signed batch (a job without a batch is
   * one of its own): failed the jobs rasci.py or the runner refused, oldest first, applied the count rasci.py ran;
   * null when none of them failed.
   */
  function why(jobs, task) {
    const own = jobs.filter((job) => job.kind === "task" && job.task === task).sort((a, b) => a.created_ts - b.created_ts);
    const newest = own[own.length - 1];
    const batch = !newest ? [] : newest.batch ? own.filter((job) => job.batch === newest.batch) : [newest];
    const failed = batch.filter((job) => REFUSED.includes(job.status));
    return failed.length ? {failed, applied: batch.filter((job) => job.status === "done").length, total: batch.length} : null;
  }

  /**
   * @param rows - the shown cards' rows.
   * @param line - the hub's queue_line: tasks holding a live queue entry, in grant order.
   * @param jobs - the hub's queue_jobs: the rows of `queue.py list --json` in grant order, null where the installed
   * queue.py lists no JSON.
   * @returns {task: {place, of, jobs}} for each shown card the queue concerns: place its 1-based stop on the queue
   * line (null for a card off the line), of the line's length, and jobs its queue jobs in grant order, a queue card's
   * own job and a task card's jobs by task; jobs stays empty without queue_jobs.
   */
  function queued(rows, line, jobs) {
    const found = {};
    for (const row of rows) {
      const place = line.indexOf(row.task);
      const own = (jobs || []).filter((job) => (row.kind === "queue" ? `${QUEUE}${job.id}` === row.task : job.task === row.task));
      if (place >= 0 || own.length) {
        found[row.task] = {place: place >= 0 ? place + 1 : null, of: line.length, jobs: own};
      }
    }
    return found;
  }

  const placeOf = (job) => (typeof job.position === "number" ? `#${job.position}` : job.position === RUNNING ? "running" : job.position || "?");

  /**
   * @param job - one queue_jobs row.
   * @returns the chips of its card overlay in display order, each {key, text, hint, tone}: its grant position, class,
   * pin, WSJF, the gate it runs (its kind), how long it waits and its ETA; a class, pin, WSJF or wait the row lacks
   * leaves its chip out, an unknown ETA reads "ETA ?".
   */
  function jobChips(job) {
    const running = job.position === RUNNING;
    const chips = [{key: "position", text: placeOf(job), hint: `${job.id}: ${running ? "granted, running now" : `grant position ${placeOf(job)}`}`, tone: "neutral"}];
    if (job.class) {
      chips.push({key: "class", text: job.class, hint: `${job.id}: class ${job.class}`, tone: "neutral"});
    }
    if (job.prio !== null) {
      chips.push({key: "prio", text: `P${job.prio}`, hint: `${job.id}: its task is pinned P${job.prio}`, tone: "neutral"});
    }
    if (job.wsjf !== null) {
      chips.push({key: "wsjf", text: `WSJF ${Number(job.wsjf.toFixed(2))}`, hint: `${job.id}: WSJF ${job.wsjf} of its task`, tone: "neutral"});
    }
    chips.push({key: "gate", text: job.kind || "?", hint: `${job.id}: runs the gate ${job.kind || "of an unknown kind"}`, tone: "teal"});
    if (job.waited_s !== null) {
      chips.push({key: "waited", text: `${running ? "waited" : "waits"} ${span(job.waited_s)}`, hint: `${job.id}: ${running ? "waited" : "waits"} ${span(job.waited_s)} in the queue`, tone: "neutral"});
    }
    const eta = job.eta_s === null ? "no ETA learned yet" : `${running ? "ends" : "starts"} in about ${span(job.eta_s)}`;
    chips.push({key: "eta", text: job.eta_s === null ? "ETA ?" : `ETA ${span(job.eta_s)}`, hint: `${job.id}: ${eta}`, tone: "neutral"});
    return chips;
  }

  /**
   * @param job - one queue_jobs row.
   * @returns {label, place, steps}: the popover's name, where the job stands (#n, running or the word queue.py gave)
   * and the rule trace that put it there, in the order queue.py applied it; a row without a trace shows its reason
   * as the only step, one without either says so.
   */
  function whyHere(job) {
    const steps = job.trace.length ? job.trace : [job.reason || "queue.py gave no trace and no reason for this job"];
    return {label: `Why here: ${job.id} at ${placeOf(job)}`, place: placeOf(job), steps};
  }

  /**
   * @param hidden - the kanban.hidden view-store list: the queue layers switched off.
   * @returns {line, jobs}: whether the numbered queue line and the job overlay of the cards show.
   */
  function layers(hidden) {
    return Object.fromEntries(QUEUE_LAYERS.map(([id]) => [id, !hidden.includes(id)]));
  }

  /**
   * @param jobs - the hub's queue_jobs.
   * @returns them with waited_s and eta_s in whole minutes.
   */
  function queueSig(jobs) {
    const minutes = (value) => (value === null ? null : Math.floor(value / MINUTE));
    return jobs === null ? null : jobs.map((job) => ({...job, waited_s: minutes(job.waited_s), eta_s: minutes(job.eta_s)}));
  }

  return {COLUMNS, LANES, FREE_FROM, QUEUE_LAYERS, BEAT_S, MARKS, onBoard, columnOf, laneOf, labelOf, board, freePin, move, stage, pending, lines, why, span, queued, jobChips, whyHere, layers, queueSig, head, marks};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Kanban;
}
