const LegendChips = (() => {
  "use strict";
  const KEEP = 100;
  const MODES = {
    hidden: {pressed: (list, id) => !list.includes(id), words: ["shown, press to hide", "hidden, press to show"], group: "Series: press a chip to hide or show it"},
    shown: {pressed: (list, id) => list.includes(id), words: ["on, press to switch it off", "off, press to switch it on"], group: "Overlays: press a chip to switch it on or off"},
  };

  /**
   * @param list - the series ids the view-store key holds.
   * @param id - the series to place.
   * @param wanted - true when the list must hold id, false when it must not.
   * @returns the list holding id once, appended when missing, or the list without id.
   */
  function placed(list, id, wanted) {
    if (!wanted) {
      return list.filter((item) => item !== id);
    }
    return list.includes(id) ? list : [...list, id];
  }

  /**
   * @param list - the hidden series ids, oldest first.
   * @param present - the ids of the series whose chips the page shows now for the same view-store key.
   * @returns the list with its oldest ids of series no longer shown dropped until at most KEEP ids remain, or
   * until only shown ones are left.
   */
  function pruned(list, present) {
    let surplus = list.length - KEEP;
    return list.filter((item) => present.has(item) || surplus-- <= 0);
  }

  function shownChips(path) {
    return new Set([...document.querySelectorAll(".legend-chip")].filter((node) => node.getAttribute("data-path") === path).map((node) => node.getAttribute("data-chip")));
  }

  /**
   * @param series - [{id, label, tone}]: one chip per series; label is its text, tone the classes that colour its swatch.
   * @param path - the section.key of the view store that holds a list of series ids.
   * @param mode - "hidden" when the list names the series switched off (all on by default; old ids of series gone
   * from the page are pruned beyond KEEP), "shown" when it names the series switched on (all off by default).
   * @returns a group with one toggle button per series, pressed while the series is on; a press fixes at once
   * whether the list must hold its id, the opposite of what this page shows, and applies that through
   * ViewStore.update, so a retry on a list another browser changed keeps that choice; the caller redraws from
   * ViewStore.on.
   */
  function render(series, path, mode) {
    if (!Object.hasOwn(MODES, mode)) {
      throw new Error(`a legend chip mode must be hidden or shown, not ${mode}`);
    }
    const {pressed, words, group: label} = MODES[mode];
    const hint = (text, on) => `${text}: ${words[on ? 0 : 1]}`;
    const listed = ViewStore.get(path);
    const group = document.createElement("div");
    group.className = "legend-chips";
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", label);
    for (const entry of series) {
      const on = pressed(listed, entry.id);
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `legend-chip ${entry.tone}`.trim();
      chip.setAttribute("data-chip", entry.id);
      chip.setAttribute("data-path", path);
      chip.setAttribute("aria-pressed", String(on));
      chip.setAttribute("title", hint(entry.label, on));
      chip.textContent = entry.label;
      chip.addEventListener("click", () => {
        const present = shownChips(path);
        const wanted = !ViewStore.get(path).includes(entry.id);
        ViewStore.update(path, (list) => (mode === "hidden" ? pruned(placed(list, entry.id, wanted), present) : placed(list, entry.id, wanted)));
        const now = pressed(ViewStore.get(path), entry.id);
        chip.setAttribute("aria-pressed", String(now));
        chip.setAttribute("title", hint(entry.label, now));
      });
      group.append(chip);
    }
    return group;
  }

  return {KEEP, render, placed, pruned};
})();
if (typeof module === "object" && module.exports) {
  module.exports = LegendChips;
}
