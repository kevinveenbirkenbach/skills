  const QUEUE_SETTINGS = [["budget_percent.ram", "Budget RAM %"], ["budget_percent.cpu", "Budget CPU %"], ["load_limits.cpu_percent", "Live guard CPU %"], ["load_limits.mem_percent", "Live guard RAM %"], ["load_limits.band_low", "Band low %"], ["load_limits.band_high", "Band high %"], ["load_limits.sample_seconds", "Load sample s"]];
  const QUEUE_KIND_SETTINGS = [["slot_limits", "Slot cap"], ["ram_cap_percent", "RAM cap %"]];
  const QUEUE_NUMBER = /^(0|[1-9][0-9]{0,5})(\.[0-9]{1,3})?$/;
  const QUEUE_REFRESH = 20000;
  const queueTab = {data: null, busy: false, staged: {}, dom: null, at: 0};

  const queueNumber = (value) => (value === null || value === undefined ? "–" : Number(value).toFixed(1).replace(/\.0$/, ""));

  /**
   * @param {string} key a setting as `<section>.<name>`.
   * @returns {number|null} its value in the learnings queue.py printed last, null when the config holds none.
   */
  function queueSetting(key) {
    const [section, name] = key.split(".");
    const values = queueTab.data ? queueTab.data[section] : null;
    return values && Object.hasOwn(values, name) ? values[name] : null;
  }

  async function fetchQueue() {
    if (queueTab.busy) {
      return;
    }
    queueTab.busy = true;
    queueTab.at = Date.now();
    try {
      const response = await fetch("/api/queue", {cache: "no-store"});
      if (response.ok) {
        queueTab.data = (await response.json()).learned;
      }
    } catch {
      ui.offline = true;
    }
    queueTab.busy = false;
    drawQueue();
  }

  /**
   * @param {string[]} argvs the queue.py arguments of each change; one passkey assertion signs them all.
   * @param {string} label what the passkey prompt and the toast name.
   * @returns {Promise<boolean>} whether the hub handed every change to the runner.
   */
  async function signQueue(argvs, label) {
    const items = argvs.map((argv) => ({kind: "queue", argv}));
    const signed = await proofFor(items, label);
    if (signed === null) {
      return false;
    }
    const result = await sendJson("/api/queue", {items, proof: signed.proof});
    toast(result.ok ? `Queue: ${label}` : `Queue: ${label}: not applied`, result.ok ? [`${items.length} → runner`] : fail(result), result.ok);
    return result.ok;
  }

  /**
   * @param {Object} job a waiting row of state.queue_jobs.
   * @returns {HTMLElement} Start now: one passkey signs `queue.py override <id>`; the job then starts past the band while the live guard allows.
   */
  function startNow(job) {
    const hint = job.override ? `${job.id}: Start now is signed; it starts once the live guard and the disk allow` : `Start now: ${job.id} skips the band, slots, reservations and rank; the live guard and the disk still hold it`;
    return h("button", {type: "button", class: "btn small primary queue-start", "data-start": job.id, disabled: job.override, ...named(`Start now: ${job.id}`, hint), on: {click: async (event) => {
      event.stopPropagation();
      if (await signQueue([["override", job.id]], `Start now ${job.id}`)) {
        await load();
      }
    }}}, icon("bi-lightning-charge"), job.override ? "Start asked" : "Start now");
  }

  function stageSetting(key, text) {
    const current = queueSetting(key);
    if (QUEUE_NUMBER.test(text) && Number(text) !== current) {
      queueTab.staged[key] = text;
    } else {
      delete queueTab.staged[key];
    }
    drawQueue();
  }

  /**
   * @param {string} key a setting as `<section>.<name>`.
   * @param {string} label its field label.
   * @returns {HTMLElement} its number field, holding the staged value or the current one.
   */
  function settingField(key, label) {
    const staged = Object.hasOwn(queueTab.staged, key);
    const current = queueSetting(key);
    return h("label", {class: `queue-setting${staged ? " staged" : ""}`, "data-setting": key}, h("span", {class: "muted"}, label),
      h("input", {class: "field", type: "text", inputmode: "decimal", value: staged ? queueTab.staged[key] : current === null ? "" : String(current), placeholder: "unset", "aria-label": `${label}: ${key}`,
        on: {change: (event) => stageSetting(key, event.target.value.trim())}}));
  }

  function queueTable(label, head, rows) {
    return h("div", {class: "table-wrap"}, h("table", {class: "queue-table", "aria-label": label},
      h("thead", {}, h("tr", {}, head.map((cell) => h("th", {scope: "col"}, cell)))),
      h("tbody", {}, rows.length ? rows : h("tr", {}, h("td", {colspan: head.length, class: "muted"}, "nothing learned yet")))));
  }

  function kindRows() {
    return Object.entries(queueTab.data.kinds).map(([kind, stats]) => h("tr", {"data-kind": kind},
      h("th", {scope: "row"}, kind, stats.light ? pill("light", "ok") : null), h("td", {}, String(stats.runs)), h("td", {}, queueNumber(stats.ram_share)), h("td", {}, queueNumber(stats.cpu_share)),
      h("td", {}, `${stats.slot_limit} (${stats.slot_source})`), QUEUE_KIND_SETTINGS.map(([section, label]) => h("td", {}, settingField(`${section}.${kind}`, label)))));
  }

  function signatureRows() {
    return queueTab.data.signatures.map((row) => h("tr", {"data-signature": `${row.kind}: ${row.signature}`},
      h("th", {scope: "row"}, h("code", {}, row.signature)), h("td", {}, row.kind), h("td", {}, String(row.runs)), h("td", {}, queueNumber(row.minutes)),
      h("td", {}, queueNumber(row.disk_gb)), h("td", {}, queueNumber(row.ram_share)), h("td", {}, queueNumber(row.cpu_share)), h("td", {}, dash(row.need_gb))));
  }

  function historyRows() {
    return [...queueTab.data.history].reverse().map((row) => h("tr", {"data-row": row.id},
      h("td", {}, when(row.end)), h("td", {}, row.kind), h("td", {}, h("code", {}, row.signature)), h("td", {}, queueNumber(row.minutes)),
      h("td", {}, pill(String(row.exit), row.exit === 0 ? "ok" : "bad")), h("td", {}, row.override ? pill("override", "warn") : "–")));
  }

  function waitingJobs() {
    const waiting = (state.queue_jobs || []).filter((job) => job.status === "waiting");
    return h("ul", {class: "queue-waiting", "aria-label": "Waiting jobs"}, waiting.length ? waiting.map((job) => h("li", {class: "queue-job", "data-job": job.id},
      h("strong", {}, job.id), h("span", {class: "muted"}, `${job.kind} · ${job.agent}`), job.reason ? h("span", {class: "queue-reason", title: job.reason}, job.reason) : null, startNow(job)))
      : h("li", {class: "muted"}, "No job waits."));
  }

  function queueApplyBar() {
    const keys = Object.keys(queueTab.staged);
    if (!keys.length) {
      return [];
    }
    const apply = async () => {
      if (await signQueue(keys.map((key) => ["config", "set", key, queueTab.staged[key]]), `Apply ${keys.length} settings`)) {
        queueTab.staged = {};
        window.setTimeout(fetchQueue, 3000);
      }
      drawQueue();
    };
    return [h("ul", {class: "mini", "aria-label": "Staged settings"}, keys.map((key) => h("li", {"data-staged": key}, h("code", {}, `${key} = ${queueTab.staged[key]}`)))), h("span", {class: "spacer"}),
      iconBtn("bi-arrow-counterclockwise", "Discard", "btn ghost", () => {
        queueTab.staged = {};
        drawQueue();
      }, "Discard: drop every staged setting"),
      h("button", {type: "button", class: "btn primary", "data-queue-apply": "", title: "Apply: one passkey signs every staged setting; the runner sets each through queue.py config set", on: {click: apply}}, icon("bi-send-check"), `Apply (${keys.length})`)];
  }

  function queueContent() {
    if (!queueTab.data) {
      return [h("p", {class: "muted"}, "The installed queue.py has not listed its learnings: it lacks `learned --json`, or the hub cannot read the queue config.")];
    }
    return [h("div", {class: "queue-settings", role: "group", "aria-label": "Settings"}, QUEUE_SETTINGS.map(([key, label]) => settingField(key, label))),
      h("h3", {}, "Kinds"), queueTable("Kinds", ["Kind", "Runs", "p90 RAM %", "Median CPU %", "Slot limit", "Slot cap", "RAM cap %"], kindRows()),
      h("h3", {}, "Signatures"), queueTable("Signatures", ["Signature", "Kind", "Runs", "Median min", "p90 disk GB", "p95 RAM %", "p95 CPU %", "Need GB"], signatureRows()),
      h("h3", {}, "Last runs"), queueTable("Last runs", ["Ended", "Kind", "Signature", "Minutes", "Exit", "Override"], historyRows())];
  }

  function drawQueue() {
    const dom = queueTab.dom;
    if (!dom || !dom.body.isConnected) {
      return;
    }
    dom.body.replaceChildren(...queueContent());
    const bar = queueApplyBar();
    dom.bar.hidden = !bar.length;
    dom.bar.replaceChildren(...bar);
  }

  function drawQueueJobs() {
    const dom = queueTab.dom;
    if (dom && dom.jobs.isConnected) {
      fadeSwap(dom.jobs, [waitingJobs()]);
      if (Date.now() - queueTab.at >= QUEUE_REFRESH) {
        fetchQueue();
      }
    }
  }

  function homeQueue() {
    homeFetch("queue", fetchQueue);
    return h("div", {class: "stack queue-tab"}, waitingJobs(), ...queueContent(), ...queueApplyBar());
  }

  function queuePanel() {
    queueTab.dom = {jobs: h("div", {}), body: h("div", {class: "stack"}), bar: h("div", {class: "apply-bar", role: "region", "aria-label": "Apply queue settings", hidden: true})};
    window.setTimeout(() => {
      drawQueueJobs();
      drawQueue();
      fetchQueue();
    }, 0);
    return h("section", {class: "card stack queue-tab", "data-panel": "stream/queue", "aria-label": "Queue"}, queueTab.dom.jobs, queueTab.dom.body, queueTab.dom.bar);
  }
