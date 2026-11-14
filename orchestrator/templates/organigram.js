const Organigram = (() => {
  "use strict";
  const LINE_KINDS = ["line", "work"];
  const RANK = ["chair", "line", "work", "cluster", "other"];
  const SUPERIOR = ["A", "C"];
  const PRESIDENTS = {id: "group:work", kind: "work", label: "Presidents"};
  const BEND = 36;

  const byName = (a, b) => a.localeCompare(b, "en");
  const byOffice = (a, b) => byName(a.office, b.office);
  const rankOf = (claim) => (RANK.includes(claim.kind) ? RANK.indexOf(claim.kind) : RANK.length);
  const ranked = (a, b) => rankOf(a) - rankOf(b) || byOffice(a, b);

  /**
   * @param claim - a council claim with its kind: chair, line, work, cluster or other.
   * @returns "chair" for the chair; "line" for a domain chair (<dimension>/<line>) and a work/* president, both in line
   * under the chair; "staff" for a cluster/* organizer and every single-segment office, drawn beside the chair.
   */
  function position(claim) {
    if (claim.kind === "chair") {
      return "chair";
    }
    return LINE_KINDS.includes(claim.kind) ? "line" : "staff";
  }

  /**
   * @param claims - the council claims.
   * @returns {chair, staff, units}: chair the chair's claim or null; staff the staff positions, organizers before the
   * other offices, each by office; units the line units, one per dimension by name and then the presidents, each
   * {id, kind, label, positions} with its positions by office.
   */
  function chart(claims) {
    const lines = claims.filter((claim) => position(claim) === "line").sort(byOffice);
    const dimensions = [...new Set(lines.filter((claim) => claim.kind === "line").map((claim) => claim.dimension))].sort(byName);
    const units = dimensions.map((dimension) => ({id: `dimension:${dimension}`, kind: "dimension", label: dimension, positions: lines.filter((claim) => claim.kind === "line" && claim.dimension === dimension)}));
    const presidents = lines.filter((claim) => claim.kind === "work");
    return {
      chair: claims.find((claim) => claim.kind === "chair") || null,
      staff: claims.filter((claim) => position(claim) === "staff").sort(ranked),
      units: presidents.length ? [...units, {...PRESIDENTS, positions: presidents}] : units,
    };
  }

  function officesOf(claims) {
    const offices = new Map();
    for (const claim of claims.filter((entry) => entry.agent).sort(ranked)) {
      offices.set(claim.agent, [...(offices.get(claim.agent) || []), claim]);
    }
    return offices;
  }

  function doers(row, offices) {
    const responsible = Object.entries(row.roles).filter(([, letters]) => letters.includes("R")).map(([party]) => party);
    return [...new Set([...responsible, row.worker])].filter((name) => offices.has(name));
  }

  function superiors(row, agent, offices) {
    return Object.entries(row.roles)
      .map(([party, letters]) => ({party, letters: SUPERIOR.filter((letter) => letters.includes(letter)).join("")}))
      .filter(({party, letters}) => party !== agent && letters && offices.has(party))
      .map(({party, letters}) => ({office: offices.get(party)[0], letters}))
      .filter(({office}) => office.kind !== "chair");
  }

  function targets(row, own) {
    const named = own.filter((claim) => claim.office === row.task || claim.work === row.task);
    return named.length ? named : [own[0]];
  }

  function join(edges, from, to, letters, task) {
    const key = `${from.office}\n${to.office}`;
    const edge = edges.get(key) || {from: from.office, to: to.office, letters: "", tasks: []};
    edges.set(key, {...edge, letters: SUPERIOR.filter((letter) => edge.letters.includes(letter) || letters.includes(letter)).join(""), tasks: [...new Set([...edge.tasks, task])].sort(byName)});
  }

  /**
   * @param claims - the council claims, each with its holder as agent.
   * @param tasks - the register's task rows, each {task, ended, worker, roles: {party: letters}}.
   * @returns the dashed edges, one {from, to, letters, tasks} per pair of offices, by from then to: an open task whose R
   * (or worker) holds an office and that names another office holder A or C makes that holder's first office (chair,
   * domain chair, president, organizer, other office; then by name) an additional superior of the agent's office for
   * the task (the office or the claimed work named like the task, else the agent's first office). letters holds the A
   * and C of the pair, tasks its tasks by name. A superior holding the chair adds no edge: the solid line runs there.
   */
  function dotted(claims, tasks) {
    const offices = officesOf(claims);
    const edges = new Map();
    for (const row of tasks.filter((entry) => !entry.ended && entry.roles)) {
      for (const agent of doers(row, offices)) {
        for (const {office, letters} of superiors(row, agent, offices)) {
          targets(row, offices.get(agent)).forEach((to) => join(edges, office, to, letters, row.task));
        }
      }
    }
    return [...edges.values()].sort((a, b) => byName(a.from, b.from) || byName(a.to, b.to));
  }

  const round = (value) => Math.round(value * 10) / 10;
  const centerX = (box) => (box.left + box.right) / 2;
  const centerY = (box) => (box.top + box.bottom) / 2;
  const segment = (x1, y1, x2, y2) => `M ${round(x1)} ${round(y1)} L ${round(x2)} ${round(y2)}`;

  function elbow(from, to) {
    const middle = round((from.bottom + to.top) / 2);
    return `M ${round(centerX(from))} ${round(from.bottom)} V ${middle} H ${round(centerX(to))} V ${round(to.top)}`;
  }

  function stem(chair, staff, units) {
    if (!staff.length && !units.length) {
      return [];
    }
    const x = centerX(chair);
    const tops = units.map((unit) => unit.box.top);
    const bus = tops.length ? Math.min(...tops) - BEND / 2 : null;
    const lowest = Math.max(chair.bottom, ...staff.map(centerY), ...(bus === null ? [] : [bus]));
    const branches = staff.map((box) => segment(x, centerY(box), centerX(box) < x ? box.right : box.left, centerY(box)));
    const drops = units.map((unit) => segment(centerX(unit.box), bus, centerX(unit.box), unit.box.top));
    const rail = units.length ? [segment(Math.min(...units.map((unit) => centerX(unit.box)), x), bus, Math.max(...units.map((unit) => centerX(unit.box)), x), bus)] : [];
    return [segment(x, chair.bottom, x, lowest), ...branches, ...rail, ...drops];
  }

  function comb(unit) {
    if (!unit.positions.length) {
      return [];
    }
    const x = unit.box.left + BEND / 2;
    const last = centerY(unit.positions[unit.positions.length - 1]);
    return [segment(x, unit.box.bottom, x, last), ...unit.positions.map((box) => segment(x, centerY(box), box.left, centerY(box)))];
  }

  /**
   * @param boxes - the drawn boxes as {left, top, right, bottom} in chart coordinates, folded ones left out:
   * {root, chair, staff: [box], units: [{box, positions: [box]}]}; root and chair may be null.
   * @returns the path data of the solid lines: root to chair, the chair's stem with its staff branches, the rail and
   * drops to the units, and each unit's comb to its positions.
   */
  function solid(boxes) {
    const top = boxes.root && boxes.chair ? [elbow(boxes.root, boxes.chair)] : [];
    const below = boxes.chair ? stem(boxes.chair, boxes.staff, boxes.units) : [];
    return [...top, ...below, ...boxes.units.flatMap(comb)];
  }

  function anchors(from, to) {
    if (from.left < to.right && to.left < from.right) {
      const side = Math.max(from.right, to.right) + BEND;
      return [[from.right, centerY(from)], [side, centerY(from)], [side, centerY(to)], [to.right, centerY(to)]];
    }
    if (to.top >= from.bottom || to.bottom <= from.top) {
      const [a, b] = to.top >= from.bottom ? [from.bottom, to.top] : [from.top, to.bottom];
      const middle = (a + b) / 2;
      return [[centerX(from), a], [centerX(from), middle], [centerX(to), middle], [centerX(to), b]];
    }
    const [a, b] = centerX(to) > centerX(from) ? [from.right, to.left] : [from.left, to.right];
    const middle = (a + b) / 2;
    return [[a, centerY(from)], [middle, centerY(from)], [middle, centerY(to)], [b, centerY(to)]];
  }

  /**
   * @param from - the superior's box as {left, top, right, bottom}.
   * @param to - the subordinate's box.
   * @returns the path data of a curve from the superior's box to the subordinate's: around the right side when the two
   * share a column, else from the facing edges.
   */
  function dashed(from, to) {
    const [start, one, two, end] = anchors(from, to).map((point) => point.map(round).join(" "));
    return `M ${start} C ${one} ${two} ${end}`;
  }

  return {position, chart, dotted, solid, dashed};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Organigram;
}
