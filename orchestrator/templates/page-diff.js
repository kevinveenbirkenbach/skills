  const DIFF_TONES = {A: "ok", M: "info", D: "bad", R: "violet", B: "neutral"};
  const diffView = {cache: new Map(), version: 0, float: null, picked: null, timer: 0};

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

  function diffBlock(file) {
    const tone = DIFF_TONES[file.status] || "neutral";
    const head = [h("span", {class: "letter", "data-tone": tone}, file.status), h("code", {class: "path"}, revealed(file.path)),
      file.mode && file.mode !== "100644" ? h("code", {class: "mode", title: `mode: ${file.mode}`}, file.mode) : null, h("span", {class: "spacer"}),
      file.note ? h("span", {class: "note", title: file.note}, icon("bi-eye-slash"), file.note) : null,
      file.status === "B" ? icon("bi-file-earmark-binary") : h("span", {class: "stat"}, h("span", {class: "add"}, `+${file.additions}`), h("span", {class: "del"}, `-${file.deletions}`))];
    if (file.status === "B" || !file.patch) {
      return h("section", {class: "diff-file", "data-path": file.path, "data-status": file.status, "data-patch": "none"}, h("div", {class: "diff-head"}, head));
    }
    const table = h("table", {class: "diff"}, h("tbody", {}, Diffs.rows(file.patch).map(patchRow)));
    return h("section", {class: "diff-file", "data-path": file.path, "data-status": file.status},
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
    return h("div", {class: "diff-files", "aria-label": `Diff: ${found.length}`}, found.map(diffBlock));
  }

  function feedbackList(ref) {
    const sent = Diffs.feedbackOf(state.messages, ref);
    return sent.length ? h("ul", {class: "feedback-list", "aria-label": `Feedback: ${sent.length}`}, sent.map((message) => h("li", {}, icon("bi-chat-left-text"), h("span", {class: "text"}, message.text), when(message.created_ts)))) : null;
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
    if (!card || !card.dataset.to || !elementOf(range.endContainer) || elementOf(range.endContainer).closest("[data-path]") !== region) {
      return null;
    }
    const quote = selection.toString();
    const code = region.querySelector("code");
    const lines = region.classList.contains("command") && code
      ? Diffs.lineSpan(code.textContent, quote)
      : Diffs.span([...region.querySelectorAll("tr[data-line]")].filter((row) => range.intersectsNode(row)).map((row) => Number(row.dataset.line)));
    if (!lines) {
      return null;
    }
    return {ref: card.dataset.ref, to: card.dataset.to, path: region.dataset.path, from: lines[0], until: lines[1], quote, rect: range.getBoundingClientRect()};
  }

  function feedbackSheet(picked) {
    hideFeedback();
    const words = h("textarea", {class: "field", rows: 4, "aria-label": "Feedback", title: "Feedback"});
    const send = iconBtn("bi-send", "Send feedback", "btn primary", async () => {
      if (!words.value.trim()) {
        words.focus();
        return;
      }
      send.disabled = true;
      const sent = await radioSend({to: picked.to, text: Diffs.feedback(picked.ref, picked.path, picked.from, picked.until, picked.quote, words.value), upload: "", cls: "post", voice: ""});
      send.disabled = false;
      if (sent) {
        closeSheet();
      }
    }, `Send feedback: a post to ${picked.to}`);
    openSheet("Feedback", [
      h("div", {class: "who"}, icon("bi-chat-left-text"), person(picked.to), h("code", {}, `${picked.path}:${picked.from}-${picked.until}`)),
      h("pre", {class: "notes"}, Diffs.quoted(picked.quote)),
      words,
      h("div", {class: "actions"}, h("span", {class: "spacer"}), send)], false);
    words.focus();
  }

  function hideFeedback() {
    if (diffView.float) {
      diffView.float.hidden = true;
    }
    diffView.picked = null;
  }

  function showFeedback(picked, x, y, menu) {
    if (!diffView.float) {
      diffView.float = h("div", {class: "feedback-float", hidden: true},
        h("button", {type: "button", class: "btn small primary icon-only", ...named("Feedback", "Feedback (f): a post with the selected lines to the requesting agent"), on: {
          mousedown: (event) => event.preventDefault(),
          click: () => diffView.picked && feedbackSheet(diffView.picked),
        }}, icon("bi-chat-left-text")));
      document.body.append(diffView.float);
    }
    diffView.picked = picked;
    diffView.float.setAttribute("role", menu ? "menu" : "toolbar");
    diffView.float.firstChild.setAttribute("role", menu ? "menuitem" : "button");
    diffView.float.style.left = `${Math.max(Math.min(x, window.innerWidth - 44), 4)}px`;
    diffView.float.style.top = `${Math.max(Math.min(y, window.innerHeight - 44), 4)}px`;
    diffView.float.hidden = false;
  }

  function feedbackButton() {
    window.clearTimeout(diffView.timer);
    diffView.timer = window.setTimeout(() => {
      const picked = selectionFeedback();
      if (picked) {
        showFeedback(picked, picked.rect.right + 4, picked.rect.bottom + 4, false);
      } else if (!diffView.float || !diffView.float.contains(document.activeElement)) {
        hideFeedback();
      }
    }, 120);
  }

  function feedbackMenu(event) {
    const picked = selectionFeedback();
    if (!picked || !(event.target instanceof Element) || !event.target.closest("[data-path]")) {
      return;
    }
    event.preventDefault();
    showFeedback(picked, event.clientX, event.clientY, true);
    diffView.float.firstChild.focus();
  }

  function feedbackKey() {
    const picked = selectionFeedback();
    if (picked) {
      feedbackSheet(picked);
    }
    return Boolean(picked);
  }
