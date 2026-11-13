  let loadTicket = 0;
  let appliedTicket = 0;
  let loadsInFlight = 0;

  async function load() {
    loadTicket += 1;
    const ticket = loadTicket;
    loadsInFlight += 1;
    const abort = new AbortController();
    const timer = window.setTimeout(() => abort.abort(), STATE_TIMEOUT);
    try {
      const response = await fetch(`/api/state?${windowQuery()}`, {cache: "no-store", signal: abort.signal});
      if (!response.ok) {
        throw new Error(String(response.status));
      }
      const next = await response.json();
      if (ticket < appliedTicket) {
        return;
      }
      appliedTicket = ticket;
      const previous = state.now;
      state = next;
      ui.offline = false;
      if (JSON.stringify(state.settings) !== settingsSig) {
        adoptSettings(state.settings);
      }
      tuneMusic(FADE / 1000);
      drawSky();
      announce();
      render(false);
      drawTime();
      drawAgent();
      drawStream();
      if (motion.current.size === 0 || ui.asOf !== motion.asOf) {
        const first = motion.current.size === 0;
        motion.asOf = ui.asOf;
        relayout(first ? 0 : ui.playing ? 450 : MOVE);
      }
      pulses(state.radio.filter((row) => row.ts > previous));
    } catch {
      if (ticket > appliedTicket) {
        ui.offline = true;
        tick();
      }
    } finally {
      window.clearTimeout(timer);
      loadsInFlight -= 1;
    }
  }

  function poll() {
    if (!loadsInFlight) {
      refresh();
    }
  }

  const SELECTION_HOLD = 20000;
  let selectedSince = 0;

  function refresh() {
    const selected = String(window.getSelection()).length > 0;
    selectedSince = selected ? selectedSince || Date.now() : 0;
    if (!ui.busy && !ui.playing && !document.hidden && (!selected || Date.now() - selectedSince >= SELECTION_HOLD)) {
      load();
    }
  }

  function follow() {
    if (ui.screen === "stream" && live() && !document.hidden) {
      fetchEvents();
    }
  }
