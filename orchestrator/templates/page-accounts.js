  const ACCOUNT_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const ACCOUNT_COLUMNS = ["Provider", "Email", "Renewal", "Next reset", "Resubscribe", "Autorenew", "Since reset", "Today", "Total", "Remaining", ""];
  const accountsView = {data: null, busy: false, body: null};
  const momentText = (moment) => `${ACCOUNT_DAYS[moment.day]} ${moment.time}`;

  function accountsPanel() {
    const body = h("div", {class: "acc-body"});
    accountsView.body = body;
    const add = iconBtn("bi-plus-lg", "Add account", "btn small soft", () => accountSheet(null), "Add account: provider, email, renewal and weekly reset; kept on this host only");
    const panel = h("section", {class: "card res-panel res-accounts", "data-panel": "resources-accounts", "aria-label": "Accounts"},
      h("div", {class: "res-head", "data-legend-slot": ""}, h("span", {class: "res-title", title: "Accounts", "aria-label": "Accounts"}, icon("bi-person-badge")), h("span", {class: "acc-title"}, "Accounts"), h("span", {class: "spacer"}),
        accountsExportMenu(), accountsImportButton(), add), body);
    return {panel, body};
  }

  function accountsExportMenu() {
    const link = (format, label) => h("a", {class: "menu-item", href: `/api/accounts/export?format=${format}`, download: "", "data-export": format, ...named(label, `${label}: download every stored account; the hub keeps no copy`)}, label);
    return h("details", {class: "menu acc-export"}, h("summary", {class: "btn small soft icon-only", ...named("Export accounts", "Export: download the accounts as CSV or TSV")}, icon("bi-download")),
      h("div", {class: "menu-box end", role: "group", "aria-label": "Export format"}, link("csv", "CSV"), link("tsv", "TSV")));
  }

  function accountsImportButton() {
    const picker = h("input", {type: "file", accept: ".csv,.tsv,.txt,text/csv,text/tab-separated-values", hidden: true, "aria-label": "Import file", "data-import-file": ""});
    picker.addEventListener("change", async () => {
      const file = picker.files[0];
      picker.value = "";
      if (file) {
        accountImportSheet(file.name, bytesBase64(await file.arrayBuffer()));
      }
    });
    return h("span", {class: "acc-import"}, picker, iconBtn("bi-upload", "Import accounts", "btn small soft", () => picker.click(), "Import: a CSV or TSV file, mapped to the fields and previewed before anything is saved"));
  }

  function bytesBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let start = 0; start < bytes.length; start += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
    }
    return btoa(binary);
  }

  async function fetchAccounts() {
    if (accountsView.busy) {
      return;
    }
    accountsView.busy = true;
    try {
      const response = await fetch("/api/accounts", {cache: "no-store"});
      if (response.ok) {
        accountsView.data = await response.json();
      }
    } catch {
      ui.offline = true;
    }
    accountsView.busy = false;
    drawAccounts();
  }

  /**
   * @param data - /api/accounts: {accounts, active, usage}.
   * @param now - epoch milliseconds.
   * @returns the table rows: each account with its next reset and usage, sorted by the next reset, then one
   * unassigned row for the tokens of no stored account, when there are any.
   */
  function accountRows(data, now) {
    const empty = {total: 0, hours: []};
    const rows = data.accounts.map((account) => ({account, next: Resources.nextMoment(account.reset, now), used: Resources.accountUsage(data.usage[account.email] || empty, account.reset, now)}));
    rows.sort((a, b) => a.next - b.next || a.account.email.localeCompare(b.account.email));
    const known = new Set(data.accounts.map((account) => account.email));
    const rest = Object.entries(data.usage).filter(([email]) => !known.has(email)).map(([, entry]) => entry);
    const unassigned = {total: rest.reduce((sum, entry) => sum + entry.total, 0), hours: rest.flatMap((entry) => entry.hours)};
    return unassigned.total ? [...rows, {account: null, next: null, used: Resources.accountUsage(unassigned, null, now)}] : rows;
  }

  function accountRow(row, active) {
    const count = (value) => (value === null ? "–" : Resources.compact(value));
    if (row.account === null) {
      return h("tr", {class: "acc-unassigned", "data-account": ""}, h("td", {colspan: 6}, "Unassigned: sessions the SessionStart hook mapped to no stored account"),
        h("td", {}, "–"), h("td", {}, count(row.used.today)), h("td", {}, count(row.used.total)), h("td", {}, "–"), h("td", {}));
    }
    const {account} = row;
    const remaining = account.limit === null ? null : Math.max(0, account.limit - row.used.since);
    const isActive = account.email === active;
    return h("tr", {"data-account": account.id, ...(isActive ? {"data-active": ""} : {})},
      h("td", {}, account.provider), h("td", {}, account.email, isActive ? h("span", {class: "pill", "data-tone": "ok", title: "The account Claude Code logged in with at the last session start"}, "active") : null),
      h("td", {}, momentText(account.renewal)), h("td", {title: momentText(account.reset)}, absolute.format(new Date(row.next))), h("td", {}, account.resubscribe || "–"),
      h("td", {}, account.autorenew ? "yes" : "no"), h("td", {}, count(row.used.since)), h("td", {}, count(row.used.today)), h("td", {}, count(row.used.total)),
      h("td", {title: account.limit === null ? "No weekly limit set" : `Limit ${account.limit} minus the tokens since the last reset`}, count(remaining)),
      h("td", {}, iconBtn("bi-pencil", `Edit ${account.email}`, "btn small ghost", () => accountSheet(account), "Edit or remove this account")));
  }

  function accountsContent(data) {
    if (data === null) {
      return h("p", {class: "muted"}, "…");
    }
    const rows = accountRows(data, Date.now());
    if (!rows.length) {
      return h("p", {class: "muted"}, "No account yet. Add one: it stays on this host, in the hub's state only.");
    }
    return h("div", {class: "acc-scroll"}, h("table", {class: "acc-table"},
      h("thead", {}, h("tr", {}, ACCOUNT_COLUMNS.map((name) => h("th", {scope: "col"}, name)))),
      h("tbody", {}, rows.map((row) => accountRow(row, data.active)))));
  }

  function drawAccounts() {
    const body = accountsView.body;
    if (body && body.isConnected) {
      body.replaceChildren(accountsContent(accountsView.data));
    }
  }

  function homeAccounts() {
    homeFetch("accounts", fetchAccounts);
    return h("div", {class: "acc-body"}, accountsContent(accountsView.data));
  }

  const IMPORT_FIELDS = [
    ["provider", "Provider"], ["email", "Email"], ["renewal", "Renewal (day and time)"], ["renewal_day", "Renewal day"], ["renewal_time", "Renewal time"],
    ["reset", "Next reset (day and time)"], ["reset_day", "Reset day"], ["reset_time", "Reset time"], ["resubscribe", "Resubscribe"], ["autorenew", "Autorenew"],
    ["limit", "Weekly token limit"], ["note", "Note"],
  ];
  const IMPORT_SEPARATORS = [["", "Detect"], [",", "Comma"], [";", "Semicolon"], ["\t", "Tab"]];

  function accountImportSheet(name, file) {
    const state = {file, separator: "", mapping: null, choices: {}, result: null};
    const box = h("div", {class: "acc-import-body"}, h("p", {class: "muted"}, "…"));
    const run = async () => {
      const result = await sendJson("/api/accounts/import/preview", {file: state.file, separator: state.separator, mapping: state.mapping, choices: state.choices});
      if (!result.ok) {
        box.replaceChildren(h("p", {class: "muted", "data-import-refused": ""}, fail(result)[0]));
        return;
      }
      state.result = result.data;
      box.replaceChildren(...importContent(state, run));
    };
    openSheet(`Import accounts: ${name}`, [h("p", {class: "muted"}, "Nothing is saved before Apply; accounts not in the file stay."), box], true);
    run();
  }

  function importMapping(state, run) {
    const {columns, mapping} = state.result;
    const select = (field, label) => h("label", {class: "acc-field"}, h("span", {}, label), h("select", {class: "field", "aria-label": `${label} column`, "data-map": field, on: {change: (event) => {
      state.mapping = {...state.result.mapping, [field]: event.target.value === "" ? null : Number(event.target.value)};
      run();
    }}}, h("option", {value: ""}, "not in file"), columns.map((column, index) => h("option", {value: String(index), ...(mapping[field] === index ? {selected: true} : {})}, column || `column ${index + 1}`))));
    const separator = h("label", {class: "acc-field"}, h("span", {}, "Separator"), h("select", {class: "field", "aria-label": "Separator", "data-separator": "", on: {change: (event) => {
      state.separator = event.target.value;
      state.mapping = null;
      run();
    }}}, IMPORT_SEPARATORS.map(([value, label]) => h("option", {value, ...(state.separator === value ? {selected: true} : {})}, label))));
    return h("div", {class: "acc-form"}, separator, IMPORT_FIELDS.map(([field, label]) => select(field, label)));
  }

  function importChoice(state, row, run) {
    if (row.status !== "update") {
      return null;
    }
    const email = row.account.email;
    return h("select", {class: "field", "aria-label": `Conflict ${email}`, "data-choice": email, on: {change: (event) => {
      state.choices = {...state.choices, [email]: event.target.value};
      run();
    }}}, ["overwrite", "keep"].map((choice) => h("option", {value: choice, ...(row.choice === choice ? {selected: true} : {})}, choice)));
  }

  function importRow(state, row, run) {
    const detail = row.status === "error" ? row.error : row.status === "update" ? row.changed.join(", ") : "";
    const who = row.account ? `${row.account.provider} · ${row.account.email}` : "–";
    return h("tr", {"data-import-row": row.status}, h("td", {}, String(row.line)), h("td", {}, h("span", {class: "pill", "data-tone": row.status === "error" ? "bad" : "ok"}, row.status)),
      h("td", {}, who), h("td", {}, detail), h("td", {}, importChoice(state, row, run)));
  }

  function importAll(state, run) {
    const updates = state.result.rows.filter((row) => row.status === "update");
    if (!updates.length) {
      return null;
    }
    const all = (choice) => btn(`All ${choice}`, "btn small ghost", () => {
      state.choices = Object.fromEntries(updates.map((row) => [row.account.email, choice]));
      run();
    });
    return h("div", {class: "actions", role: "group", "aria-label": "Every conflict"}, all("overwrite"), all("keep"));
  }

  function importContent(state, run) {
    const {rows, missing, errors} = state.result;
    const blocked = missing.length > 0 || errors > 0 || rows.length === 0;
    const apply = h("button", {type: "button", class: "btn primary", "data-import-apply": "", ...(blocked ? {disabled: true} : {})}, icon("bi-check-lg"), "Apply");
    apply.addEventListener("click", () => applyImport(state, run));
    const notice = missing.length ? h("p", {class: "muted", "data-import-missing": ""}, `Missing: ${missing.join(", ")}`) : null;
    const table = rows.length ? h("div", {class: "acc-scroll"}, h("table", {class: "acc-table"},
      h("thead", {}, h("tr", {}, ["Line", "Status", "Account", "Changes or error", "Conflict"].map((label) => h("th", {scope: "col"}, label)))),
      h("tbody", {}, rows.map((row) => importRow(state, row, run))))) : null;
    return [importMapping(state, run), notice, importAll(state, run), table, h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), apply)];
  }

  async function applyImport(state, run) {
    const result = await sendJson("/api/accounts/import/apply", {file: state.file, separator: state.separator, mapping: state.result.mapping, choices: state.choices, digest: state.result.digest});
    if (result.status === 409) {
      toast("Import: the accounts changed meanwhile", ["The preview was refreshed; check it and apply again."], false);
      run();
      return;
    }
    if (!result.ok) {
      toast("Import: not applied", fail(result), false);
      return;
    }
    closeSheet();
    fetchAccounts();
    toast("Import applied", [`${result.data.added} added, ${result.data.updated} updated, ${result.data.kept} kept, ${result.data.unchanged} unchanged`], true);
  }

  function momentFields(label, moment) {
    const day = h("select", {class: "field", "aria-label": `${label} weekday`}, ACCOUNT_DAYS.map((name, index) => h("option", {value: String(index), ...(moment && moment.day === index ? {selected: true} : {})}, name)));
    const time = h("input", {type: "time", class: "field", "aria-label": `${label} time`, value: moment ? moment.time : "00:00"});
    return {day, time, row: h("div", {class: "acc-field"}, h("span", {}, label), h("div", {class: "acc-pair"}, day, time))};
  }

  function accountSheet(account) {
    const text = (label, type, value, extra) => h("input", {type, class: "field", "aria-label": label, value, ...extra});
    const provider = text("Provider", "text", account ? account.provider : "", {maxlength: 40});
    const email = text("Email", "email", account ? account.email : "", {});
    const renewal = momentFields("Renewal", account && account.renewal);
    const reset = momentFields("Weekly reset", account && account.reset);
    const resubscribe = text("Resubscribe", "date", account ? account.resubscribe : "", {});
    const autorenew = h("input", {type: "checkbox", "aria-label": "Autorenew", ...(account && account.autorenew ? {checked: true} : {})});
    const limit = text("Weekly token limit", "number", account && account.limit !== null ? String(account.limit) : "", {min: 0, step: 1});
    const note = text("Note", "text", account ? account.note : "", {maxlength: 200});
    const labelled = (label, input) => h("label", {class: "acc-field"}, h("span", {}, label), input);
    const save = h("button", {type: "button", class: "btn primary"}, icon("bi-check-lg"), "Save");
    save.addEventListener("click", async () => {
      const fields = {
        provider: provider.value.trim(), email: email.value.trim(), renewal: {day: Number(renewal.day.value), time: renewal.time.value}, reset: {day: Number(reset.day.value), time: reset.time.value},
        resubscribe: resubscribe.value, autorenew: autorenew.checked, limit: limit.value === "" ? null : Number(limit.value), note: note.value.trim(),
      };
      const result = await sendJson("/api/accounts", {id: account ? account.id : "", account: fields});
      if (!result.ok) {
        toast("Account: not saved", fail(result), false);
        return;
      }
      closeSheet();
      fetchAccounts();
    });
    const remove = account ? h("button", {type: "button", class: "btn danger"}, icon("bi-trash"), "Remove") : null;
    if (remove) {
      remove.addEventListener("click", async () => {
        const result = await sendJson(`/api/accounts/${account.id}/delete`, {});
        if (!result.ok) {
          toast("Account: not removed", fail(result), false);
          return;
        }
        closeSheet();
        fetchAccounts();
      });
    }
    openSheet(account ? `Account: ${account.email}` : "Add account", [
      h("p", {class: "muted"}, "Kept on this host in the hub's state, mode 0600; never in git, the view store or the radio."),
      h("div", {class: "acc-form"}, labelled("Provider", provider), labelled("Email", email), renewal.row, reset.row, labelled("Resubscribe", resubscribe),
        labelled("Autorenew", autorenew), labelled("Weekly token limit", limit), labelled("Note", note)),
      h("div", {class: "actions"}, remove, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), save)], false);
    provider.focus();
  }
