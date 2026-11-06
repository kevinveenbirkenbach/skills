  document.getElementById("palette").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) {
      closePalette();
    }
  });
  document.getElementById("sheet").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) {
      closeSheet();
    }
  });
  document.getElementById("palette-open").addEventListener("click", openPalette);
  document.getElementById("settings-open").addEventListener("click", settingsSheet);
  document.addEventListener("click", (event) => closeMenus(event.target instanceof Element ? event.target.closest("details.menu") : null));
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement) {
      document.body.classList.remove("leitstand");
    }
    window.setTimeout(measure, 50);
  });
  document.addEventListener("pointerdown", context, {once: true});
  document.addEventListener("keydown", context, {once: true});
  document.addEventListener("pointerdown", unlock);
  document.addEventListener("keydown", keyboard);
  document.addEventListener("visibilitychange", refresh);
  window.addEventListener("hashchange", apply);
  window.addEventListener("resize", measure);
  window.addEventListener("resize", redrawSky);
  window.addEventListener("resize", requestSpace);
  skyPanel();
  radio.element = h("audio", {preload: "none"});
  radio.element.addEventListener("error", () => {
    if (radio.element.getAttribute("src")) {
      radio.playing = false;
      radio.url = "";
      tuneMusic(FADE / 1000);
    }
  });
  drawSky();
  musicButton();
  syncMusic();
  syncRadio();
  timeBar();
  notifyLabel();
  announce();
  measure();
  apply();
  drawTime();
  motion.asOf = ui.asOf;
  relayout(0);
  window.setInterval(refresh, 10000);
  window.setInterval(follow, 3000);
  window.setInterval(() => relayout(MOVE), RELAYOUT);
  window.setInterval(() => live() && drawSky(), 30000);
  window.setInterval(syncRadio, 20000);
  window.setInterval(() => {
    if (tree.dom && !document.hidden) {
      fetchTree();
    }
  }, 60000);
