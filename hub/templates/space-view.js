const SpaceView = (() => {
  "use strict";
  const RAD = Math.PI / 180;
  const DEFAULTS = {
    graph: {axis: "none", yaw: 30, pitch: 20, zoom: 1, pan_x: 0, pan_y: 0},
    sky: {azimuth: 180, altitude: 0, fov: 180},
  };
  const LIMITS = {
    graph: {yaw: [-180, 180], pitch: [-90, 90], zoom: [0.25, 4], pan_x: [-2000, 2000], pan_y: [-2000, 2000]},
    sky: {azimuth: [0, 360], altitude: [-30, 85], fov: [20, 240]},
  };
  const AXES = ["none", "time", "spawn"];
  const DEPTH = 600;
  const LEVELS = 4;
  const FRAME = 860;
  const DISTANCE = 1600;
  const NEAR = 120;
  const HORIZON = 0.86;
  const REACH = 0.94;
  const clamp = (value, low, high) => Math.min(Math.max(value, low), high);
  const signed = (deg) => ((((deg + 180) % 360) + 360) % 360) - 180;
  const around = (deg) => ((deg % 360) + 360) % 360;

  function ease(progress) {
    return progress < 0.5 ? 4 * progress ** 3 : 1 - (-2 * progress + 2) ** 3 / 2;
  }

  function turn(from, to, share) {
    const full = 2 * Math.PI;
    const delta = ((((to - from + Math.PI) % full) + full) % full) - Math.PI;
    return from + delta * share;
  }

  function rotation(yaw, pitch) {
    const [cy, sy, cp, sp] = [Math.cos(yaw * RAD), Math.sin(yaw * RAD), Math.cos(pitch * RAD), Math.sin(pitch * RAD)];
    return [cy, 0, sy, sp * sy, cp, -sp * cy, -cp * sy, sp, cp * cy];
  }

  function apply(matrix, point) {
    return {
      x: matrix[0] * point.x + matrix[1] * point.y + matrix[2] * point.z,
      y: matrix[3] * point.x + matrix[4] * point.y + matrix[5] * point.z,
      z: matrix[6] * point.x + matrix[7] * point.y + matrix[8] * point.z,
    };
  }

  function camera(view, width, height) {
    return {matrix: rotation(view.yaw, view.pitch), scale: (Math.min(width, height) / FRAME) * view.zoom, panX: view.pan_x, panY: view.pan_y, cx: width / 2, cy: height / 2, width, height};
  }

  function project(cam, point) {
    const turned = apply(cam.matrix, point);
    const reach = DISTANCE + turned.z;
    if (reach < NEAR) {
      return null;
    }
    const size = (cam.scale * DISTANCE) / reach;
    return {x: cam.cx + (turned.x + cam.panX) * size, y: cam.cy + (turned.y + cam.panY) * size, depth: turned.z, size};
  }

  function depthSort(items) {
    return [...items].sort((a, b) => b.depth - a.depth);
  }

  function depthOf(axis, sample, range) {
    if (axis === "time") {
      const [low, high] = range;
      const share = high > low ? clamp((sample.ts - low) / (high - low), 0, 1) : 1;
      return DEPTH * (0.5 - share);
    }
    if (axis === "spawn") {
      return -DEPTH / 2 + (DEPTH / LEVELS) * clamp(sample.level, 0, LEVELS);
    }
    return 0;
  }

  function clampView(kind, view) {
    const limits = LIMITS[kind];
    const wrapped = kind === "graph" ? {...view, yaw: signed(view.yaw)} : {...view, azimuth: around(view.azimuth)};
    return Object.fromEntries(Object.entries(wrapped).map(([key, value]) => [key, Object.hasOwn(limits, key) ? clamp(value, limits[key][0], limits[key][1]) : value]));
  }

  function tidy(view) {
    return Object.fromEntries(Object.entries(view).map(([key, value]) => [key, typeof value === "number" ? Math.round(value * 100) / 100 : value]));
  }

  function tween(kind, from, to, share) {
    const angle = kind === "graph" ? "yaw" : "azimuth";
    return Object.fromEntries(Object.entries(to).map(([key, value]) => {
      if (typeof value !== "number") {
        return [key, value];
      }
      if (key === angle) {
        return [key, turn(from[key] * RAD, value * RAD, share) / RAD];
      }
      return [key, from[key] + (value - from[key]) * share];
    }));
  }

  function lens(view, width, height) {
    return {matrix: rotation(-view.azimuth, -view.altitude), kx: width / view.fov, ky: ((REACH * HORIZON * height) / 90) * (180 / view.fov), cx: width / 2, cy: HORIZON * height, width, height, view};
  }

  function place(sight, alt, az) {
    const flat = Math.cos(alt * RAD);
    const turned = apply(sight.matrix, {x: Math.sin(az * RAD) * flat, y: -Math.sin(alt * RAD), z: Math.cos(az * RAD) * flat});
    const lon = Math.atan2(turned.x, turned.z) / RAD;
    const lat = Math.asin(clamp(-turned.y, -1, 1)) / RAD;
    return {x: sight.cx + sight.kx * lon, y: sight.cy - sight.ky * lat, lon, lat};
  }

  function horizon(sight, steps) {
    return Array.from({length: steps + 1}, (_, index) => place(sight, 0, sight.view.azimuth - 180 + (360 * index) / steps)).sort((a, b) => a.x - b.x);
  }

  function compass(azimuth) {
    return Math.round(around(azimuth) / 45) % 8;
  }

  return {
    DEFAULTS, LIMITS, AXES, DEPTH, LEVELS, REACH,
    clamp, ease, turn, rotation, apply, camera, project, depthSort, depthOf, clampView, tidy, tween, lens, place, horizon, compass,
  };
})();
if (typeof module === "object" && module.exports) {
  module.exports = SpaceView;
}
