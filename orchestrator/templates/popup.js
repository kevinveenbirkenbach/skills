const Popup = (() => {
  "use strict";
  const GAP = 16;
  const REACH = 40;
  const MIN = 160;
  const clamp = (value, low, high) => Math.max(low, Math.min(value, high));
  const fixed = (value) => Math.round(value * 10) / 10;

  function leader(anchor, box) {
    const cx = anchor.left + anchor.width / 2;
    const cy = anchor.top + anchor.height / 2;
    const x2 = clamp(cx, box.left, box.left + box.width);
    const y2 = clamp(cy, box.top, box.top + box.height);
    const dx = x2 - cx;
    const dy = y2 - cy;
    const share = Math.min(dx ? anchor.width / 2 / Math.abs(dx) : Infinity, dy ? anchor.height / 2 / Math.abs(dy) : Infinity);
    return share >= 1 ? null : {x1: fixed(cx + dx * share), y1: fixed(cy + dy * share), x2: fixed(x2), y2: fixed(y2)};
  }

  function vertical(anchor, size, view, left) {
    const below = view.height - GAP - (anchor.top + anchor.height + REACH);
    const above = anchor.top - REACH - GAP;
    const down = below >= size.height || (above < size.height && below >= above);
    const room = down ? below : above;
    if (room < Math.min(size.height, MIN)) {
      return {left, top: clamp(anchor.top + anchor.height + REACH, GAP, view.height - size.height - GAP), height: null};
    }
    const height = Math.min(size.height, room);
    return {left, top: down ? anchor.top + anchor.height + REACH : anchor.top - REACH - height, height: height < size.height ? height : null};
  }

  /**
   * @param anchor - the picked node's viewport box {left, top, width, height}, or null for a popup without a node.
   * @param size - the popup's natural {width, height}.
   * @param view - the viewport's {width, height}.
   * @returns {left, top, height, line}: the popup's corner right or left of the node, else below or above it with
   * height capping it to the room there (null: no cap), else below and clamped into the viewport; line {x1, y1, x2,
   * y2} runs from the node's edge to the nearest point of the popup, null without a node or when the popup covers it.
   */
  function place(anchor, size, view) {
    if (!anchor) {
      return {left: fixed(Math.max(GAP, (view.width - size.width) / 2)), top: fixed(Math.max(GAP, (view.height - size.height) / 2)), height: null, line: null};
    }
    const top = clamp(anchor.top + anchor.height / 2 - size.height / 2, GAP, view.height - size.height - GAP);
    const left = clamp(anchor.left + anchor.width / 2 - size.width / 2, GAP, view.width - size.width - GAP);
    const right = anchor.left + anchor.width + REACH;
    const before = anchor.left - REACH - size.width;
    const spot = right + size.width <= view.width - GAP ? {left: right, top, height: null} : before >= GAP ? {left: before, top, height: null} : vertical(anchor, size, view, left);
    const box = {left: spot.left, top: spot.top, width: size.width, height: spot.height === null ? size.height : spot.height};
    return {left: fixed(spot.left), top: fixed(spot.top), height: spot.height === null ? null : fixed(spot.height), line: leader(anchor, box)};
  }

  /**
   * @param nodes - {id, label} records.
   * @param query - the typed search text; blank finds nothing.
   * @param limit - the most hits returned.
   * @returns the first node of every distinct label containing the query, case-insensitive, labels starting with it
   * first, otherwise in node order.
   */
  function hits(nodes, query, limit) {
    const words = String(query).trim().toLowerCase();
    if (!words) {
      return [];
    }
    const found = new Map();
    for (const node of nodes) {
      const at = String(node.label).toLowerCase().indexOf(words);
      if (at >= 0 && !found.has(node.label)) {
        found.set(node.label, {node, first: at === 0});
      }
    }
    return [...found.values()].sort((a, b) => Number(b.first) - Number(a.first)).slice(0, limit).map((entry) => entry.node);
  }

  return {GAP, REACH, MIN, place, hits};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Popup;
}
