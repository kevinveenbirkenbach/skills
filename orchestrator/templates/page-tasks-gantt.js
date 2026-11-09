  const GANTT = {label: 240, right: 28, top: 34, lane: 30, width: 1180, bar: 16, ticks: 4};
  const BURN = {width: 900, height: 340, left: 52, right: 24, top: 20, bottom: 40};
  const EDGE_WORDS = {after: "Follows (rasci.py set --after)", base: "Branches from (base branch)", queue: "Waits behind (queue order)"};
  const SERIES_WORDS = {scope: "Scope (burnup)", done: "Done (burnup)", remaining: "Remaining (burndown)", unestimated: "Unestimated tasks"};
  const STEP_WORDS = [["started", "Started"], ["ended", "Ended"], ["joined", "Joined the scope"]];
  const ESTIMATION_ICONS = {none: "bi-1-circle", points: "bi-suit-diamond"};
  const TREND_DAYS = [1, 365];
  const TREND_REACH = 3;
  const LINE_OFFICE = /^(?!work\/|cluster\/)[a-z0-9][a-z0-9._-]*\/[a-z0-9][a-z0-9._-]*$/;
  const estimation = () => settings.estimation;
  const cut = (text, size) => (text.length > size ? `${text.slice(0, size - 1)}…` : text);
  const lineHolders = () => Object.fromEntries(state.claims.filter((claim) => LINE_OFFICE.test(claim.office) && claim.agent).map((claim) => [claim.office, claim.agent]));

  function ganttDefs() {
    return s("defs", {},
      s("pattern", {id: "gantt-hatch", width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)"},
        s("rect", {class: "hatch-ground", width: 8, height: 8}), s("line", {class: "hatch-line", x1: 0, y1: 0, x2: 0, y2: 8})),
      s("marker", {id: "gantt-tip", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 8, markerHeight: 8, markerUnits: "userSpaceOnUse", orient: "auto-start-reverse"},
        s("path", {class: "gantt-tip", d: "M0,0 L10,5 L0,10 z"})));
  }

  function ganttAxis(svg, x, begin, end, height) {
    for (let index = 0; index <= GANTT.ticks; index += 1) {
      const ts = begin + ((end - begin) * index) / GANTT.ticks;
      svg.append(s("line", {class: "grid", x1: fixed(x(ts)), x2: fixed(x(ts)), y1: GANTT.top - 6, y2: height - 4}));
      svg.append(s("text", {class: "axis", x: fixed(x(ts)), y: GANTT.top - 14, "text-anchor": index === 0 ? "start" : index === GANTT.ticks ? "end" : "middle"}, (end - begin > DAY ? absolute : clock).format(stampOf(ts))));
    }
  }

  function ganttMark(row, bar, x, middle) {
    const tone = Object.hasOwn(TASK_STATUS, row.status) ? TASK_STATUS[row.status][1] : "neutral";
    const classes = `${bar.dot ? "gantt-dot" : "gantt-bar"} tone-${tone}${bar.forecast ? " forecast" : ""}`;
    const attrs = {class: classes, "data-task": bar.task, "data-start": bar.start, "data-end": bar.end, "data-forecast": String(bar.forecast)};
    const words = s("title", {}, `${row.task}: ${bar.forecast ? "forecast " : ""}${absolute.format(stampOf(bar.start))} to ${absolute.format(stampOf(bar.end))}`);
    if (bar.dot) {
      return s("circle", {...attrs, cx: fixed(x(bar.start)), cy: fixed(middle), r: 5}, words);
    }
    return s("rect", {...attrs, x: fixed(x(bar.start)), y: fixed(middle - GANTT.bar / 2), width: fixed(Math.max(x(bar.end) - x(bar.start), 2)), height: GANTT.bar, rx: 3}, words);
  }

  function ganttChart(rows) {
    const now = state.now;
    const drawnBars = Plan.bars(rows, state.task_edges, {now, estimation: estimation(), forecast: taskView.forecast});
    if (!drawnBars.length) {
      return emptyState("No bar", "No shown task has started, and real only draws no forecast.");
    }
    const lanes = new Map(drawnBars.map((bar, index) => [bar.task, index]));
    const bars = new Map(drawnBars.map((bar) => [bar.task, bar]));
    const begin = Math.min(now, ...drawnBars.map((bar) => bar.start));
    const end = Math.max(now, ...drawnBars.map((bar) => bar.end));
    const span = Math.max(end - begin, 3600);
    const height = GANTT.top + drawnBars.length * GANTT.lane + 10;
    const x = (ts) => GANTT.label + ((ts - begin) / span) * (GANTT.width - GANTT.label - GANTT.right);
    const middle = (task) => GANTT.top + lanes.get(task) * GANTT.lane + GANTT.lane / 2;
    const svg = s("svg", {class: "chart gantt", width: GANTT.width, height, viewBox: `0 0 ${GANTT.width} ${height}`, role: "img", "aria-label": "Gantt: one bar per task from start to end, hatched bars are forecasts, arrows lead from a task to the one that follows it"}, ganttDefs());
    ganttAxis(svg, x, begin, begin + span, height);
    const byTask = new Map(rows.map((row) => [row.task, row]));
    drawnBars.forEach((bar, index) => {
      const row = byTask.get(bar.task);
      const top = GANTT.top + index * GANTT.lane;
      svg.append(s("rect", {class: index % 2 ? "lane odd" : "lane", x: 0, y: top, width: GANTT.width, height: GANTT.lane}));
      svg.append(s("text", {class: "lane-label", x: 8, y: top + GANTT.lane / 2, dy: "0.35em", "data-task": row.task, on: {click: () => taskSheet(row.task)}}, s("title", {}, `${row.task}: ${titleOf(row)}`), cut(row.task, 30)));
      svg.append(ganttMark(row, bar, x, middle(bar.task)));
    });
    svg.append(s("line", {class: "now", x1: fixed(x(now)), x2: fixed(x(now)), y1: GANTT.top - 6, y2: height - 4}));
    const arrows = s("g", {class: "gantt-edges"});
    for (const edge of state.task_edges) {
      const from = bars.get(edge.from);
      const to = bars.get(edge.to);
      if (!from || !to) {
        continue;
      }
      const [x1, y1, x2, y2] = [x(from.end), middle(edge.from), x(to.start), middle(edge.to)];
      arrows.append(s("path", {class: `gantt-edge k-${edge.kind}`, "data-kind": edge.kind, "data-from": edge.from, "data-to": edge.to, d: `M${fixed(x1)},${fixed(y1)} C${fixed(x1 + 28)},${fixed(y1)} ${fixed(x2 - 28)},${fixed(y2)} ${fixed(x2)},${fixed(y2)}`, "marker-end": "url(#gantt-tip)"},
        s("title", {}, `${edge.to}: ${EDGE_WORDS[edge.kind] || edge.kind} ${edge.from}`)));
    }
    svg.append(arrows);
    const legend = h("div", {class: "legend"}, h("span", {class: "gantt-key forecast"}, "Forecast (hatched)"), Object.entries(EDGE_WORDS).map(([kind, words]) => h("span", {class: `gantt-key k-${kind}`}, words)));
    return h("div", {class: "gantt-box"}, h("div", {class: "gantt-scroll"}, svg), legend);
  }

  function burnAxis(svg, from, to, top) {
    const x = (t) => BURN.left + ((t - from) / Math.max(to - from, 1)) * (BURN.width - BURN.left - BURN.right);
    const y = (value) => BURN.top + (1 - value / top) * (BURN.height - BURN.top - BURN.bottom);
    for (const value of [0, top / 2, top]) {
      svg.append(s("line", {class: "grid", x1: BURN.left, x2: BURN.width - BURN.right, y1: fixed(y(value)), y2: fixed(y(value))}));
      svg.append(s("text", {class: "axis", x: BURN.left - 8, y: fixed(y(value)), dy: "0.35em", "text-anchor": "end"}, String(Math.round(value * 10) / 10)));
    }
    for (const [index, t] of [from, (from + to) / 2, to].entries()) {
      svg.append(s("text", {class: "axis", x: fixed(x(t)), y: BURN.height - 14, "text-anchor": ["start", "middle", "end"][index]}, (to - from > DAY ? absolute : clock).format(stampOf(t))));
    }
    return {x, y};
  }

  function burnPoints(series, changes, names, x, y) {
    const marks = s("g", {class: "burn-points"});
    series.forEach((point, index) => {
      const change = changes[index];
      const listed = STEP_WORDS.filter(([key]) => change[key].length).map(([key, label]) => `${label}: ${change[key].join(", ")}`);
      const words = listed.length ? listed.join("\n") : "No work package started, ended or joined the scope here";
      for (const name of names) {
        marks.append(s("circle", {
          class: `burn-point k-${name}`, cx: fixed(x(point.t)), cy: fixed(y(point[name])), r: 3.5, "data-step": index, "data-series": name, "data-t": point.t, "data-value": point[name],
          ...Object.fromEntries(STEP_WORDS.map(([key]) => [`data-${key}`, change[key].join(" ")])),
        }, s("title", {}, `${absolute.format(stampOf(point.t))} · ${SERIES_WORDS[name]}: ${point[name]}\n${words}`)));
      }
    });
    return marks;
  }

  function trendNote(trend) {
    const forecast = trend ? trend.forecast : null;
    const words = forecast !== null ? `Forecast: ${absolute.format(stampOf(forecast))}` : trend ? "No forecast: the trend never reaches 0 remaining, so done never meets scope" : "No forecast: too few points for a trend";
    return h("span", {class: "burn-forecast", "data-forecast": forecast === null ? "" : String(forecast)}, icon("bi-graph-up-arrow"), words);
  }

  function burnTrend(svg, trend, end, x, y) {
    for (const name of Plan.TRENDED) {
      const line = trend.lines[name];
      svg.append(s("path", {class: `burn-trend k-${name}`, "data-series": name, "data-from": trend.start, "data-to": end, d: `M${fixed(x(trend.start))},${fixed(y(Plan.lineAt(line, trend.start)))} L${fixed(x(end))},${fixed(y(Plan.lineAt(line, end)))}`},
        s("title", {}, `${SERIES_WORDS[name]} trend`)));
    }
    if (trend.forecast !== null) {
      const at = fixed(x(end));
      svg.append(s("line", {class: "forecast-line", x1: at, x2: at, y1: BURN.top, y2: BURN.height - BURN.bottom, "data-forecast": trend.forecast}));
      svg.append(s("text", {class: "forecast-label", x: at, y: BURN.top + 10, dx: -4, "text-anchor": "end"}, `Forecast ${absolute.format(stampOf(trend.forecast))}${end < trend.forecast ? " (beyond the chart)" : ""}`));
    }
  }

  function burnSpan(picked, trend) {
    const forecast = trend ? trend.forecast : null;
    if (forecast === null) {
      return {reach: picked.to, end: picked.to};
    }
    const reach = Math.min(Math.max(forecast, picked.to), picked.to + TREND_REACH * Math.max(picked.to - picked.from, 1));
    return {reach, end: Math.min(forecast, reach)};
  }

  function burnChart(rows, shown) {
    const picked = Plan.scoped(rows, taskView.scope, {filtered: shown, since: state.since, until: state.until, now: state.now, holders: lineHolders()});
    const series = Plan.burn(picked.rows, {estimation: estimation(), from: picked.from, to: picked.to}).points;
    const trend = Plan.trend(series, settings.trend);
    const {reach, end} = burnSpan(picked, trend);
    const names = estimation() === "points" ? Plan.SERIES : Plan.SERIES.filter((name) => name !== "unestimated");
    const ends = trend ? Plan.TRENDED.flatMap((name) => [trend.start, end].map((t) => Plan.lineAt(trend.lines[name], t))) : [];
    const top = Math.max(1, ...series.flatMap((point) => names.map((name) => point[name])), ...ends);
    const unit = estimation() === "points" ? "story points; unestimated tasks as a line of their own" : "tasks";
    const svg = s("svg", {class: "chart burn", viewBox: `0 0 ${BURN.width} ${BURN.height}`, role: "img", "aria-label": `Burndown and burnup in ${unit}; hover a point for the work packages of its step`});
    const {x, y} = burnAxis(svg, picked.from, reach, top);
    const last = series[series.length - 1];
    if (reach > picked.to) {
      svg.append(s("line", {class: "now", x1: fixed(x(picked.to)), x2: fixed(x(picked.to)), y1: BURN.top, y2: BURN.height - BURN.bottom}));
    }
    for (const name of names) {
      const d = series.map((point, index) => (index ? `H${fixed(x(point.t))} V${fixed(y(point[name]))}` : `M${fixed(x(point.t))},${fixed(y(point[name]))}`)).join(" ");
      svg.append(s("path", {class: `burn-line k-${name}`, "data-series": name, "data-last": String(last[name]), d}, s("title", {}, `${SERIES_WORDS[name]}: ${last[name]}`)));
    }
    if (trend) {
      burnTrend(svg, trend, end, x, y);
    }
    svg.append(burnPoints(series, Plan.steps(picked.rows, series, picked.from), names, x, y));
    const legend = h("div", {class: "legend"}, names.map((name) => h("span", {class: `burn-key k-${name}`, "data-series": name}, `${SERIES_WORDS[name]}: ${last[name]}`)),
      settings.trend.mode === "off" ? null : trendNote(trend));
    return h("div", {class: "burn-box"}, svg, legend, h("p", {class: "muted"}, `${picked.rows.length} tasks in scope, counted in ${unit}`));
  }

  async function chooseEstimation(id) {
    if (id === estimation()) {
      return;
    }
    if (await saveSettings({...settings, estimation: id})) {
      toast(`Estimation: ${Plan.ESTIMATIONS.find(([name]) => name === id)[1]}`, [], true);
    }
    drawTasks();
  }

  async function chooseTrend(next) {
    if (await saveSettings({...settings, trend: next})) {
      toast(`Trend: ${Plan.TRENDS.find(([id]) => id === next.mode)[1]}${next.mode === "velocity" ? ` over ${next.days} days` : ""}`, [], true);
    }
    syncPlan();
    drawTasks();
  }

  function trendControls() {
    const mode = h("select", {class: "field", ...named("Trend", "Trend: off, linear regression (least squares over the shown window) or velocity (the mean burn rate of the last N days); the forecast is where it reaches 0 remaining"), on: {change: (event) => chooseTrend({...settings.trend, mode: event.target.value})}},
      Plan.TRENDS.map(([id, label]) => h("option", {value: id, selected: id === settings.trend.mode}, label)));
    const [low, high] = TREND_DAYS;
    const days = h("input", {type: "number", class: "field", min: low, max: high, step: 1, value: settings.trend.days, ...named("Velocity days", `Velocity days: the mean burn rate over the last N days, ${low} to ${high}`), on: {change: (event) => {
      const value = Number(event.target.value);
      if (Number.isInteger(value) && value >= low && value <= high) {
        chooseTrend({...settings.trend, days: value});
      } else {
        event.target.value = String(settings.trend.days);
      }
    }}});
    const box = h("label", {class: "plan-group", hidden: settings.trend.mode !== "velocity"}, days, "days");
    taskView.plan.trend = {mode, days, box};
    return h("div", {class: "plan-group", role: "group", "aria-label": "Trend and forecast"}, mode, box);
  }

  async function requestEstimates() {
    const signed = await signedProof("/api/board/sign", {action: "estimates"}, "Request estimates");
    if (signed) {
      await act("estimates", "Request estimates", {proof: signed.proof});
    }
  }

  function sortControls() {
    const select = h("select", {class: "field", "aria-label": "Sort", on: {change: (event) => {
      taskView.sort = event.target.value;
      drawTasks();
    }}}, Plan.SORTS.map(([id, label]) => h("option", {value: id, selected: id === taskView.sort}, label)));
    const turn = (button) => relabel(button, taskView.descending ? "bi-sort-up" : "bi-sort-down", taskView.descending ? "Descending" : "Ascending", `${taskView.descending ? "Descending" : "Ascending"}: click to reverse`);
    const direction = h("button", {type: "button", class: "btn small icon-only", "data-direction": "", on: {click: (event) => {
      taskView.descending = !taskView.descending;
      turn(event.currentTarget);
      drawTasks();
    }}});
    turn(direction);
    return h("div", {class: "plan-group", role: "group", "aria-label": "Sort order"}, select, direction);
  }

  function bulkControls() {
    const value = fibonacciPicker("Business value of the selection", 8);
    const count = counter(0);
    const button = h("button", {type: "button", class: "btn small primary", id: "bulk-value", disabled: true, ...named("Set business value", "Set business value: of every selected task as Operator, signed once with the passkey"), on: {click: () => bulkValue(Number(value.value))}},
      icon("bi-gem"), count);
    taskView.bulk = {button, count};
    return h("div", {class: "plan-group", role: "group", "aria-label": "Business value of the selection"}, value, button);
  }

  function forecastControl() {
    return h("label", {class: "plan-group"}, "Forecast", h("select", {class: "field", "aria-label": "Forecast", on: {change: (event) => {
      taskView.forecast = event.target.value;
      drawTasks();
    }}}, Plan.FORECASTS.map(([id, label]) => h("option", {value: id, selected: id === taskView.forecast}, label))));
  }

  function scopeChoices() {
    const agents = [...new Set(state.tasks.filter((row) => row.kind !== "queue").flatMap((row) => [row.worker, ...Object.keys(row.roles)]).filter((name) => name && name !== "-"))].sort((a, b) => a.localeCompare(b, "en"));
    return [["all", "Whole register"], ["filter", "List filter in the time window"], ...agents.map((name) => [`agent:${name}`, `Agent: ${name}`]), ...Object.entries(lineHolders()).map(([office, holder]) => [`line:${office}`, `Line: ${office} (${holder})`])];
  }

  function scopeControl() {
    const choices = scopeChoices();
    if (!choices.some(([id]) => id === taskView.scope)) {
      taskView.scope = "all";
    }
    return h("select", {class: "field", ...named("Scope", "Scope: the whole register, the list filter in the time window, or one agent or line"), on: {change: (event) => {
      taskView.scope = event.target.value;
      drawTasks();
    }}}, choices.map(([id, label]) => h("option", {value: id, selected: id === taskView.scope}, label)));
  }

  function planTools(view) {
    const modes = h("div", {class: "segmented", role: "group", "aria-label": "Estimation"}, Plan.ESTIMATIONS.map(([id, label]) => h("button", {
      type: "button", class: "icon-only", "data-estimation": id, "aria-pressed": String(estimation() === id), ...named(label, `${label}: ${id === "points" ? "the Fibonacci complexity of rasci.py estimate" : "every task counts 1"}`), on: {click: () => chooseEstimation(id)},
    }, icon(ESTIMATION_ICONS[id]))));
    const request = h("button", {type: "button", class: "btn small icon-only", id: "request-estimates", hidden: estimation() !== "points", ...named("Request estimates", "Request estimates: one newsletter asks every agent with a RASCI role in an unestimated task for business value and complexity"), on: {click: requestEstimates}}, icon("bi-send-check"));
    taskView.plan = {modes, request, trend: null};
    const own = {list: () => [sortControls(), bulkControls()], gantt: forecastControl, burn: () => [scopeControl(), trendControls()]}[view];
    return [modes, request, own ? own() : null];
  }

  function syncPlan() {
    const plan = taskView.plan;
    if (!plan) {
      return;
    }
    for (const button of plan.modes.querySelectorAll("button")) {
      button.setAttribute("aria-pressed", String(button.dataset.estimation === estimation()));
    }
    plan.request.hidden = estimation() !== "points";
    if (plan.trend) {
      plan.trend.mode.value = settings.trend.mode;
      plan.trend.box.hidden = settings.trend.mode !== "velocity";
      if (document.activeElement !== plan.trend.days) {
        plan.trend.days.value = String(settings.trend.days);
      }
    }
    if (taskView.bulk) {
      const picked = state.tasks.filter((row) => row.editable && taskView.picked.has(row.task)).length;
      taskView.bulk.count.textContent = String(picked);
      taskView.bulk.button.disabled = picked === 0;
    }
  }

  function pickTask(task, on) {
    if (on) {
      taskView.picked.add(task);
    } else {
      taskView.picked.delete(task);
    }
    syncPlan();
  }

  async function bulkValue(value) {
    const rows = state.tasks.filter((row) => row.editable && taskView.picked.has(row.task));
    if (!rows.length) {
      return;
    }
    const changes = rows.map((row) => ({task: row.task, argv: ["estimate", row.task, ESTIMATOR, "--value", String(value)]}));
    if (await changeTasks(changes, `Business value ${value} for ${rows.length} tasks`, null)) {
      taskView.picked.clear();
      taskView.sig = "";
      drawTasks();
    }
  }
