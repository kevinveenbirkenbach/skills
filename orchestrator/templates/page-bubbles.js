  const BUBBLE_FONT = "/vendor/comic-neue.woff2";
  const BUBBLE_FADE = 400;
  const BUBBLE_EDGE = 8;
  const bubbles = {shown: new Map(), frame: 0, font: null, quiet: [], waiting: [], warned: 0};

  function bubbleLayer() {
    return document.getElementById("bubbles");
  }

  function bubbleFont() {
    // The CSP has no font-src, so a url() face is refused; a face built from fetched bytes loads nothing itself.
    if (!bubbles.font) {
      bubbles.font = fetch(BUBBLE_FONT, {cache: "force-cache"})
        .then((response) => (response.ok ? response.arrayBuffer() : Promise.reject(new Error(String(response.status)))))
        .then((data) => new FontFace("Comic Neue", data, {style: "normal", weight: "400"}).load())
        .then((loaded) => document.fonts.add(loaded))
        .catch(() => null);
    }
    return bubbles.font;
  }

  function inView(box) {
    return box.width > 0 && box.height > 0 && box.left + box.width > 0 && box.top + box.height > 0 && box.left < window.innerWidth && box.top < window.innerHeight;
  }

  function clipped(box, frame) {
    const left = Math.max(box.left, frame.left);
    const top = Math.max(box.top, frame.top);
    return {left, top, width: Math.min(box.left + box.width, frame.left + frame.width) - left, height: Math.min(box.top + box.height, frame.top + frame.height) - top};
  }

  function clipsOf(node) {
    const frames = [];
    for (let at = node; at.parentElement && at.parentElement !== document.body && getComputedStyle(at).position !== "fixed"; at = at.parentElement) {
      const style = getComputedStyle(at.parentElement);
      if (style.display !== "contents" && style.display !== "inline" && (style.overflowX !== "visible" || style.overflowY !== "visible")) {
        frames.push(at.parentElement.getBoundingClientRect());
      }
    }
    return frames;
  }

  function anchorOf(key) {
    const projected = g3.tab === "agents" ? anchor3d(key)() : null;
    if (projected && inView(projected)) {
      return projected;
    }
    for (const node of document.querySelectorAll(`[data-face="${CSS.escape(key)}"]`)) {
      const box = node.getBoundingClientRect();
      const shown = inView(box) ? clipsOf(node).reduce(clipped, box) : null;
      if (shown && inView(shown)) {
        return shown;
      }
    }
    return null;
  }

  function bubbleNode(item) {
    const words = h("span", {class: "bubble-words"});
    return {node: h("div", {class: "speech-bubble", "data-who": item.who}, h("strong", {class: "bubble-who"}, nameOf(item.who)), words), words};
  }

  function placeBubble(view, box, scale) {
    const layer = bubbleLayer();
    const bar = layer.querySelector(".bubble-bar");
    if (!box) {
      if (view.node.parentElement !== bar) {
        view.node.style.removeProperty("left");
        view.node.style.removeProperty("top");
        bar.append(view.node);
      }
      return;
    }
    if (view.node.parentElement !== layer) {
      layer.append(view.node);
    }
    const [width, height] = [view.node.offsetWidth * scale, view.node.offsetHeight * scale];
    const middle = box.left + box.width / 2;
    const left = Math.min(Math.max(middle, BUBBLE_EDGE + width / 2), window.innerWidth - BUBBLE_EDGE - width / 2);
    view.node.style.left = `${fixed(left)}px`;
    view.node.style.top = `${fixed(Math.max(box.top - 4, BUBBLE_EDGE + height))}px`;
    view.node.style.setProperty("--tail", `${fixed((middle - left) / scale)}px`);
  }

  function saidOf(item) {
    return item.words || Bubbles.words(item.line);
  }

  function wordsRead(item) {
    if (!item.started) {
      return 0;
    }
    const [said, floor] = [saidOf(item).length, item.floor || 0];
    return Math.min(said, floor + Bubbles.shown(item.span ?? said - floor, item.duration, (performance.now() - item.started) / 1000));
  }

  function drawBubble(entry, view) {
    const {item} = entry;
    const said = saidOf(item);
    const count = wordsRead(item);
    const text = said.slice(0, count).join(" ") || "…";
    if (view.words.textContent !== text) {
      view.words.textContent = text;
      view.words.scrollTop = view.words.scrollHeight;
    }
    Object.assign(view.node.dataset, {scale: String(entry.scale), state: item.quiet ? "quiet" : item.started ? "speaking" : "waiting", words: String(count)});
    view.node.style.setProperty("--scale", String(entry.scale));
    placeBubble(view, anchorOf(entry.who), entry.scale);
  }

  function startQuiet(spoken) {
    const {start, waiting} = Bubbles.admit(bubbles.quiet, bubbles.waiting, new Set(spoken.map((entry) => entry.who)));
    bubbles.waiting = waiting;
    for (const item of start) {
      Object.assign(item, {started: performance.now(), duration: Bubbles.reading(saidOf(item).length)});
      item.timer = window.setTimeout(() => {
        bubbles.quiet = bubbles.quiet.filter((other) => other !== item);
        drawBubbles();
      }, item.duration * 1000);
    }
    bubbles.quiet = [...bubbles.quiet, ...start];
  }

  /**
   * @param {Array<object>} items the silent bubbles of the rows one poll brought live, oldest first.
   */
  function quietBubbles(items) {
    bubbles.waiting = items.reduce(Bubbles.queued, bubbles.waiting);
  }

  function drawBubbles() {
    try {
      renderBubbles();
    } catch (error) {
      if (Date.now() - bubbles.warned > SPEECH_QUIET) {
        bubbles.warned = Date.now();
        toast("Drawing speech bubbles failed", [String(error.message || error)], false);
      }
    }
  }

  function renderBubbles() {
    if (!settings.bubbles) {
      return;
    }
    const head = speech.current || speech.loading || speech.item;
    startQuiet(Bubbles.plan(head, speech.pending));
    const planned = Bubbles.plan(head, speech.pending, bubbles.quiet).filter((entry) => entry.item.bubble !== false);
    const kept = new Set(planned.map((entry) => entry.item));
    for (const [item, view] of bubbles.shown) {
      if (!kept.has(item)) {
        bubbles.shown.delete(item);
        view.node.dataset.read = String(wordsRead(item));
        view.node.classList.add("leaving");
        window.setTimeout(() => view.node.remove(), BUBBLE_FADE);
      }
    }
    for (const entry of planned) {
      if (!bubbles.shown.has(entry.item)) {
        bubbles.shown.set(entry.item, bubbleNode(entry.item));
      }
      drawBubble(entry, bubbles.shown.get(entry.item));
    }
    if (bubbles.shown.size && !bubbles.frame) {
      bubbles.frame = window.requestAnimationFrame(() => {
        bubbles.frame = 0;
        drawBubbles();
      });
    }
  }

  function clearBubbles() {
    window.cancelAnimationFrame(bubbles.frame);
    bubbles.frame = 0;
    bubbles.shown.clear();
    bubbles.quiet.forEach((item) => window.clearTimeout(item.timer));
    Object.assign(bubbles, {quiet: [], waiting: []});
    for (const node of bubbleLayer().querySelectorAll(".speech-bubble")) {
      node.remove();
    }
  }

  function syncBubbles() {
    document.getElementById("bubbles-toggle").setAttribute("aria-pressed", String(settings.bubbles));
    document.querySelectorAll(".radio-bubbles").forEach((button) => button.setAttribute("aria-pressed", String(settings.bubbles)));
    bubbleLayer().hidden = !settings.bubbles;
    if (settings.bubbles) {
      bubbleFont();
      drawBubbles();
    } else {
      clearBubbles();
      dropSilent();
    }
  }

  function toggleBubbles() {
    saveSettings({...settings, bubbles: !settings.bubbles});
  }
