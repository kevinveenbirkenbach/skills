  async function load() {
    try {
      const response = await fetch(`/api/state?${windowQuery()}${wantsTrack() ? "&track=1" : ""}`, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(String(response.status));
      }
      const next = await response.json();
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
      drawDrawer();
      drawStream();
      if (motion.current.size === 0 || ui.asOf !== motion.asOf) {
        const first = motion.current.size === 0;
        motion.asOf = ui.asOf;
        relayout(first ? 0 : ui.playing ? 450 : MOVE);
      }
      pulses(state.radio.filter((row) => row.ts > previous));
    } catch {
      ui.offline = true;
      tick();
    }
  }

  function refresh() {
    if (!ui.busy && !ui.playing && !document.hidden && String(window.getSelection()).length === 0) {
      load();
    }
  }

  function follow() {
    if (ui.screen === "stream" && live() && !document.hidden) {
      fetchEvents();
    }
  }
