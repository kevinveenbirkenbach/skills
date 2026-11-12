const Resources = (() => {
  "use strict";
  const IDLE = 30;
  const SATURATED = 90;
  const CALM = 50;
  const GAP = 1800;
  const STEP = 60;
  const COUNTS = ["input", "output", "cache_read", "cache_write"];
  const ZONES = [{kind: "idle", from: 0, to: IDLE}, {kind: "saturated", from: SATURATED, to: 100}];
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const share = (part, whole) => (finite(part) && finite(whole) && whole > 0 ? Math.round((1000 * part) / whole) / 10 : null);
  const listOf = (row, key) => (Array.isArray(row[key]) ? row[key].filter((item) => item && typeof item === "object") : []);
  const timed = (samples) => samples.filter((row) => row && finite(row.t));

  function series(samples, pick) {
    const found = new Map();
    for (const row of timed(samples)) {
      for (const [name, kind, value] of pick(row)) {
        const key = `${kind}\u0000${name}`;
        if (!found.has(key)) {
          found.set(key, {name: String(name), kind, points: []});
        }
        found.get(key).points.push([row.t, finite(value) ? value : null]);
      }
    }
    return [...found.values()];
  }

  function lines(samples) {
    return {
      disks: series(samples, (row) => listOf(row, "disks").map((disk) => [disk.mount, "disk", share(disk.used, disk.total)])),
      host: series(samples, (row) => [["CPU", "host", row.cpu], ["RAM", "host", row.ram], ["Swap", "host", row.swap]]),
      gpu: series(samples, (row) => listOf(row, "gpus").flatMap((gpu) => [[gpu.name, "util", gpu.asleep ? null : gpu.util], [gpu.name, "vram", gpu.asleep ? null : share(gpu.vram_used, gpu.vram_total)]])),
    };
  }

  function segments(points) {
    const found = [];
    let current = [];
    let last = null;
    for (const [t, value] of points) {
      if (current.length && (value === null || t - last > GAP)) {
        found.push(current);
        current = [];
      }
      if (value !== null) {
        current.push([t, value]);
      }
      last = t;
    }
    if (current.length) {
      found.push(current);
    }
    return found;
  }

  function spans(samples, test, value) {
    const rows = timed(samples);
    const found = [];
    let open = null;
    rows.forEach((row, index) => {
      if (open && index && row.t - rows[index - 1].t > GAP) {
        found.push(open);
        open = null;
      }
      if (!test(row)) {
        if (open) {
          found.push(open);
        }
        open = null;
        return;
      }
      const next = rows[index + 1];
      const end = row.t + (next && next.t - row.t <= GAP ? next.t - row.t : STEP);
      const peak = value(row);
      open = open ? {from: open.from, to: end, peak: Math.max(open.peak, peak)} : {from: row.t, to: end, peak};
    });
    if (open) {
      found.push(open);
    }
    return found;
  }

  function waits(samples) {
    const waiting = (row) => (row.queue && finite(row.queue.waiting) ? row.queue.waiting : 0);
    return spans(samples, (row) => waiting(row) > 0 && finite(row.cpu) && finite(row.ram) && row.cpu < CALM && row.ram < CALM, waiting);
  }

  function gpuSpans(samples, test) {
    const names = [...new Set(timed(samples).flatMap((row) => listOf(row, "gpus").filter(test).map((gpu) => String(gpu.name))))];
    return names.map((name) => ({name, spans: spans(samples, (row) => listOf(row, "gpus").some((gpu) => String(gpu.name) === name && test(gpu)), () => 1)}));
  }

  const asleep = (samples) => gpuSpans(samples, (gpu) => gpu.asleep === true);
  const unknown = (samples) => gpuSpans(samples, (gpu) => gpu.asleep !== true && !finite(gpu.util) && !finite(gpu.vram_used));

  function stack(tokens) {
    const totals = new Map();
    const hours = new Map();
    for (const row of tokens) {
      if (!row || !finite(row.t) || typeof row.agent !== "string") {
        continue;
      }
      const counts = COUNTS.map((name) => (finite(row[name]) && row[name] > 0 ? row[name] : 0));
      const sum = counts.reduce((total, value) => total + value, 0);
      if (!totals.has(row.agent)) {
        totals.set(row.agent, 0);
      }
      totals.set(row.agent, totals.get(row.agent) + sum);
      if (!hours.has(row.t)) {
        hours.set(row.t, new Map());
      }
      const hour = hours.get(row.t);
      if (!hour.has(row.agent)) {
        hour.set(row.agent, {agent: row.agent, total: 0, models: [], ...Object.fromEntries(COUNTS.map((name) => [name, 0]))});
      }
      const entry = hour.get(row.agent);
      COUNTS.forEach((name, index) => {
        entry[name] += counts[index];
      });
      entry.total += sum;
      if (typeof row.model === "string" && !entry.models.includes(row.model)) {
        entry.models.push(row.model);
      }
    }
    const agents = [...totals].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([agent]) => agent);
    const bars = [...hours.keys()].sort((a, b) => a - b).map((t) => {
      let base = 0;
      const parts = agents.filter((agent) => hours.get(t).has(agent)).map((agent) => {
        const entry = hours.get(t).get(agent);
        const part = {...entry, from: base, to: base + entry.total};
        base += entry.total;
        return part;
      });
      return {t, total: base, parts};
    });
    return {agents, totals: Object.fromEntries(totals), bars, top: Math.max(0, ...bars.map((bar) => bar.total))};
  }

  return {IDLE, SATURATED, CALM, GAP, COUNTS, ZONES, lines, segments, spans, waits, asleep, unknown, stack};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Resources;
}
