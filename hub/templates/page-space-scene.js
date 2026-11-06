  function shownCursor() {
    const glide = space.cursor;
    if (glide.to === null) {
      return state.until;
    }
    const progress = calm.matches ? 1 : Math.min((performance.now() - glide.start) / PLANE, 1);
    return progress >= 1 ? glide.to : glide.from + (glide.to - glide.from) * Space.ease(progress);
  }

  function sceneInput() {
    const span = [Math.min(Math.max(state.since, state.first), state.until), state.until];
    const range = ui.asOf !== null && ui.preset !== -1 ? [Math.min(state.first, span[0]), Math.max(state.now, span[1])] : span;
    const lives = {};
    const subagents = {};
    for (const [key, entry] of space.subs) {
      if (entry.data) {
        lives[key] = [entry.data.since, entry.data.until];
        subagents[key] = entry.data.subagents;
      }
    }
    return {
      axis: space.views.graph.axis, range, span, cursor: shownCursor(), nodes: state.graph.nodes, track: state.graph.track, now: Object.fromEntries(layout(state.graph.nodes)),
      lives, subagents, radio: state.radio, grants: state.grants, chair: chairKey(), cap: Space.ARC_CAP,
    };
  }

  function buildSpace() {
    const input = sceneInput();
    space.sceneCursor = input.cursor;
    space.scene = Space.scene(input);
  }

  function spaceLabel() {
    const hint = AXES.find(([id]) => id === space.views.graph.axis)[2];
    return `3D-Graph, ${hint}. Pfeiltasten drehen, Umschalt+Pfeile verschieben, Plus und Minus zoomen, 0 setzt zurück. Alle Weltlinien stehen darunter als Schaltflächen.`;
  }

  function stageSpace() {
    if (!graphDom.space) {
      const canvas = h("canvas", {class: "space", tabindex: 0, role: "application", "aria-roledescription": "3D-Graph", "aria-label": spaceLabel(), "aria-describedby": "space-help"});
      steer(canvas, "graph", graphHooks);
      graphDom.space = {canvas, note: h("div", {class: "space-note", "aria-live": "polite"}), list: h("div", {class: "space-list"}), data: null, version: -1, node: undefined, words: "", open: false};
      graphDom.stage.replaceChildren(canvas, graphDom.space.note, graphDom.space.list);
    }
    if (space.cursor.to !== state.until) {
      space.cursor = {from: space.cursor.to === null ? state.until : shownCursor(), to: state.until, start: performance.now()};
    }
    if (wantsTrack() && !state.graph.track.length && Date.now() - space.trackAsked > TRACK_RETRY) {
      space.trackAsked = Date.now();
      load();
    }
    buildSpace();
    const held = graphDom.space;
    if (held.data !== state || held.version !== space.version || held.node !== ui.node) {
      held.data = state;
      held.version = space.version;
      held.node = ui.node;
      drawSpaceList();
      refreshSubs();
    }
    drawSpaceNote();
    requestSpace();
  }

  function drawSpaceNote() {
    const built = space.scene;
    const format = (ts) => absolute.format(stampOf(ts));
    const axis = built.axis === "time" ? `Zeitachse ${format(built.range[0])} – ${format(built.range[1])}` : `Stand ${format(built.span[1])}`;
    const words = `${built.lines.length} Weltlinien · ${built.arcs.length} Bögen · ${axis}${built.dropped ? ` · ${built.dropped} weitere Ereignisse nur im Stream` : ""}`;
    if (graphDom.space.words === words) {
      return;
    }
    graphDom.space.words = words;
    const dropped = built.dropped ? [h("span", {}, "Gezeichnet: Mayday und Pan-Pan, Spawns, Sicherheit, Freigaben, dann die neuesten."), btn("Funk im Stream", "btn small soft", () => useView("radio"))] : [];
    graphDom.space.note.replaceChildren(h("span", {}, words), ...dropped);
  }

  function drawSpaceList() {
    const built = space.scene;
    const held = graphDom.space;
    const chip = (line) => {
      const text = line.kind === "twig" ? short(line.title) : Space.nameAt(line.timeline, built.span[1]);
      const former = [...new Set(line.timeline.map((entry) => entry.name))];
      const hint = line.kind === "twig" ? `${line.title} · Transkript im Stream zeigen` : `${NODE_KINDS[line.kind]}${former.length > 1 ? ` · Namen: ${former.join(" → ")}` : ""}`;
      return h("button", {type: "button", class: "chip", title: hint, "aria-label": `${text}: ${hint}`, "aria-pressed": String(line.node !== null && line.node === ui.node), on: {click: () => pickLine(line)}}, line.kind === "twig" ? text : [face(text, false), text]);
    };
    const twigs = built.lines.filter((line) => line.kind === "twig");
    const more = twigs.length ? h("details", {open: held.open}, h("summary", {}, `${twigs.length} Subagenten aus den Transkripten`), h("div", {class: "chips"}, twigs.map(chip))) : null;
    if (more) {
      more.addEventListener("toggle", () => {
        held.open = more.open;
      });
    }
    held.list.replaceChildren(h("div", {class: "chips", role: "group", "aria-label": "Weltlinien"}, built.lines.filter((line) => line.kind !== "twig").map(chip)), more || "");
  }

  async function refreshSubs() {
    if (!graph3d() || space.loading) {
      return;
    }
    const due = state.graph.nodes.filter((node) => (node.kind === "session" || node.kind === "chair") && SESSION_ID.test(node.id))
      .filter((node) => !space.subs.has(node.id) || Date.now() - space.subs.get(node.id).at > SUBS_TTL);
    if (!due.length) {
      return;
    }
    space.loading = true;
    await Promise.all(due.map(async (node) => {
      let data = null;
      try {
        const response = await fetch(`/api/subagents?session=${encodeURIComponent(node.id)}`, {cache: "no-store"});
        data = response.ok ? await response.json() : null;
      } catch {
        data = null;
      }
      space.subs.set(node.id, {at: Date.now(), data});
    }));
    space.loading = false;
    space.version += 1;
    stage();
  }

  function spaceStyle() {
    if (!space.style || space.styleKey !== sky.mode) {
      const css = window.getComputedStyle(document.documentElement);
      const value = (name) => css.getPropertyValue(`--${name}`).trim();
      const roles = {line: "line-strong", accent: "accent", muted: "muted", violet: "violet", direct: "direct", broadcast: "broadcast", alarm: "alarm", security: "security", grant: "grant", panel: "panel", text: "text"};
      space.styleKey = sky.mode;
      space.style = {
        colors: Object.fromEntries(Object.entries(roles).map(([role, name]) => [role, value(name)])),
        font: `560 ${value("fs-sm")} ${value("sans")}`, strong: `700 ${value("fs-sm")} ${value("sans")}`, level: "Tiefe",
      };
    }
    const built = space.scene;
    return {
      ...space.style, selected: ui.node, cursor: live() ? "Jetzt" : "Stand",
      format: (ts) => (built.range[1] - built.range[0] > DAY ? absolute : clock).format(stampOf(ts)),
    };
  }

  function requestSpace() {
    if (!space.frame) {
      space.frame = window.requestAnimationFrame(paintSpace);
    }
  }

  function paintSpace() {
    space.frame = 0;
    if (!graph3d() || !graphDom || !graphDom.space || !space.scene) {
      return;
    }
    const canvas = graphDom.space.canvas;
    const paint = canvas.getContext("2d");
    if (!paint) {
      return;
    }
    const cursor = shownCursor();
    if (cursor !== space.sceneCursor) {
      buildSpace();
    }
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    paint.setTransform(ratio, 0, 0, ratio, 0, 0);
    space.cam = Space.camera(seenView("graph"), width, height);
    Space.paint(paint, space.scene, space.cam, spaceStyle());
    if (space.glides.graph || cursor !== space.cursor.to) {
      requestSpace();
    }
  }

  function pickLine(line) {
    if (line.kind === "twig") {
      focusSub(line.session, line.sub);
    } else {
      select(line.node);
    }
  }

  function pickSpace(x, y) {
    const hit = space.scene && space.cam ? Space.pick(space.scene, space.cam, x, y, 10) : null;
    if (!hit) {
      return;
    }
    if (hit.kind === "line") {
      pickLine(hit.line);
    } else if (hit.arc.kind === "spawn") {
      focusSub(hit.arc.source, hit.arc.sub);
    } else if (hit.arc.kind === "grant") {
      select(hit.arc.target);
    } else {
      useSaved({name: "", kinds: ["radio"], waiting: false, q: "", agent: hit.arc.row >= 0 ? state.radio[hit.arc.row].from : nameOf(hit.arc.source)});
    }
  }
