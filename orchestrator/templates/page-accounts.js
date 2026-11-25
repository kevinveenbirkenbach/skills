  const ACCOUNT_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const ACCOUNT_COLUMNS = ["Provider", "Email", "Renewal", "Next reset", "Resubscribe", "Autorenew", "Since reset", "Today", "Total", "Remaining", ""];
  const accountsView = {data: null, busy: false, body: null};
  const momentText = (moment) => `${ACCOUNT_DAYS[moment.day]} ${moment.time}`;

  function accountsPanel() {
    const body = h("div", {class: "acc-body"});
    accountsView.body = body;
    const add = iconBtn("bi-plus-lg", "Add account", "btn small soft", () => accountSheet(null), "Add account: provider, email, renewal and weekly reset; kept on this host only");
    const panel = h("section", {class: "card res-panel res-accounts", "data-panel": "resources-accounts", "aria-label": "Accounts"},
      h("div", {class: "res-head", "data-star-slot": ""}, h("span", {class: "res-title", title: "Accounts", "aria-label": "Accounts"}, icon("bi-person-badge")), h("span", {class: "acc-title"}, "Accounts"), h("span", {class: "spacer"}), add), body);
    return {panel, body};
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
