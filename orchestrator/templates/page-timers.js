  function startTimers() {
    const moving = () => relayout(MOVE);
    const liveSky = () => live() && drawSky();
    const whileShown = (task) => () => document.hidden || task();
    document.addEventListener("visibilitychange", () => document.hidden || [moving, syncRadio].forEach((task) => task()));
    window.setInterval(poll, 10000);
    window.setInterval(follow, 3000);
    whileShown(watchClosed)();
    window.setInterval(whileShown(watchClosed), CLOSED_POLL);
    window.setInterval(whileShown(moving), RELAYOUT);
    window.setInterval(whileShown(liveSky), 30000);
    window.setInterval(syncRadio, 20000);
    window.setInterval(whileShown(() => tree.dom && fetchTree()), 60000);
  }
