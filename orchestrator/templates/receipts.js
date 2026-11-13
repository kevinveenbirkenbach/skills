const Receipts = (() => {
  "use strict";
  const SHOWN = 8;

  /**
   * @param {object} row a radio row of the state or the ref of a radio entry of the Stream, with readers and acks.
   * @returns {object} shown and hidden: every reader with acked true where its receipt exists, the first SHOWN as avatars and the rest behind "+N".
   */
  function strip(row) {
    const acks = new Set(Array.isArray(row.acks) ? row.acks : []);
    const readers = (Array.isArray(row.readers) ? row.readers : []).map((reader) => ({...reader, acked: acks.has(reader.session)}));
    return {shown: readers.slice(0, SHOWN), hidden: readers.slice(SHOWN)};
  }

  /**
   * @param {object} reader an entry of strip().
   * @param {function(number): string} format renders a read time.
   * @returns {string} the reader's name, its read time where the hub knows one, prefixed "about" where only a sighting gives it, and whether it acknowledged.
   */
  function label(reader, format) {
    const known = reader.read !== null && reader.read !== undefined;
    const read = known ? `read ${reader.approximate ? "about " : ""}${format(reader.read)}` : "read";
    return [reader.name, read, reader.acked ? "acknowledged" : ""].filter(Boolean).join(" · ");
  }

  /**
   * @param {object} entry a Stream entry.
   * @returns {string} its headline; a radio entry whose sender the route already shows names only the recipients.
   */
  function headline(entry) {
    if (entry.kind !== "radio" || !entry.agent) {
      return entry.title;
    }
    return `→ ${entry.ref.to.length ? entry.ref.to.join(", ") : "all"}`;
  }

  /**
   * @param {Array<object>} rows radio rows of the state.
   * @returns {string} changes whenever a reader, its read time or an ack of any row does, so a log that redraws only on change shows them on the next poll.
   */
  function signature(rows) {
    const read = (reader) => `${reader.session}@${reader.read ?? ""}${reader.approximate ? "~" : ""}`;
    return rows.map((row) => `${(row.readers || []).map(read).join(",")}/${(row.acks || []).join(",")}`).join("|");
  }

  return {SHOWN, strip, label, headline, signature};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Receipts;
}
