const KanbanMarks = (() => {
  "use strict";
  const DAY = 86400;
  const HOUR = 3600;
  const MINUTE = 60;
  const BEAT_S = 5 * MINUTE;
  const HEAD_SHOWN = 32;
  const QUEUE = "queue";
  const RUNNING = "running";
  const RESPONSIBLE = "R";
  const NOBODY = "-";
  const MARKS = [["queue", "bi-cpu", "accent"], ["agent", "bi-person-workspace", "ok"], ["hub", "bi-terminal", "info"]];

  /**
   * @param seconds - a span in seconds.
   * @returns the span in words, cut to its two largest units: "45 s", "12 min", "2 h 5 min", "3 d 4 h".
   */
  function span(seconds) {
    const whole = Math.max(0, Math.floor(seconds));
    if (whole < MINUTE) {
      return `${whole} s`;
    }
    if (whole < HOUR) {
      return `${Math.floor(whole / MINUTE)} min`;
    }
    const [big, unit, small, rest] = whole < DAY ? [HOUR, "h", MINUTE, "min"] : [DAY, "d", HOUR, "h"];
    const part = Math.floor((whole % big) / small);
    return part ? `${Math.floor(whole / big)} ${unit} ${part} ${rest}` : `${Math.floor(whole / big)} ${unit}`;
  }

  /**
   * @param command - a hub job's command.
   * @returns its first line, cut to HEAD_SHOWN characters with an ellipsis.
   */
  function head(command) {
    const line = command.trim().split("\n")[0].trim();
    return line.length > HEAD_SHOWN ? `${line.slice(0, HEAD_SHOWN - 1)}…` : line;
  }

  function queueMark(row, tasks, now) {
    const own = tasks.filter((job) => job.kind === QUEUE && job.status === RUNNING && (job.task === row.task || job.queue.parent === row.task));
    const first = own.filter((job) => job.start !== null).sort((a, b) => a.start - b.start)[0] || own[0];
    if (!first) {
      return null;
    }
    const runtime = first.start === null ? "?" : span(now - first.start);
    const more = own.length > 1 ? `, ${own.length - 1} more running` : "";
    return {text: `${first.queue.kind} · ${runtime}`, hint: `${row.task}: queue job ${first.task} runs ${first.queue.kind} for ${runtime}${more}`, at: first.start};
  }

  function agentMark(row, beats, now) {
    const names = [row.worker, ...Object.entries(row.roles).filter(([, letters]) => letters.includes(RESPONSIBLE)).map(([party]) => party)];
    const fresh = [...new Set(names)].filter((name) => name !== NOBODY && Object.hasOwn(beats, name) && now - beats[name] >= -MINUTE && now - beats[name] <= BEAT_S);
    const name = fresh.sort((a, b) => beats[b] - beats[a])[0];
    if (!name) {
      return null;
    }
    const ago = span(now - beats[name]);
    return {text: `${name} · ${ago}`, hint: `${row.task}: ${name} works on it, last beat ${ago} ago`, at: beats[name]};
  }

  function hubMark(row, runner, now) {
    if (!runner || runner.task !== row.task) {
      return null;
    }
    const shown = head(runner.command) || runner.job;
    return {text: shown, hint: `${row.task}: the hub runs ${runner.job} for ${span(now - runner.started)}: ${runner.command || runner.job}`, at: runner.started};
  }

  /**
   * @param row - a card's task row: task, worker and roles.
   * @param sources - {now, tasks, beats, runner}: now the hub's epoch seconds; tasks the hub's task rows, whose queue
   * rows are the entries of queue.json; beats the hub's {agent: epoch of its latest heartbeat}; runner the hub job
   * runner-job.json names, {job, task, started, command}, or null.
   * @returns the card's marks in MARKS order, each {key, icon, tone, text, hint, at}: queue while a queue job of the
   * task or the queue card's own job runs (its kind and runtime), agent while the task's worker or an R beat within
   * BEAT_S (the freshest of them and how long ago), hub while runner-job.json names the task (the command's head).
   */
  function marks(row, sources) {
    const found = {queue: queueMark(row, sources.tasks, sources.now), agent: agentMark(row, sources.beats, sources.now), hub: hubMark(row, sources.runner, sources.now)};
    return MARKS.filter(([key]) => found[key]).map(([key, icon, tone]) => ({key, icon, tone, ...found[key]}));
  }

  return {BEAT_S, MARKS, span, head, marks};
})();
if (typeof module === "object" && module.exports) {
  module.exports = KanbanMarks;
}
