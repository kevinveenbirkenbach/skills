  const RATES = {poll: 60, fewest: 2, most: 3};
  const RATE_PERIODS = [
    ["minute", "min", "per minute"],
    ["hour", "h", "per hour"],
    ["day", "d", "per day"],
    ["week", "wk", "per week"],
    ["month", "mo", "per month of 30 days"],
    ["year", "yr", "per year of 365 days"],
    ["total", "all", "in total since records begin"],
  ];
  const RATE_METRICS = [
    ["tasks", "bi-check2-square", "Tasks done", "count"],
    ["commits", "bi-git", "Commits", "count"],
    ["krs", "bi-bullseye", "Key results met", "count"],
    ["tokens", "bi-coin", "Tokens", "count"],
    ["cpu", "bi-cpu", "CPU", "percent"],
    ["ram", "bi-memory", "RAM", "percent"],
    ["vram", "bi-gpu-card", "VRAM", "vram"],
    ["swap", "bi-arrow-left-right", "Swap", "percent"],
    ["disk", "bi-hdd", "Disk", "disk"],
  ];
  const BYTE_UNITS = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  const rateView = {data: null, dom: null, busy: false, at: -Infinity};
  const periodOf = (id) => RATE_PERIODS.find(([name]) => name === id) || RATE_PERIODS[1];
  const metricOf = (id) => RATE_METRICS.find(([name]) => name === id);

  function bytesText(value) {
    const power = value > 0 ? Math.min(Math.floor(Math.log2(value) / 10), BYTE_UNITS.length - 1) : 0;
    return `${power ? fixed(value / 2 ** (10 * power)) : Math.round(value)} ${BYTE_UNITS[power]}`;
  }

  function countText(value) {
    if (value >= 1000) {
      return compactCount(value);
    }
    if (value >= 10 || Number.isInteger(value)) {
      return String(Math.round(value));
    }
    return value < 0.1 ? String(Number(value.toPrecision(1))) : fixed(value);
  }

  /**
   * @param entry - one metric of one period from /api/rates, or null before the first answer.
   * @param kind - the metric's kind: count, percent, vram or disk.
   * @param short - the period's short name a count is per, "" for none.
   * @returns the cell text: ≈ before an extrapolated count, n/a for a gauge without a sample.
   */
  function rateText(entry, kind, short) {
    if (!entry) {
      return "…";
    }
    if (entry.value === null) {
      return "n/a";
    }
    if (kind === "count") {
      return `${entry.approx ? "≈ " : ""}${countText(entry.value)}${short ? `/${short}` : ""}`;
    }
    return kind === "vram" && entry.used !== null ? `${percentOf(entry.value)} · ${bytesText(entry.used)}` : percentOf(entry.value);
  }

  function rateHint(entry, metric, period) {
    const [id, , label, kind] = metric;
    const [, , per] = period;
    if (!entry) {
      return `${label} ${per}: loading`;
    }
    if (entry.value === null) {
      return `${label} ${per}: n/a, no sample in this window`;
    }
    const source = entry.source === "total" ? "all records of this kind" : `the last ${entry.source}`;
    const scaled = entry.approx ? `; ≈ none in this window or its records begin later, scaled from ${source}` : "";
    const where = id === "disk" ? ` on ${entry.mount}, ${bytesText(entry.used)} of ${bytesText(entry.total)}` : "";
    const mean = kind === "count" ? "" : " on average";
    return `${label} ${per}: ${rateText(entry, kind, "")}${mean}${where}${scaled}`;
  }

  function ratesBar() {
    const host = document.getElementById("rates");
    const period = h("select", {class: "field rates-period", ...named("Rate period", "Rate period: the window the chip counts over"), on: {change: (event) => chooseRates({...settings.rates, period: event.target.value})}},
      RATE_PERIODS.map(([id, short, per]) => h("option", {value: id, title: per}, short)));
    const chip = h("summary", {class: "rates-chip"});
    const body = h("tbody", {});
    const head = h("tr", {}, h("th", {scope: "col"}, "Metric"), h("th", {scope: "col", title: "Shown in the chip"}, "Chip"), RATE_PERIODS.map(([id, short, per]) => h("th", {scope: "col", "data-period": id, title: per}, short)));
    const box = h("div", {class: "menu-box end rates-box", role: "group", "aria-label": "Rates per period"},
      h("h3", {}, "Rates per period"),
      h("div", {class: "rates-scroll"}, h("table", {class: "rates-table"}, h("thead", {}, head), body)),
      h("p", {class: "muted"}, `≈ means an estimate: none in the window, so the shortest longer window that holds any, scaled down, or a window reaching back before the records of its kind begin, scaled from those records. n/a means no sample in the window. Total counts since records begin; the gauges average over the window. The chip shows ${RATES.fewest} to ${RATES.most} metrics.`));
    const menu = h("details", {class: "menu rates-menu"}, chip, box);
    host.replaceChildren(period, menu);
    rateView.dom = {period, chip, body, menu};
  }

  function rateCell(metric, period, chosen) {
    const entry = rateView.data ? rateView.data.rates[period[0]][metric[0]] : null;
    const short = period[0] === "total" ? "" : period[1];
    return h("td", {"data-period": period[0], "data-approx": String(Boolean(entry && entry.approx)), "aria-current": period[0] === chosen.period ? "true" : null, title: rateHint(entry, metric, period)},
      rateText(entry, metric[3], metric[3] === "count" ? short : ""));
  }

  function rateRow(metric, chosen) {
    const [id, name, label] = metric;
    const shown = chosen.metrics.includes(id);
    const locked = shown ? chosen.metrics.length <= RATES.fewest : chosen.metrics.length >= RATES.most;
    const pick = h("input", {type: "checkbox", checked: shown, disabled: locked, "aria-label": `${label} in the chip`, on: {change: () => chooseRates({...chosen, metrics: shown ? chosen.metrics.filter((other) => other !== id) : [...chosen.metrics, id]})}});
    return h("tr", {"data-metric": id}, h("th", {scope: "row"}, icon(name), ` ${label}`), h("td", {}, pick), RATE_PERIODS.map((period) => rateCell(metric, period, chosen)));
  }

  function drawRates() {
    const dom = rateView.dom;
    if (!dom) {
      return;
    }
    const chosen = settings.rates;
    const period = periodOf(chosen.period);
    const short = period[0] === "total" ? "" : period[1];
    const entries = chosen.metrics.map((id) => [metricOf(id), rateView.data ? rateView.data.rates[period[0]][id] : null]);
    dom.period.value = period[0];
    dom.chip.replaceChildren(...entries.map(([metric, entry]) => h("span", {class: "rate", "data-metric": metric[0], "data-approx": String(Boolean(entry && entry.approx)), title: rateHint(entry, metric, period)},
      icon(metric[1]), h("span", {class: "rate-value"}, rateText(entry, metric[3], metric[3] === "count" ? short : "")))), caret());
    dom.chip.setAttribute("aria-label", `Rates ${period[2]}: ${entries.map(([metric, entry]) => `${metric[2]} ${rateText(entry, metric[3], "")}`).join(", ")}`);
    dom.chip.title = "Rates: every metric per period";
    const focused = document.activeElement instanceof Element ? document.activeElement.closest("#rates tr[data-metric]") : null;
    dom.body.replaceChildren(...RATE_METRICS.map((metric) => rateRow(metric, chosen)));
    const again = focused ? dom.body.querySelector(`tr[data-metric="${focused.dataset.metric}"] input`) : null;
    if (again) {
      again.focus();
    }
  }

  async function chooseRates(next) {
    if (!(await saveSettings({...settings, rates: next}))) {
      drawRates();
    }
  }

  async function fetchRates() {
    rateView.busy = true;
    try {
      const response = await fetch("/api/rates", {cache: "no-store"});
      if (response.ok) {
        rateView.data = await response.json();
      }
    } catch {
      ui.offline = true;
    }
    rateView.at = nowSeconds();
    rateView.busy = false;
    drawRates();
  }

  function pollRates() {
    if (!rateView.dom) {
      ratesBar();
      drawRates();
    }
    if (!document.hidden && !rateView.busy && nowSeconds() - rateView.at >= RATES.poll) {
      fetchRates();
    }
  }
