const Ambience = (() => {
  "use strict";
  const RAD = Math.PI / 180;
  const DAY_MS = 86400000;
  const J2000 = 2451545;
  const AU = 149597870.7;
  const EARTH = 6378.14;
  const GLASS = 0.8;
  const CARD = 0.92;
  const LIGHT_FROM = 4;
  const SKY = [
    [-90, "#03050b", "#070a14"],
    [-18, "#04060e", "#0a0f1f"],
    [-12, "#080d1f", "#18203d"],
    [-6, "#111c3d", "#3b3763"],
    [-3, "#1c2b5a", "#8a5b6c"],
    [0, "#2b4377", "#de8a5e"],
    [3, "#44679f", "#efab6d"],
    [6, "#5884bf", "#f1c690"],
    [12, "#5d92d0", "#c8dbee"],
    [30, "#4e89d5", "#b4d2f1"],
    [90, "#3f7fd8", "#a9cbef"],
  ];
  const STAGES = [[-18, "night"], [-12, "astronomical"], [-6, "nautical"], [0, "civil"], [6, "golden"], [Infinity, "day"]];
  const THEMES = {
    light: {
      bg: "#eef2f7", panel: "#ffffff", sunken: "#f2f4f8", hover: "#eaeef5", text: "#121821", muted: "#434e5f", faint: "#6b7586",
      line: "#dde3eb", "line-strong": "#c7cfda", accent: "#2f55d4", "accent-soft": "#e6ecfd", "on-accent": "#ffffff",
      ok: "#16804a", "ok-soft": "#e3f3ea", bad: "#c2352a", "bad-soft": "#fcebea", warn: "#8a5200", "warn-soft": "#fff1d9",
      info: "#2a5bd0", "info-soft": "#e7eefc", violet: "#6f3fc4", "violet-soft": "#f0e9fb", teal: "#0b7f78", "teal-soft": "#def2f0",
      "neutral-soft": "#eceff4", direct: "#3a6ff7", broadcast: "#12a39a", alarm: "#e0453a", security: "#8a4bd8", grant: "#2f9e58",
      "add-bg": "#e7f6ec", "add-text": "#14632f", "del-bg": "#fdeeed", "del-text": "#9b2219", "hunk-bg": "#edf1fd",
      shadow: "0 1px 2px rgb(15 23 42 / 6%), 0 4px 14px rgb(15 23 42 / 6%)", "shadow-lift": "0 12px 36px rgb(15 23 42 / 16%)",
    },
    dark: {
      bg: "#0b0f15", panel: "#121821", sunken: "#0e131a", hover: "#1a212b", text: "#e7ebf2", muted: "#a3adbb", faint: "#6f7988",
      line: "#252d38", "line-strong": "#343e4b", accent: "#8fadff", "accent-soft": "#1b2440", "on-accent": "#0b1020",
      ok: "#4cc47e", "ok-soft": "#12291c", bad: "#ff7b72", "bad-soft": "#341614", warn: "#f2b84b", "warn-soft": "#33260f",
      info: "#7da5ff", "info-soft": "#18233f", violet: "#b994ff", "violet-soft": "#251a3b", teal: "#43c9bf", "teal-soft": "#0f2a28",
      "neutral-soft": "#1d242e", direct: "#6f9bff", broadcast: "#3cc7bd", alarm: "#ff6b61", security: "#b58cff", grant: "#4cc97a",
      "add-bg": "#0f2a1a", "add-text": "#8fe0aa", "del-bg": "#33151a", "del-text": "#ffaaa3", "hunk-bg": "#18213a",
      shadow: "0 1px 2px rgb(0 0 0 / 40%), 0 6px 18px rgb(0 0 0 / 28%)", "shadow-lift": "0 16px 44px rgb(0 0 0 / 55%)",
    },
  };
  const sin = (deg) => Math.sin(deg * RAD);
  const cos = (deg) => Math.cos(deg * RAD);
  const tan = (deg) => Math.tan(deg * RAD);
  const clamp = (value, low, high) => Math.min(Math.max(value, low), high);
  const asin = (value) => Math.asin(clamp(value, -1, 1)) / RAD;
  const acos = (value) => Math.acos(clamp(value, -1, 1)) / RAD;
  const atan2 = (y, x) => Math.atan2(y, x) / RAD;
  const wrap = (deg) => ((deg % 360) + 360) % 360;

  function julian(ms) {
    return ms / DAY_MS + 2440587.5;
  }

  function centuries(ms) {
    return (julian(ms) - J2000) / 36525;
  }

  function sidereal(ms) {
    const days = julian(ms) - J2000;
    const t = days / 36525;
    return wrap(280.46061837 + 360.98564736629 * days + 0.000387933 * t * t - (t * t * t) / 38710000);
  }

  function obliquity(t) {
    const omega = 125.04 - 1934.136 * t;
    return 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60 + 0.00256 * cos(omega);
  }

  function equatorial(lambda, beta, eps) {
    return {
      ra: wrap(atan2(sin(lambda) * cos(eps) - tan(beta) * sin(eps), cos(lambda))),
      dec: asin(sin(beta) * cos(eps) + cos(beta) * sin(eps) * sin(lambda)),
    };
  }

  function horizontal(ha, dec, lat) {
    return {
      alt: asin(sin(lat) * sin(dec) + cos(lat) * cos(dec) * cos(ha)),
      az: wrap(atan2(sin(ha), cos(ha) * sin(lat) - tan(dec) * cos(lat)) + 180),
    };
  }

  function sun(ms, lat, lon) {
    const t = centuries(ms);
    const l0 = wrap(280.46646 + t * (36000.76983 + t * 0.0003032));
    const m = 357.52911 + t * (35999.05029 - 0.0001537 * t);
    const e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t);
    const center = sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t)) + sin(2 * m) * (0.019993 - 0.000101 * t) + sin(3 * m) * 0.000289;
    const lambda = wrap(l0 + center - 0.00569 - 0.00478 * sin(125.04 - 1934.136 * t));
    const eps = obliquity(t);
    const place = equatorial(lambda, 0, eps);
    const y = tan(eps / 2) ** 2;
    const eot = (4 * (y * sin(2 * l0) - 2 * e * sin(m) + 4 * e * y * sin(m) * cos(2 * l0) - 0.5 * y * y * sin(4 * l0) - 1.25 * e * e * sin(2 * m))) / RAD;
    const distance = (1.000001018 * (1 - e * e)) / (1 + e * cos(m + center));
    const minutes = (((ms % DAY_MS) + DAY_MS) % DAY_MS) / 60000;
    const ha = (minutes + eot + 4 * lon) / 4 - 180;
    return {...place, lambda, eot, distance, ha, ...horizontal(ha, place.dec, lat)};
  }

  function moon(ms, lat, lon) {
    const t = centuries(ms);
    const anomaly = 134.9 + 477198.85 * t;
    const lambda = wrap(218.32 + 481267.881 * t + 6.29 * sin(anomaly) - 1.27 * sin(259.2 - 413335.38 * t) + 0.66 * sin(235.7 + 890534.23 * t)
      + 0.21 * sin(269.9 + 954397.7 * t) - 0.19 * sin(357.5 + 35999.05 * t) - 0.11 * sin(186.6 + 966404.05 * t));
    const beta = 5.13 * sin(93.3 + 483202.03 * t) + 0.28 * sin(228.2 + 960400.87 * t) - 0.28 * sin(318.3 + 6003.18 * t) - 0.17 * sin(217.6 - 407332.2 * t);
    const parallax = 0.9508 + 0.0518 * cos(anomaly) + 0.0095 * cos(259.2 - 413335.38 * t) + 0.0078 * cos(235.7 + 890534.23 * t) + 0.0028 * cos(269.9 + 954397.7 * t);
    const place = equatorial(lambda, beta, obliquity(t));
    const distance = EARTH / sin(parallax);
    const ha = sidereal(ms) + lon - place.ra;
    const seen = horizontal(ha, place.dec, lat);
    const light = sun(ms, lat, lon);
    const dra = light.ra - place.ra;
    const elongation = acos(sin(light.dec) * sin(place.dec) + cos(light.dec) * cos(place.dec) * cos(dra));
    const phase = atan2(light.distance * AU * sin(elongation), distance - light.distance * AU * cos(elongation));
    const limb = wrap(atan2(cos(light.dec) * sin(dra), sin(light.dec) * cos(place.dec) - cos(light.dec) * sin(place.dec) * cos(dra)));
    const parallactic = atan2(sin(ha), tan(lat) * cos(place.dec) - sin(place.dec) * cos(ha));
    return {
      ...place, lambda, beta, distance, phase, limb,
      alt: seen.alt - parallax * cos(seen.alt),
      az: seen.az,
      lit: (1 + cos(phase)) / 2,
      tilt: wrap(limb - parallactic),
      waxing: wrap(lambda - light.lambda) < 180,
    };
  }

  function hex(text) {
    return [1, 3, 5].map((index) => parseInt(text.slice(index, index + 2), 16));
  }

  function mix(from, to, share) {
    return from.map((value, index) => value + (to[index] - value) * share);
  }

  function css(rgb) {
    return `rgb(${rgb.map((value) => Math.round(value)).join(" ")})`;
  }

  function luminance(rgb) {
    const [r, g, b] = rgb.map((value) => {
      const channel = value / 255;
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  function contrast(first, second) {
    const [high, low] = [luminance(first), luminance(second)].sort((a, b) => b - a);
    return (high + 0.05) / (low + 0.05);
  }

  function skyAt(alt) {
    const level = clamp(alt, SKY[0][0], SKY[SKY.length - 1][0]);
    const index = Math.max(SKY.findIndex(([edge]) => edge >= level), 1);
    const [low, lowTop, lowBottom] = SKY[index - 1];
    const [high, highTop, highBottom] = SKY[index];
    const share = (level - low) / (high - low);
    return {top: mix(hex(lowTop), hex(highTop), share), bottom: mix(hex(lowBottom), hex(highBottom), share)};
  }

  function stage(alt) {
    return STAGES.find(([edge]) => alt < edge)[1];
  }

  function starlight(alt) {
    return clamp((-alt - 6) / 10, 0, 1);
  }

  function modeAt(alt) {
    return alt >= LIGHT_FROM ? "light" : "dark";
  }

  function modeOf(top, bottom) {
    return luminance(mix(hex(top), hex(bottom), 0.5)) > 0.2 ? "light" : "dark";
  }

  function stars(count, seed) {
    let state = seed >>> 0;
    const next = () => {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
      return state / 4294967296;
    };
    return Array.from({length: count}, () => ({ra: next() * 360, dec: asin(next() * 2 - 1), glow: next() ** 2}));
  }

  function minutesOf(text) {
    const [hours, minutes] = text.split(":").map(Number);
    return hours * 60 + minutes;
  }

  function slotOf(date) {
    return {day: (date.getDay() + 6) % 7, minute: date.getHours() * 60 + date.getMinutes()};
  }

  function covers(stream, slot) {
    const start = minutesOf(stream.from);
    const end = minutesOf(stream.to);
    if (start < end) {
      return stream.days.includes(slot.day) && slot.minute >= start && slot.minute < end;
    }
    return (stream.days.includes(slot.day) && slot.minute >= start) || (stream.days.includes((slot.day + 6) % 7) && slot.minute < end);
  }

  function activeStream(streams, slot) {
    return streams.find((stream) => stream.on && covers(stream, slot)) || null;
  }

  return {GLASS, CARD, SKY, THEMES, julian, sidereal, horizontal, sun, moon, hex, mix, css, luminance, contrast, skyAt, stage, starlight, modeAt, modeOf, stars, slotOf, activeStream};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Ambience;
}
