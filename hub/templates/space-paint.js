const SpacePaint = (() => {
  "use strict";
  const {clamp, project, depthSort} = typeof SpaceView === "object" ? SpaceView : require("./space-view.js");
  const LOOKS = {
    guide: ["line", 1, 1],
    "line:operator": ["accent", 2.4, 0.9],
    "line:chair": ["accent", 2, 0.85],
    "line:session": ["muted", 1.6, 0.8],
    "line:subagent": ["violet", 1.2, 0.75],
    "line:twig": ["violet", 1, 0.6],
    "line:selected": ["accent", 3.2, 1],
    "arc:direct": ["direct", 1.3, 0.6],
    "arc:broadcast": ["broadcast", 1.2, 0.55],
    "arc:alarm": ["alarm", 2, 0.9],
    "arc:security": ["security", 1.5, 0.75],
    "arc:grant": ["grant", 1.6, 0.75],
    "arc:spawn": ["violet", 1.4, 0.8],
  };
  const DISCS = {operator: 9, chair: 7, session: 5.5, subagent: 3.5, twig: 3};
  const RIM = 330;
  const HALO = 14;
  const SLICE = 25;
  const ROUND = 48;
  const MARGIN = 40;

  function ring(center, radius, count) {
    return Array.from({length: count}, (_, index) => {
      const angle = (2 * Math.PI * index) / count;
      return {x: center.x + radius * Math.cos(angle), y: center.y + radius * Math.sin(angle), z: center.z};
    });
  }

  function arcPoints(arc) {
    return arc.kind === "broadcast" ? ring(arc.from, HALO, 12) : [arc.from, arc.via, arc.to];
  }

  function visible(cam, marks) {
    let [left, right, upper, lower] = [Infinity, -Infinity, Infinity, -Infinity];
    for (const mark of marks) {
      if (mark === null) {
        return false;
      }
      left = Math.min(left, mark.x);
      right = Math.max(right, mark.x);
      upper = Math.min(upper, mark.y);
      lower = Math.max(lower, mark.y);
    }
    return right >= -MARGIN && left <= cam.width + MARGIN && lower >= -MARGIN && upper <= cam.height + MARGIN;
  }

  function mean(marks) {
    return marks.reduce((sum, mark) => sum + mark.depth, 0) / marks.length;
  }

  function pen(ctx, colors, look) {
    const [role, width, alpha] = LOOKS[look];
    ctx.strokeStyle = colors[role];
    ctx.lineWidth = width;
    ctx.globalAlpha = alpha;
  }

  function paint(ctx, built, cam, style) {
    const colors = style.colors;
    const stats = {items: 0, arcs: 0, culled: 0, batches: 0, labels: 0};
    const buckets = new Map(Object.keys(LOOKS).map((look) => [look, []]));
    const others = [];
    const marksOf = (points) => points.map((entry) => project(cam, entry));
    const stroke = (look, marks, type, closed) => {
      if (!visible(cam, marks)) {
        stats.culled += 1;
        return false;
      }
      buckets.get(look).push({type, look, marks, closed, depth: Math.round(mean(marks) / SLICE) * SLICE});
      return true;
    };
    const label = (at, text, tone, strong) => {
      const mark = project(cam, at);
      if (mark && visible(cam, [mark])) {
        others.push({type: "label", mark, text, tone, strong, depth: mark.depth - 1});
      }
    };
    for (const guide of built.guides) {
      const marks = marksOf(ring({x: 0, y: 0, z: guide.z}, RIM, ROUND));
      if (stroke("guide", marks, "path", true)) {
        label({x: 0, y: -RIM, z: guide.z}, built.axis === "time" ? style.format(guide.ts) : `${style.level} ${guide.level}`, "muted", false);
      }
    }
    if (built.plane) {
      const marks = marksOf(ring({x: 0, y: 0, z: built.plane.z}, RIM, ROUND));
      if (visible(cam, marks)) {
        others.push({type: "plane", marks, depth: mean(marks)});
        label({x: RIM * Math.SQRT1_2, y: -RIM * Math.SQRT1_2, z: built.plane.z}, `${style.cursor} ${style.format(built.plane.ts)}`, "accent", true);
      }
    }
    built.lines.forEach((line) => {
      const marks = marksOf(line.points);
      const look = line.node !== null && line.node === style.selected ? "line:selected" : `line:${line.kind}`;
      for (let index = 1; index < marks.length; index += 1) {
        stroke(look, [marks[index - 1], marks[index]], "path", false);
      }
      const tail = marks[marks.length - 1];
      if ((line.alive || built.axis !== "time") && tail && visible(cam, [tail])) {
        others.push({type: "disc", mark: tail, look, radius: DISCS[line.kind] * clamp(tail.size, 0.5, 2.5), dim: !line.alive, depth: tail.depth - 0.5});
      }
    });
    for (const arc of built.arcs) {
      if (stroke(`arc:${arc.tone}`, marksOf(arcPoints(arc)), arc.kind === "broadcast" ? "path" : "curve", arc.kind === "broadcast")) {
        stats.arcs += 1;
      }
    }
    for (const entry of built.labels) {
      label(entry.at, entry.text, "text", built.lines[entry.line].node !== null && built.lines[entry.line].node === style.selected);
    }
    const items = depthSort([...[...buckets.values()].flat(), ...others]);
    stats.items = items.length;
    ctx.clearRect(0, 0, cam.width, cam.height);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.textAlign = "center";
    let open = "";
    const flush = () => {
      if (open) {
        ctx.stroke();
        stats.batches += 1;
        open = "";
      }
    };
    for (const item of items) {
      const marks = item.marks;
      if (item.type === "path" || item.type === "curve") {
        if (item.look !== open) {
          flush();
          pen(ctx, colors, item.look);
          ctx.beginPath();
          open = item.look;
        }
        ctx.moveTo(marks[0].x, marks[0].y);
        if (item.type === "curve") {
          ctx.quadraticCurveTo(marks[1].x, marks[1].y, marks[2].x, marks[2].y);
        } else {
          for (let index = 1; index < marks.length; index += 1) {
            ctx.lineTo(marks[index].x, marks[index].y);
          }
          if (item.closed) {
            ctx.closePath();
          }
        }
        continue;
      }
      flush();
      if (item.type === "plane") {
        ctx.beginPath();
        marks.forEach((mark, index) => (index ? ctx.lineTo(mark.x, mark.y) : ctx.moveTo(mark.x, mark.y)));
        ctx.closePath();
        ctx.globalAlpha = 0.1;
        ctx.fillStyle = colors.accent;
        ctx.fill();
        ctx.globalAlpha = 0.55;
        ctx.strokeStyle = colors.accent;
        ctx.lineWidth = 1.2;
        ctx.stroke();
      } else if (item.type === "disc") {
        ctx.beginPath();
        ctx.arc(item.mark.x, item.mark.y, item.radius, 0, 2 * Math.PI);
        ctx.globalAlpha = item.dim ? 0.5 : 1;
        ctx.fillStyle = colors.panel;
        ctx.fill();
        pen(ctx, colors, item.look);
        ctx.globalAlpha = item.dim ? 0.5 : 1;
        ctx.stroke();
      } else {
        stats.labels += 1;
        ctx.globalAlpha = 1;
        ctx.font = item.strong ? style.strong : style.font;
        ctx.lineWidth = 4;
        ctx.strokeStyle = colors.panel;
        ctx.strokeText(item.text, item.mark.x, item.mark.y - 10);
        ctx.fillStyle = colors[item.tone];
        ctx.fillText(item.text, item.mark.x, item.mark.y - 10);
      }
    }
    flush();
    ctx.globalAlpha = 1;
    return stats;
  }

  return {arcPoints, paint};
})();
if (typeof module === "object" && module.exports) {
  module.exports = SpacePaint;
}
