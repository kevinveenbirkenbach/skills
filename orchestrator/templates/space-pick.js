const SpacePick = (() => {
  "use strict";
  const {clamp, project} = typeof SpaceView === "object" ? SpaceView : require("./space-view.js");
  const {arcPoints} = typeof SpacePaint === "object" ? SpacePaint : require("./space-paint.js");
  const CURVE = 8;

  function gap(x, y, a, b) {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const length = dx * dx + dy * dy;
    const share = length ? clamp(((x - a.x) * dx + (y - a.y) * dy) / length, 0, 1) : 0;
    return Math.hypot(a.x + dx * share - x, a.y + dy * share - y);
  }

  function nearest(x, y, marks) {
    if (marks.some((mark) => mark === null)) {
      return {distance: Infinity, depth: Infinity};
    }
    if (marks.length === 1) {
      return {distance: Math.hypot(marks[0].x - x, marks[0].y - y), depth: marks[0].depth};
    }
    let best = {distance: Infinity, depth: Infinity};
    for (let index = 1; index < marks.length; index += 1) {
      const distance = gap(x, y, marks[index - 1], marks[index]);
      if (distance < best.distance) {
        best = {distance, depth: (marks[index - 1].depth + marks[index].depth) / 2};
      }
    }
    return best;
  }

  function curve(marks) {
    if (marks.some((mark) => mark === null)) {
      return marks;
    }
    const [a, b, c] = marks;
    return Array.from({length: CURVE + 1}, (_, index) => {
      const t = index / CURVE;
      const u = 1 - t;
      return {x: u * u * a.x + 2 * u * t * b.x + t * t * c.x, y: u * u * a.y + 2 * u * t * b.y + t * t * c.y, depth: u * u * a.depth + 2 * u * t * b.depth + t * t * c.depth};
    });
  }

  function pick(built, cam, x, y, reach) {
    let best = null;
    const consider = (found, hit) => {
      if (found.distance > reach) {
        return;
      }
      if (!best || found.distance < best.distance - 0.5 || (found.distance <= best.distance + 0.5 && found.depth < best.depth)) {
        best = {...hit, distance: found.distance, depth: found.depth};
      }
    };
    built.lines.forEach((line, index) => consider(nearest(x, y, line.points.map((entry) => project(cam, entry))), {kind: "line", index, line}));
    built.arcs.forEach((arc, index) => {
      const marks = arcPoints(arc).map((entry) => project(cam, entry));
      consider(nearest(x, y, arc.kind === "broadcast" ? [...marks, marks[0]] : curve(marks)), {kind: "arc", index, arc});
    });
    return best;
  }

  return {pick};
})();
if (typeof module === "object" && module.exports) {
  module.exports = SpacePick;
}
