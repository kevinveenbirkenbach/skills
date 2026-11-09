  const TASK_STATUS = {queued: ["waiting", "info"], running: ["running", "ok"], blocked: ["blocked", "bad"], done: ["done", "neutral"], stopped: ["stopped", "neutral"], awaiting: ["waiting for a grant", "warn"]};
  const TASK_COLUMNS = [["queued", "Waiting"], ["running", "Running"], ["blocked", "Blocked"], ["done", "Done"], ["stopped", "Stopped"]];
  const TASK_KINDS = {command: ["Command", "bad"], hotfix: ["Hotfix", "warn"], queue: ["Queue job", "teal"]};
  const TASK_FILTERS = [
    ["all", "All", "bi-list-check", () => true],
    ["open", "Open", "bi-play-circle", (row) => !row.ended],
    ["work", "Open work", "bi-pencil-square", (row) => row.open_work.length > 0],
    ["operator", "Waits on Operator", "bi-person-raised-hand", null],
    ["grant", "Waiting for a grant", "bi-hourglass-split", (row) => row.kind === "queue" && row.status === "awaiting"],
    ["ended", "Ended", "bi-check2-circle", (row) => row.ended],
  ];
  const ROLE_TONES = {R: "ok", A: "violet", S: "info", C: "warn", I: "neutral"};
  const ROLE_WORDS = {R: "Responsible", A: "Accountable", S: "Supportive", C: "Consulted", I: "Informed"};
  const MATRIX_PARTIES = 40;
  const taskView = {filter: "all", q: "", dom: null, sig: "", sort: "prio", descending: false, forecast: "always", scope: "all", picked: new Set(), plan: null, bulk: null};

  const columnOf = (row) => (TASK_COLUMNS.some(([id]) => id === row.status) ? row.status : "queued");
  const branchOf = (row) => row.worktree_branch || (row.branch !== "-" ? row.branch : "");
  const titleOf = (row) => (row.title !== "-" ? row.title : row.task);
  const openJobs = (task) => state.jobs.filter((job) => job.kind === "task" && job.task === task && (job.status === "queued" || job.status === "running"));

  function taskStatus(row) {
    const [label, tone] = Object.hasOwn(TASK_STATUS, row.status) ? TASK_STATUS[row.status] : [row.status, "neutral"];
    return pill(label, tone);
  }

  function taskBadges(row, withStatus) {
    const [kindName, kindTone] = Object.hasOwn(TASK_KINDS, row.kind) ? TASK_KINDS[row.kind] : [null, null];
    const score = row.wsjf;
    return [
      kindName ? pill(kindName, kindTone) : null,
      withStatus ? taskStatus(row) : null,
      row.total ? pill(`KR ${row.met}/${row.total}`, row.met === row.total ? "ok" : "info") : null,
      row.prio !== null ? h("span", {class: "pill", "data-tone": "violet", title: "pinned priority"}, `Prio ${row.prio}`) : null,
      score ? h("span", {class: "pill", "data-tone": "teal", title: `WSJF: business value ${score.value} / complexity ${score.complexity}`}, `WSJF ${score.score}`) : null,
      openJobs(row.task).length ? pill("Change at the runner", "warn") : null,
    ];
  }

  function roleSummary(row) {
    const holders = (letter) => Object.entries(row.roles).filter(([, letters]) => letters.includes(letter)).map(([party]) => party);
    return ["R", "A"].map((letter) => (holders(letter).length ? h("span", {title: ROLE_WORDS[letter]}, `${letter}: ${holders(letter).join(", ")}`) : null));
  }

  function taskPlace(row) {
    if (row.kind === "queue") {
      return h("span", {}, `${row.queue.kind} for ${row.queue.parent} · queued `, when(row.queue.enqueued));
    }
    const place = row.worktree || (row.workdir !== "-" ? row.workdir : "");
    return place ? h("code", {title: row.repo || place}, place) : null;
  }

  function opener(row) {
    return h("button", {type: "button", class: "linkish", title: `Open ${row.task}`, on: {click: () => taskSheet(row.task)}}, row.kind === "command" ? h("code", {}, titleOf(row)) : titleOf(row));
  }

  function taskItem(row) {
    const classes = ["task-row", row.open_work.length ? "open-work" : "", row.ended ? "ended" : ""].filter(Boolean).join(" ");
    const pick = row.editable ? h("input", {type: "checkbox", class: "task-pick", "aria-label": `Select ${row.task}`, title: `Select ${row.task} for a bulk business value`, checked: taskView.picked.has(row.task), on: {change: (event) => pickTask(row.task, event.target.checked)}}) : null;
    return h("li", {class: classes, "data-task": row.task, "data-kind": row.kind, "data-status": row.status},
      h("div", {class: "head-row"}, pick, h("code", {class: "task-id"}, row.task), taskBadges(row, true), h("span", {class: "spacer"}),
        row.editable ? iconBtn("bi-sort-numeric-down", "Priority", "btn small soft", () => taskSheet(row.task), `Priority and WSJF of ${row.task}: pin or estimate, signed with the passkey`) : null),
      opener(row),
      row.objective !== "-" ? h("div", {class: "muted"}, `Objective: ${row.objective}`) : null,
      h("div", {class: "task-meta"}, row.worker !== "-" ? h("span", {class: "who"}, face(row.worker, false), person(row.worker)) : null, roleSummary(row), taskPlace(row)),
      flowLine(row.flow, branchOf(row)),
      workChips(row.open_work));
  }

  function taskCard(row) {
    const classes = ["task-card", row.open_work.length ? "open-work" : "", row.ended ? "ended" : ""].filter(Boolean).join(" ");
    return h("li", {class: classes, "data-task": row.task},
      h("div", {class: "head-row"}, h("code", {class: "task-id"}, row.task)),
      opener(row),
      h("div", {class: "states"}, taskBadges(row, row.status === "awaiting")),
      row.worker !== "-" ? h("span", {class: "muted"}, row.worker) : null,
      row.flow ? flowLine(row.flow, branchOf(row)) : null,
      workChips(row.open_work));
  }

  function taskBoard(rows) {
    return h("div", {class: "task-board"}, TASK_COLUMNS.map(([id, label]) => {
      const cards = rows.filter((row) => columnOf(row) === id);
      return h("section", {class: "card task-column", "data-column": id, "aria-label": label},
        h("h3", {class: "group-title"}, label, counter(cards.length)),
        cards.length ? h("ol", {class: "task-cards"}, cards.map(taskCard)) : h("p", {class: "muted"}, "empty"));
    }));
  }

  function roleLetters(letters) {
    return [...letters].map((letter) => h("span", {class: "letter", "data-tone": ROLE_TONES[letter], title: ROLE_WORDS[letter]}, letter));
  }

  function taskMatrix(rows) {
    const parties = [...new Set(rows.flatMap((row) => Object.keys(row.roles)))].sort((a, b) => Number(a !== HUMAN) - Number(b !== HUMAN) || a.localeCompare(b, "en"));
    if (!parties.length) {
      return emptyState("No roles", "None of the shown tasks names R, A, S, C or I.");
    }
    const columns = parties.slice(0, MATRIX_PARTIES);
    const legend = h("div", {class: "legend"}, Object.entries(ROLE_WORDS).map(([letter, word]) => h("span", {}, roleLetters(letter), word)),
      parties.length > columns.length ? h("span", {class: "muted"}, `${parties.length - columns.length} more parties not shown`) : null);
    const head = h("thead", {}, h("tr", {}, h("th", {scope: "col"}, "Task"), columns.map((party) => h("th", {scope: "col", title: party}, h("span", {class: "party"}, party)))));
    const line = (row) => h("tr", {"data-task": row.task, class: row.open_work.length ? "open-work" : null},
      h("th", {scope: "row"}, h("div", {class: "matrix-task"}, h("code", {class: "task-id"}, row.task), opener(row))),
      columns.map((party) => {
        const letters = Object.hasOwn(row.roles, party) ? row.roles[party] : "";
        return h("td", {title: letters ? `${party}: ${letters}` : null}, roleLetters(letters));
      }));
    const table = h("table", {class: "matrix", "aria-label": "RASCI matrix: tasks by parties"}, head, h("tbody", {}, rows.map(line)));
    return h("div", {class: "matrix-box"}, h("div", {class: "matrix-scroll"}, table), legend);
  }

  function chooseTaskFilter(id) {
    if (id === "operator") {
      go("inbox", null);
      return;
    }
    taskView.filter = id;
    if (ui.screen === "inbox") {
      go("tasks", null);
    } else {
      drawTasks();
    }
  }

  function taskChips(rows, inbox) {
    return TASK_FILTERS.map(([id, label, name, test]) => {
      const total = test ? rows.filter(test).length : waitingCount();
      return h("button", {type: "button", class: "chip preset", "data-filter": id, "aria-pressed": String(inbox ? id === "operator" : id === taskView.filter), title: `${label}: ${total}`, on: {click: () => chooseTaskFilter(id)}},
        icon(name), label, counter(total));
    });
  }

  function taskViewSwitch(inbox) {
    return h("div", {class: "segmented", role: "group", "aria-label": "View"}, Nav.TASK_VIEWS.map(([id, name]) => h("button", {
      type: "button", class: "icon-only", ...named(name), "aria-pressed": String(!inbox && ui.views.tasks === id), on: {click: () => go("tasks", id)},
    }, icon(Nav.ICONS[id]))));
  }

  function tasksScreen() {
    const inbox = ui.screen === "inbox";
    const view = ui.views.tasks;
    const chips = h("div", {class: "chips", role: "group", "aria-label": "Task filters"});
    const count = h("span", {class: "muted"});
    const search = inbox ? null : h("input", {type: "search", class: "field", placeholder: "Filter by task, title, worker, branch …", value: taskView.q, "aria-label": "Filter tasks", on: {input: (event) => {
      taskView.q = event.target.value;
      drawTasks();
    }}});
    const body = inbox ? inboxScreen() : h("div", {class: "tasks-body"});
    taskView.dom = {chips, count, body, inbox, view};
    taskView.sig = "";
    taskView.plan = null;
    taskView.bulk = null;
    return h("div", {class: "graph tasks"}, h("div", {class: "card controls"}, taskViewSwitch(inbox), search, count), inbox ? null : planBar(view), choiceBar(), chips, body);
  }

  function drawTasks() {
    const dom = taskView.dom;
    if (!dom) {
      return;
    }
    const q = taskView.q.trim().toLowerCase();
    const sig = JSON.stringify([state.tasks, state.jobs, state.task_edges, settings.estimation, taskView.filter, taskView.sort, taskView.descending, taskView.forecast, taskView.scope, q, waitingCount(), Math.floor(nowSeconds() / 60)]);
    if (sig === taskView.sig) {
      return;
    }
    taskView.sig = sig;
    const rows = state.tasks;
    const editable = new Set(rows.filter((row) => row.editable).map((row) => row.task));
    for (const task of [...taskView.picked]) {
      if (!editable.has(task)) {
        taskView.picked.delete(task);
      }
    }
    syncPlan();
    dom.chips.replaceChildren(...taskChips(rows, dom.inbox));
    if (dom.inbox) {
      dom.count.textContent = `${rows.length} tasks in the register`;
      return;
    }
    const [, , , test] = TASK_FILTERS.find(([id]) => id === taskView.filter);
    const hit = (row) => !q || [row.task, row.title, row.worker, row.branch, row.workdir, row.objective].some((text) => String(text).toLowerCase().includes(q));
    const shown = rows.filter(test).filter(hit);
    dom.count.textContent = `${shown.length} of ${rows.length} tasks`;
    const views = {
      list: (found) => h("ol", {class: "task-list"}, Plan.sortRows(found, taskView.sort, taskView.descending).map(taskItem)),
      board: taskBoard,
      rasci: taskMatrix,
      gantt: ganttChart,
      burn: (found) => burnChart(rows, found),
    };
    dom.body.replaceChildren(shown.length || dom.view === "burn" ? views[dom.view](shown) : emptyState("No task", "No entry matches this filter."));
  }
