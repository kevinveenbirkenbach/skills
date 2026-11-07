  const consoles = new Map();
  const FOLLOW_SLACK = 12;
  const CONSOLE_POLL = 2000;
  const jobOpen = (job) => job.status === "queued" || job.status === "running";
  const withoutOutput = (item) => (item.job ? {...item, job: {...item.job, output: null}} : item);
  const consoleSizes = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const view = consoles.get(entry.target.dataset.job);
      if (view && view.follow) {
        view.out.scrollTop = view.out.scrollHeight;
      }
    }
  });

  function lasting(seconds) {
    const total = Math.max(0, Math.round(seconds));
    if (total < 60) {
      return `${total} s`;
    }
    if (total < 3600) {
      return `${Math.floor(total / 60)} min ${total % 60} s`;
    }
    return `${Math.floor(total / 3600)} h ${Math.floor((total % 3600) / 60)} min`;
  }

  function consoleWords(job) {
    if (job.status === "queued") {
      return `wartet auf den Runner seit ${lasting(nowSeconds() - job.created_ts)}`;
    }
    if (job.status === "running") {
      return `läuft seit ${lasting(nowSeconds() - job.started)}`;
    }
    if (job.status === "refused") {
      return "der Runner hat die Signatur nicht angenommen";
    }
    return `Exit-Code ${job.code} nach ${lasting(job.finished - job.started)}`;
  }

  function paintConsole(view, job) {
    const text = job.output || (jobOpen(job) ? "Noch keine Ausgabe." : "Keine Ausgabe.");
    if (view.out.textContent !== text) {
      view.out.textContent = text;
    }
    view.box.dataset.status = job.status;
    view.line.replaceChildren(status(job.status), h("span", {}, consoleWords(job)));
  }

  function consoleOf(job) {
    let view = consoles.get(job.id);
    if (!view) {
      const out = h("pre", {class: "console-out", tabindex: "0", "aria-label": "Ausgabe des Befehls", "data-job": job.id});
      const line = h("div", {class: "console-status"});
      view = {box: h("div", {class: "console", "data-job": job.id}, line, out), out, line, follow: true, top: 0};
      out.addEventListener("scroll", () => {
        view.top = out.scrollTop;
        view.follow = out.scrollHeight - out.scrollTop - out.clientHeight <= FOLLOW_SLACK;
      });
      consoles.set(job.id, view);
      consoleSizes.observe(out);
    }
    paintConsole(view, job);
    return view.box;
  }

  function settleConsoles(items) {
    const shown = new Set(items.filter((item) => item.job).map((item) => item.job.id));
    for (const [id, view] of consoles) {
      if (!shown.has(id)) {
        consoleSizes.unobserve(view.out);
        consoles.delete(id);
      } else if (view.box.isConnected) {
        view.out.scrollTop = view.follow ? view.out.scrollHeight : view.top;
      }
    }
  }

  function repaintConsoles(items) {
    for (const item of items) {
      const view = item.job ? consoles.get(item.job.id) : null;
      if (view) {
        paintConsole(view, item.job);
      }
    }
    settleConsoles(items);
  }

  async function dismissJob(job) {
    const result = await sendJson("/api/inbox/dismiss", {id: job.id});
    if (!result.ok) {
      toast("Schließen nicht möglich", fail(result), false);
    }
    await load();
  }

  window.setInterval(() => {
    if (ui.screen === "inbox" && state.inbox.some((item) => item.held || (item.job && jobOpen(item.job)))) {
      refresh();
    }
  }, CONSOLE_POLL);
