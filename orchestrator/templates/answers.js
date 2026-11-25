const Answers = (() => {
  const plain = (option) => String(option.label).trim().toLowerCase();

  /**
   * @param item - an inbox item or Match card with kind, and for a choice its options and multi.
   * @returns {Object|null} {yes, no}: the labels of a single choice whose only options are Yes and No, else null.
   */
  function pair(item) {
    const options = item.options || [];
    if (item.multi || options.length !== 2) {
      return null;
    }
    const yes = options.find((option) => plain(option) === "yes");
    const no = options.find((option) => plain(option) === "no");
    return yes && no ? {yes: yes.label, no: no.label} : null;
  }

  /**
   * @param item - as pair() takes it.
   * @returns {boolean} whether Accept and Reject answer it without a numbered form: a permission ask or a Yes/No choice.
   */
  const boolean = (item) => item.kind === "ask" || pair(item) !== null;

  /**
   * @param no - the No label of the choice.
   * @param text - the typed comment, maybe empty or multi-line.
   * @param limit - the longest answer the hub takes.
   * @returns {string} No without a comment, else "No: comment" on one line as the Other answer, cut to limit; never an option label.
   */
  function declined(no, text, limit) {
    const line = text.replace(/\s+/g, " ").trim();
    return line ? `${no}: ${line}`.slice(0, limit).trim() : no;
  }

  return {pair, boolean, declined};
})();

if (typeof module === "object" && module.exports) {
  module.exports = Answers;
}
