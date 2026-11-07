  const FIBONACCI = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89];
  const PRIO_MAX = 999;
  const ESTIMATOR = HUMAN;
  const shownArgv = (argv) => ["rasci.py", ...argv].join(" ");
  const prioText = (text) => (/^[1-9][0-9]{0,2}$/.test(text.trim()) ? String(Number(text.trim())) : "");

  function fibonacciPicker(label, picked) {
    return h("select", {class: "field", "aria-label": label}, FIBONACCI.map((value) => h("option", {value, selected: value === picked}, String(value))));
  }

  async function changeTask(row, argv, label, outcome) {
    const items = [{kind: "task", id: row.task, argv}];
    outcome.replaceChildren(h("p", {class: "muted"}, "Signiere mit dem Passkey …"));
    const signed = await proofFor(items, label);
    if (signed === null) {
      outcome.replaceChildren(h("p", {class: "muted"}, "Nicht signiert: nichts wurde übergeben."));
      return;
    }
    const result = await sendJson("/api/tasks", {items, proof: signed.proof});
    if (!result.ok || !result.data) {
      toast(`${label}: nicht möglich`, fail(result), false);
      outcome.replaceChildren(h("p", {class: "muted"}, `${result.status} ${result.text}`.trim()));
      return;
    }
    outcome.replaceChildren(h("p", {class: "muted", "data-jobs": result.data.jobs.join(" ")}, `Signiert und an den Runner übergeben (Job ${result.data.jobs.join(", ")}); er ruft rasci.py auf dem Host auf.`));
    toast(`${label}: an den Runner übergeben`, [shownArgv(argv)], true);
    await load();
  }

  function priorityForm(row) {
    const outcome = h("div", {class: "mini", "aria-live": "polite"});
    const own = row.estimates[ESTIMATOR] || null;
    const prio = h("input", {type: "number", class: "field", min: 1, max: PRIO_MAX, step: 1, value: row.prio === null ? "" : row.prio, "aria-label": "Priorität", placeholder: "1"});
    const value = fibonacciPicker("Geschäftswert", own ? own.value : 5);
    const complexity = fibonacciPicker("Komplexität", own ? own.complexity : 3);
    const pinCode = h("code", {});
    const estimateCode = h("code", {});
    const prioArgv = () => ["set", row.task, "--prio", prioText(prio.value)];
    const estimateArgv = () => ["estimate", row.task, ESTIMATOR, "--value", value.value, "--complexity", complexity.value];
    const pin = h("button", {type: "button", class: "btn small primary", ...named("Anheften", "Anheften: Priorität mit dem Passkey signieren")}, icon("bi-pin-angle-fill"), "Anheften");
    const estimate = h("button", {type: "button", class: "btn small primary", ...named("Schätzung speichern", "Schätzung signiert an den Runner geben")}, icon("bi-calculator"), "Schätzung speichern");
    const sync = () => {
      pin.disabled = !prioText(prio.value);
      pinCode.textContent = pin.disabled ? `Priorität 1 bis ${PRIO_MAX} eingeben` : shownArgv(prioArgv());
      estimateCode.textContent = shownArgv(estimateArgv());
    };
    for (const field of [prio, value, complexity]) {
      field.addEventListener("input", sync);
    }
    pin.addEventListener("click", () => changeTask(row, prioArgv(), `Priorität ${row.task}`, outcome));
    estimate.addEventListener("click", () => changeTask(row, estimateArgv(), `WSJF ${row.task}`, outcome));
    const drop = own ? h("button", {type: "button", class: "btn small danger", ...named("Schätzung verwerfen", "Schätzung verwerfen: deine Schätzung mit dem Passkey signiert löschen"), on: {click: () => changeTask(row, ["estimate", row.task, ESTIMATOR, "--drop"], `WSJF ${row.task}`, outcome)}}, icon("bi-x-circle"), "Schätzung verwerfen") : null;
    sync();
    return h("section", {class: "task-edit", "aria-label": "Priorität und WSJF"},
      h("h3", {}, "Priorität anheften"),
      h("div", {class: "task-form"}, h("label", {}, "Priorität (1 zuerst)", prio), pin),
      h("div", {class: "command"}, pinCode),
      h("h3", {}, `WSJF schätzen als ${ESTIMATOR}`),
      h("div", {class: "task-form"}, h("label", {}, "Geschäftswert", value), h("label", {}, "Komplexität", complexity), estimate, drop),
      h("div", {class: "command"}, estimateCode),
      h("p", {class: "muted"}, "Dein Passkey signiert genau diesen Aufruf; der Runner auf dem Host prüft die Signatur und die Form der Argumente und startet rasci.py ohne Shell. Die Priorität der Agenten bleibt unberührt."),
      onLocalhost() ? null : h("p", {class: "muted"}, "Signieren geht nur unter ", localLink()),
      outcome);
  }

  function taskRoles(row) {
    const entries = Object.entries(row.roles);
    return [h("h3", {}, "RASCI", counter(entries.length)),
      entries.length ? h("ul", {class: "mini"}, entries.map(([party, letters]) => h("li", {}, h("div", {class: "row"}, h("span", {class: "who"}, face(party, false), person(party)), h("span", {}, roleLetters(letters)))))) : h("p", {class: "muted"}, "Keine Rollen eingetragen.")];
  }

  function taskEstimates(row) {
    const entries = Object.entries(row.estimates);
    const score = row.wsjf;
    return [h("h3", {}, "WSJF-Schätzungen", counter(entries.length)),
      entries.length ? h("ul", {class: "mini"}, entries.map(([party, entry]) => h("li", {}, h("div", {class: "row"}, h("strong", {}, party), h("span", {class: "muted"}, `Geschäftswert ${entry.value} · Komplexität ${entry.complexity}`))))) : h("p", {class: "muted"}, "Noch keine Schätzung: die Aufgabe rangiert nach den geschätzten."),
      score ? h("p", {class: "muted"}, `Median ${score.value} / ${score.complexity} = WSJF ${score.score}`) : null];
  }

  function taskJobs(row) {
    const jobs = state.jobs.filter((job) => job.kind === "task" && job.task === row.task).slice(-5).reverse();
    return jobs.length ? [h("h3", {}, "Signierte Änderungen", counter(jobs.length)), h("ul", {class: "mini"}, jobs.map((job) => h("li", {"data-job": job.status},
      h("div", {class: "row"}, h("code", {}, job.command), status(job.status)),
      job.status === "refused" || job.status === "failed" ? h("pre", {class: "notes"}, job.output) : null)))] : null;
  }

  function taskSheet(id) {
    const row = state.tasks.find((entry) => entry.task === id);
    if (!row) {
      return;
    }
    const facts = [["Ziel", row.objective], ["Key Results", row.total ? `${row.met} von ${row.total} erfüllt` : ""], ["Workdir", row.workdir], ["Branch", row.branch], ["Worktree", row.worktree], ["Repository", row.repo]];
    openSheet(row.task, [
      h("div", {class: "who"}, taskBadges(row, true), row.worker !== "-" ? [face(row.worker, false), person(row.worker)] : null),
      h("p", {class: "text"}, titleOf(row)),
      meta(row.queue ? [["Queue", `${row.queue.kind} für ${row.queue.parent}`], ...facts.slice(2)] : facts),
      workChips(row.open_work),
      flowDetails(row.flow, branchOf(row)),
      taskRoles(row),
      row.kind === "task" ? taskEstimates(row) : null,
      row.editable ? priorityForm(row) : h("p", {class: "muted"}, row.ended ? "Beendet: Priorität und WSJF bleiben, wie sie sind." : "Priorität und WSJF gibt es nur für Aufgaben des Registers, nicht für Befehle, Hotfixes und Queue-Jobs."),
      taskJobs(row),
    ], false);
  }
