  const FIBONACCI = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89];
  const PRIO_MAX = 999;
  const ESTIMATOR = HUMAN;
  const shownArgv = (argv) => ["rasci.py", ...argv].join(" ");
  const prioText = (text) => (/^[1-9][0-9]{0,2}$/.test(text.trim()) ? String(Number(text.trim())) : "");

  function fibonacciPicker(label, picked) {
    return h("select", {class: "field", "aria-label": label}, FIBONACCI.map((value) => h("option", {value, selected: value === picked}, String(value))));
  }

  async function changeTasks(changes, label, outcome) {
    const items = changes.map(({task, argv}) => ({kind: "task", id: task, argv}));
    const tell = (attrs, text) => (outcome ? outcome.replaceChildren(h("p", {class: "muted", ...attrs}, text)) : null);
    tell({}, "Signing with the passkey …");
    const signed = await proofFor(items, label);
    if (signed === null) {
      tell({}, "Not signed: nothing was handed over.");
      return false;
    }
    const result = await sendJson("/api/tasks", {items, proof: signed.proof});
    if (!result.ok || !result.data) {
      toast(`${label}: not possible`, fail(result), false);
      tell({}, `${result.status} ${result.text}`.trim());
      return false;
    }
    tell({"data-jobs": result.data.jobs.join(" ")}, `Signed and handed to the runner (job ${result.data.jobs.join(", ")}); it calls rasci.py on the host.`);
    toast(`${label}: handed to the runner`, changes.map(({argv}) => shownArgv(argv)), true);
    await load();
    return true;
  }

  function changeTask(row, argv, label, outcome) {
    return changeTasks([{task: row.task, argv}], label, outcome);
  }

  function priorityForm(row) {
    const outcome = h("div", {class: "mini", "aria-live": "polite"});
    const own = row.estimates[ESTIMATOR] || null;
    const prio = h("input", {type: "number", class: "field", min: 1, max: PRIO_MAX, step: 1, value: row.prio === null ? "" : row.prio, "aria-label": "Priority", placeholder: "1"});
    const value = fibonacciPicker("Business value", own ? own.value : 5);
    const complexity = fibonacciPicker("Complexity", own && own.complexity ? own.complexity : 3);
    const alone = fibonacciPicker("Business value as Operator", own ? own.value : 8);
    const pinCode = h("code", {});
    const estimateCode = h("code", {});
    const valueCode = h("code", {});
    const prioArgv = () => ["set", row.task, "--prio", prioText(prio.value)];
    const estimateArgv = () => ["estimate", row.task, ESTIMATOR, "--value", value.value, "--complexity", complexity.value];
    const valueArgv = () => ["estimate", row.task, ESTIMATOR, "--value", alone.value];
    const pin = h("button", {type: "button", class: "btn small primary", ...named("Pin", "Pin: sign the priority with the passkey")}, icon("bi-pin-angle-fill"), "Pin");
    const estimate = h("button", {type: "button", class: "btn small primary", ...named("Save estimate", "Hand the estimate to the runner, signed")}, icon("bi-calculator"), "Save estimate");
    const setValue = h("button", {type: "button", class: "btn small primary", ...named("Set business value", "Set the business value as Operator, signed with the passkey; WSJF uses it instead of the median")}, icon("bi-gem"), "Set business value");
    const sync = () => {
      pin.disabled = !prioText(prio.value);
      pinCode.textContent = pin.disabled ? `Enter a priority from 1 to ${PRIO_MAX}` : revealed(shownArgv(prioArgv()));
      estimateCode.textContent = revealed(shownArgv(estimateArgv()));
      valueCode.textContent = revealed(shownArgv(valueArgv()));
    };
    for (const field of [prio, value, complexity, alone]) {
      field.addEventListener("input", sync);
    }
    pin.addEventListener("click", () => changeTask(row, prioArgv(), `Priority ${row.task}`, outcome));
    estimate.addEventListener("click", () => changeTask(row, estimateArgv(), `WSJF ${row.task}`, outcome));
    setValue.addEventListener("click", () => changeTask(row, valueArgv(), `Business value ${row.task}`, outcome));
    const drop = own ? h("button", {type: "button", class: "btn small danger", ...named("Discard estimate", "Discard estimate: delete your estimate, signed with the passkey"), on: {click: () => changeTask(row, ["estimate", row.task, ESTIMATOR, "--drop"], `WSJF ${row.task}`, outcome)}}, icon("bi-x-circle"), "Discard estimate") : null;
    sync();
    return h("section", {class: "task-edit", "aria-label": "Priority and WSJF"},
      h("h3", {}, "Pin priority"),
      h("div", {class: "task-form"}, h("label", {}, "Priority (1 first)", prio), pin),
      h("div", {class: "command"}, pinCode),
      h("h3", {}, `Estimate WSJF as ${ESTIMATOR}`),
      h("div", {class: "task-form"}, h("label", {}, "Business value", value), h("label", {}, "Complexity", complexity), estimate, drop),
      h("div", {class: "command"}, estimateCode),
      h("h3", {}, `Business value as ${ESTIMATOR}`),
      h("div", {class: "task-form"}, h("label", {}, "Business value", alone), setValue),
      h("div", {class: "command"}, valueCode),
      h("p", {class: "muted"}, "WSJF uses your business value instead of the median of the agents' values."),
      h("p", {class: "muted"}, "Your passkey signs exactly this call; the runner on the host checks the signature and the shape of the arguments and starts rasci.py without a shell. The agent priority stays untouched."),
      onLocalhost() ? null : h("p", {class: "muted"}, "Signing works only under ", localLink()),
      outcome);
  }

  function taskRoles(row) {
    const entries = Object.entries(row.roles);
    return [h("h3", {}, "RASCI", counter(entries.length)),
      entries.length ? h("ul", {class: "mini"}, entries.map(([party, letters]) => h("li", {}, h("div", {class: "row"}, h("span", {class: "who"}, face(party, false), person(party)), h("span", {}, roleLetters(letters)))))) : h("p", {class: "muted"}, "No roles entered.")];
  }

  function taskEstimates(row) {
    const entries = Object.entries(row.estimates);
    const score = row.wsjf;
    return [h("h3", {}, "WSJF estimates", counter(entries.length)),
      entries.length ? h("ul", {class: "mini"}, entries.map(([party, entry]) => h("li", {}, h("div", {class: "row"}, h("strong", {}, party), h("span", {class: "muted"}, `Business value ${entry.value} · complexity ${dash(entry.complexity)}`))))) : h("p", {class: "muted"}, "No estimate yet: the task ranks after the estimated ones."),
      score ? h("p", {class: "muted"}, `${Object.hasOwn(row.estimates, ESTIMATOR) ? `${ESTIMATOR}'s business value` : "Median business value"} ${score.value} / median complexity ${score.complexity} = WSJF ${score.score}`) : null];
  }

  function taskJobs(row) {
    const jobs = state.jobs.filter((job) => job.kind === "task" && job.task === row.task).slice(-5).reverse();
    return jobs.length ? [h("h3", {}, "Signed changes", counter(jobs.length)), h("ul", {class: "mini"}, jobs.map((job) => h("li", {"data-job": job.status},
      h("div", {class: "row"}, h("code", {}, revealed(job.command)), status(job.status)),
      job.status === "refused" || job.status === "failed" ? h("pre", {class: "notes"}, job.output) : null)))] : null;
  }

  function taskSheet(id) {
    const row = state.tasks.find((entry) => entry.task === id);
    if (!row) {
      return;
    }
    const facts = [["Objective", row.objective], ["Key Results", row.total ? `${row.met} of ${row.total} met` : ""], ["Workdir", row.workdir], ["Branch", row.branch], ["Worktree", row.worktree], ["Repository", row.repo]];
    openSheet(row.task, [
      h("div", {class: "who"}, taskBadges(row, true), row.worker !== "-" ? [face(row.worker, false), person(row.worker)] : null),
      h("p", {class: "text"}, titleOf(row)),
      meta(row.queue ? [["Queue", `${row.queue.kind} for ${row.queue.parent}`], ...facts.slice(2)] : facts),
      workChips(row.open_work),
      flowDetails(row.flow, branchOf(row)),
      taskRoles(row),
      row.kind === "task" ? taskEstimates(row) : null,
      row.editable ? priorityForm(row) : h("p", {class: "muted"}, row.ended ? "Ended: priority and WSJF stay as they are." : "Priority and WSJF exist only for tasks of the register, not for commands, hotfixes and queue jobs."),
      taskJobs(row),
    ], false);
  }
