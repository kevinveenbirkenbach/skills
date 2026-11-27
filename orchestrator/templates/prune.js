const Prune = (() => {
  "use strict";
  const {staleFor, STALE_DAYS} = typeof Plan === "object" ? Plan : require("./plan.js");
  const {marks} = typeof KanbanMarks === "object" ? KanbanMarks : require("./kanban-marks.js");
  const KIND = "prune";
  const ANNOUNCE = "announce";
  const APPLY = "prune";
  const MINUTE = 60;
  const MINUTES = {value: 10, min: 1, max: 60, page: 5};
  const DAYS = {min: 1, max: 999};

  /**
   * @param rows - the hub's task rows.
   * @param sources - the mark sources of KanbanMarks.marks: {now, tasks, beats, runner}.
   * @param days - N: how many days without a register change make a task stale.
   * @returns the stale tasks, oldest change first: register tasks the operator may change (editable: open, no
   * operator/ or hotfix/ record) without a register change for N days and without a running mark.
   */
  function stale(rows, sources, days) {
    const found = rows.filter((row) => row.editable && staleFor(row, sources.now, days) && !marks(row, sources).length);
    return found.sort((a, b) => a.updated - b.updated || a.task.localeCompare(b.task));
  }

  /**
   * @param tasks - the ticked task slugs.
   * @param days - N of the stale list.
   * @param since - the epoch the list was taken at; a register change after it keeps a task.
   * @param minutes - the answer window on the dial.
   * @returns the two items one passkey assertion signs: the announce job, run at once, and the rasci.py prune job,
   * which the runner holds back until the deadline since + minutes.
   */
  function items(tasks, days, since, minutes) {
    const deadline = since + minutes * MINUTE;
    return [
      {kind: KIND, argv: [ANNOUNCE, "--days", String(days), "--deadline", String(deadline), ...tasks]},
      {kind: KIND, argv: [APPLY, "--since", String(since), ...tasks], not_before: deadline},
    ];
  }

  /**
   * @param jobs - the hub's runner jobs (state.jobs).
   * @param now - the hub's epoch seconds.
   * @returns the queued apply job of a signed prune nearest its deadline as {job, deadline, tasks, left}, left the whole
   * seconds until the deadline and never below 0; null without one.
   */
  function pending(jobs, now) {
    const queued = jobs.filter((job) => job.kind === KIND && job.status === "queued" && typeof job.not_before === "number" && Array.isArray(job.argv) && job.argv[0] === APPLY);
    const next = queued.sort((a, b) => a.not_before - b.not_before)[0];
    return next ? {job: next.id, deadline: next.not_before, tasks: next.argv.slice(3), left: Math.max(0, Math.ceil(next.not_before - now))} : null;
  }

  /**
   * @param seconds - whole seconds left.
   * @returns them as m:ss.
   */
  function clock(seconds) {
    return `${Math.floor(seconds / MINUTE)}:${String(seconds % MINUTE).padStart(2, "0")}`;
  }

  /**
   * @param text - what the operator typed in the days field.
   * @returns the whole number of days between DAYS.min and DAYS.max it names, else null.
   */
  function daysOf(text) {
    const value = /^[0-9]{1,3}$/.test(text.trim()) ? Number(text.trim()) : NaN;
    return value >= DAYS.min && value <= DAYS.max ? value : null;
  }

  return {KIND, MINUTE, MINUTES, DAYS, STALE_DAYS, stale, items, pending, clock, daysOf};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Prune;
}
