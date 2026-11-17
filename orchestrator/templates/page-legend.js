  const LEGEND_PARTS = ".legend, .res-legend, .home-metric > .legend-chips";
  const LEGEND_PATHS = {view: "legend.views", tile: "legend.tiles"};
  const legendView = {buttons: new WeakMap()};

  const legendShown = (path, key) => ViewStore.get(path)[key] !== false;

  function legendToggle(path, key) {
    const show = !legendShown(path, key);
    ViewStore.update(path, (flags) => {
      const next = {...flags};
      delete next[key];
      return show ? next : {...next, [key]: false};
    });
  }

  function legendButton(path, key) {
    const button = iconBtn("bi-info-circle", "Legend", "btn small ghost legend-toggle", (event) => {
      event.stopPropagation();
      legendToggle(path, key);
    });
    button.dataset.legendKey = key;
    button.addEventListener("pointerdown", (event) => event.stopPropagation());
    return button;
  }

  function paintLegend(owner, button, shown) {
    const state = shown ? "shown" : "hidden";
    if (owner.dataset.legend !== state) {
      owner.dataset.legend = state;
    }
    if (button.getAttribute("aria-pressed") !== String(shown)) {
      button.setAttribute("aria-pressed", String(shown));
      button.title = `Legend: ${shown ? "shown, press to hide it" : "hidden, press to show it"}`;
    }
  }

  /**
   * @param owner - a panel of a view or a Home tile.
   * @param path - the view-store key of its kind, legend.views or legend.tiles.
   * @param key - its panel id or pin key there.
   * @param place - (button) => void putting the button in its spot, or null when the owner holds no legend.
   */
  function legendFor(owner, path, key, place) {
    const made = legendView.buttons.get(owner);
    if (!place) {
      if (made) {
        made.remove();
        legendView.buttons.delete(owner);
      }
      if (owner.dataset.legend) {
        delete owner.dataset.legend;
      }
      return;
    }
    const button = made && made.dataset.legendKey === key ? made : legendButton(path, key);
    legendView.buttons.set(owner, button);
    place(button);
    paintLegend(owner, button, legendShown(path, key));
  }

  const ownOf = (host, selector) => [...host.querySelectorAll(selector)].find((node) => node.closest(Panels.HOSTS) === host) || null;

  function markLegends() {
    for (const host of document.querySelectorAll("#main [data-panel]")) {
      if (host.closest(".home-tile")) {
        continue;
      }
      const star = ownOf(host, ".star");
      legendFor(host, LEGEND_PATHS.view, host.dataset.panel, star && ownOf(host, LEGEND_PARTS) ? (button) => star.nextElementSibling !== button && star.after(button) : null);
    }
    for (const tile of document.querySelectorAll(".home-tile[data-pin]")) {
      const open = tile.querySelector(".home-open");
      legendFor(tile, LEGEND_PATHS.tile, tile.dataset.pin, tile.querySelector(`.home-body :is(${LEGEND_PARTS})`) ? (button) => open.previousElementSibling !== button && open.before(button) : null);
    }
  }

  function legendBoot() {
    new MutationObserver(markLegends).observe(document.body, {childList: true, subtree: true});
    ViewStore.on("legend", () => {
      markLegends();
      drawHome();
      drawResources();
    });
    markLegends();
  }
