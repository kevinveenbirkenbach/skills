  function spaceTools() {
    const axis = space.views.graph.axis;
    const deep = axis !== "none";
    return h("div", {class: "space-tools"},
      h("div", {class: "segmented", role: "group", "aria-label": "Tiefenachse"}, AXES.map(([id, label, hint]) => h("button", {type: "button", "aria-pressed": String(axis === id), title: hint, "aria-label": `Tiefenachse ${label}: ${hint}`, on: {click: () => chooseAxis(id)}}, label))),
      deep ? h("button", {type: "button", class: "btn small ghost", title: "Drehung, Zoom und Verschiebung zurücksetzen (Taste 0)", "aria-label": "3D-Ansicht zurücksetzen", on: {click: () => resetView("graph")}}, "⟲ Ansicht") : null,
      deep ? h("span", {class: "muted", id: "space-help"}, "Ziehen dreht · Umschalt+Ziehen verschiebt · Rad oder zwei Finger zoomen · Pfeile, + / −, 0") : null);
  }

  const graph3d = () => ui.screen === "graph" && ui.graph === "orbit" && space.views.graph.axis !== "none";
  const wantsTrack = () => graph3d() && space.views.graph.axis === "time";

  function chooseAxis(id) {
    if (id === space.views.graph.axis) {
      return;
    }
    setView("graph", {...space.views.graph, axis: id}, false);
    render(false);
  }

  function stage() {
    if (!graphDom || ui.screen !== "graph") {
      return;
    }
    graphDom.pulses = null;
    if (graph3d()) {
      stageSpace();
      return;
    }
    graphDom.stage.replaceChildren({orbit, chord, swimlane}[ui.graph]());
  }

  function drawSide() {
    if (graphDom && ui.screen === "graph") {
      graphDom.aside.replaceChildren(...side());
    }
  }

  function seenView(kind) {
    const glide = space.glides[kind];
    const progress = glide && !calm.matches ? Math.min((performance.now() - glide.start) / GLIDE, 1) : 1;
    if (progress >= 1) {
      space.glides[kind] = null;
      return space.views[kind];
    }
    return Space.tween(kind, glide.from, space.views[kind], Space.ease(progress));
  }

  function settle(kind) {
    if (space.glides[kind]) {
      space.views[kind] = Space.clampView(kind, seenView(kind));
      space.glides[kind] = null;
    }
  }

  function setView(kind, next, smooth) {
    space.glides[kind] = smooth && !calm.matches ? {from: seenView(kind), start: performance.now()} : null;
    space.views[kind] = Space.clampView(kind, next);
    space.edits += 1;
    window.clearTimeout(space.timer);
    space.timer = window.setTimeout(persistViews, SAVE_DELAY);
    if (kind === "graph") {
      requestSpace();
    } else {
      redrawSky();
    }
  }

  const nudge = (kind, change, smooth) => setView(kind, change(space.views[kind]), smooth);
  const savedSpace = () => ({graph: Space.tidy(space.views.graph), sky: Space.tidy(space.views.sky)});

  async function persistViews() {
    const mark = space.edits;
    if (await saveSettings({...settings, space: savedSpace()}) && space.edits === mark) {
      space.saved = mark;
    }
  }

  function resetView(kind) {
    setView(kind, kind === "graph" ? {...Space.DEFAULTS.graph, axis: space.views.graph.axis} : {...Space.DEFAULTS.sky}, true);
  }

  function steerKey(event, kind, hooks) {
    const arrows = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]};
    if (event.altKey || event.ctrlKey || event.metaKey) {
      return;
    }
    if (Object.hasOwn(arrows, event.key)) {
      const [x, y] = arrows[event.key];
      if (event.shiftKey && hooks.panStep) {
        hooks.panStep(x, y);
      } else {
        hooks.turnStep(x, y);
      }
    } else if (event.key === "+" || event.key === "=") {
      hooks.zoomStep(ZOOM);
    } else if (event.key === "-" || event.key === "_") {
      hooks.zoomStep(1 / ZOOM);
    } else if (event.key === "0") {
      resetView(kind);
    } else if (event.key === "Escape" && kind === "sky") {
      skyLook(false);
    } else {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
  }

  function steer(element, kind, hooks) {
    const pointers = new Map();
    let travel = 0;
    let spread = 0;
    const gap = () => {
      const [a, b] = [...pointers.values()];
      return Math.hypot(a.x - b.x, a.y - b.y);
    };
    element.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse" && event.button !== 0) {
        return;
      }
      element.setPointerCapture(event.pointerId);
      pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
      settle(kind);
      travel = pointers.size === 1 ? 0 : Infinity;
      spread = pointers.size === 2 ? gap() : 0;
    });
    element.addEventListener("pointermove", (event) => {
      const last = pointers.get(event.pointerId);
      if (!last) {
        return;
      }
      const dx = event.clientX - last.x;
      const dy = event.clientY - last.y;
      pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
      travel += Math.abs(dx) + Math.abs(dy);
      if (pointers.size === 2) {
        const next = gap();
        if (spread > 0 && next > 0) {
          hooks.zoom(next / spread);
        }
        spread = next;
      } else if (pointers.size === 1 && travel > 3) {
        if (event.shiftKey && hooks.pan) {
          hooks.pan(dx, dy);
        } else {
          hooks.rotate(dx, dy);
        }
      }
    });
    const release = (event) => {
      if (!pointers.delete(event.pointerId)) {
        return;
      }
      spread = pointers.size === 2 ? gap() : 0;
      if (event.type === "pointerup" && !pointers.size && travel <= 3 && hooks.pick) {
        const box = element.getBoundingClientRect();
        hooks.pick(event.clientX - box.left, event.clientY - box.top);
      }
    };
    element.addEventListener("pointerup", release);
    element.addEventListener("pointercancel", release);
    element.addEventListener("wheel", (event) => {
      event.preventDefault();
      settle(kind);
      hooks.zoom(Math.exp(-event.deltaY * [1, 16, 400][event.deltaMode] * 0.0015));
    }, {passive: false});
    element.addEventListener("keydown", (event) => steerKey(event, kind, hooks));
  }

  const graphHooks = {
    rotate: (dx, dy) => nudge("graph", (view) => ({...view, yaw: view.yaw - dx * 0.4, pitch: view.pitch + dy * 0.4}), false),
    pan: (dx, dy) => nudge("graph", (view) => ({...view, pan_x: view.pan_x + dx / (space.cam ? space.cam.scale : 1), pan_y: view.pan_y + dy / (space.cam ? space.cam.scale : 1)}), false),
    zoom: (factor) => nudge("graph", (view) => ({...view, zoom: view.zoom * factor}), false),
    turnStep: (x, y) => nudge("graph", (view) => ({...view, yaw: view.yaw - x * TURN, pitch: view.pitch + y * TURN}), true),
    panStep: (x, y) => nudge("graph", (view) => ({...view, pan_x: view.pan_x + x * NUDGE, pan_y: view.pan_y + y * NUDGE}), true),
    zoomStep: (factor) => nudge("graph", (view) => ({...view, zoom: view.zoom * factor}), true),
    pick: (x, y) => pickSpace(x, y),
  };

  const skyLens = () => Space.lens(seenView("sky"), window.innerWidth, window.innerHeight);

  const skyHooks = {
    rotate: (dx, dy) => {
      const sight = skyLens();
      nudge("sky", (view) => ({...view, azimuth: view.azimuth - dx / sight.kx, altitude: view.altitude + dy / sight.ky}), false);
    },
    pan: null,
    zoom: (factor) => nudge("sky", (view) => ({...view, fov: view.fov / factor}), false),
    turnStep: (x, y) => nudge("sky", (view) => ({...view, azimuth: view.azimuth + x * TURN, altitude: view.altitude - y * TURN}), true),
    panStep: null,
    zoomStep: (factor) => nudge("sky", (view) => ({...view, fov: view.fov / factor}), true),
    pick: null,
  };
