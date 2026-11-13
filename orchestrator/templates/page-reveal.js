  const UNSEEN = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}\p{Zs}\p{Default_Ignorable_Code_Point}]/gu;
  const EMOJI_BASES = new Set(JSON.parse(document.getElementById("emoji-bases").textContent));
  const PRESENTATION = new Set([0xFE0E, 0xFE0F]);

  /**
   * @param {string} text the text a match sits in.
   * @param {number} offset the UTF-16 index of the match.
   * @returns {number} the code point right before offset, NaN at the start.
   */
  const codePointBefore = (text, offset) => {
    const pair = offset > 1 ? text.codePointAt(offset - 2) : 0;
    return pair > 0xFFFF ? pair : text.charCodeAt(offset - 1);
  };

  /**
   * @param {string} text a text a passkey prompt, a signed-item preview or an inbox diff shows.
   * @returns {string} the text with every control, format, line or paragraph separator, space separator but the space and default-ignorable character but the tab shown as ⟨U+XXXX⟩, the set signing.unseen() refuses, except a variation selector right after a code point of EMOJI_BASES, the pair signing.presented() accepts, so no text hides, reorders or splits what the passkey signs.
   */
  const revealed = (text) => String(text).replace(UNSEEN, (char, offset, whole) => (char === "\t" || char === " " || (PRESENTATION.has(char.codePointAt(0)) && EMOJI_BASES.has(codePointBefore(whole, offset))) ? char : `⟨U+${char.codePointAt(0).toString(16).toUpperCase().padStart(4, "0")}⟩`));

  /**
   * @param {string} text a text of several lines a signed-item preview shows.
   * @returns {string} each line through revealed(), joined by real line breaks.
   */
  const revealedLines = (text) => String(text).split("\n").map(revealed).join("\n");
