const Diffs = (() => {
  "use strict";
  const COLLAPSE = 400;
  const QUOTE_LIMIT = 2000;
  const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;
  const KINDS = {"+": "add", "-": "del", " ": "ctx"};

  function rows(patch) {
    const found = [];
    let [old, now] = [0, 0];
    String(patch).split("\n").forEach((text, index) => {
      const line = index + 1;
      const hunk = HUNK.exec(text);
      if (hunk) {
        [old, now] = [Number(hunk[1]), Number(hunk[2])];
        found.push({kind: "hunk", line, old: "", new: "", text});
        return;
      }
      const kind = KINDS[text[0]];
      if (!kind) {
        return;
      }
      const row = {kind, line, old: kind === "add" ? "" : old, new: kind === "del" ? "" : now, text: text.slice(1)};
      old += kind === "add" ? 0 : 1;
      now += kind === "del" ? 0 : 1;
      found.push(row);
    });
    return found;
  }

  const collapsed = (file) => file.additions + file.deletions > COLLAPSE;

  function span(numbers) {
    const known = numbers.filter((value) => Number.isInteger(value) && value > 0);
    return known.length ? [Math.min(...known), Math.max(...known)] : null;
  }

  function lineSpan(text, quote) {
    const full = String(text);
    const at = full.indexOf(quote);
    if (!quote || at < 0) {
      return [1, full.split("\n").length];
    }
    const from = full.slice(0, at).split("\n").length;
    return [from, from + quote.split("\n").length - 1];
  }

  function quoted(text) {
    const clean = String(text).trim();
    return clean.length > QUOTE_LIMIT ? `${clean.slice(0, QUOTE_LIMIT)}…` : clean;
  }

  const feedback = (ref, path, from, to, quote, words) => `Feedback on ${ref} ${path}:${from}-${to}: "${quoted(quote)}" ${String(words).trim()}`;
  const feedbackOf = (messages, ref) => messages.filter((message) => String(message.text).startsWith(`Feedback on ${ref} `));

  return {COLLAPSE, QUOTE_LIMIT, rows, collapsed, span, lineSpan, quoted, feedback, feedbackOf};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Diffs;
}
