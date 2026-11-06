  const skyMoment = () => (live() ? Date.now() : (ui.asOf === null ? state.until : ui.asOf) * 1000);

  function applyTheme(sun) {
    const custom = settings.theme === "custom";
    const mode = custom ? Ambience.modeOf(settings.colors.top, settings.colors.bottom) : settings.theme === "sky" ? Ambience.modeAt(sun.alt) : settings.theme;
    const glass = Boolean(window.CSS && CSS.supports("(backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))")) && !window.matchMedia("(prefers-reduced-transparency: reduce)").matches;
    const key = [mode, custom ? settings.colors.accent : "", glass].join("|");
    if (key === sky.mode) {
      return;
    }
    sky.mode = key;
    const root = document.documentElement;
    const tokens = Ambience.THEMES[mode];
    for (const [name, value] of Object.entries(tokens)) {
      root.style.setProperty(`--${name}`, value);
    }
    if (custom) {
      root.style.setProperty("--accent", settings.colors.accent);
      root.style.setProperty("--accent-soft", Ambience.css(Ambience.mix(Ambience.hex(settings.colors.accent), Ambience.hex(tokens.panel), 0.84)));
    }
    root.style.setProperty("--veil", `${glass ? Ambience.GLASS * 100 : 100}%`);
    root.style.setProperty("--card", `${glass ? Ambience.CARD * 100 : 100}%`);
    root.style.colorScheme = mode;
    root.dataset.mode = mode;
    requestSpace();
  }

  function drawMoon(paint, at, radius, moon) {
    const tilt = (moon.tilt * Math.PI) / 180;
    paint.save();
    paint.translate(at.x, at.y);
    paint.rotate(Math.atan2(-Math.cos(tilt), -Math.sin(tilt)));
    const halo = paint.createRadialGradient(0, 0, radius, 0, 0, radius * 4);
    halo.addColorStop(0, `rgb(235 240 255 / ${(0.28 * moon.lit).toFixed(3)})`);
    halo.addColorStop(1, "rgb(235 240 255 / 0)");
    paint.fillStyle = halo;
    paint.fillRect(-radius * 4, -radius * 4, radius * 8, radius * 8);
    paint.fillStyle = "rgb(60 68 92 / 0.55)";
    paint.beginPath();
    paint.arc(0, 0, radius, 0, Math.PI * 2);
    paint.fill();
    paint.fillStyle = "#f3f0e4";
    paint.beginPath();
    paint.arc(0, 0, radius, -Math.PI / 2, Math.PI / 2, false);
    paint.ellipse(0, 0, Math.abs(2 * moon.lit - 1) * radius, radius, 0, Math.PI / 2, -Math.PI / 2, moon.lit < 0.5);
    paint.closePath();
    paint.fill();
    paint.restore();
  }

  function drawSky() {
    const ms = skyMoment();
    const sun = Ambience.sun(ms, settings.latitude, settings.longitude);
    const moon = Ambience.moon(ms, settings.latitude, settings.longitude);
    applyTheme(sun);
    const view = seenView("sky");
    const facing = COMPASS[Space.compass(view.azimuth)];
    const turned = ["azimuth", "altitude", "fov"].some((key) => Math.abs(view[key] - Space.DEFAULTS.sky[key]) >= 0.5);
    const moonText = moon.alt > 0 ? ` · Mond ${Math.round(moon.lit * 100)} % ${moon.waxing ? "zunehmend" : "abnehmend"}` : "";
    document.getElementById("sky-note").textContent = `${sun.alt > 0 ? "☀" : "☾"} ${STAGE_LABELS[Ambience.stage(sun.alt)]}${moonText}${turned ? ` · Blick ${facing[0]}` : ""}`;
    if (space.look) {
      const words = `Blick nach ${facing[1]} · ${((Math.round(view.azimuth) % 360) + 360) % 360}° · Höhe ${Math.round(view.altitude)}° · Sichtfeld ${Math.round(view.fov)}°`;
      space.compass.textContent = words;
      sky.canvas.setAttribute("aria-label", `Himmel, ${words}. Pfeiltasten drehen den Blick, Plus und Minus zoomen, 0 setzt zurück, Esc beendet.`);
    }
    const canvas = sky.canvas;
    const paint = canvas.getContext("2d");
    if (!paint) {
      return;
    }
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = window.innerWidth;
    const height = window.innerHeight;
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    paint.setTransform(ratio, 0, 0, ratio, 0, 0);
    const sight = Space.lens(view, width, height);
    const place = (alt, az) => Space.place(sight, alt, az);
    const inside = (at, margin) => at.x >= -margin && at.x <= width + margin && at.y >= -margin && at.y <= height + margin;
    const seen = (body, at) => body.alt > -2 && Math.abs(at.lon) <= view.fov / 2 + 10 && inside(at, 100);
    const colors = settings.theme === "custom" ? {top: Ambience.hex(settings.colors.top), bottom: Ambience.hex(settings.colors.bottom)} : Ambience.skyAt(sun.alt);
    const low = place(0, view.azimuth);
    const high = place(90, view.azimuth);
    const air = paint.createLinearGradient(low.x + (high.x - low.x) / Space.REACH, low.y + (high.y - low.y) / Space.REACH, low.x, low.y);
    air.addColorStop(0, Ambience.css(colors.top));
    air.addColorStop(1, Ambience.css(colors.bottom));
    paint.fillStyle = air;
    paint.fillRect(0, 0, width, height);
    const dusk = Math.max(0, 1 - Math.abs(sun.alt) / 14);
    const glowAt = place(Math.max(sun.alt, -3), sun.az);
    if (dusk > 0 && Math.abs(glowAt.lon) <= 135) {
      const x = Math.min(Math.max(glowAt.x, sight.cx - sight.kx * 100), sight.cx + sight.kx * 100);
      const glow = paint.createRadialGradient(x, glowAt.y, 0, x, glowAt.y, width * 0.5);
      glow.addColorStop(0, `rgb(255 186 128 / ${(0.45 * dusk).toFixed(3)})`);
      glow.addColorStop(1, "rgb(255 186 128 / 0)");
      paint.fillStyle = glow;
      paint.fillRect(0, 0, width, height);
    }
    const light = Ambience.starlight(sun.alt);
    if (light > 0) {
      const spin = Ambience.sidereal(ms) + settings.longitude;
      paint.fillStyle = "#ffffff";
      for (const star of sky.stars) {
        const spot = Ambience.horizontal(spin - star.ra, star.dec, settings.latitude);
        const at = spot.alt > 1 ? place(spot.alt, spot.az) : null;
        if (at && Math.abs(at.lon) <= view.fov / 2 && inside(at, 4)) {
          paint.globalAlpha = light * (0.25 + 0.75 * star.glow);
          paint.beginPath();
          paint.arc(at.x, at.y, 0.5 + star.glow * 1.2, 0, Math.PI * 2);
          paint.fill();
        }
      }
      paint.globalAlpha = 1;
    }
    const sunAt = place(sun.alt, sun.az);
    if (seen(sun, sunAt)) {
      const at = sunAt;
      const halo = paint.createRadialGradient(at.x, at.y, 0, at.x, at.y, 90);
      halo.addColorStop(0, "rgb(255 236 200 / 0.55)");
      halo.addColorStop(1, "rgb(255 236 200 / 0)");
      paint.fillStyle = halo;
      paint.fillRect(at.x - 90, at.y - 90, 180, 180);
      paint.fillStyle = Ambience.css(Ambience.mix([255, 170, 90], [255, 246, 220], Math.min(Math.max(sun.alt / 20, 0), 1)));
      paint.beginPath();
      paint.arc(at.x, at.y, 15, 0, Math.PI * 2);
      paint.fill();
    }
    const moonAt = place(moon.alt, moon.az);
    if (seen(moon, moonAt)) {
      drawMoon(paint, moonAt, 12, moon);
    }
    const edge = Space.horizon(sight, 96);
    const bottom = Math.max(height, ...edge.map((at) => at.y)) + 2;
    const trace = (lift) => edge.forEach((at, index) => (index ? paint.lineTo(at.x, at.y + lift) : paint.moveTo(at.x, at.y + lift)));
    const ground = paint.createLinearGradient(0, low.y, 0, low.y + height - sight.cy);
    ground.addColorStop(0, Ambience.css(Ambience.mix(colors.bottom, [4, 6, 10], 0.72)));
    ground.addColorStop(1, Ambience.css(Ambience.mix(colors.bottom, [4, 6, 10], 0.9)));
    paint.fillStyle = ground;
    paint.beginPath();
    trace(0);
    paint.lineTo(edge[edge.length - 1].x, bottom);
    paint.lineTo(edge[0].x, bottom);
    paint.closePath();
    paint.fill();
    paint.strokeStyle = "rgb(255 255 255 / 0.18)";
    paint.lineWidth = 1;
    paint.beginPath();
    trace(0.5);
    paint.stroke();
    paint.fillStyle = "rgb(255 255 255 / 0.5)";
    paint.font = "600 11px system-ui, sans-serif";
    paint.textAlign = "center";
    COMPASS.forEach(([label], index) => {
      const at = place(0, index * 45);
      if (Math.abs(at.lon) <= view.fov / 2 + 0.5) {
        paint.fillText(label, Math.min(Math.max(at.x, 14), width - 14), at.y + 16);
      }
    });
    if (space.glides.sky) {
      redrawSky();
    }
  }

  function redrawSky() {
    window.cancelAnimationFrame(sky.frame);
    sky.frame = window.requestAnimationFrame(drawSky);
  }

  function skyLook(on) {
    const canvas = sky.canvas;
    space.look = on;
    document.body.classList.toggle("sky-look", on);
    document.getElementById("sky-panel").hidden = !on;
    if (on) {
      canvas.removeAttribute("aria-hidden");
      canvas.setAttribute("tabindex", "0");
      canvas.setAttribute("role", "application");
      canvas.setAttribute("aria-roledescription", "Himmel");
      drawSky();
      canvas.focus();
      return;
    }
    for (const name of ["tabindex", "role", "aria-roledescription", "aria-label"]) {
      canvas.removeAttribute(name);
    }
    canvas.setAttribute("aria-hidden", "true");
    document.getElementById("settings-open").focus();
  }

  function skyPanel() {
    const panel = document.getElementById("sky-panel");
    const step = (text, label, run) => h("button", {type: "button", class: "btn small", title: label, "aria-label": label, on: {click: run}}, text);
    space.compass = h("span", {class: "compass", "aria-live": "polite"});
    panel.append(space.compass,
      step("◀", "Blick nach links drehen (Pfeil links)", () => skyHooks.turnStep(-1, 0)),
      step("▶", "Blick nach rechts drehen (Pfeil rechts)", () => skyHooks.turnStep(1, 0)),
      step("▲", "Blick heben (Pfeil hoch)", () => skyHooks.turnStep(0, -1)),
      step("▼", "Blick senken (Pfeil runter)", () => skyHooks.turnStep(0, 1)),
      step("−", "Sichtfeld weiten (Minus)", () => skyHooks.zoomStep(1 / ZOOM)),
      step("+", "Hineinzoomen (Plus)", () => skyHooks.zoomStep(ZOOM)),
      step("⟲ Zurücksetzen", "Blick zurücksetzen: Süden, Horizont, Sichtfeld 180° (Taste 0)", () => resetView("sky")),
      step("Fertig", "Himmel verlassen (Esc)", () => skyLook(false)));
    steer(sky.canvas, "sky", skyHooks);
  }
