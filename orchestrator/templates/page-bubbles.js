  const BUBBLE_FONT = "/vendor/comic-neue.woff2";
  const BUBBLE_FADE = 400;
  const BUBBLE_EDGE = 8;
  const bubbles = {shown: new Map(), frame: 0, font: null};

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

  function anchorOf(key) {
    const projected = g3.tab === "agents" ? anchor3d(key)() : null;
    if (projected && inView(projected)) {
      return projected;
    }
    return [...document.querySelectorAll(`[data-face="${CSS.escape(key)}"]`)].map((node) => node.getBoundingClientRect()).find(inView) || null;
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
    return item.started ? Bubbles.shown(saidOf(item).length, item.duration, (performance.now() - item.started) / 1000) : 0;
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
    Object.assign(view.node.dataset, {scale: String(entry.scale), state: item.started ? "speaking" : "waiting", words: String(count)});
    view.node.style.setProperty("--scale", String(entry.scale));
    placeBubble(view, anchorOf(entry.who), entry.scale);
  }

  function drawBubbles() {
    if (!settings.bubbles) {
      return;
    }
    const planned = Bubbles.plan(speech.current || speech.loading, speech.pending);
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
    for (const node of bubbleLayer().querySelectorAll(".speech-bubble")) {
      node.remove();
    }
  }

  function syncBubbles() {
    document.getElementById("bubbles-toggle").setAttribute("aria-pressed", String(settings.bubbles));
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
