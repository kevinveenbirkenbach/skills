  const RUNNING_WORDS = {queue: "Queue job running", agent: "Agent working", hub: "Hub job running"};

  const markSources = () => ({now: state.now, tasks: state.tasks, beats: state.beats, runner: state.runner});

  /**
   * @param row - a task row.
   * @param found - Kanban.marks of the row.
   * @returns {boolean} whether the row works right now: it runs and a queue job, an agent beat or the hub job backs
   * that, so it carries the heartbeat class is-working; a queued, waiting, stale or ended row stays still.
   */
  const taskWorking = (row, found) => row.status === "running" && !row.ended && found.length > 0;

  /**
   * @param row - a card's task row.
   * @param found - Kanban.marks of the row.
   * @returns {HTMLElement|null} one labelled chip per mark, null without any.
   */
  function markChips(row, found) {
    if (!found.length) {
      return null;
    }
    const hint = (mark) => (mark.at === null ? mark.hint : `${mark.hint}, since ${absolute.format(stampOf(mark.at))}`);
    return h("div", {class: "kanban-marks", role: "group", "aria-label": `Running now: ${row.task}`}, found.map((mark) =>
      h("span", {class: "pill kanban-mark", "data-mark": mark.key, "data-tone": "neutral", role: "img", ...named(`${RUNNING_WORDS[mark.key]}: ${mark.text}`, hint(mark))}, icon(mark.icon), mark.text)));
  }

  /**
   * @param count - the shown cards with at least one mark.
   * @returns {HTMLElement} the board's Running toggle: pressed, it shows only marked cards.
   */
  function runningToggle(count) {
    const words = `Running: ${count} cards a queue job, an agent or the hub works on now`;
    return h("button", {type: "button", class: "btn small", id: "kanban-running", "aria-pressed": String(kanban.running), ...named("Running", `${words}, ${kanban.running ? "only these shown" : "every card shown"}`), on: {click: () => {
      kanban.running = !kanban.running;
      taskView.sig = "";
      drawTasks();
    }}}, icon("bi-activity"), h("span", {class: "tool-word"}, "Running"), counter(count));
  }
