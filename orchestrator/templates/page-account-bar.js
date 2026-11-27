  const USAGE_DELAY = 400;
  const USAGE_STEPS = {ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 10, PageDown: -10};
  const usageTenth = (value) => Math.round(value * 10) / 10;
  const usageClamp = (value) => Math.min(100, Math.max(0, value));
  let usageSaved = Promise.resolve();

  function forecastToggle() {
    const toggle = h("button", {type: "button", class: "btn small soft acc-switch", "data-forecast-toggle": "", "aria-pressed": String(settings.forecast),
      ...named("Auto forecast", "Auto forecast: mark the share each account reaches at its reset if the tokens of the last 24 hours keep their rate")}, icon("bi-graph-up-arrow"), h("span", {}, "Auto forecast"));
    toggle.addEventListener("click", async () => {
      if (await saveSettings({...settings, forecast: !settings.forecast})) {
        drawAccounts();
      }
    });
    accountsView.toggle = toggle;
    return toggle;
  }

  function dayTime(ms) {
    const at = new Date(ms);
    return momentText({day: at.getDay(), time: `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`});
  }

  function forecastMark(row, now) {
    if (!settings.forecast || row.account.limit <= 0) {
      return null;
    }
    const expected = UsageBar.forecast(row.account.limit, row.entry, row.bar.share, now, row.next);
    const hint = expected.full === null ? `${Math.round(expected.share)} % expected at the reset, ${dayTime(row.next)}` : `100 % at ${dayTime(expected.full)}`;
    const mark = h("span", {class: "acc-forecast", "data-forecast": expected.full === null ? "reset" : "full", title: hint});
    mark.style.setProperty("--forecast", `${usageClamp(expected.share)}%`);
    return mark;
  }

  /**
   * @param bar - the slider whose share waits to be stored.
   * @param id - the account's id.
   * @param share - the percent to store.
   * @param delay - milliseconds to wait for a further step; each step restarts it.
   * Holds the Accounts redraw until the newest calibration of the account is stored, then draws it.
   */
  function calibrateLater(bar, id, share, delay) {
    const held = accountsView.held.get(id);
    if (held) {
      window.clearTimeout(held.timer);
    }
    const mark = {timer: 0};
    accountsView.held.set(id, mark);
    bar.setAttribute("data-pending", "");
    mark.timer = window.setTimeout(() => {
      usageSaved = usageSaved.then(async () => {
        const result = await sendJson(`/api/accounts/${id}/calibrate`, {share});
        if (result.ok && result.data) {
          accountsView.data.calibrations[id] = result.data;
        } else {
          toast("Usage: not calibrated", fail(result), false);
        }
        if (accountsView.held.get(id) === mark) {
          accountsView.held.delete(id);
          drawAccounts();
        }
      });
    }, delay);
  }

  /**
   * @param row - an accountRows() row of an account with a limit.
   * @param now - epoch milliseconds.
   * @returns the usage bar: an ARIA slider whose fill shows the share in its flowing colour; dragging it or the arrows
   * (1 %) and Page Up and Down (10 %) calibrate the share to what the provider shows.
   */
  function usageBar(row, now) {
    const {account} = row;
    const mark = forecastMark(row, now);
    const bar = h("div", {class: "acc-bar", role: "slider", tabindex: "0", "data-usage": account.id, "aria-label": `Usage of ${account.email}`, "aria-valuemin": "0", "aria-valuemax": "100",
      ...(row.bar.calibrated ? {"data-calibrated": ""} : {})}, h("span", {class: "acc-fill"}), mark, h("span", {class: "acc-handle"}));
    let share = row.bar.share;
    const show = (value) => {
      share = value;
      bar.style.setProperty("--share", `${usageClamp(value)}%`);
      bar.style.setProperty("--fill", UsageBar.fillColor(value));
      bar.setAttribute("aria-valuenow", String(usageTenth(usageClamp(value))));
      bar.setAttribute("aria-valuetext", `${usageTenth(value)} % of ${Resources.compact(account.limit)} tokens${mark ? `; ${mark.title}` : ""}`);
    };
    const pointed = (event) => {
      const box = bar.getBoundingClientRect();
      show(usageTenth(usageClamp((100 * (event.clientX - box.left)) / box.width)));
    };
    const release = () => {
      window.removeEventListener("pointermove", pointed);
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
      bar.removeAttribute("data-dragging");
      calibrateLater(bar, account.id, share, 0);
    };
    bar.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) {
        return;
      }
      event.preventDefault();
      bar.focus({preventScroll: true});
      bar.setAttribute("data-dragging", "");
      accountsView.held.set(account.id, {timer: 0});
      pointed(event);
      window.addEventListener("pointermove", pointed);
      window.addEventListener("pointerup", release);
      window.addEventListener("pointercancel", release);
    });
    bar.addEventListener("keydown", (event) => {
      if (!(event.key in USAGE_STEPS)) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      show(usageTenth(usageClamp(usageClamp(share) + USAGE_STEPS[event.key])));
      calibrateLater(bar, account.id, share, USAGE_DELAY);
    });
    show(share);
    return bar;
  }
