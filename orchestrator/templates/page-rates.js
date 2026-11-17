  const RATES = {poll: 60, fewest: 2, most: 9};
  const RATE_PERIODS = [
    ["minute", "min", "per minute"],
    ["hour", "h", "per hour"],
    ["day", "d", "per day"],
    ["week", "wk", "per week"],
    ["month", "mo", "per month of 30 days"],
    ["year", "yr", "per year of 365 days"],
    ["total", "all", "in the whole window"],
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
  const rateView = {data: null, dom: null, ticket: 0, at: -Infinity};
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
   * @returns the cell text: ≈ before an estimated count, n/a without a record or sample in the window.
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
      return `${label} ${per}: n/a, ${kind === "count" ? "no record of this kind reaches into the window" : "no sample in the window"}`;
    }
    const length = rateView.data.to - rateView.data.from;
    const covered = entry.covered !== null && entry.covered < length - 1;
    const scaled = !entry.approx ? "" : covered ? `; ≈ its records cover only the last ${spanName(entry.covered)} of the window, so the rate divides by that part` : "; ≈ the window is shorter than the hour tokens are counted in";
    const where = id === "disk" ? ` on ${entry.mount}, ${bytesText(entry.used)} of ${bytesText(entry.total)}` : "";
    const mean = kind === "count" ? "" : " on average";
    return `${label} ${per}: ${rateText(entry, kind, "")}${mean}${where}${scaled}`;
  }

  function ratesBar() {
    const host = document.getElementById("rates");
    const chip = h("summary", {class: "rates-chip"});
    const units = h("div", {class: "segmented rates-units", role: "group", "aria-label": "Rate unit"},
      RATE_PERIODS.map(([id, short, per]) => h("button", {type: "button", "data-period": id, title: per, on: {click: () => chooseRates({...settings.rates, period: id})}}, short)));
    const body = h("tbody", {});
    const head = h("tr", {}, h("th", {scope: "col"}, "Metric"), h("th", {scope: "col", title: "Shown in the chip"}, "Chip"), RATE_PERIODS.map(([id, short, per]) => h("th", {scope: "col", "data-period": id, title: per}, short)));
    const box = h("div", {class: "menu-box end rates-box", role: "group", "aria-label": "Rates per period"},
      h("h3", {}, "Rates per period"), ...timeSection(), h("h3", {}, "Unit"), units,
      h("div", {class: "rates-scroll"}, h("table", {class: "rates-table"}, h("thead", {}, head), body)),
      h("p", {class: "muted"}, `Every column rates the chosen window: a count is its sum per unit, all the sum itself; a gauge averages over the window. ≈ means the records of a kind begin inside the window, so the rate divides by the part they cover, or the window is shorter than the hour tokens are counted in. n/a means no record or sample in the window. The chip shows ${RATES.fewest} to ${RATES.most} metrics.`));
    const menu = h("details", {class: "menu rates-menu"}, chip, box);
    host.replaceChildren(menu);
    rateView.dom = {chip, units, body, menu};
    window.addEventListener("resize", () => fitChip(chip));
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

  function fitChip(chip) {
    const shown = [...chip.querySelectorAll(".rate")];
    const more = chip.querySelector(".rate-more");
    if (!more) {
      return;
    }
    shown.forEach((node) => {
      node.hidden = false;
    });
    more.hidden = true;
    for (let kept = shown.length; kept > 1 && chip.scrollWidth > chip.clientWidth; kept -= 1) {
      shown[kept - 1].hidden = true;
      more.hidden = false;
      more.textContent = `+${shown.length - kept + 1}`;
    }
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
    for (const button of dom.units.children) {
      button.setAttribute("aria-pressed", String(button.dataset.period === period[0]));
    }
    dom.chip.replaceChildren(h("span", {class: "rate-window"}, `${windowName()} · ${short ? `/${short}` : "all"}`),
      ...entries.map(([metric, entry]) => h("span", {class: "rate", "data-metric": metric[0], "data-approx": String(Boolean(entry && entry.approx)), title: rateHint(entry, metric, period)},
        icon(metric[1]), h("span", {class: "rate-value"}, rateText(entry, metric[3], metric[3] === "count" ? short : "")))),
      h("span", {class: "rate-more", hidden: true}), caret());
    dom.chip.setAttribute("aria-label", `Rates ${period[2]} over ${windowName()}: ${entries.map(([metric, entry]) => `${metric[2]} ${rateText(entry, metric[3], "")}`).join(", ")}`);
    dom.chip.title = "Rates per period: time range, replay, unit and every metric";
    fitChip(dom.chip);
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
    rateView.ticket += 1;
    const ticket = rateView.ticket;
    rateView.at = nowSeconds();
    try {
      const response = await fetch(`/api/rates?${windowQuery()}`, {cache: "no-store"});
      if (response.ok && ticket === rateView.ticket) {
        rateView.data = await response.json();
      }
    } catch {
      ui.offline = true;
    }
    drawRates();
  }

  function pollRates() {
    if (!document.hidden && nowSeconds() - rateView.at >= RATES.poll) {
      fetchRates();
    }
  }
