  const USAGE_GROUPS = [["skill", "Skill"], ["tool", "Tool"], ["subagent", "Subagent"], ["repo", "Repository"], ["model", "Model"], ["agent", "Agent"], ["account", "Account"], ["hour", "Hour"], ["day", "Day"]];
  const USAGE_PERIODS = [[3600, "Last hour"], [86400, "Last 24 h"], [7 * 86400, "Last 7 days"], [30 * 86400, "Last 30 days"], [90 * 86400, "Last 90 days"]];
  const USAGE_COUNTS = [["input", "Input"], ["output", "Output"], ["cache_read", "Cache read"], ["cache_write", "Cache write"], ["total", "Total"]];
  const USAGE_COLUMNS = [["key", "Name"], ...USAGE_COUNTS, ["share", "Share"], ["cost", "Est. $"], ["hit_rate", "Cache hit rate"]];
  const USAGE_EMPTY = {skill: "(no skill)", tool: "(text only)", subagent: "(main thread)", repo: "(no repository)", model: "(no model)", agent: "(no agent)", account: "(unmapped)"};
  const USAGE_SPANS = {hour: 3600, day: 86400};
  const USAGE_CONTEXT = ["Day", "Agent", "Turns", "Median", "p90", "Compactions"];
  const usageView = {data: null, ask: 0, body: null, controls: null, group: "skill", period: 86400, span: null, filters: {}, sort: {key: "total", down: true}};
  const usageCount = (value) => Resources.compact(value);
  const usageDay = new Intl.DateTimeFormat("en-GB", {dateStyle: "medium", timeZone: "UTC"});
  const usageTime = (t, group) => (group === "day" ? usageDay : absolute).format(stampOf(t));

  function usagePanel() {
    const group = h("select", {class: "field use-select", "aria-label": "Group by", title: "Group the tokens by one dimension", "data-usage-group": "", on: {change: () => usageGroup(group.value)}},
      USAGE_GROUPS.map(([value, label]) => h("option", {value}, label)));
    const period = h("select", {class: "field use-select", "aria-label": "Period", title: "The period the tokens fall in", "data-usage-period": "", on: {change: () => usagePeriod(Number(period.value))}},
      USAGE_PERIODS.map(([value, label]) => h("option", {value: String(value)}, label)));
    const body = h("div", {class: "use-body"});
    usageView.body = body;
    usageView.controls = {group, period};
    const panel = h("section", {class: "card res-panel res-usage", "data-panel": "resources-usage", "aria-label": "Usage"},
      h("div", {class: "res-head", "data-legend-slot": ""}, h("span", {class: "res-title", title: "Usage", "aria-label": "Usage"}, icon("bi-pie-chart")), h("span", {class: "acc-title"}, "Usage"), h("span", {class: "spacer"}), group, period), body);
    return {panel, body};
  }

  function usageGroup(group) {
    usageView.group = group;
    fetchUsage();
  }

  function usagePeriod(seconds) {
    usageView.period = seconds;
    usageView.span = null;
    fetchUsage();
  }

  function usageQuery() {
    const span = usageView.span || {since: Math.floor(nowSeconds() - usageView.period), until: null};
    const pairs = [["group", usageView.group], ["since", String(span.since)], ...(span.until === null ? [] : [["until", String(span.until)]]), ...Object.entries(usageView.filters)];
    return pairs.map(([name, value]) => `${encodeURIComponent(name)}=${encodeURIComponent(value)}`).join("&");
  }

  async function fetchUsage() {
    usageView.ask += 1;
    const ask = usageView.ask;
    try {
      const response = await fetch(`/api/usage?${usageQuery()}`, {cache: "no-store"});
      if (response.ok && ask === usageView.ask) {
        usageView.data = await response.json();
      }
    } catch {
      ui.offline = true;
    }
    if (ask === usageView.ask) {
      drawUsage();
    }
  }

  /**
   * @param key - the clicked row's group key: a dimension's value, or the start of an hour or day.
   */
  function usageDrill(key) {
    const group = usageView.group;
    if (Object.hasOwn(USAGE_SPANS, group)) {
      usageView.span = {since: key, until: key + USAGE_SPANS[group]};
    } else {
      usageView.filters = {...usageView.filters, [group]: key};
    }
    fetchUsage();
  }

  function usageUnfilter(name) {
    if (name === "span") {
      usageView.span = null;
    } else {
      usageView.filters = Object.fromEntries(Object.entries(usageView.filters).filter(([key]) => key !== name));
    }
    fetchUsage();
  }

  function usageSort(key) {
    usageView.sort = {key, down: usageView.sort.key === key ? !usageView.sort.down : key !== "key"};
    drawUsage();
  }

  /**
   * @param rows - /api/usage rows.
   * @returns the rows ordered by usageView.sort, a null value last in either direction.
   */
  function usageSorted(rows) {
    const {key, down} = usageView.sort;
    return [...rows].sort((a, b) => {
      const left = a[key];
      const right = b[key];
      if (left === right) {
        return 0;
      }
      if (left === null || right === null) {
        return left === null ? 1 : -1;
      }
      const order = typeof left === "number" && typeof right === "number" ? left - right : String(left).localeCompare(String(right));
      return down ? -order : order;
    });
  }

  function usageName(group, key) {
    if (Object.hasOwn(USAGE_SPANS, group)) {
      return usageTime(key, group);
    }
    return key === "" ? USAGE_EMPTY[group] : key;
  }

  function usageCells(row) {
    const cost = row.cost === null ? "–" : `$${row.cost.toFixed(2)}`;
    return [
      ...USAGE_COUNTS.map(([name]) => h("td", {"data-column": name}, usageCount(row[name]))),
      h("td", {"data-column": "share"}, row.share === null ? "–" : `${row.share} %`),
      h("td", {"data-column": "cost", title: row.cost === null ? "A model without a known price counts in this row" : ""}, cost),
      h("td", {"data-column": "hit_rate"}, row.hit_rate === null ? "–" : `${Math.round(row.hit_rate * 1000) / 10} %`),
    ];
  }

  function usageRow(row, group) {
    const press = (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        usageDrill(row.key);
      }
    };
    const label = usageName(group, row.key);
    return h("tr", {class: "use-row", tabindex: 0, "data-key": String(row.key), title: `Show only ${label}`, on: {click: () => usageDrill(row.key), keydown: press}},
      h("td", {"data-column": "key"}, label), usageCells(row));
  }

  function usageHead() {
    return h("tr", {}, USAGE_COLUMNS.map(([key, label]) => {
      const active = usageView.sort.key === key;
      return h("th", {scope: "col", "aria-sort": active ? (usageView.sort.down ? "descending" : "ascending") : "none"},
        h("button", {type: "button", class: "use-sort", "data-sort": key, title: `Sort by ${label}`, on: {click: () => usageSort(key)}}, label));
    }));
  }

  function usageTable(data) {
    if (!data.rows.length) {
      return h("p", {class: "muted"}, "No tokens in this period and filter.");
    }
    return h("div", {class: "acc-scroll"}, h("table", {class: "acc-table use-table", "data-usage-table": ""},
      h("thead", {}, usageHead()),
      h("tbody", {}, usageSorted(data.rows).map((row) => usageRow(row, data.group))),
      h("tfoot", {}, h("tr", {class: "use-total"}, h("th", {scope: "row"}, "Total"), usageCells(data.total)))));
  }

  function usageFilters() {
    const chip = (name, words) => h("button", {type: "button", class: "btn small soft use-filter", "data-filter": name, ...named(words, `Remove the filter ${words}`), on: {click: () => usageUnfilter(name)}}, h("span", {}, words), icon("bi-x-lg"));
    const chips = Object.entries(usageView.filters).map(([name, value]) => chip(name, `${name}: ${usageName(name, value)}`));
    if (usageView.span) {
      chips.push(chip("span", `from ${absolute.format(stampOf(usageView.span.since))}`));
    }
    return chips.length ? h("div", {class: "use-filters", role: "group", "aria-label": "Filters"}, chips) : null;
  }

  function usageContext(list) {
    if (!list.length) {
      return null;
    }
    const size = (value) => (value === null ? "–" : usageCount(value));
    return h("div", {class: "use-context"}, h("span", {class: "acc-title"}, "Context per turn"), h("div", {class: "acc-scroll"}, h("table", {class: "acc-table use-table", "data-usage-context": ""},
      h("thead", {}, h("tr", {}, USAGE_CONTEXT.map((name) => h("th", {scope: "col"}, name)))),
      h("tbody", {}, list.map((row) => h("tr", {"data-day": row.day, "data-agent": row.agent},
        h("td", {}, usageTime(row.day, "day")), h("td", {}, row.agent), h("td", {}, String(row.turns)), h("td", {}, size(row.median)), h("td", {}, size(row.p90)), h("td", {}, String(row.compactions))))))));
  }

  function usageContent(data) {
    if (data === null) {
      return [h("p", {class: "muted"}, "…")];
    }
    return [
      usageFilters(),
      usageTable(data),
      data.split ? h("p", {class: "muted use-note", "data-usage-split": ""}, "A message with several tools counts under each of them, so the shares can sum above 100 %.") : null,
      h("p", {class: "muted use-note", title: data.prices.source}, `Est. $ from the list prices of ${data.prices.date}; a model without a known price shows –.`),
      usageContext(data.context),
    ].filter(Boolean);
  }

  function homeUsage() {
    homeFetch("usage", fetchUsage);
    return h("div", {class: "use-body"}, usageContent(usageView.data));
  }

  function drawUsage() {
    const body = usageView.body;
    if (!body || !body.isConnected) {
      return;
    }
    usageView.controls.group.value = usageView.group;
    usageView.controls.period.value = String(usageView.period);
    body.replaceChildren(...usageContent(usageView.data));
  }
