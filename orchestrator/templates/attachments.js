const Attachments = (() => {
  "use strict";
  const MARK = "📎 ";
  const WARN = "⚠️ ";
  const BROWSER_PASTE = "image.png";
  const two = (number) => String(number).padStart(2, "0");

  const pathLine = (path) => `${MARK}${path}`;
  const placeholder = (name) => `${MARK}uploading ${name}…`;

  /**
   * @param {string} name the file name.
   * @param {string} reason why the upload failed, on one or more lines.
   * @returns {string} one line naming the file and the reason; it carries no path.
   */
  function failed(name, reason) {
    const said = String(reason).replace(/\s+/g, " ").trim().slice(0, 200);
    return `${WARN}${name}: ${said || "upload failed"}`;
  }

  /**
   * @param {Date} when the moment of the paste.
   * @returns {string} YYYYMMDD-HHMMSS in local time.
   */
  function stamp(when) {
    return `${when.getFullYear()}${two(when.getMonth() + 1)}${two(when.getDate())}-${two(when.getHours())}${two(when.getMinutes())}${two(when.getSeconds())}`;
  }

  /**
   * @param {File} file a file from the clipboard, read for its name and type.
   * @param {Date} when the moment of the paste.
   * @returns {string} the file's own name, or paste-<stamp>.<ext> for an image without one.
   */
  function pastedName(file, when) {
    // Trip-wire: Chromium and Firefox name every pasted screenshot "image.png", so that name counts as none.
    const own = file.name && file.name !== BROWSER_PASTE ? file.name : "";
    if (own) {
      return own;
    }
    const kind = String(file.type || "").split("/");
    const ext = kind[0] === "image" && /^[a-z0-9]+/.test(kind[1] || "") ? kind[1].match(/^[a-z0-9]+/)[0] : "png";
    return `paste-${stamp(when)}.${ext}`;
  }

  /**
   * @param {string} value the text of the field.
   * @param {number} start the start of its selection.
   * @param {number} end the end of its selection.
   * @param {string} line the line to insert in place of the selection.
   * @param {string} gap "\n" for a textarea, " " for a one-line field.
   * @returns {Object} {value, caret}: value with line as its own line (or word) at the selection, the caret right after it.
   */
  function placed(value, start, end, line, gap) {
    const before = value.slice(0, start);
    const after = value.slice(end);
    const lead = before && !before.endsWith(gap) ? gap : "";
    const tail = after && !after.startsWith(gap) ? gap : "";
    return {value: `${before}${lead}${line}${tail}${after}`, caret: before.length + lead.length + line.length};
  }

  /**
   * @param {string} value the text of the field.
   * @param {string} from the line to replace, such as a placeholder.
   * @param {string} to its replacement.
   * @param {number} caret the caret before the swap.
   * @returns {Object} {value, caret, found}: value with the first from replaced, the caret moved with the text after it.
   */
  function swapped(value, from, to, caret) {
    const at = value.indexOf(from);
    if (at < 0) {
      return {value, caret, found: false};
    }
    const moved = caret >= at + from.length ? caret + to.length - from.length : Math.min(caret, at + to.length);
    return {value: `${value.slice(0, at)}${to}${value.slice(at + from.length)}`, caret: moved, found: true};
  }

  /**
   * @param {string} value the text of a textarea.
   * @returns {string[]} the host path of every path line, in text order.
   */
  function paths(value) {
    return value.split("\n").filter((line) => line.startsWith(`${MARK}/`)).map((line) => line.slice(MARK.length));
  }

  /**
   * @param {string} value the text of a textarea.
   * @param {string} path the host path whose line goes.
   * @returns {string} value without the first line that is exactly the path line; other lines stay as they are.
   */
  function removed(value, path) {
    const lines = value.split("\n");
    const at = lines.indexOf(pathLine(path));
    return at < 0 ? value : [...lines.slice(0, at), ...lines.slice(at + 1)].join("\n");
  }

  const baseName = (path) => path.slice(path.lastIndexOf("/") + 1);
  const pictured = (type) => String(type || "").startsWith("image/");

  return {pathLine, placeholder, failed, stamp, pastedName, placed, swapped, paths, removed, baseName, pictured};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Attachments;
}
