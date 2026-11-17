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
  popupDialog().addEventListener("click", (event) => {
    if (event.target === event.currentTarget) {
      closePopup();
    }
  });
  document.getElementById("palette-open").addEventListener("click", openPalette);
  document.getElementById("settings-open").addEventListener("click", settingsSheet);
  document.getElementById("bubbles-toggle").addEventListener("click", toggleBubbles);
  document.addEventListener("click", (event) => closeMenus(event.target instanceof Element ? event.target.closest(MENUS) : null));
  document.addEventListener("scroll", placeStations, {capture: true, passive: true});
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
  document.addEventListener("keydown", ctxKeydown);
  document.addEventListener("contextmenu", ctxContextMenu);
  document.addEventListener("selectionchange", feedbackButton);
  document.addEventListener("visibilitychange", refresh);
  window.addEventListener("focus", refresh);
  window.addEventListener("hashchange", apply);
  window.addEventListener("resize", measure);
  window.addEventListener("resize", redrawSky);
  window.addEventListener("resize", refresh3d);
  window.addEventListener("resize", placePopup);
  window.addEventListener("resize", placeStations);
  skyPanel();
  micWatch();
  radioSpot();
  radio.element = radioElement();
  drawSky();
  musicButton();
  syncBubbles();
  syncMusic();
  syncRadio();
  ratesBar();
  notifyLabel();
  announce();
  measure();
  homeBoot();
  legendBoot();
  apply();
  drawTime();
  motion.asOf = ui.asOf;
  relayout(0);
  window.setInterval(poll, 10000);
  window.setInterval(follow, 3000);
  window.setInterval(() => relayout(MOVE), RELAYOUT);
  window.setInterval(() => live() && drawSky(), 30000);
  window.setInterval(syncRadio, 20000);
  window.setInterval(() => {
    if (tree.dom && !document.hidden) {
      fetchTree();
    }
  }, 60000);
