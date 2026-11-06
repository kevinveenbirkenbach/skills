const SpaceScene = (() => {
  "use strict";
  const {LEVELS, clamp, turn, depthOf} = typeof SpaceView === "object" ? SpaceView : require("./space-view.js");
  const TONES = {direct: "direct", broadcast: "broadcast", mayday: "alarm", "pan-pan": "alarm", security: "security", grant: "grant", spawn: "spawn"};
  const RANKS = {alarm: 0, spawn: 1, security: 2, grant: 3, direct: 4, broadcast: 5};
  const MOON = 38;
  const MOON_SPREAD = 0.5;
  const TWIG = 30;
  const TWIG_SPREAD = 0.45;
  const ARC_CAP = 1500;

  function bend(from, to) {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const length = Math.hypot(dx, dy) || 1;
    return {x: ((from.x + to.x) / 2) * 0.82 - (dy / length) * 22, y: ((from.y + to.y) / 2) * 0.82 + (dx / length) * 22};
  }

  function satellite(base, index, count, reach, spread) {
    const angle = base.angle + (index - (count - 1) / 2) * spread;
    return {x: base.x + reach * Math.cos(angle), y: base.y + reach * Math.sin(angle), angle};
  }

  function moon(base, index, count) {
    return satellite(base, index, count, MOON, MOON_SPREAD);
  }

  function nameAt(timeline, ts) {
    const valid = timeline.filter((entry) => entry.since <= ts);
    return (valid.length ? valid[valid.length - 1] : timeline[0]).name;
  }

  function spotAt(track, id, ts) {
    let after = 0;
    while (after < track.length && track[after].ts < ts) {
      after += 1;
    }
    const late = track[Math.min(after, track.length - 1)].orbit[id];
    const early = track[Math.max(after - 1, 0)].orbit[id];
    if (!late || !early) {
      return late || early || null;
    }
    const span = after > 0 && after < track.length ? track[after].ts - track[after - 1].ts : 0;
    const share = span > 0 ? (ts - track[after - 1].ts) / span : 1;
    return {angle: turn(early.angle, late.angle, share), radius: early.radius + (late.radius - early.radius) * share};
  }

  function born(row) {
    return row.since === null ? row.started : row.since;
  }

  function tree(rows) {
    const order = [...rows].sort((a, b) => born(a) - born(b) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    const parents = {};
    order.forEach((row, index) => {
      const elders = order.slice(0, index).filter((other) => other.depth === row.depth - 1);
      const living = elders.filter((other) => other.until === null || other.until >= born(row));
      const chosen = (living.length ? living : elders).at(-1);
      parents[row.id] = row.depth > 1 && chosen ? chosen.id : "";
    });
    return {order, parents};
  }

  function capArcs(arcs, cap) {
    if (arcs.length <= cap) {
      return {kept: arcs, dropped: 0};
    }
    const ranks = arcs.map((arc) => (Object.hasOwn(RANKS, arc.tone) ? RANKS[arc.tone] : RANKS.direct));
    const order = arcs.map((arc, index) => index).sort((a, b) => ranks[a] - ranks[b] || arcs[b].ts - arcs[a].ts || a - b);
    const chosen = order.slice(0, cap).sort((a, b) => a - b);
    return {kept: chosen.map((index) => arcs[index]), dropped: arcs.length - cap};
  }

  function scene(input) {
    const {axis, range, span, cursor, nodes, track, now, lives, subagents, radio, grants, chair, cap} = input;
    const floor = span[0];
    const top = Math.max(Math.min(cursor, span[1]), floor);
    const last = track.length ? track[track.length - 1].ts : -Infinity;
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const moons = new Map();
    for (const node of nodes.filter((entry) => entry.kind === "subagent")) {
      moons.set(node.parent, [...(moons.get(node.parent) || []), node]);
    }
    const lines = [];
    const labels = [];
    const arcs = [];
    const point = (spot, ts, level) => ({x: spot.x, y: spot.y, z: depthOf(axis, {ts, level}, range), ts});
    const headed = (spot) => ({x: spot.x, y: spot.y, angle: spot.x === 0 && spot.y === 0 ? -Math.PI / 2 : Math.atan2(spot.y, spot.x)});
    const stamps = (start, end) => (axis === "time" && start < end ? [start, ...track.map((sample) => sample.ts).filter((ts) => ts > start && ts < end), end] : [end]);

    function anchor(id, ts) {
      const node = byId.get(id);
      if (!node || node.kind === "operator") {
        return {x: 0, y: 0};
      }
      if (node.kind === "subagent") {
        const family = moons.get(node.parent);
        return moon(headed(anchor(byId.has(node.parent) ? node.parent : chair, ts)), family.indexOf(node), family.length);
      }
      const spot = axis === "time" && ts < last ? spotAt(track, id, ts) : null;
      return spot ? {x: spot.radius * Math.cos(spot.angle), y: spot.radius * Math.sin(spot.angle)} : now[id] || {x: 0, y: 0};
    }

    function within(life) {
      const start = Math.max(floor, life && life[0] !== null ? life[0] : floor);
      const end = Math.min(top, life && life[1] !== null ? life[1] : top);
      return start <= end ? [start, end] : [floor, top];
    }

    function addLine(entry, place, start, end) {
      const points = stamps(start, end).map((ts) => point(place(ts), ts, entry.level));
      const index = lines.length;
      lines.push({...entry, points});
      if (entry.kind === "subagent" || (entry.kind === "twig" && !entry.alive)) {
        return;
      }
      const tail = points[points.length - 1];
      labels.push({line: index, at: tail, text: nameAt(entry.timeline, tail.ts)});
      if (axis !== "time") {
        return;
      }
      const head = points[0];
      const changes = entry.timeline.filter((change) => change.since > head.ts && change.since < tail.ts);
      for (const change of changes) {
        labels.push({line: index, at: point(place(change.since), change.since, entry.level), text: change.name});
      }
      if (changes.length) {
        labels.push({line: index, at: head, text: nameAt(entry.timeline, head.ts)});
      }
    }

    function connect(source, targets, tone, ts, row, count, kind) {
      const moment = axis === "time" ? ts : top;
      const from = point(anchor(source, moment), moment, 0);
      if (!targets.length) {
        arcs.push({kind: "broadcast", tone, ts, source, target: "*", sub: "", row, count, from, via: from, to: from});
        return;
      }
      for (const target of targets) {
        if (target !== source && byId.has(target)) {
          const to = point(anchor(target, moment), moment, 0);
          arcs.push({kind, tone, ts, source, target, sub: "", row, count, from, via: {...bend(from, to), z: from.z}, to});
        }
      }
    }

    for (const node of nodes) {
      const owner = node.kind === "subagent" ? node.parent : node.id;
      const [start, end] = within(lives[owner]);
      const timeline = node.timeline && node.timeline.length ? node.timeline : [{name: node.label, since: floor}];
      addLine({node: node.id, kind: node.kind, session: owner, sub: "", level: node.kind === "subagent" ? 1 : 0, timeline, title: node.label, alive: end >= top}, (ts) => anchor(node.id, ts), start, end);
    }
    for (const session of Object.keys(subagents).sort()) {
      if (!byId.has(session)) {
        continue;
      }
      const {order, parents} = tree(subagents[session]);
      const families = new Map();
      for (const row of order) {
        families.set(parents[row.id], [...(families.get(parents[row.id]) || []), row.id]);
      }
      const chains = new Map();
      for (const row of order) {
        const family = families.get(parents[row.id]);
        chains.set(row.id, [...(chains.get(parents[row.id]) || []), {index: family.indexOf(row.id), count: family.length}]);
      }
      const reach = (chain, ts) => chain.reduce((spot, link) => satellite(spot, link.index, link.count, TWIG, TWIG_SPREAD), headed(anchor(session, ts)));
      for (const row of order) {
        const since = born(row);
        if (since > top || (row.until !== null && row.until < floor)) {
          continue;
        }
        const chain = chains.get(row.id);
        const end = Math.min(top, row.until === null ? top : row.until);
        const alive = row.until === null || row.until >= top;
        const name = row.type || "Subagent";
        addLine({node: null, kind: "twig", session, sub: row.id, level: row.depth, timeline: [{name, since}], title: `${name}: ${row.description}`, alive}, (ts) => reach(chain, ts), Math.max(floor, since), end);
        if (axis !== "time" || since >= floor) {
          const moment = axis === "time" ? since : end;
          const from = point(reach(chain.slice(0, -1), moment), moment, row.depth - 1);
          const to = point(reach(chain, moment), moment, row.depth);
          arcs.push({kind: "spawn", tone: "spawn", ts: since, source: session, target: session, sub: row.id, row: -1, count: 1, from, via: {x: (from.x + to.x) / 2, y: (from.y + to.y) / 2, z: (from.z + to.z) / 2}, to});
        }
      }
    }
    const heard = radio.map((row, index) => ({row, index})).filter(({row}) => row.ts >= floor && row.ts <= top && byId.has(row.source));
    const granted = grants.map((grant, index) => ({grant, index})).filter(({grant}) => grant.ts >= floor && grant.ts <= top && byId.has(chair));
    if (axis === "time") {
      for (const {row, index} of heard) {
        connect(row.source, row.targets, TONES[row.class] || "direct", row.ts, index, 1, "message");
      }
      for (const {grant, index} of granted) {
        connect(chair, [grant.target], "grant", grant.ts, index, 1, "grant");
      }
    } else {
      const groups = new Map();
      const gather = (source, targets, tone, ts, kind) => {
        for (const target of targets.length ? targets : ["*"]) {
          const key = `${kind}\u0000${source}\u0000${target}\u0000${tone}`;
          const group = groups.get(key) || {source, target, tone, ts, kind, count: 0};
          group.count += 1;
          group.ts = Math.max(group.ts, ts);
          groups.set(key, group);
        }
      };
      for (const {row} of heard) {
        gather(row.source, row.targets, TONES[row.class] || "direct", row.ts, "message");
      }
      for (const {grant} of granted) {
        gather(chair, [grant.target], "grant", grant.ts, "grant");
      }
      for (const group of groups.values()) {
        connect(group.source, group.target === "*" ? [] : [group.target], group.tone, group.ts, -1, group.count, group.kind);
      }
    }
    const {kept, dropped} = capArcs(arcs, cap);
    const levels = [...new Set(lines.map((line) => clamp(line.level, 0, LEVELS)))].sort((a, b) => a - b);
    const guides = axis === "time" ? range.map((ts) => ({z: depthOf(axis, {ts, level: 0}, range), ts, level: 0})) : levels.map((level) => ({z: depthOf(axis, {ts: top, level}, range), ts: top, level}));
    const plane = axis === "time" ? {z: depthOf(axis, {ts: top, level: 0}, range), ts: top} : null;
    return {axis, range, span: [floor, top], lines, labels, arcs: kept, guides, plane, total: arcs.length, dropped};
  }

  return {TONES, ARC_CAP, bend, moon, nameAt, tree, capArcs, scene};
})();
if (typeof module === "object" && module.exports) {
  module.exports = SpaceScene;
}
