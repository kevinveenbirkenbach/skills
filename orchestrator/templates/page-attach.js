  const ATTACH_HINT = "Attach files: pick them here, paste a screenshot or drop files on the field; each lands as its path line at the cursor";
  const attachThumbs = new Map();
  const attachRows = new WeakMap();
  const attachWired = new WeakSet();

  const attachGap = (field) => (field.tagName === "TEXTAREA" ? "\n" : " ");
  const attachFiles = (transfer) => [...((transfer && transfer.files) || [])];
  const attachDrags = (event) => Boolean(event.dataTransfer && [...event.dataTransfer.types].includes("Files"));

  function attachSet(field, value, caret) {
    field.value = value;
    field.setSelectionRange(caret, caret);
    field.dispatchEvent(new Event("input", {bubbles: true}));
  }

  function attachPut(field, line) {
    const start = field.selectionStart ?? field.value.length;
    const next = Attachments.placed(field.value, start, field.selectionEnd ?? start, line, attachGap(field));
    attachSet(field, next.value, next.caret);
  }

  /**
   * @param {HTMLInputElement|HTMLTextAreaElement} field the field an upload started in.
   * @param {string} line the upload's placeholder.
   * @returns {HTMLInputElement|HTMLTextAreaElement} field, or after a redraw its rebuilt twin under the same aria-label that holds the placeholder now.
   */
  function attachHolder(field, line) {
    const key = micKey(field);
    if (field.isConnected || !key) {
      return field;
    }
    return [...document.querySelectorAll(Voice.FIELDS)].find((other) => micKey(other) === key && other.value.includes(line)) || field;
  }

  function attachSwap(field, from, to) {
    const holder = attachHolder(field, from);
    const next = Attachments.swapped(holder.value, from, to, holder.selectionEnd ?? holder.value.length);
    if (next.found) {
      attachSet(holder, next.value, next.caret);
    }
  }

  /**
   * @param {HTMLInputElement|HTMLTextAreaElement} field the field the path line lands in, at its cursor.
   * @param {File} file the pasted, dropped or picked file.
   * @param {boolean} pasted true for a file from the clipboard, which gets paste-<timestamp>.png when it has no name of its own.
   */
  async function attachUpload(field, file, pasted) {
    const name = pasted || !file.name ? Attachments.pastedName(file, new Date()) : file.name;
    const wait = Attachments.placeholder(name);
    attachPut(field, wait);
    const answer = file.size > UPLOAD_LIMIT ? null : await send(`/api/uploads?name=${encodeURIComponent(name)}`, file, "application/octet-stream");
    const path = answer && answer.ok && answer.data ? answer.data.path : "";
    if (path && Attachments.pictured(file.type)) {
      attachThumbs.set(path, URL.createObjectURL(file));
    }
    const reason = !answer ? `too large, at most ${UPLOAD_LIMIT / 1048576} MiB` : `upload failed, ${answer.status ? `${answer.status} ${answer.text}` : "hub unreachable"}`;
    attachSwap(field, wait, path ? Attachments.pathLine(path) : Attachments.failed(name, reason));
  }

  function attachDrop(field, path) {
    const thumb = attachThumbs.get(path);
    if (thumb) {
      URL.revokeObjectURL(thumb);
      attachThumbs.delete(path);
    }
    const value = Attachments.removed(field.value, path);
    attachSet(field, value, Math.min(field.selectionEnd ?? value.length, value.length));
    field.focus();
  }

  function attachChip(field, path) {
    const name = Attachments.baseName(path);
    const thumb = attachThumbs.get(path);
    return h("span", {class: "mic-chip", role: "listitem", title: path, "data-path": path},
      thumb ? h("img", {class: "mic-chip-thumb", src: thumb, alt: ""}) : icon("bi-file-earmark"),
      h("span", {class: "mic-chip-name"}, name),
      h("button", {type: "button", class: "mic-chip-drop", ...named(`Remove ${name}`, `Remove ${name}: the chip and its line`), on: {click: () => attachDrop(field, path)}}, "✕"));
  }

  function attachDraw(field) {
    const row = attachRows.get(field);
    const found = Attachments.paths(field.value);
    row.replaceChildren(...found.map((path) => attachChip(field, path)));
    row.hidden = !found.length;
  }

  /**
   * @param {HTMLInputElement|HTMLTextAreaElement} field a framed text field; paste and drop of files upload into it.
   */
  function attachWire(field) {
    if (attachWired.has(field)) {
      return;
    }
    attachWired.add(field);
    field.addEventListener("paste", (event) => {
      const files = attachFiles(event.clipboardData);
      // Trip-wire: a copy from a spreadsheet or an office app carries a picture of the cells besides the text; text wins, so Ctrl+V of text never uploads.
      if (!files.length || event.clipboardData.getData("text/plain")) {
        return;
      }
      event.preventDefault();
      files.forEach((file) => attachUpload(field, file, true));
    });
    field.addEventListener("dragover", (event) => {
      if (attachDrags(event)) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }
    });
    field.addEventListener("drop", (event) => {
      const files = attachDrags(event) ? attachFiles(event.dataTransfer) : [];
      if (!files.length) {
        return;
      }
      event.preventDefault();
      field.focus();
      files.forEach((file) => attachUpload(field, file, false));
    });
  }

  /**
   * @param {HTMLTextAreaElement} field the textarea the chips belong to.
   * @returns {HTMLElement} its chip row, made once and kept, redrawn from the path lines of its text on every input.
   */
  function attachRow(field) {
    const kept = attachRows.get(field);
    if (kept) {
      return kept;
    }
    const row = h("div", {class: "mic-chips", role: "list", "aria-label": "Attachments", hidden: true});
    attachRows.set(field, row);
    field.addEventListener("input", () => attachDraw(field));
    attachDraw(field);
    return row;
  }

  /**
   * @param {HTMLTextAreaElement} field the textarea the picked files land in.
   * @returns {HTMLElement[]} the hidden file input and the 📎 button that opens it, for the footer before the mic.
   */
  function attachPicker(field) {
    const picker = h("input", {type: "file", multiple: true, hidden: true, tabindex: "-1", class: "mic-attach-file", "aria-label": "Attach files"});
    picker.addEventListener("change", () => {
      attachFiles(picker).forEach((file) => attachUpload(field, file, false));
      picker.value = "";
    });
    const button = h("button", {type: "button", class: "mic-attach", "aria-controls": field.id, ...named("Attach files", ATTACH_HINT), on: {click: () => picker.click()}}, icon("bi-paperclip"));
    return [picker, button];
  }
