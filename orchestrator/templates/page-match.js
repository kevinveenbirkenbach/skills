  const MATCH_REFRESH = 2000;
  const MATCH_PEEKS = 2;
  const LONG_PRESS = 550;
  const PRESS_SLOP = 10;
  const MATCH_KINDS = {commit: ["Commit", "info", "bi-git"], command: ["Command", "warn", "bi-terminal"], ask: ["Ask", "warn", "bi-shield-lock"], decision: ["Decision", "info", "bi-signpost-split"], rule: ["Rule", "neutral", "bi-shield-check"]};
  const MATCH_VERDICTS = {accept: ["Accept", "ok", "bi-check-lg"], reject: ["Reject", "bad", "bi-x-lg"]};
  const SWIPE_SHARE = 0.25;
  const SWIPE_UP = 80;
  const FEEDBACK_LIMIT = 2000;
  const FLY_MS = 400;
  const CONFETTI = 28;
  const COMMENTS_KEPT = 5;
  const PATTERNS = ["dots", "stripes", "waves", "grid", "rings"];
  const matchView = {cards: null, order: [], marks: new Map(), opened: new Map(), decisions: new Map(), overview: false, front: null, drag: null, dom: null, sig: "", fetched: 0, loading: false, press: null, flying: false, openBefore: 0, epoch: 0};

  /**
   * @returns {Promise<void>} settled when this read ends, at once while another runs; a response requested before
   * the last release (matchView.epoch) still lists the released cards, so it is dropped and read again.
   */
  async function fetchMatch() {
    if (matchView.loading) {
      return;
    }
    matchView.loading = true;
    matchView.fetched = Date.now();
    const epoch = matchView.epoch;
    try {
      const response = await fetch("/api/match", {cache: "no-store"});
      if (response.ok) {
        const data = await response.json();
        if (epoch === matchView.epoch) {
          matchView.cards = Array.isArray(data.cards) ? data.cards : [];
        }
      }
    } catch {
      matchView.cards = matchView.cards || [];
    } finally {
      matchView.loading = false;
    }
    if (epoch !== matchView.epoch) {
      await fetchMatch();
      return;
    }
    drawMatch();
  }

  function matchOrder(cards) {
    const ids = new Set(cards.map((card) => card.id));
    const kept = matchView.order.filter((id) => ids.has(id));
    const fresh = cards.filter((card) => !kept.includes(card.id)).sort((a, b) => Number(a.stale) - Number(b.stale) || (a.created_ts || 0) - (b.created_ts || 0));
    matchView.order = [...kept, ...fresh.map((card) => card.id)];
    const byId = new Map(cards.map((card) => [card.id, card]));
    return matchView.order.map((id) => byId.get(id));
  }

  function ageWords(born) {
    if (typeof born !== "number") {
      return "age unknown";
    }
    const days = Math.max(0, Math.floor((state.now - born) / DAY));
    return days === 1 ? "1 day" : `${days} days`;
  }

  const cardKey = (card) => `${card.id}@${card.hash}`;

  /**
   * @returns {string[]} this browser's last COMMENTS_KEPT distinct saved line comments, newest first.
   */
  function savedComments() {
    const kept = stored(STORE.comments, []);
    return Array.isArray(kept) ? kept.filter((text) => typeof text === "string" && text).slice(0, COMMENTS_KEPT) : [];
  }

  const peeksShown = () => stored(STORE.peeks, true) !== false;

  function rememberComment(text) {
    keep(STORE.comments, [text, ...savedComments().filter((old) => old !== text)].slice(0, COMMENTS_KEPT));
  }

  function marksOf(card) {
    const key = cardKey(card);
    if (!matchView.marks.has(key)) {
      matchView.marks.set(key, []);
    }
    return matchView.marks.get(key);
  }

  function contentRows(text) {
    const lines = String(text).split("\n");
    if (lines.length && lines[lines.length - 1] === "") {
      lines.pop();
    }
    return lines.map((line, index) => h("tr", {class: "ctx", "data-line": index + 1}, h("td", {class: "num"}, index + 1), h("td", {class: "code"}, revealed(line))));
  }

  function markRow(mark, columns) {
    return h("tr", {class: "match-mark", "data-line": mark.line}, h("td", {colspan: columns}, icon("bi-chat-square-text"), h("span", {class: "match-mark-text"}, revealed(mark.comment))));
  }

  const patched = (card) => card.kind === "commit" || card.kind === "ask" || Boolean(card.merge);
  const pickOnly = (card) => card.kind === "decision" && card.entry === "decision";
  const flies = (card) => !card.stale && card.kind !== "rule" && (card.kind !== "decision" || Boolean(card.recommended));

  function matchFileRows(card, file) {
    const diffed = patched(card);
    const rows = diffed ? (file.patch ? Diffs.rows(file.patch).map(patchRow) : []) : file.state === "read" ? contentRows(file.content) : [];
    const columns = diffed ? 4 : 2;
    const marks = marksOf(card).filter((mark) => mark.path === file.path);
    return rows.flatMap((row) => {
      const line = row.dataset.line;
      const here = marks.filter((mark) => String(mark.line) === line);
      if (here.length) {
        row.classList.add("marked");
      }
      return [row, ...here.map((mark) => markRow(mark, columns))];
    });
  }

  function fileHead(card, file) {
    const count = marksOf(card).filter((mark) => mark.path === file.path).length;
    const marks = count ? h("span", {class: "match-marks", title: `${count} marks`}, String(count)) : null;
    if (patched(card)) {
      const tone = DIFF_TONES[file.status] || "neutral";
      const stat = file.status === "B" ? icon("bi-file-earmark-binary") : h("span", {class: "stat"}, h("span", {class: "add"}, `+${file.additions}`), h("span", {class: "del"}, `-${file.deletions}`));
      return h("summary", {class: "diff-head"}, h("span", {class: "letter", "data-tone": tone}, file.status), h("code", {class: "path"}, revealed(file.path)), h("span", {class: "spacer"}),
        file.note ? h("span", {class: "note", title: file.note}, icon("bi-eye-slash"), file.note) : null, marks, stat);
    }
    const tone = file.state === "read" ? "ok" : "bad";
    return h("summary", {class: "diff-head"}, h("span", {class: "letter", "data-tone": tone}, icon("bi-file-earmark-text")), h("code", {class: "path"}, revealed(file.path)), h("span", {class: "spacer"}),
      file.state === "read" ? null : h("span", {class: "note", title: file.reason}, icon("bi-exclamation-triangle"), `refused: ${file.reason}`), marks, h("span", {class: "muted"}, `${file.size} B`));
  }

  function fileBlock(card, file, index) {
    const opened = matchView.opened.has(card.id) ? matchView.opened.get(card.id).has(file.path) : index === 0;
    const rows = matchFileRows(card, file);
    const table = rows.length ? h("div", {class: "diff-scroll"}, h("table", {class: "diff"}, h("tbody", {}, rows))) : h("p", {class: "muted"}, patched(card) ? "No patch shipped for this file." : "Not read.");
    const block = h("details", {class: "match-file", "data-path": file.path, "data-state": patched(card) ? null : file.state, open: opened}, fileHead(card, file), table);
    block.addEventListener("toggle", () => remember(card, block));
    return h("li", {}, block);
  }

  function remember(card, block) {
    if (!matchView.opened.has(card.id)) {
      matchView.opened.set(card.id, new Set());
    }
    const open = matchView.opened.get(card.id);
    if (block.open) {
      open.add(block.dataset.path);
    } else {
      open.delete(block.dataset.path);
    }
  }

  function closeComment(card) {
    const open = card.querySelector(".match-comment");
    if (open) {
      open.remove();
    }
  }

  function commentField(card, data, row) {
    const article = row.closest(".match-card");
    closeComment(article);
    const file = row.closest(".match-file");
    const words = h("textarea", {class: "field", rows: 2, "aria-label": "Comment", placeholder: "Comment on this line"});
    const save = h("button", {type: "button", class: "btn small primary match-save", ...named("Save mark"), on: {click: () => {
      if (!words.value.trim()) {
        words.focus();
        return;
      }
      marksOf(data).push({path: file.dataset.path, line: Number(row.dataset.line), comment: words.value.trim()});
      rememberComment(words.value.trim());
      drawMatch(true);
    }}}, icon("bi-bookmark-fill"), "Save");
    const cancel = h("button", {type: "button", class: "btn small ghost", ...named("Cancel"), on: {click: () => closeComment(article)}}, "Cancel");
    const columns = row.children.length;
    const field = h("tr", {class: "match-comment"}, h("td", {colspan: columns}, h("div", {class: "match-comment-box"}, h("code", {}, `${file.dataset.path}:${row.dataset.line}`),
      presetChips(words, savedComments(), "Recent comments"), words, h("div", {class: "actions"}, cancel, save))));
    row.after(field);
    words.focus();
  }

  function codeRow(event) {
    const row = event.target instanceof Element ? event.target.closest(".match-file tr[data-line]") : null;
    return row && !row.classList.contains("match-mark") ? row : null;
  }

  function markable(article, data) {
    article.addEventListener("contextmenu", (event) => {
      const row = codeRow(event);
      if (row) {
        event.preventDefault();
        commentField(article, data, row);
      }
    });
    article.addEventListener("pointerdown", (event) => {
      const row = codeRow(event);
      if (!row || event.pointerType !== "touch") {
        return;
      }
      const press = {x: event.clientX, y: event.clientY, timer: window.setTimeout(() => {
        matchView.press = null;
        commentField(article, data, row);
      }, LONG_PRESS)};
      matchView.press = press;
    });
    const drop = () => {
      if (matchView.press) {
        window.clearTimeout(matchView.press.timer);
        matchView.press = null;
      }
    };
    article.addEventListener("pointermove", (event) => {
      if (matchView.press && Math.hypot(event.clientX - matchView.press.x, event.clientY - matchView.press.y) > PRESS_SLOP) {
        drop();
      }
    });
    article.addEventListener("pointerup", drop);
    article.addEventListener("pointercancel", drop);
  }

  /**
   * @param {string} worktree the card's worktree path.
   * @param {string} repo the card's repository path.
   * @returns {string} the worktree below the repository relative to it, the repository itself as "checkout", any
   * other path as its last three folders.
   */
  function worktreeWords(worktree, repo) {
    if (repo && worktree === repo) {
      return "checkout";
    }
    if (repo && worktree.startsWith(`${repo}/`)) {
      return worktree.slice(repo.length + 1);
    }
    const parts = worktree.split("/").filter(Boolean);
    return parts.length > 3 ? `…/${parts.slice(-3).join("/")}` : worktree;
  }

  function placeChip(place, iconName, label, value, words) {
    const full = revealed(value);
    const chip = h("button", {type: "button", class: "match-where", "data-place": place, title: `${label}: ${full} (click copies)`, "aria-label": `${label}: ${full}, click copies`},
      icon(iconName), h("span", {}, revealed(words)));
    chip.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(value);
        toast(`Copied ${label.toLowerCase()}`, [full], true);
      } catch {
        toast("Not copied", ["The browser refused the clipboard."], false);
      }
    });
    return chip;
  }

  function placeRow(card) {
    const chips = [
      card.branch ? placeChip("branch", "bi-git", "Branch", card.branch, card.branch) : null,
      card.repo ? placeChip("repo", "bi-folder2", "Repository", card.repo, card.repo.split("/").filter(Boolean).pop() || card.repo) : null,
      card.worktree ? placeChip("worktree", "bi-diagram-2", "Worktree", card.worktree, worktreeWords(card.worktree, card.repo)) : null,
    ].filter(Boolean);
    return chips.length ? h("div", {class: "match-place", "aria-label": "Place"}, chips) : null;
  }

  function matchHead(card) {
    const [kindName, kindTone, kindIcon] = MATCH_KINDS[card.kind] || [card.kind, "neutral", "bi-collection"];
    const metrics = card.metrics || [];
    return h("header", {class: "match-head"},
      h("div", {class: "match-who"}, face(card.agent || "-", true), h("strong", {class: "match-name"}, revealed(card.agent || "unknown agent")), h("span", {class: "match-age"}, ageWords(card.born))),
      metrics.length ? h("ul", {class: "match-metrics", "aria-label": "Scores"}, metrics.map((metric) => h("li", {class: "match-metric", "data-metric": metric.id, title: revealed(`${metric.label}: ${metric.value}`)},
        h("span", {"aria-hidden": "true"}, metric.emoji), h("span", {class: "match-metric-label"}, metric.label), h("strong", {}, revealed(metric.value))))) : null,
      h("div", {class: "states"}, h("span", {class: "pill", "data-tone": kindTone}, icon(kindIcon), kindName), card.gate ? pill(`gate ${card.gate}`, card.gate === "pass" ? "ok" : "bad") : null,
        card.score && !metrics.length ? h("span", {class: "pill", "data-tone": "neutral"}, revealed(card.score)) : null, card.stale ? h("span", {class: "pill match-stale-pill", "data-tone": "bad"}, icon("bi-hourglass-split"), "stale") : null),
      placeRow(card),
      h("h2", {class: "match-title"}, revealed(card.title)),
      card.stale ? h("p", {class: "match-stale"}, icon("bi-exclamation-triangle"), revealed(card.stale_reason)) : null);
  }

  function matchOptions(card) {
    const kept = matchView.decisions.get(cardKey(card));
    return h("div", {class: "options match-options", role: "group", "aria-label": "Options"}, card.options.map((option) => h("button", {
      type: "button", class: `option${option.label === card.recommended ? " recommended" : ""}`, "aria-pressed": String(Boolean(kept && kept.label === option.label)),
      title: revealed(`${option.label}: picked now, sent to ${card.agent || "its agent"} as a post at the release`), on: {click: () => decide(card, "accept", "", option.label)},
    }, h("strong", {}, revealed(option.label)), option.description ? h("span", {}, revealed(option.description)) : null)));
  }

  function matchPayload(card) {
    if (card.kind === "decision") {
      return h("section", {class: "match-payload"}, card.reason && card.reason !== "-" ? h("p", {class: "match-reason"}, revealed(card.reason)) : null, matchOptions(card));
    }
    if (card.kind === "rule") {
      return h("section", {class: "match-payload"}, ruleRequestBody({...card, detail: card.reason}));
    }
    if (card.kind === "ask") {
      return h("section", {class: "match-payload"}, h("pre", {class: "match-command"}, h("code", {}, revealed(card.command))), h("p", {class: "match-directory"}, revealed(card.directory)),
        card.warnings.length ? h("p", {class: "match-warnings"}, card.warnings.map((warning) => pill(warning, "bad"))) : null);
    }
    if (card.kind !== "command") {
      return null;
    }
    const merge = card.merge;
    const short = (oid) => oid.slice(0, 12);
    const preview = merge ? h("p", {class: "match-merge", "data-error": String(Boolean(merge.error))}, icon(merge.error ? "bi-exclamation-triangle" : "bi-sign-merge-left"),
      merge.error ? `No merge preview: ${merge.error}` : `Brings in ${short(merge.base)} → ${short(merge.target)}, onto HEAD ${short(merge.head)}`) : null;
    return h("section", {class: "match-payload"},
      h("pre", {class: "match-command"}, h("code", {}, revealed(card.command))),
      h("p", {class: "match-directory"}, revealed(card.directory)),
      card.reason && card.reason !== "-" ? h("p", {class: "match-reason"}, revealed(card.reason)) : null, preview);
  }

  /**
   * @param {HTMLElement} article the card.
   * @param {string} id the card id; the same id always gets the same two hues and pattern, so a redraw never flickers.
   */
  function paint(article, id) {
    const seed = Faces.hash(id);
    const hue = seed % 360;
    article.style.setProperty("--card-hue", String(hue));
    article.style.setProperty("--card-hue-2", String((hue + 40 + ((seed >>> 9) % 100)) % 360));
    article.dataset.pattern = PATTERNS[(seed >>> 17) % PATTERNS.length];
  }

  function matchCard(card) {
    const files = card.files || [];
    const none = card.kind === "commit" ? "No diff shipped with this stage." : card.kind === "ask" ? "Its tool call changes no file." : card.merge ? (card.merge.error ? "No diff to show." : "The merge brings no change.") : "Its command names no file.";
    const list = files.length ? h("ol", {class: "match-files", "aria-label": `Files: ${files.length}`}, files.map((file, index) => fileBlock(card, file, index))) : card.kind === "decision" || card.kind === "rule" ? null : h("p", {class: "muted"}, none);
    const body = h("div", {class: "match-body"}, matchPayload(card), list);
    body.addEventListener("scroll", () => openOnScroll(body, ".match-file"), {passive: true});
    const article = h("article", {class: "card match-card front", "data-card": card.id, "data-kind": card.kind, "data-stale": String(Boolean(card.stale)), "aria-label": `${card.kind} card of ${card.agent || "an agent"}`},
      matchHead(card), body);
    article.style.setProperty("--agent-hue", String(Faces.hash(card.agent) % 360));
    paint(article, card.id);
    markable(article, card);
    window.setTimeout(() => openOnScroll(body, ".match-file"), 0);
    return article;
  }

  function peekTab(card) {
    const [kindName, kindTone] = MATCH_KINDS[card.kind] || [card.kind, "neutral"];
    return h("button", {type: "button", class: "match-peek", "data-card": card.id, "data-stale": String(Boolean(card.stale)), ...named(`Show ${kindName.toLowerCase()} card: ${card.title}`), on: {click: () => {
      matchView.order = [card.id, ...matchView.order.filter((id) => id !== card.id)];
      drawMatch(true);
    }}}, face(card.agent || "-", false), h("span", {class: "pill", "data-tone": kindTone}, kindName), card.stale ? h("span", {class: "pill", "data-tone": "bad"}, "stale") : null, h("span", {class: "match-peek-title"}, revealed(card.title)));
  }

  /**
   * @param {object} card a match card.
   * @returns {string} every mark of the card as one line "path:line: comment", in the order they were set.
   */
  function feedbackOf(card) {
    return marksOf(card).map((mark) => `${mark.path}:${mark.line}: ${mark.comment}`).join("\n");
  }

  /**
   * @param {string} verdict accept, reject or later: the way the front card flies off, its stamp shown on the way.
   * @param {Function} then runs once the card is gone; at once without a front card or under reduced motion, never
   * while another card still flies.
   */
  function flyOff(verdict, then) {
    const front = matchView.dom && matchView.dom.stack.querySelector(".match-card.front");
    if (matchView.flying) {
      return;
    }
    if (!front || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      then();
      return;
    }
    matchView.flying = true;
    let landed = false;
    const land = () => {
      if (!landed) {
        landed = true;
        matchView.flying = false;
        then();
      }
    };
    front.dataset.leaning = verdict;
    front.dataset.fly = verdict;
    front.addEventListener("animationend", (event) => event.target === front && land());
    window.setTimeout(land, FLY_MS);
  }

  /**
   * @param {object} card the card decided.
   * @param {string} verdict accept or reject.
   * @param {string} feedback the rejection text, else empty.
   * @param {string} label the picked option of a decision card, else empty.
   */
  function decide(card, verdict, feedback, label) {
    flyOff(verdict, () => {
      matchView.decisions.set(cardKey(card), {verdict, feedback, label});
      drawMatch(true);
    });
  }

  function confetti() {
    return h("div", {class: "match-confetti", "aria-hidden": "true"}, Array.from({length: CONFETTI}, (_, index) => {
      const bit = h("i", {});
      bit.style.setProperty("--x", `${(index * 37) % 100}%`);
      bit.style.setProperty("--c", String((index * 47) % 360));
      bit.style.setProperty("--r", `${(index % 2 ? 1 : -1) * (180 + index * 23)}deg`);
      bit.style.setProperty("--d", `${(index % 7) * 0.06}s`);
      return bit;
    }));
  }

  function acceptCard(card) {
    if (card.stale) {
      toast("Accept: refused", [`The card is stale: ${card.stale_reason}. Add it again to decide it.`], false);
      return;
    }
    if (card.kind === "rule") {
      const item = state.inbox.find((entry) => keyOf(entry) === card.id);
      if (item) {
        openItem(item);
      } else {
        toast("Accept: the rule request is gone", [], false);
      }
      return;
    }
    if (card.kind === "decision" && !card.recommended) {
      toast("Accept: pick one of its options", ["The decision recommends none, so the card waits for your pick."], false);
      return;
    }
    decide(card, "accept", "", card.kind === "decision" ? card.recommended : "");
  }

  function rejectCard(card) {
    if (pickOnly(card)) {
      toast("Reject: not possible", ["A choice is answered with one of its options."], false);
      return;
    }
    const kept = matchView.decisions.get(cardKey(card));
    const words = h("textarea", {class: "field match-feedback", rows: 6, maxlength: FEEDBACK_LIMIT, "aria-label": "Feedback"});
    words.value = (kept && kept.verdict === "reject" ? kept.feedback : feedbackOf(card)).slice(0, FEEDBACK_LIMIT);
    const confirm = h("button", {type: "button", class: "btn danger match-feedback-reject"}, icon("bi-x-lg"), "Reject");
    confirm.addEventListener("click", () => {
      closeSheet();
      decide(card, "reject", words.value.trim(), "");
    });
    const note = `${card.agent || "The agent"} gets this text by radio call at the release; nothing is sent before.`;
    openSheet(`Reject: ${card.title}`, [h("p", {class: "muted"}, note), reasonChips(words), words, h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), confirm)], false);
    words.focus();
  }

  function laterCard(card) {
    flyOff("later", () => {
      matchView.order = [...matchView.order.filter((id) => id !== card.id), card.id];
      drawMatch(true);
    });
  }

  /**
   * @param {string} key the key of a keydown the global handler did not take.
   * @returns {boolean} whether the Match stack took it: the right arrow accepts the front card, the left arrow
   * rejects it, the up arrow sends it to the back.
   */
  function matchKey(key) {
    const card = matchView.front;
    if (!card || ui.screen !== "match" || !matchView.dom || !matchView.dom.stack.isConnected) {
      return false;
    }
    const act = {ArrowRight: acceptCard, ArrowLeft: rejectCard, ArrowUp: laterCard}[key];
    if (act) {
      act(card);
    }
    return Boolean(act);
  }

  function draggable(article, card) {
    const head = article.querySelector(".match-head");
    const move = (event) => {
      const drag = matchView.drag;
      if (drag && drag.id === event.pointerId) {
        const [dx, dy] = [event.clientX - drag.x, event.clientY - drag.y];
        const up = -dy > Math.abs(dx);
        article.style.transform = `translate(${dx}px, ${Math.min(0, dy)}px) rotate(${dx / 40}deg)`;
        article.dataset.leaning = up ? "later" : dx > 0 ? "accept" : dx < 0 ? "reject" : "";
        article.style.setProperty("--lean", String(Math.min(1, up ? -dy / SWIPE_UP : Math.abs(dx) / (SWIPE_SHARE * article.getBoundingClientRect().width))));
      }
    };
    const release = (event) => {
      const drag = matchView.drag;
      if (!drag || drag.id !== event.pointerId) {
        return;
      }
      drag.end();
      const [dx, dy] = [event.clientX - drag.x, event.clientY - drag.y];
      const far = SWIPE_SHARE * article.getBoundingClientRect().width;
      const swiped = event.type === "pointercancel" ? "" : Math.abs(dx) >= far && Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "accept" : "reject") : -dy >= SWIPE_UP && -dy > Math.abs(dx) ? "later" : "";
      article.style.removeProperty("--lean");
      if (!((swiped === "accept" && flies(card)) || swiped === "later")) {
        article.style.removeProperty("transform");
        delete article.dataset.leaning;
      }
      if (!article.isConnected) {
        return;
      }
      ({accept: acceptCard, reject: rejectCard, later: laterCard}[swiped] || (() => null))(card);
    };
    head.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || matchView.drag || (event.target instanceof Element && event.target.closest("button, a, input, textarea, select"))) {
        return;
      }
      const end = () => {
        matchView.drag = null;
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", release);
        window.removeEventListener("pointercancel", release);
      };
      matchView.drag = {x: event.clientX, y: event.clientY, id: event.pointerId, end};
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", release);
      window.addEventListener("pointercancel", release);
    });
  }

  /**
   * @param {object} card a decided match card.
   * @param {object} decision its {verdict, feedback, label}.
   * @returns {object} the inbox entry the release signs: an approval of the review or the ask, the picked option of a
   * decision, the operator row bound to the payload hash the card showed, or a rejection carrying the feedback as a
   * radio call to the card's agent.
   */
  function matchEntry(card, decision) {
    const kind = card.entry || (card.kind === "commit" ? "review" : "operator");
    const entry = {kind, id: card.ref, verb: decision.verdict === "accept" ? "approve" : "reject", label: decision.verdict === "accept" ? decision.label || "" : "", sha256: kind === "operator" ? card.sha256 || "" : ""};
    if (decision.verdict === "reject") {
      return {...entry, channel: "call", reason: decision.feedback, to: card.to || ""};
    }
    return card.kind === "command" ? {...entry, payload: card.hash} : entry;
  }

  function decided(cards) {
    return cards.map((card) => [card, matchView.decisions.get(cardKey(card))]).filter(([, decision]) => decision);
  }

  async function releaseMatch(cards) {
    const picked = decided(cards);
    const released = await submit(picked.map(([card, decision]) => matchEntry(card, decision)), `Release: ${picked.length === 1 ? "1 decision" : `${picked.length} decisions`}`);
    if (released) {
      const gone = new Set(picked.map(([card]) => card.id));
      matchView.epoch += 1;
      matchView.cards = matchView.cards.filter((card) => !gone.has(card.id));
      picked.forEach(([card]) => matchView.decisions.delete(cardKey(card)));
      matchView.overview = false;
      drawMatch(true);
      await fetchMatch();
    }
  }

  function overviewRow(card, decision) {
    const [kindName, kindTone, kindIcon] = MATCH_KINDS[card.kind] || [card.kind, "neutral", "bi-collection"];
    const [word, tone, mark] = MATCH_VERDICTS[decision.verdict];
    const other = decision.verdict === "accept" ? "reject" : "accept";
    const flip = (other === "reject" && pickOnly(card)) || (other === "accept" && !flies(card)) ? null : iconBtn(MATCH_VERDICTS[other][2], MATCH_VERDICTS[other][0], "btn small ghost match-flip", () => (other === "accept" ? acceptCard(card) : rejectCard(card)), `${MATCH_VERDICTS[other][0]} instead`);
    const back = iconBtn("bi-arrow-counterclockwise", "Back to the stack", "btn small ghost match-undecide", () => {
      matchView.decisions.delete(cardKey(card));
      matchView.overview = false;
      drawMatch(true);
    });
    return h("li", {class: "match-decision", "data-card": card.id, "data-verdict": decision.verdict},
      h("div", {class: "row"}, face(card.agent || "-", false), h("span", {class: "pill", "data-tone": kindTone}, icon(kindIcon), kindName), h("strong", {class: "match-decision-title"}, revealed(card.title)), h("span", {class: "spacer"}),
        h("span", {class: "pill match-verdict", "data-tone": tone}, icon(mark), decision.label ? revealed(`${word}: ${decision.label}`) : word), decision.verdict === "reject" ? iconBtn("bi-pencil", "Edit feedback", "btn small ghost match-edit", () => rejectCard(card)) : null, flip, back),
      decision.verdict === "reject" ? h("pre", {class: "match-decision-feedback"}, revealedLines(decision.feedback === "" ? "no feedback text" : decision.feedback)) : null);
  }

  /**
   * @param {Array<object>} cards the cards in stack order.
   * @returns {string} why the release waits, empty when it can go: a commit whose gate is not green is released
   * only on its own, as the inbox grants it.
   */
  function releaseBlock(cards) {
    const picked = decided(cards);
    if (!picked.length) {
      return "Nothing decided yet.";
    }
    const lone = picked.find(([card, decision]) => card.kind === "commit" && decision.verdict === "accept" && card.gate !== "pass");
    return lone && picked.length > 1 ? `The commit "${lone[0].title}" has no green gate and is released only on its own: send it back to the stack or release it alone.` : "";
  }

  function overview(cards, open) {
    const picked = decided(cards);
    const block = releaseBlock(cards);
    const release = h("button", {type: "button", class: "btn primary match-release", disabled: Boolean(block), title: block || "One passkey signature releases every decision; 3 s remain to undo."},
      icon("bi-key"), picked.length === 1 ? "Release 1 decision" : `Release ${picked.length} decisions`);
    release.addEventListener("click", () => releaseMatch(cards));
    const back = open ? iconBtn("bi-stack", `Back to the stack (${open})`, "btn ghost match-back", () => {
      matchView.overview = false;
      drawMatch(true);
    }) : null;
    return h("section", {class: "card match-overview", "aria-label": "Decisions"},
      h("h2", {class: "panel-title"}, "Decisions"),
      h("p", {class: "muted"}, "Nothing has run yet. Accepted commits get the operator's signature for their exact tree, accepted commands run once as jobs under Waits on Operator, accepted asks are granted, every picked option goes to its agent as a post, every rejection goes to its agent by radio call."),
      picked.length ? h("ol", {class: "match-decisions"}, picked.map(([card, decision]) => overviewRow(card, decision))) : h("p", {class: "muted"}, "No decision yet."),
      block && picked.length ? h("p", {class: "match-release-block"}, icon("bi-exclamation-triangle"), block) : null,
      h("div", {class: "actions"}, back, h("span", {class: "spacer"}), release));
  }

  function matchScreen() {
    const stack = h("div", {class: "match-stack"});
    const count = h("span", {class: "muted"});
    const tally = h("span", {class: "match-tally"}, "0");
    const decisions = h("button", {type: "button", class: "btn small soft match-open-overview", ...named("Decisions", "Decisions: the list of every decision, to change and release them"), on: {click: () => {
      matchView.overview = true;
      drawMatch(true);
    }}}, icon("bi-card-checklist"), tally);
    const peeks = h("button", {type: "button", class: "btn small soft match-peeks-toggle", "aria-pressed": String(peeksShown()), ...named("Next cards", "Next cards: show or hide the row of waiting cards below the buttons"), on: {click: () => {
      keep(STORE.peeks, !peeksShown());
      drawMatch(true);
    }}}, icon("bi-collection"));
    matchView.dom = {stack, count, decisions, tally, peeks};
    matchView.sig = "";
    if (matchView.drag) {
      matchView.drag.end();
    }
    const bar = h("div", {class: "card controls task-toolbar", role: "toolbar", "aria-label": "Match"}, h("strong", {}, icon("bi-stack"), "Match"), count, h("span", {class: "spacer"}), decisions, peeks,
      iconBtn("bi-list-check", "Tasks", "btn small soft", () => go("tasks", null), "Tasks: back to the task list"), h("span", {"data-star-slot": ""}));
    fetchMatch();
    return h("div", {class: "graph tasks match", "data-panel": "tasks/match"}, bar, stack);
  }

  /**
   * @returns {Element} the Match stack for a Home tile, kept while it still holds the live stack, without the
   * data-panel and toolbar of the screen: its card count and decisions button go to the tile head.
   */
  function homeMatch() {
    const kept = homeView.hosts.get("tasks/match");
    if (kept && matchView.dom && kept.contains(matchView.dom.stack)) {
      return kept;
    }
    const host = h("div", {class: "match-home"}, matchScreen());
    host.querySelectorAll("[data-panel]").forEach((node) => node.removeAttribute("data-panel"));
    host.querySelector(".task-toolbar").remove();
    homeView.heads.set("tasks/match", h("div", {role: "toolbar", "aria-label": "Match"}, matchView.dom.count, matchView.dom.decisions, matchView.dom.peeks));
    homeView.hosts.set("tasks/match", host);
    window.setTimeout(() => drawMatch(true), 0);
    return host;
  }

  function drawMatch(force) {
    const dom = matchView.dom;
    if (!dom || !dom.stack.isConnected) {
      return;
    }
    if (!matchView.loading && Date.now() - matchView.fetched > MATCH_REFRESH) {
      fetchMatch();
    }
    if (matchView.cards === null) {
      dom.stack.replaceChildren(h("p", {class: "muted"}, "Loading cards …"));
      return;
    }
    const cards = matchOrder(matchView.cards);
    const byKey = new Map(cards.map((card) => [cardKey(card), card]));
    [...matchView.decisions].forEach(([key, decision]) => {
      const card = byKey.get(key);
      if (!card || (decision.verdict === "accept" && card.stale)) {
        matchView.decisions.delete(key);
      }
    });
    const open = cards.filter((card) => !matchView.decisions.has(cardKey(card)));
    const shownOverview = matchView.overview || (!open.length && matchView.decisions.size > 0);
    const sig = JSON.stringify([cards.map((card) => [card.id, card.hash, card.live_hash, card.stale, card.born, card.gate, card.files ? card.files.length : null]), [...matchView.decisions], shownOverview, Math.floor(state.now / DAY)]);
    if (!force && sig === matchView.sig) {
      return;
    }
    matchView.sig = sig;
    const cleared = matchView.openBefore > 0 && !open.length;
    matchView.openBefore = open.length;
    dom.count.textContent = open.length === 1 ? "1 card waits" : `${open.length} cards wait`;
    dom.tally.textContent = String(matchView.decisions.size);
    dom.peeks.setAttribute("aria-pressed", String(peeksShown()));
    dom.decisions.hidden = !matchView.decisions.size || shownOverview;
    if (!cards.length) {
      matchView.front = null;
      dom.stack.replaceChildren(emptyState("No card waits", "Nothing waits on the operator."));
      return;
    }
    if (shownOverview) {
      matchView.front = null;
      const shown = overview(cards, open.length);
      if (cleared) {
        shown.prepend(confetti());
      }
      dom.stack.replaceChildren(shown);
      return;
    }
    const [front, ...rest] = open;
    matchView.front = front;
    const act = (cls, iconName, word, hint, disabled, run) => h("button", {type: "button", class: `match-act ${cls}`, disabled, ...named(word, hint), on: {click: run}},
      h("span", {class: "match-act-face", "aria-hidden": "true"}, icon(iconName)), h("span", {class: "match-act-label"}, word));
    const hint = front.stale ? `Accept: refused while the card is stale (${front.stale_reason})` : front.kind === "rule" ? "Accept: opens its row, where the passkey signs exactly this rule" : front.kind === "decision" ? (front.recommended ? `Accept: ${front.recommended} (right arrow, swipe right)` : "Accept: pick one of its options") : "Accept (right arrow, swipe right)";
    const accept = act("match-accept", "bi-check-lg", "Accept", revealed(hint), Boolean(front.stale) || (front.kind === "decision" && !front.recommended), () => acceptCard(front));
    const reject = act("match-reject", "bi-x-lg", "Reject", pickOnly(front) ? "Reject: a choice is answered with one of its options" : "Reject with feedback (left arrow, swipe left)", pickOnly(front), () => rejectCard(front));
    const later = act("match-later", "bi-arrow-up", "Later", "Later: to the back of the stack (up arrow, swipe up)", !rest.length, () => laterCard(front));
    const peeks = rest.length && peeksShown() ? h("div", {class: "match-peeks", role: "group", "aria-label": `${rest.length} more cards`}, rest.map(peekTab)) : null;
    const behind = rest.slice(0, MATCH_PEEKS).map((card, index) => {
      const sheet = h("div", {class: "match-behind", "aria-hidden": "true"});
      sheet.style.setProperty("--depth", String(index + 1));
      return sheet;
    });
    const before = dom.stack.querySelector(".match-card.front");
    const scrolled = before && before.dataset.card === front.id ? before.querySelector(".match-body").scrollTop : 0;
    const shown = matchCard(front);
    shown.dataset.fresh = String(!before || before.dataset.card !== front.id);
    draggable(shown, front);
    dom.stack.replaceChildren(h("div", {class: "match-deck"}, behind, shown), h("div", {class: "match-actions"}, reject, later, accept), peeks);
    shown.querySelector(".match-body").scrollTop = scrolled;
  }
