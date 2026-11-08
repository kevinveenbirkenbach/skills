const Faces = (() => {
  "use strict";
  const SIZE = 40;
  const INK = "#2b2622";
  const dot = (cx, cy, rx, ry, fill) => ["ellipse", {cx, cy, rx, ry, fill}];
  const line = (d, width) => ["path", {d, fill: "none", stroke: INK, "stroke-width": width, "stroke-linecap": "round", "stroke-linejoin": "round"}];
  const blob = (d, fill) => ["path", {d, fill}];
  const sclera = (cx) => ["ellipse", {cx, cy: 20, rx: 3.2, ry: 3, fill: "#fff", stroke: INK, "stroke-width": 0.8}];
  const cheek = (cx) => ["ellipse", {cx, cy: 25, rx: 2.4, ry: 1.5, fill: "#f08a8a", opacity: 0.6}];
  const SHAPES = [
    ["ellipse", {cx: 20, cy: 22, rx: 13, ry: 13}],
    ["ellipse", {cx: 20, cy: 23, rx: 11, ry: 14}],
    ["rect", {x: 7, y: 9, width: 26, height: 26, rx: 8}],
    ["ellipse", {cx: 20, cy: 22, rx: 15, ry: 12}],
  ];
  const COLOURS = ["#f6d5b8", "#e3ac85", "#b97a55", "#7d4f33", "#f4cf5d", "#9fd4c7", "#c2b2f2"];
  const EYES = [
    [dot(15, 20, 1.8, 1.8, INK), dot(25, 20, 1.8, 1.8, INK)],
    [dot(15, 20, 1.4, 2.5, INK), dot(25, 20, 1.4, 2.5, INK)],
    [line("M12.5 21q2.5-3 5 0M22.5 21q2.5-3 5 0", 1.6)],
    [line("M12.5 20.5h5M22.5 20.5h5", 1.6)],
    [sclera(15), sclera(25), dot(15.6, 20.4, 1.4, 1.4, INK), dot(25.6, 20.4, 1.4, 1.4, INK)],
  ];
  const BROWS = [
    [],
    [line("M12 15.5h6M22 15.5h6", 1.4)],
    [line("M12 16q3-2.5 6 0M22 16q3-2.5 6 0", 1.4)],
    [line("M12 14.5l6 1.5M28 14.5l-6 1.5", 1.4)],
  ];
  const MOUTHS = [
    blob("M14 27q6 6 12 0z", INK),
    dot(20, 28, 2.2, 2, INK),
    blob("M13 26q7 7 14 0q-7 2-14 0z", INK),
    ["rect", {x: 15, y: 27.2, width: 10, height: 1.8, rx: 0.9, fill: INK}],
    blob("M15 28q5 3 10-2q-5 4.5-10 2z", INK),
  ];
  const HAIR = [
    [],
    [blob("M7 19q0-12 13-12t13 12q-5-6-13-6t-13 6z", "#3b2a20")],
    [blob("M9 15l2-8 3 5 3-7 3 6 3-6 3 7 3-5 2 8q-11-4-22 0z", "#d9a441")],
    [blob("M8 14q12-14 24 0z", "#3f6fb5"), ["rect", {x: 17, y: 12.5, width: 19, height: 2.6, rx: 1.3, fill: "#2f568f"}]],
    [blob("M8 13q12-17 24 0z", "#c0504d"), ["rect", {x: 7, y: 11.5, width: 26, height: 3, rx: 1.5, fill: "#9c3d3a"}], dot(20, 4.6, 2.6, 2.6, "#f1f1f1")],
    [dot(20, 6.5, 4.5, 4, "#6b3f2a"), blob("M8 18q1-11 12-11t12 11q-4-5-12-5t-12 5z", "#6b3f2a")],
  ];
  const EXTRAS = [
    [],
    [["path", {d: "M11 20a4 3.2 0 1 0 8 0a4 3.2 0 1 0-8 0M21 20a4 3.2 0 1 0 8 0a4 3.2 0 1 0-8 0M19 20h2", fill: "none", stroke: INK, "stroke-width": 1.1}]],
    [cheek(12.5), cheek(27.5)],
    [["rect", {x: 4.5, y: 18, width: 3.5, height: 8, rx: 1.75, fill: INK}], line("M6.5 25.5q1 5 7.5 4.5", 1.3)],
    [12.5, 14.5, 12, 27.5, 25.5, 28].map((cx, index) => dot(cx, 24 + (index % 3) * 1.1, 0.75, 0.75, "#8a5a3c")),
  ];
  const ATTRIBUTES = {shape: SHAPES, colour: COLOURS, eyes: EYES, brows: BROWS, mouth: MOUTHS, hair: HAIR, accessory: EXTRAS};
  const COUNTS = Object.fromEntries(Object.entries(ATTRIBUTES).map(([name, list]) => [name, list.length]));
  const COMBINATIONS = Object.values(COUNTS).reduce((product, count) => product * count, 1);

  function hash(text) {
    let value = 2166136261;
    for (const char of String(text)) {
      value = Math.imul(value ^ char.codePointAt(0), 16777619);
    }
    value = Math.imul(value ^ (value >>> 16), 0x85ebca6b);
    value = Math.imul(value ^ (value >>> 13), 0xc2b2ae35);
    return (value ^ (value >>> 16)) >>> 0;
  }

  /**
   * @param id - the agent's stable key: its session id, or name:<name> for an agent without a session.
   * @returns {pick, parts}: pick holds the variant index of every attribute in ATTRIBUTES order; parts lists the
   * [tag, attributes] SVG children of a 0 0 SIZE SIZE view box from back to front, the mouth carrying class "mouth".
   */
  function of(id) {
    let rest = hash(id);
    const pick = {};
    for (const [name, count] of Object.entries(COUNTS)) {
      pick[name] = rest % count;
      rest = Math.floor(rest / count);
    }
    const [tag, shape] = SHAPES[pick.shape];
    const [mouth, lips] = MOUTHS[pick.mouth];
    const parts = [
      [tag, {...shape, fill: COLOURS[pick.colour], stroke: INK, "stroke-width": 0.8, "stroke-opacity": 0.4}],
      ...HAIR[pick.hair],
      ...EYES[pick.eyes],
      ...BROWS[pick.brows],
      [mouth, {...lips, class: "mouth"}],
      ...EXTRAS[pick.accessory],
    ];
    return {pick, parts};
  }

  return {SIZE, COUNTS, COMBINATIONS, of};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Faces;
}
