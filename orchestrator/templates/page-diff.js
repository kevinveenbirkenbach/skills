  const DIFF_TONES = {A: "ok", M: "info", D: "bad", R: "violet", B: "neutral"};
  const HIDDEN_NOTES = new Set(["masked", "content withheld"]);
  const LINE_NOTES_GO = "Your line comments go to the requesting agent with Deny as a call, or after Grant as a post.";
  const LINE_JOIN = ";\n";
  const diffView = {cache: new Map(), revealed: new Map(), marks: new Map(), version: 0, float: null, picked: null, timer: 0, hit: null};
  const revealedOf = (item) => diffView.revealed.get(keyOf(item)) || new Map();
  const hiddenFile = (item, file) => HIDDEN_NOTES.has(file.note) && !revealedOf(item).has(file.path);
  const lineMarksOf = (ref) => diffView.marks.get(ref) || [];
  const lineSpanOf = (mark) => `${mark.path}:${mark.from === mark.until ? mark.from : `${mark.from}-${mark.until}`}`;

  /**
   * @param {string} ref the keyOf() of an inbox item.
   * @returns {string} its line comments as "path:line: comment" in the order they were set, joined by LINE_JOIN so they
   * stay apart once a denial folds the lines into one; "" without one.
   */
  const lineNotes = (ref) => lineMarksOf(ref).map((mark) => `${lineSpanOf(mark)}: ${mark.comment}`).join(LINE_JOIN);

  /**
   * @param {string} ref the keyOf() of an inbox item.
   * @param {Object[]} marks its line comments [{path, from, until, comment}]; empty forgets them.
   */
  function setLineMarks(ref, marks) {
    if (marks.length) {
      diffView.marks.set(ref, marks);
    } else {
      diffView.marks.delete(ref);
    }
    diffView.version += 1;
    drawInbox();
    drawStream();
    repaintReview();
  }

  /**
   * @param {string} ref the keyOf() of the item the rows belong to.
   * @param {string} path the file the rows show.
   * @param {HTMLElement[]} rows its table rows; a code row carries data-line.
   * @returns {HTMLElement[]} the rows, each commented one marked and its comments shown after the last line they cover.
   */
  function withLineMarks(ref, path, rows) {
    const marks = lineMarksOf(ref).filter((mark) => mark.path === path);
    const placed = new Set();
    return rows.flatMap((row) => {
      const line = Number(row.dataset.line);
      if (!marks.some((mark) => line >= mark.from && line <= mark.until)) {
        return [row];
      }
      row.setAttribute("class", `${row.getAttribute("class") || ""} marked`.trim());
      const here = marks.filter((mark) => mark.until === line && !placed.has(mark));
      here.forEach((mark) => placed.add(mark));
      return [row, ...here.map((mark) => h("tr", {class: "match-mark", "data-line": line}, h("td", {colspan: row.children.length}, icon("bi-chat-square-text"), h("span", {class: "match-mark-text"}, revealed(mark.comment)))))];
    });
  }

  function forgetRevealed() {
    const waiting = new Set(state.inbox.map(keyOf));
    for (const key of [...diffView.revealed.keys()]) {
      if (!waiting.has(key)) {
        diffView.revealed.delete(key);
      }
    }
  }

  async function revealFiles(item, paths) {
    const route = `/api/diffs/${item.kind}/${encodeURIComponent(item.id)}/reveal`;
    const label = paths.length === 1 ? `Reveal: ${short(paths[0])}` : `Reveal ${paths.length} files`;
    const signed = await signedProof(`${route}/sign`, {paths}, label, null);
    if (!signed || !signed.proof) {
      return;
    }
    const result = await sendJson(route, {paths, proof: signed.proof});
    if (!result.ok || !result.data) {
      toast(`${label}: not possible`, fail(result), false);
      return;
    }
    diffView.revealed.set(keyOf(item), new Map([...revealedOf(item), ...Object.entries(result.data.patches)]));
    diffView.version += 1;
    drawInbox();
    drawStream();
  }

  function revealButton(item, paths, words) {
    const hint = `${words}: your passkey signs the reveal; the clear text stays in this page only and the reveal is logged`;
    return h("button", {type: "button", class: "btn small ghost reveal", ...named(words, hint), on: {click: (event) => {
      event.preventDefault();
      event.stopPropagation();
      revealFiles(item, paths);
    }}}, icon("bi-eye"), words);
  }

  /**
   * @param {Element} body the scrolling element that holds the files.
   * @param {string} selector the files: details elements in reading order.
   * Opens the first closed file once the open file before it ends inside the visible part of body.
   */
  function openOnScroll(body, selector) {
    const files = [...body.querySelectorAll(selector)];
    const view = body.getBoundingClientRect();
    for (let index = 0; index < files.length - 1; index += 1) {
      const file = files[index];
      if (!file.open) {
        return;
      }
      const next = files[index + 1];
      if (!next.open && file.getBoundingClientRect().bottom <= view.bottom + 8) {
        next.open = true;
        return;
      }
    }
  }

  function diffOf(item) {
    if (!item || typeof item.diff !== "number" || !["review", "ask"].includes(item.kind)) {
      return null;
    }
    const key = keyOf(item);
    if (!diffView.cache.has(key)) {
      diffView.cache.set(key, "loading");
      fetch(`/api/diffs/${item.kind}/${encodeURIComponent(item.id)}`, {cache: "no-store"})
        .then((response) => (response.ok ? response.json() : {diff: null}))
        .then((data) => diffView.cache.set(key, Array.isArray(data.diff) ? data.diff : null))
        .catch(() => diffView.cache.set(key, null))
        .then(() => {
          diffView.version += 1;
          drawInbox();
          drawStream();
        });
    }
    return diffView.cache.get(key);
  }

  function patchRow(row) {
    const number = row.new || row.old || null;
    if (row.kind === "hunk") {
      return h("tr", {class: "hunk"}, h("td", {colspan: 3}), h("td", {class: "code"}, revealed(row.text)));
    }
    return h("tr", {class: row.kind, "data-line": number},
      h("td", {class: "num"}, row.old), h("td", {class: "num"}, row.new), h("td", {class: "sign"}, SIGNS[row.kind] || " "), h("td", {class: "code"}, revealed(row.text)));
  }

  function diffBlock(item, raw) {
    const clear = revealedOf(item).get(raw.path);
    const hidden = hiddenFile(item, raw);
    const file = clear === undefined ? raw : {...raw, patch: clear, note: ""};
    const tone = DIFF_TONES[file.status] || "neutral";
    const head = [h("span", {class: "letter", "data-tone": tone}, file.status), pathCode(item.directory, file.path, revealed(file.path)),
      file.mode && file.mode !== "100644" ? h("code", {class: "mode", title: `mode: ${file.mode}`}, file.mode) : null, h("span", {class: "spacer"}),
      file.note ? h("span", {class: "note", title: file.note}, icon("bi-eye-slash"), file.note) : null,
      hidden ? revealButton(item, [file.path], "Reveal") : null,
      clear === undefined ? null : h("span", {class: "note revealed", title: "revealed by your passkey, kept in this page only"}, icon("bi-eye"), "revealed"),
      file.status === "B" ? icon("bi-file-earmark-binary") : h("span", {class: "stat"}, h("span", {class: "add"}, `+${file.additions}`), h("span", {class: "del"}, `-${file.deletions}`))];
    const shown = clear === undefined ? (hidden ? raw.note : null) : "revealed";
    if (file.status === "B" || !file.patch) {
      return h("section", {class: "diff-file", "data-path": file.path, "data-status": file.status, "data-patch": "none", "data-hidden": shown}, h("div", {class: "diff-head"}, head));
    }
    const table = h("table", {class: "diff"}, h("tbody", {}, withLineMarks(keyOf(item), file.path, Diffs.rows(file.patch).map(patchRow))));
    return h("section", {class: "diff-file", "data-path": file.path, "data-status": file.status, "data-hidden": shown},
      h("details", {open: !Diffs.collapsed(file)}, h("summary", {class: "diff-head"}, head), h("div", {class: "diff-scroll"}, table)));
  }

  function diffBlocks(item) {
    const found = diffOf(item);
    if (found === null || found === undefined) {
      return null;
    }
    if (found === "loading") {
      return h("p", {class: "muted"}, "…");
    }
    const hidden = found.filter((file) => hiddenFile(item, file)).map((file) => file.path);
    return h("div", {class: "diff-files", "aria-label": `Diff: ${found.length}`},
      hidden.length > 1 ? h("div", {class: "reveal-all"}, revealButton(item, hidden, `Reveal all ${hidden.length}`)) : null,
      found.map((file) => diffBlock(item, file)));
  }

  function feedbackList(ref) {
    const sent = Diffs.feedbackOf(state.messages, ref);
    const marks = lineMarksOf(ref);
    const marked = marks.map((mark, index) => h("li", {class: "line-mark"}, icon("bi-bookmark-fill"), h("code", {}, revealed(lineSpanOf(mark))), h("span", {class: "text"}, revealed(mark.comment)),
      iconBtn("bi-x-lg", "Remove comment", "btn small ghost", () => setLineMarks(ref, marks.filter((_, at) => at !== index)), `Remove the comment on ${revealed(lineSpanOf(mark))}`)));
    return sent.length || marks.length ? h("ul", {class: "feedback-list", "aria-label": `Feedback: ${sent.length + marks.length}`, title: marks.length ? LINE_NOTES_GO : null}, marked,
      sent.map((message) => h("li", {}, icon("bi-chat-left-text"), h("span", {class: "text"}, message.text), when(message.created_ts)))) : null;
  }

  /**
   * @param {HTMLElement} row a code row with data-line, as a right-click hits it.
   * @returns {Object|null} the row as the lines a comment covers, like selectionFeedback(); null outside a [data-path]
   * region of an inbox item. An item without a requester takes marks too: Deny via … picks whom they go to.
   */
  function rowPick(row) {
    const region = row.closest("[data-path]");
    const card = region && region.closest("[data-ref]");
    if (!card || !card.dataset.ref || !row.dataset.line || row.classList.contains("match-mark") || row.closest(".match-card")) {
      return null;
    }
    const line = Number(row.dataset.line);
    return {ref: card.dataset.ref, to: card.dataset.to || "", path: region.dataset.path, from: line, until: line, anchor: row, inline: Boolean(region.closest("#sheet"))};
  }

  /**
   * @param {Object} picked the lines to comment: {ref, to, path, from, until, anchor, inline}; inline puts the field
   * under the anchor instead of a sheet of its own.
   */
  function markLines(picked) {
    hideFeedback();
    const words = h("textarea", {class: "field", rows: 3, maxlength: OTHER_LIMIT, "aria-label": "Comment", placeholder: "Comment on these lines", "data-skills": ""});
    const save = () => {
      const comment = words.value.trim();
      if (!comment) {
        words.focus();
        return false;
      }
      setLineMarks(picked.ref, [...lineMarksOf(picked.ref), {path: picked.path, from: picked.from, until: picked.until, comment}]);
      rememberComment(comment);
      return true;
    };
    const head = h("code", {}, revealed(lineSpanOf(picked)));
    const chips = presetChips(words, savedComments(), "Recent comments");
    const saveButton = (cls, done) => h("button", {type: "button", class: cls, ...named("Save comment", LINE_NOTES_GO), on: {click: () => save() && done()}}, icon("bi-bookmark-fill"), "Save");
    if (picked.inline) {
      const box = h("div", {class: "match-comment-box"}, head, chips, words);
      const field = picked.anchor.tagName === "TR" ? h("tr", {class: "match-comment"}, h("td", {colspan: picked.anchor.children.length}, box)) : h("div", {class: "match-comment"}, box);
      box.append(h("div", {class: "actions"}, btn("Cancel", "btn small ghost", () => vanish(field)), saveButton("btn small primary", () => vanish(field))));
      document.querySelectorAll("#sheet .match-comment").forEach((open) => vanish(open));
      picked.anchor.after(field);
    } else {
      openSheet("Comment", [h("div", {class: "who"}, icon("bi-chat-left-text"), person(picked.to), head), h("p", {class: "muted"}, LINE_NOTES_GO), chips, words,
        h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), saveButton("btn primary", closeSheet))], false);
    }
    words.focus();
  }

  function selectionFeedback() {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount || !selection.toString().trim()) {
      return null;
    }
    const range = selection.getRangeAt(0);
    const elementOf = (node) => (node instanceof Element ? node : node.parentElement);
    const region = elementOf(range.startContainer) && elementOf(range.startContainer).closest("[data-path]");
    const card = region && region.closest("[data-ref]");
    if (!card || !card.dataset.ref || !elementOf(range.endContainer) || elementOf(range.endContainer).closest("[data-path]") !== region) {
      return null;
    }
    const quote = selection.toString();
    const code = region.querySelector("code");
    const rows = [...region.querySelectorAll("tr[data-line]")].filter((row) => !row.classList.contains("match-mark") && range.intersectsNode(row));
    const lines = region.classList.contains("command") && code ? Diffs.lineSpan(code.textContent, quote) : Diffs.span(rows.map((row) => Number(row.dataset.line)));
    if (!lines) {
      return null;
    }
    return {ref: card.dataset.ref, to: card.dataset.to || "", path: region.dataset.path, from: lines[0], until: lines[1], anchor: rows.length ? rows[rows.length - 1] : region, inline: Boolean(region.closest("#sheet")), rect: range.getBoundingClientRect()};
  }

  function hideFeedback() {
    if (diffView.float) {
      diffView.float.hidden = true;
    }
    diffView.picked = null;
  }

  function showFeedback(picked, x, y) {
    if (!diffView.float) {
      diffView.float = h("div", {class: "feedback-float", role: "toolbar", hidden: true},
        h("button", {type: "button", class: "btn small primary icon-only", ...named("Comment", `Comment (f) on the selected lines. ${LINE_NOTES_GO}`), on: {
          mousedown: (event) => event.preventDefault(),
          click: () => diffView.picked && markLines(diffView.picked),
        }}, icon("bi-chat-left-text")));
      document.body.append(diffView.float);
    }
    diffView.picked = picked;
    diffView.float.style.left = `${Math.max(Math.min(x, window.innerWidth - 44), 4)}px`;
    diffView.float.style.top = `${Math.max(Math.min(y, window.innerHeight - 44), 4)}px`;
    diffView.float.hidden = false;
  }

  function feedbackButton() {
    window.clearTimeout(diffView.timer);
    diffView.timer = window.setTimeout(() => {
      const picked = selectionFeedback();
      if (picked) {
        showFeedback(picked, picked.rect.right + 4, picked.rect.bottom + 4);
      } else if (!diffView.float || !diffView.float.contains(document.activeElement)) {
        hideFeedback();
      }
    }, 120);
  }

  /**
   * @param {HTMLElement} node the [data-path] region the menu is for.
   * @returns the context menu items of a diff file or a command: Comment on the selected lines, else on the code row the
   * right-click hit.
   */
  function feedbackItems(node) {
    const row = diffView.hit && node.contains(diffView.hit) ? diffView.hit.closest("tr[data-line]") : null;
    const picked = selectionFeedback() || (row ? rowPick(row) : null);
    return picked ? [{label: "Comment", hint: `f: ${lineSpanOf(picked)}. ${LINE_NOTES_GO}`, run: () => markLines(picked)}] : [];
  }

  function feedbackKey() {
    const picked = selectionFeedback();
    if (picked) {
      markLines(picked);
    }
    return Boolean(picked);
  }
