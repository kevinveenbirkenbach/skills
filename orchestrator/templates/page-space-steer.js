  function stage() {
    if (!graphDom || ui.screen !== "agents" || ui.views.agents === "tree" || ui.views.agents === "hierarchy") {
      return;
    }
    graphDom.pulses = null;
    if (ui.views.agents === "3d") {
      stage3d("agents", graphDom.stage);
      return;
    }
    graphDom.stage.replaceChildren({orbit, chord, swimlane}[ui.views.agents]());
  }

  function drawSide() {
    if (graphDom && ui.screen === "agents" && ui.views.agents !== "tree" && ui.views.agents !== "hierarchy") {
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
    if (kind === "sky") {
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
