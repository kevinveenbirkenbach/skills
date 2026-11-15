const Morse = (() => {
  "use strict";
  const CODES = {
    a: ".-", b: "-...", c: "-.-.", d: "-..", e: ".", f: "..-.", g: "--.", h: "....", i: "..", j: ".---", k: "-.-", l: ".-..", m: "--",
    n: "-.", o: "---", p: ".--.", q: "--.-", r: ".-.", s: "...", t: "-", u: "..-", v: "...-", w: ".--", x: "-..-", y: "-.--", z: "--..",
    0: "-----", 1: ".----", 2: "..---", 3: "...--", 4: "....-", 5: ".....", 6: "-....", 7: "--...", 8: "---..", 9: "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.", "!": "-.-.--", "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...",
    ":": "---...", ";": "-.-.-.", "=": "-...-", "+": ".-.-.", "-": "-....-", _: "..--.-", "\"": ".-..-.", $: "...-..-", "@": ".--.-.",
    ä: ".-.-", æ: ".-.-", à: ".--.-", å: ".--.-", ç: "-.-..", è: ".-..-", é: "..-..", ñ: "--.--", ö: "---.", ø: "---.", ü: "..--", ß: "...--..",
  };
  const UNITS = {dot: 1, dash: 3, inner: 1, letter: 3, word: 7};
  const PARIS = 50;
  const MINUTE = 60000;
  const SPEED = {min: 5, max: 40, step: 1};

  function codeOf(char) {
    const folded = char.toLowerCase();
    const base = folded.normalize("NFD").charAt(0);
    if (Object.hasOwn(CODES, folded)) {
      return CODES[folded];
    }
    return Object.hasOwn(CODES, base) ? CODES[base] : "";
  }

  /**
   * @param {string} text clear text.
   * @returns {Array<Array<string>>} its words, each the codes of its letters, case-folded; a letter with an accent and no code of its own keys its base letter, any other character without a code is skipped and a word left without one is dropped.
   */
  function words(text) {
    return String(text).normalize("NFC").split(/\s+/).map((word) => [...word].map(codeOf).filter(Boolean)).filter((codes) => codes.length);
  }

  /**
   * @param {string} text a prosign such as SOS.
   * @returns {Array<Array<string>>} one word holding one sign: the codes of its letters keyed without the gap between letters; none for a text without a code.
   */
  function joined(text) {
    const sign = words(text).flat().join("");
    return sign ? [[sign]] : [];
  }

  /**
   * @param {number} wpm the speed in words per minute.
   * @returns {number} the length of one dot in ms after PARIS: a word is 50 dot units.
   */
  function dot(wpm) {
    return MINUTE / (PARIS * wpm);
  }

  function letterUnits(code, at, tones) {
    let end = at;
    [...code].forEach((mark, index) => {
      const length = mark === "-" ? UNITS.dash : UNITS.dot;
      tones.push([end, length]);
      end += length + (index < code.length - 1 ? UNITS.inner : 0);
    });
    return end;
  }

  /**
   * @param {Array<Array<string>>} signs words of letter codes, as words and joined give them.
   * @param {number} wpm the speed in words per minute.
   * @returns {{tones: Array<Array<number>>, ms: number}} every tone as [start, length] in ms and the whole length in ms, each word closed by the gap between words as PARIS counts it.
   */
  function timeline(signs, wpm) {
    const tones = [];
    let at = 0;
    for (const word of signs) {
      word.forEach((code, letter) => {
        at = letterUnits(code, at, tones) + (letter < word.length - 1 ? UNITS.letter : 0);
      });
      at += UNITS.word;
    }
    const unit = dot(wpm);
    return {tones: tones.map(([start, length]) => [start * unit, length * unit]), ms: at * unit};
  }

  /**
   * @param {number} wpm the speed in words per minute.
   * @returns {string} the speed as the radio shows it, with the dot units per minute after PARIS.
   */
  function rate(wpm) {
    return `${wpm} WPM (${wpm * PARIS} dots/min)`;
  }

  return {SPEED, CODES, words, joined, dot, timeline, rate};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Morse;
}
