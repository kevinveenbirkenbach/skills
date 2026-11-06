  function animate(duration, frame, done) {
    const began = performance.now();
    const run = (now) => {
      const progress = Math.min((now - began) / duration, 1);
      frame(progress);
      if (progress < 1) {
        window.requestAnimationFrame(run);
      } else {
        done();
      }
    };
    window.requestAnimationFrame(run);
  }

  function travel(layer, row, target) {
    const from = positions.get(row.source);
    const shade = tone(row.class);
    if (!layer.isConnected || !from) {
      return;
    }
    if (target === "*") {
      const ring = s("circle", {class: `pulse-ring t-${shade}`, cx: fixed(from.x), cy: fixed(from.y), r: 18});
      layer.append(ring);
      animate(1400, (t) => {
        ring.setAttribute("r", fixed(18 + 54 * t));
        ring.setAttribute("opacity", fixed(1 - t));
      }, () => ring.remove());
      return;
    }
    const to = positions.get(target);
    if (!to) {
      return;
    }
    const control = Space.bend(from, to);
    const dot = s("circle", {class: `pulse t-${shade}`, r: 5});
    layer.append(dot);
    animate(1200, (t) => {
      const u = 1 - t;
      dot.setAttribute("cx", fixed(u * u * from.x + 2 * u * t * control.x + t * t * to.x));
      dot.setAttribute("cy", fixed(u * u * from.y + 2 * u * t * control.y + t * t * to.y));
    }, () => dot.remove());
  }

  function pulses(rows) {
    if (calm.matches || ui.screen !== "graph" || ui.graph !== "orbit" || !live() || !graphDom || !graphDom.pulses) {
      return;
    }
    const layer = graphDom.pulses;
    rows.slice(-24).forEach((row, index) => {
      for (const target of row.targets.length ? row.targets : ["*"]) {
        window.setTimeout(() => travel(layer, row, target), index * 260);
      }
    });
  }
