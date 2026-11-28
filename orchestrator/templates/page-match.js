  const MATCH_PEEKS = 2;
  const LONG_PRESS = 550;
  const PRESS_SLOP = 10;
  const MATCH_KINDS = {commit: ["Commit", "info", "bi-git"], command: ["Command", "warn", "bi-terminal"], ask: ["Ask", "warn", "bi-shield-lock"], decision: ["Decision", "info", "bi-signpost-split"], rule: ["Rule", "neutral", "bi-shield-check"]};
  const MATCH_VERDICTS = {accept: ["Accept", "ok", "bi-check-lg"], reject: ["Reject", "bad", "bi-x-lg"], drop: ["Drop (expired)", "neutral", "bi-trash"]};
  const SWIPE_SHARE = 0.25;
  const SWIPE_UP = 80;
  const FEEDBACK_LIMIT = 2000;
  const FLY_MS = 400;
  const CONFETTI = 28;
  const CONFETTI_GONE = 9000;
  const DROPS_KEPT = 200;
  const COMMENTS_KEPT = 5;
  const PATTERNS = ["dots", "stripes", "waves", "grid", "rings"];
  const RELEASE = "release";
  const MATCH_STAMPS = {running: "RUNNING", queued: "QUEUED", stale: "STALE", expired: "EXPIRED", claude: "IN CLAUDE", blocked: "BLOCKED"};
  const lapsedCard = (card) => card.blocked_kind === "expired" || card.blocked_kind === "claude";
  const droppable = (card) => card.blocked_kind === "expired";

  /**
   * @param {object} card a lapsed card (lapsedCard()) with its expires time in epoch seconds.
   * @returns {string} the stamp's tooltip: the clock time its hook stopped waiting and how long ago, as "expired 14:02,
   * 12 minutes ago", for a card whose dialog is still open in Claude as "open in Claude since 14:02, 12 minutes ago".
   */
  function expiredWords(card) {
    const since = `${clock.format(stampOf(card.expires))}, ${ago(card.expires)}`;
    return card.blocked_kind === "claude" ? `open in Claude since ${since}` : `expired ${since}`;
  }

  /**
   * @param {object} card a card as /api/match serves it.
   * @returns {string} why it is greyed, a MATCH_STAMPS key: stale first, else its blocked_kind (running or queued), any
   * other block as blocked; "" for a card that can act.
   */
  function greyStamp(card) {
    if (card.stale) {
      return "stale";
    }
    if (!card.blocked) {
      return "";
    }
    return Object.hasOwn(MATCH_STAMPS, card.blocked_kind) ? card.blocked_kind : "blocked";
  }

  const MATCH_SHOWS = [...Object.entries(MATCH_KINDS).map(([kind, [word]]) => [kind, word]), ["expired", "Expired"], ["stale", "Stale"], ["greyed", "Greyed"]];
  const SHOW_STATES = {stale: "stale", expired: "expired", claude: "expired", running: "greyed", queued: "greyed", blocked: "greyed"};
  const showState = (card) => SHOW_STATES[greyStamp(card)] || "";
  const shownCard = (card, hidden) => !hidden.has(card.kind) && !hidden.has(showState(card));
  const hiddenWords = (count) => `${count} hidden`;
  const allHiddenWords = (count) => `All ${count} ${count === 1 ? "card" : "cards"} hidden by the Show filter`;

  /**
   * @returns {Set<string>} the MATCH_SHOWS keys this browser's Show filter hides; any other stored value is ignored.
   */
  function matchHidden() {
    const kept = stored(STORE.show, []);
    return new Set(Array.isArray(kept) ? kept.filter((key) => MATCH_SHOWS.some(([one]) => one === key)) : []);
  }

  /**
   * @param {Array<object>} cards the cards in stack order.
   * @param {Set<string>} hidden the MATCH_SHOWS keys the Show filter hides.
   * @returns {object} open: the undecided cards; shown: those of them the filter lets through; hidden: how many it
   * hides. A decided card is never hidden: it stays on the release card and goes out with the release.
   */
  function showSplit(cards, hidden) {
    const open = cards.filter((card) => !decisionOf(card));
    const shown = open.filter((card) => shownCard(card, hidden));
    return {open, shown, hidden: open.length - shown.length};
  }

  /**
   * @param {Array<object>} open the undecided cards.
   * @returns {object} per MATCH_SHOWS key how many of them it covers: each card counts once for its kind and once for
   * its state (showState()), an acting card for no state.
   */
  function showCounts(open) {
    return Object.fromEntries(MATCH_SHOWS.map(([key]) => [key, open.filter((card) => card.kind === key || showState(card) === key).length]));
  }

  /**
   * @param {string} key a MATCH_SHOWS key: shown again when hidden, hidden when shown, remembered in this browser.
   */
  function toggleShow(key) {
    const hidden = matchHidden();
    if (hidden.has(key)) {
      hidden.delete(key);
    } else {
      hidden.add(key);
    }
    keep(STORE.show, [...hidden]);
    drawMatch(true);
  }

  function showAll() {
    keep(STORE.show, []);
    drawMatch(true);
  }

  /**
   * @returns {Array<object>} the Show items of the context menu: per MATCH_SHOWS key a checkbox with the count of the
   * undecided cards it covers, then Show all; none before the first fetch.
   */
  function matchShowItems() {
    if (!matchView.cards) {
      return [];
    }
    const counts = showCounts(showSplit(matchView.cards, new Set()).open);
    return [...MATCH_SHOWS.map(([key, word]) => ({label: word, hint: String(counts[key]), checked: () => !matchHidden().has(key), run: () => toggleShow(key)})),
      {label: "Show all", hint: "every kind and state", run: showAll}];
  }

  /**
   * @param {Event} event the click on the "N hidden" button of the Match head: it opens the context menu under it and
   * stops there, since menuClick() on the document would close the menu again at once.
   */
  function openShowMenu(event) {
    const button = event.currentTarget;
    const box = button.getBoundingClientRect();
    event.stopPropagation();
    ctxOpen(button, {x: box.left, y: box.bottom});
  }
  const MOVES = {ArrowRight: "accept", d: "accept", ArrowLeft: "reject", a: "reject", ArrowUp: "later", w: "later", s: "undo"};
  const matchView = {cards: null, order: [], marks: new Map(), opened: new Map(), decisions: new Map(), toggles: new Map(), history: [], release: null, releasing: false, front: null, drag: null, dom: null, sig: "", fetched: 0, loading: false, press: null, flying: false, openBefore: 0, epoch: 0, timer: null, turn: 0};

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
          const dropped = new Set(droppedKeys());
          matchView.cards = (Array.isArray(data.cards) ? data.cards : []).filter((card) => !dropped.has(cardKey(card)));
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
    matchCycle();
  }

  const matchRefresh = () => MatchClock.bounded(settings.match.refresh);
  const matchShown = () => Boolean(matchView.dom && matchView.dom.stack.isConnected);

  /**
   * @param {HTMLElement} glass a refresh hourglass of matchGlass().
   * Gives it the current turn, its sand the interval as --match-refresh and its tooltip the interval.
   */
  function glassLook(glass) {
    const seconds = matchRefresh();
    glass.dataset.turn = String(matchView.turn);
    glass.style.setProperty("--match-refresh", `${seconds}s`);
    glass.title = `Refresh: Match fetches the cards every ${seconds} s; a click fetches now, a right-click sets the interval`;
  }

  function matchCycle() {
    window.clearTimeout(matchView.timer);
    matchView.timer = null;
    if (!matchShown()) {
      return;
    }
    matchView.turn += 1;
    document.querySelectorAll(".match-glass").forEach((glass) => {
      glassLook(glass);
      glass.replaceChildren(glassFace());
    });
    matchView.timer = window.setTimeout(() => {
      if (matchShown()) {
        fetchMatch();
      }
    }, MatchClock.wait(Date.now(), matchView.fetched, matchRefresh()));
  }

  function refreshDial() {
    const picked = dial({value: matchRefresh(), label: "Match refresh in seconds", name: "match-refresh-dial", min: MatchClock.MIN, max: MatchClock.MAX, page: MatchClock.PAGE, readout: Dial.countdown,
      spoken: (seconds) => `Match fetches the cards every ${seconds} seconds`, readonly: false, live: null});
    const save = async () => {
      const refresh = picked.value();
      if (refresh === settings.match.refresh || await saveSettings({...settings, space: savedSpace(), match: {refresh}})) {
        closeSheet();
        fetchMatch();
      }
    };
    openSheet("Match refresh", h("div", {class: "stack match-refresh-sheet"},
      h("p", {class: "muted"}, `How often Match fetches its cards, ${MatchClock.MIN} to ${MatchClock.MAX} s. Drag the hand, click a tick, or use the arrows (1 s) and Page Up / Down (${MatchClock.PAGE} s).`), picked.root,
      h("div", {class: "sheet-foot"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), btn("Save", "btn primary match-refresh-save", save))), false);
    picked.root.focus({preventScroll: true});
  }

  /**
   * @returns {HTMLElement} the refresh hourglass of the empty deck: it flips after every fetch and its sand runs for
   * the interval; a click fetches at once and restarts the cycle, a right-click opens the dial for the interval.
   */
  function matchGlass() {
    const glass = h("button", {type: "button", class: "match-glass large", "aria-label": "Refresh", on: {click: () => fetchMatch(), contextmenu: (event) => {
      event.preventDefault();
      refreshDial();
    }}}, glassFace());
    glassLook(glass);
    return glass;
  }

  const toFront = (id) => {
    matchView.order = [id, ...matchView.order.filter((one) => one !== id)];
  };
  const toBack = (id) => {
    matchView.order = [...matchView.order.filter((one) => one !== id), id];
  };

  /**
   * @param {string[]} kept the order so far: card ids and RELEASE.
   * @param {string[]} fresh the ids of the cards new to the stack.
   * @param {Set<string>} open the ids of the undecided cards.
   * @returns {string[]} kept with the fresh cards queued before the release card, or behind it while it is the front
   * card the operator sees now; the release card keeps its place in the round.
   */
  function releaseLast(kept, fresh, open) {
    const at = kept.indexOf(RELEASE);
    const front = kept.find((id) => id === RELEASE || open.has(id));
    return at < 0 || front === RELEASE ? [...kept, ...fresh] : [...kept.slice(0, at), ...fresh, ...kept.slice(at)];
  }

  /**
   * @param {string} id the card the step acts on, or RELEASE.
   * Keeps the order and the card's decision from before the step, so S can put both back.
   */
  function logStep(id) {
    matchView.history.push({id, order: [...matchView.order], decision: matchView.decisions.get(id)});
  }

  function undoStep() {
    const step = matchView.history.pop();
    if (!step) {
      toast("Nothing to undo", ["Every step back to the last release is undone."], false);
      return;
    }
    matchView.order = step.order;
    if (step.decision) {
      matchView.decisions.set(step.id, step.decision);
    } else {
      matchView.decisions.delete(step.id);
    }
    drawMatch(true);
  }

  function matchOrder(cards) {
    const ids = new Set(cards.map((card) => card.id));
    const kept = matchView.order.filter((id) => ids.has(id) || id === RELEASE);
    const fresh = cards.filter((card) => !kept.includes(card.id)).sort((a, b) => Number(Boolean(a.blocked)) - Number(Boolean(b.blocked)) || Number(a.stale) - Number(b.stale) || (a.created_ts || 0) - (b.created_ts || 0));
    const open = new Set(cards.filter((card) => !decisionOf(card)).map((card) => card.id));
    matchView.order = releaseLast(kept, fresh.map((card) => card.id), open);
    const byId = new Map(cards.map((card) => [card.id, card]));
    return matchView.order.filter((id) => id !== RELEASE).map((id) => byId.get(id));
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
   * @param {object} card a card as /api/match serves it now.
   * @returns {object|undefined} its decision: a reject or drop by card id whatever the card's hash, an accept only for
   * the exact hash it was made on.
   */
  function decisionOf(card) {
    const decision = matchView.decisions.get(card.id);
    return decision && (decision.verdict !== "accept" || decision.hash === card.hash) ? decision : undefined;
  }

  /**
   * @returns {string[]} this browser's last COMMENTS_KEPT distinct saved line comments, newest first.
   */
  function savedComments() {
    const kept = stored(STORE.comments, []);
    return Array.isArray(kept) ? kept.filter((text) => typeof text === "string" && text).slice(0, COMMENTS_KEPT) : [];
  }

  const peeksShown = () => stored(STORE.peeks, true) !== false;
  const matchWide = () => stored(STORE.wide, false) === true;

  function widenToggle() {
    const wide = matchWide();
    return iconBtn(wide ? "bi-arrows-angle-contract" : "bi-arrows-angle-expand", wide ? "Normal width" : "Full width", "btn small ghost match-widen", () => {
      keep(STORE.wide, !matchWide());
      drawMatch(true);
    }, wide ? "Normal width: the card back to at most 960 px" : "Full width: the card over the whole Match area");
  }

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
  const pickOnly = (card) => card.kind === "decision" && card.entry === "decision" && !Answers.pair(card);
  const needsPick = (card) => card.kind === "decision" && !card.recommended && !Answers.pair(card);
  const acceptLabel = (card) => (card.kind !== "decision" ? "" : Answers.pair(card) ? Answers.pair(card).yes : card.recommended);
  const flies = (card) => !card.blocked && !card.stale && card.kind !== "rule" && !needsPick(card);

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
      return h("summary", {class: "diff-head"}, h("span", {class: "letter", "data-tone": tone}, file.status), pathCode(card.worktree || card.directory, file.path, revealed(file.path)), h("span", {class: "spacer"}),
        file.note ? h("span", {class: "note", title: file.note}, icon("bi-eye-slash"), file.note) : null, marks, stat);
    }
    const tone = file.state === "read" ? "ok" : "bad";
    return h("summary", {class: "diff-head"}, h("span", {class: "letter", "data-tone": tone}, icon("bi-file-earmark-text")), pathCode(card.worktree || card.directory, file.path, revealed(file.path)), h("span", {class: "spacer"}),
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
    vanish(card.querySelector(".match-comment:not([data-vanishing])"));
  }

  function commentField(card, data, row) {
    const article = row.closest(".match-card");
    closeComment(article);
    const file = row.closest(".match-file");
    const words = h("textarea", {class: "field", rows: 2, "aria-label": "Comment", placeholder: "Comment on this line", "data-skills": card.repo || ""});
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

  function codeRow(event, selector) {
    const row = event.target instanceof Element ? event.target.closest(selector) : null;
    return row && !row.classList.contains("match-mark") && !row.classList.contains("match-comment") ? row : null;
  }

  /**
   * @param {HTMLElement} root the element whose code rows take marks: a Match card or the review modal's diff.
   * @param {string} selector the code rows inside root.
   * @param {Function} open takes the row a right-click or a touch long press hit and opens its comment field;
   * Shift+right-click keeps the browser's own menu.
   */
  function markable(root, selector, open) {
    root.addEventListener("contextmenu", (event) => {
      const row = event.shiftKey ? null : codeRow(event, selector);
      if (row) {
        event.preventDefault();
        event.stopPropagation();
        open(row);
      }
    });
    root.addEventListener("pointerdown", (event) => {
      const row = codeRow(event, selector);
      if (!row || event.pointerType !== "touch") {
        return;
      }
      const press = {x: event.clientX, y: event.clientY, timer: window.setTimeout(() => {
        matchView.press = null;
        open(row);
      }, LONG_PRESS)};
      matchView.press = press;
    });
    const drop = () => {
      if (matchView.press) {
        window.clearTimeout(matchView.press.timer);
        matchView.press = null;
      }
    };
    root.addEventListener("pointermove", (event) => {
      if (matchView.press && Math.hypot(event.clientX - matchView.press.x, event.clientY - matchView.press.y) > PRESS_SLOP) {
        drop();
      }
    });
    root.addEventListener("pointerup", drop);
    root.addEventListener("pointercancel", drop);
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

  /**
   * @param {string} place branch, repo or worktree.
   * @param {string} iconName the chip's icon.
   * @param {string} label what the chip names.
   * @param {string} value the full branch name or path.
   * @param {string} words the short text the chip shows.
   * @returns {HTMLElement} a path chip as a pathLink() when value is absolute, otherwise a button whose click copies value.
   */
  function placeChip(place, iconName, label, value, words) {
    const full = revealed(value);
    const link = place === "branch" ? null : pathLink(value, {class: "match-where", "data-place": place, title: `${label}: ${full} (${PATH_ACTIONS})`, "aria-label": `${label}: ${full}, ${PATH_ACTIONS}`},
      icon(iconName), h("span", {}, revealed(words)));
    if (link) {
      return link;
    }
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
    return h("header", {class: "match-head"}, widenToggle(),
      h("div", {class: "match-who"}, agentLink(card.agent || "-", true, "match-name"), h("span", {class: "match-age"}, ageWords(card.born))),
      metrics.length ? h("ul", {class: "match-metrics", "aria-label": "Scores"}, metrics.map((metric) => h("li", {class: "match-metric", "data-metric": metric.id, title: revealed(`${metric.label}: ${metric.value}`)},
        h("span", {"aria-hidden": "true"}, metric.emoji), h("span", {class: "match-metric-label"}, metric.label), h("strong", {}, revealed(metric.value))))) : null,
      h("div", {class: "states"}, h("span", {class: "pill", "data-tone": kindTone}, icon(kindIcon), kindName), card.gate ? pill(`gate ${card.gate}`, card.gate === "pass" ? "ok" : "bad") : null,
        card.score && !metrics.length ? h("span", {class: "pill", "data-tone": "neutral"}, revealed(card.score)) : null, card.stale ? h("span", {class: "pill match-stale-pill", "data-tone": "bad"}, icon("bi-hourglass-split"), "stale") : null),
      placeRow(card),
      h("h2", {class: "match-title", title: card.title_full || null}, revealed(card.title)),
      card.stale ? h("p", {class: "match-stale"}, icon("bi-exclamation-triangle"), revealed(card.stale_reason)) : null);
  }

  /**
   * @param {Object} card a decision card; a multi one keeps its toggled options in matchView.toggles across redraws until Send.
   * @returns {HTMLElement} its choiceDialog(); an answer is picked now and sent at the release.
   */
  function matchOptions(card) {
    const key = cardKey(card);
    const kept = decisionOf(card);
    const toggled = matchView.toggles.get(key) || new Set(kept ? kept.label.split(PICKED) : []);
    matchView.toggles.set(key, toggled);
    const pick = (label) => {
      matchView.toggles.delete(key);
      decide(card, "accept", "", label);
    };
    return choiceDialog({...card, id: card.ref}, {pick, toggled, chosen: kept ? kept.label : "", locked: lapsedCard(card), hint: `picked now, sent to ${card.agent || "its agent"} at the release`, group: "match-options", other: OTHER_PROMPT});
  }

  function matchPayload(card) {
    if (card.kind === "decision") {
      return h("section", {class: "match-payload"}, card.reason && card.reason !== "-" ? h("p", {class: "match-reason"}, revealed(card.reason)) : null, Answers.pair(card) ? null : matchOptions(card));
    }
    if (card.kind === "rule") {
      return h("section", {class: "match-payload"}, ruleRequestBody({...card, detail: card.reason}));
    }
    if (card.kind === "ask") {
      return h("section", {class: "match-payload"}, h("p", {class: "match-directory"}, revealed(card.directory)),
        card.warnings.length ? h("p", {class: "match-warnings"}, card.warnings.map((warning) => pill(warning, "bad"))) : null, card.merge ? matchPreviewLine(card.merge) : null);
    }
    if (card.kind !== "command") {
      return null;
    }
    return h("section", {class: "match-payload"},
      h("p", {class: "match-directory"}, revealed(card.directory)),
      card.reason && card.reason !== "-" ? h("p", {class: "match-reason"}, revealed(card.reason)) : null, card.merge ? matchPreviewLine(card.merge) : null);
  }

  /**
   * @param {Object} merge the runner preview of a card: kind merge or commit-tree, head, base, target, and error, the git
   * error line that kept the diff, "" for none.
   * @returns {HTMLElement} the line naming what the diff below shows, or its error in place of the diff.
   */
  function matchPreviewLine(merge) {
    const short = (oid) => oid.slice(0, 12);
    const tree = merge.kind === "commit-tree";
    const words = merge.error ? `${tree ? "No commit-tree diff" : "No merge preview"}: ${merge.error}`
      : tree ? `Commits tree ${short(merge.target)} onto parent ${short(merge.base)}` : `Brings in ${short(merge.base)} → ${short(merge.target)}, onto HEAD ${short(merge.head)}`;
    return h("p", {class: "match-merge", "data-kind": merge.kind, "data-error": String(Boolean(merge.error))}, icon(merge.error ? "bi-exclamation-triangle" : tree ? "bi-git" : "bi-sign-merge-left"), words);
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
    const previewed = card.merge ? (card.merge.error ? "No diff to show." : card.merge.kind === "commit-tree" ? "The commit changes no file." : "The merge brings no change.") : "";
    const none = card.kind === "commit" ? (card.diff_error ? `No diff shipped with this stage. ${card.diff_error}` : "No diff shipped with this stage.") : previewed || (card.kind === "ask" ? "Its tool call changes no file." : "Its command names no file.");
    const list = files.length ? h("ol", {class: "match-files", "aria-label": `Files: ${files.length}`}, files.map((file, index) => fileBlock(card, file, index))) : card.kind === "decision" || card.kind === "rule" ? null : h("p", {class: "muted"}, none);
    const commanded = card.kind === "ask" || card.kind === "command";
    const command = commanded ? h("pre", {class: "match-command"}, h("code", {}, revealed(card.command))) : null;
    const code = command || files.length ? codeBox(card.id, "open", [command, list], commanded ? card.command : "", [], null) : list;
    const body = h("div", {class: "match-body"}, card.blocked ? h("p", {class: "match-blocked"}, icon("bi-hourglass-split"), revealed(card.blocked)) : null, matchPayload(card), code);
    body.addEventListener("scroll", () => openOnScroll(body, ".match-file"), {passive: true});
    const stamp = greyStamp(card);
    const article = h("article", {class: "card match-card front", "data-card": card.id, "data-kind": card.kind, "data-stale": String(Boolean(card.stale)), ...(card.blocked ? {"data-blocked": "", title: card.blocked} : {}), "aria-label": `${card.kind} card of ${card.agent || "an agent"}`},
      matchHead(card), body, stamp ? h("span", {class: "match-stamp", "data-stamp": stamp, ...(lapsedCard(card) ? {title: expiredWords(card), on: {mouseenter: (event) => {
        event.currentTarget.title = expiredWords(card);
      }}} : {"aria-hidden": "true"})}, MATCH_STAMPS[stamp]) : null);
    article.style.setProperty("--agent-hue", String(Faces.hash(card.agent) % 360));
    paint(article, card.id);
    markable(article, ".match-file tr[data-line]", (row) => commentField(article, card, row));
    window.setTimeout(() => openOnScroll(body, ".match-file"), 0);
    return article;
  }

  function peekTab(card) {
    const [kindName, kindTone] = MATCH_KINDS[card.kind] || [card.kind, "neutral"];
    return h("button", {type: "button", class: "match-peek", "data-card": card.id, "data-stale": String(Boolean(card.stale)), ...(card.blocked ? {"data-blocked": ""} : {}), ...named(`Show ${kindName.toLowerCase()} card: ${card.title}`, card.blocked ? `${card.title}: ${card.blocked}` : undefined), on: {click: () => {
      toFront(card.id);
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
    if (!front || front.classList.contains("match-release-card") || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
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
      logStep(card.id);
      refusedIds.delete(card.ref);
      matchView.decisions.set(card.id, {verdict, feedback, label, hash: card.hash, card, risk: false});
      drawMatch(true);
    });
  }

  /**
   * @param {object} card an expired card (droppable()): it leaves the deck at once with the vanish() fade, without a
   * feedback sheet or a radio message, and the next release dismisses it in the hub for every browser; S puts it back.
   */
  function dropCard(card) {
    logStep(card.id);
    refusedIds.delete(card.ref);
    matchView.decisions.set(card.id, {verdict: "drop", feedback: "", label: "", hash: card.hash, card, risk: false});
    drawMatch(true);
  }

  function confetti() {
    document.querySelectorAll(".confetti-rain").forEach((old) => vanish(old));
    if (calm.matches) {
      return;
    }
    const bar = document.getElementById("head");
    const top = bar ? Math.max(0, Math.round(bar.getBoundingClientRect().bottom)) : 0;
    const layer = h("div", {class: "confetti-rain", "aria-hidden": "true"}, Array.from({length: CONFETTI}, (_, index) => {
      const bit = h("i", {});
      bit.style.setProperty("--x", String(((index * 37) % 100) / 100));
      bit.style.setProperty("--c", String((index * 47) % 360));
      bit.style.setProperty("--r", `${(index % 2 ? 1 : -1) * 180 * (1 + (index % 3))}deg`);
      bit.style.setProperty("--d", `${(index % 7) * 0.1}s`);
      bit.style.setProperty("--t", `${1.4 + (index % 5) * 0.25}s`);
      return bit;
    }));
    layer.style.setProperty("--top", `${top}px`);
    layer.style.setProperty("--fall", `${Math.max(0, window.innerHeight - top)}px`);
    const end = () => vanish(layer);
    layer.addEventListener("animationend", (event) => event.target === layer && end());
    window.setTimeout(end, CONFETTI_GONE);
    document.body.append(layer);
  }

  /**
   * @returns {boolean} whether the card can not act here; the toast then names its reason under the verdict.
   */
  function refusedHere(card, verdict) {
    const refused = Boolean(card.blocked) && !(verdict === "Reject" && lapsedCard(card));
    if (refused) {
      toast(`${verdict}: not possible now`, [card.blocked], false);
    }
    return refused;
  }

  function acceptCard(card) {
    if (refusedHere(card, "Accept")) {
      return;
    }
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
    if (needsPick(card)) {
      toast("Accept: pick one of its options", ["The decision recommends none, so the card waits for your pick."], false);
      return;
    }
    decide(card, "accept", "", acceptLabel(card));
  }

  function rejectCard(card) {
    if (refusedHere(card, "Reject")) {
      return;
    }
    if (droppable(card)) {
      dropCard(card);
      return;
    }
    if (pickOnly(card) && !lapsedCard(card)) {
      toast("Reject: not possible", ["A choice is answered with one of its options."], false);
      return;
    }
    const kept = decisionOf(card);
    const words = h("textarea", {class: "field match-feedback", rows: 6, maxlength: FEEDBACK_LIMIT, "aria-label": "Feedback", "data-skills": card.repo || ""});
    words.value = (kept && kept.verdict === "reject" ? kept.feedback : feedbackOf(card)).slice(0, FEEDBACK_LIMIT);
    const confirm = h("button", {type: "button", class: "btn danger match-feedback-reject"}, icon("bi-x-lg"), "Reject");
    const pair = card.kind === "decision" && !lapsedCard(card) ? Answers.pair(card) : null;
    confirm.addEventListener("click", () => {
      closeSheet();
      decide(card, "reject", words.value.trim(), pair ? Answers.declined(pair.no, words.value, OTHER_LIMIT) : "");
    });
    const note = `${card.agent || "The agent"} gets this text by radio call at the release; nothing is sent before.`;
    openSheet(`Reject: ${card.title}`, [h("p", {class: "muted"}, note), reasonChips(words), words, h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), confirm)], false);
    words.focus();
  }

  function laterCard(card) {
    flyOff("later", () => {
      logStep(card.id);
      toBack(card.id);
      drawMatch(true);
    });
  }

  /**
   * @param {string} key the key of a keydown the global handler did not take.
   * @returns {boolean} whether the Match stack took it: D or the right arrow accepts the front card, A or the left
   * arrow rejects it, W or the up arrow skips to the next card, S undoes the last step; on the release card D
   * releases, A and W go on to the next card.
   */
  function matchKey(key) {
    const move = MOVES[key.length === 1 ? key.toLowerCase() : key];
    if (!move || ui.screen !== "match" || !matchView.dom || !matchView.dom.stack.isConnected) {
      return false;
    }
    if (move === "undo") {
      undoStep();
      return true;
    }
    if (matchView.release) {
      const run = matchView.release[move];
      if (run) {
        run();
      }
      return Boolean(run);
    }
    const card = matchView.front;
    if (card && !(move === "accept" && lapsedCard(card))) {
      ({accept: acceptCard, reject: rejectCard, later: laterCard})[move](card);
    }
    return Boolean(card);
  }

  /**
   * @param {HTMLElement} article the front card, dragged by its head.
   * @param {object} acts what a swipe runs: accept (right), reject (left), later (up); a missing one leaves the card.
   * @param {Function} stays takes the swipe and tells whether the card keeps its offset while it flies off.
   */
  function draggable(article, acts, stays) {
    const head = article.querySelector(".match-head");
    const move = (event) => {
      const drag = matchView.drag;
      if (drag && drag.id === event.pointerId) {
        const [dx, dy] = [event.clientX - drag.x, event.clientY - drag.y];
        const up = -dy > Math.abs(dx);
        article.style.transform = `translate(${dx}px, ${Math.min(0, dy)}px) rotate(${dx / 40}deg)`;
        const lean = up ? "later" : dx > 0 ? "accept" : dx < 0 ? "reject" : "";
        article.dataset.leaning = acts[lean] ? lean : "";
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
      if (!(acts[swiped] && stays(swiped))) {
        article.style.removeProperty("transform");
        delete article.dataset.leaning;
      }
      if (!article.isConnected || !acts[swiped]) {
        return;
      }
      acts[swiped]();
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
   * decision, the operator row bound to the payload hash the card showed, a rejection carrying the feedback as a
   * radio call to the card's agent, or for a drop the hub-wide dismissal of the expired request, which tells no agent.
   */
  function matchEntry(card, decision) {
    const kind = card.entry || (card.kind === "commit" ? "review" : "operator");
    if (decision.verdict === "drop") {
      return {kind: "dismiss", target: kind, id: card.ref, scope: "expired"};
    }
    const entry = {kind, id: card.ref, verb: decision.verdict === "accept" ? "approve" : "reject", label: decision.verdict === "accept" ? decision.label || "" : "", sha256: kind === "operator" ? card.sha256 || "" : ""};
    if (card.kind === "decision" && Answers.pair(card) && !lapsedCard(card)) {
      return {...entry, verb: "approve", label: decision.label};
    }
    if (decision.verdict === "reject") {
      return {...entry, channel: "call", reason: decision.feedback, to: card.to || ""};
    }
    return card.kind === "command" ? {...entry, payload: card.hash} : entry;
  }

  /**
   * @param {Array<object>} cards the cards /api/match serves now, in stack order.
   * @returns {Array<Array>} [card, decision] pairs: the decided cards in stack order, then each reject whose card is
   * gone, as its card from the time of the reject marked withdrawn.
   */
  function decided(cards) {
    const here = new Set(cards.map((card) => card.id));
    const shown = cards.map((card) => [card, decisionOf(card)]).filter(([, decision]) => decision);
    const gone = [...matchView.decisions.values()].filter((decision) => !here.has(decision.card.id)).map((decision) => [{...decision.card, withdrawn: true}, decision]);
    return [...shown, ...gone];
  }

  const risky = (card, decision) => card.kind === "commit" && decision.verdict === "accept" && card.gate !== "pass";
  const decisionWords = (count) => (count === 1 ? "1 decision" : `${count} decisions`);

  /**
   * @param {object} card a card on the release card.
   * @param {object} decision its decision.
   * @returns {string} why the release cannot carry the row now, "" when it can: the hub refused it last time, it was
   * accepted and expired since, or it is blocked; a reject or drop of a lapsed card still releases.
   */
  function unreleasable(card, decision) {
    if (card.withdrawn) {
      return "";
    }
    const refused = refusedIds.get(card.ref);
    if (refused) {
      return `the hub refused it: ${refused}; reject or drop it`;
    }
    const lapsed = lapsedCard(card);
    if (lapsed && decision.verdict === "accept") {
      return `${expiredWords(card)}: can no longer be granted; reject or drop it`;
    }
    return card.blocked && !(lapsed && decision.verdict !== "accept") ? `not possible now: ${card.blocked}; drop it or send it back to the stack` : "";
  }

  /**
   * @param {Array<Array>} picked [card, decision] pairs from decided().
   * @returns {object} lone: risk-accepted red-gate commits, each signed on its own first; rest: every other accept and
   * reject, signed together with dismissals: the dropped expired cards, dismissed in the hub without a radio message;
   * gone: withdrawn rejects, sent by radio only, a withdrawn drop needing nothing; held: red-gate commits whose risk is
   * not accepted, which block the release until each is risk-accepted or sent back to the stack; bad: rows
   * unreleasable() names, which block the release until each is changed or dropped.
   */
  function releasePlan(picked) {
    const signed = picked.filter(([card]) => !card.withdrawn);
    const bad = signed.filter(([card, decision]) => unreleasable(card, decision));
    const good = signed.filter((pair) => !bad.includes(pair));
    return {
      lone: good.filter(([card, decision]) => risky(card, decision) && decision.risk),
      rest: good.filter(([card, decision]) => !risky(card, decision) && decision.verdict !== "drop"),
      dismissals: good.filter(([, decision]) => decision.verdict === "drop"),
      gone: picked.filter(([card, decision]) => card.withdrawn && decision.verdict !== "drop"),
      held: good.filter(([card, decision]) => risky(card, decision) && !decision.risk),
      bad,
    };
  }

  const droppedKeys = () => {
    const kept = stored(STORE.dropped, []);
    return Array.isArray(kept) ? kept.filter((key) => typeof key === "string") : [];
  };

  /**
   * @param {Array<Array>} bad the unreleasable [card, decision] pairs: their decisions go, their cards leave the deck
   * in this browser for good, the last DROPS_KEPT dropped cards remembered.
   */
  function dropUnreleasable(bad) {
    const keys = bad.map(([card]) => cardKey(card));
    bad.forEach(([card]) => {
      matchView.decisions.delete(card.id);
      refusedIds.delete(card.ref);
    });
    keep(STORE.dropped, [...keys, ...droppedKeys().filter((key) => !keys.includes(key))].slice(0, DROPS_KEPT));
    const gone = new Set(bad.map(([card]) => card.id));
    matchView.cards = matchView.cards.filter((card) => !gone.has(card.id));
    matchView.order = matchView.order.filter((id) => !gone.has(id));
    matchView.history = [];
    toast(`Dropped ${decisionWords(bad.length)}`, bad.map(([card]) => card.title), true);
    drawMatch(true);
  }

  async function releaseMatch(cards) {
    const plan = releasePlan(decided(cards));
    if (plan.bad.length) {
      toast("Release: not possible", plan.bad.map(([card, decision]) => `${card.title}: ${unreleasable(card, decision)}`), false);
      return;
    }
    const together = [...plan.rest, ...plan.dismissals];
    if (matchView.releasing || plan.held.length || !(plan.lone.length + together.length + plan.gone.length)) {
      return;
    }
    matchView.releasing = true;
    const names = new Map([...plan.lone, ...together].map(([card]) => [card.ref, card.title]));
    const done = [];
    try {
      for (const pair of plan.lone) {
        if (!(await submit([matchEntry(...pair)], `Release: ${pair[0].title}`, names))) {
          return;
        }
        done.push(pair);
      }
      if (together.length && !(await submit(together.map((pair) => matchEntry(...pair)), `Release: ${decisionWords(together.length)}`, names))) {
        return;
      }
      done.push(...together, ...plan.gone);
    } finally {
      matchView.releasing = false;
      if (done.length) {
        await settleRelease(done);
      } else {
        drawMatch(true);
      }
    }
  }

  /**
   * @param {Array<Array>} done the released [card, decision] pairs: their cards leave the stack, a withdrawn reject
   * goes to its agent by radio call, the line notes of an accepted card by post.
   */
  async function settleRelease(done) {
    const gone = new Set(done.map(([card]) => card.id));
    matchView.epoch += 1;
    matchView.cards = matchView.cards.filter((card) => !gone.has(card.id));
    done.forEach(([card]) => matchView.decisions.delete(card.id));
    matchView.history = [];
    drawMatch(true);
    await fetchMatch();
    for (const [card, decision] of done) {
      if (card.withdrawn) {
        await radioSend({to: card.to || card.agent, text: `Rejected: ${card.title}. The card was withdrawn before the release. Feedback:\n${decision.feedback}`, upload: "", cls: "call", voice: ""});
        continue;
      }
      const notes = decision.verdict === "accept" ? feedbackOf(card) : "";
      if (notes && card.to) {
        await radioSend({to: card.to, text: `Granted: ${card.title}. Notes:\n${notes}`, upload: "", cls: "post", voice: ""});
      }
      matchView.marks.delete(cardKey(card));
    }
  }

  function riskButton(decision) {
    const taken = Boolean(decision.risk);
    const words = taken ? "Risk accepted" : "Accept risk: gate not green";
    const hint = taken ? "Risk accepted: the commit gets its own passkey signature at the release; click to take it back" : "Accept risk: the gate is not green; until you click, the release leaves this commit out and it goes back to the stack";
    return h("button", {type: "button", class: "btn small match-accept-risk", "aria-pressed": String(taken), "data-tone": taken ? "warn" : "bad", title: hint, on: {click: () => {
      decision.risk = !taken;
      drawMatch(true);
    }}}, icon(taken ? "bi-shield-fill-exclamation" : "bi-shield-exclamation"), words);
  }

  function backToStack(card) {
    logStep(card.id);
    matchView.decisions.delete(card.id);
    refusedIds.delete(card.ref);
    toBack(card.id);
    drawMatch(true);
  }

  /**
   * @param {object} card a card on the release card.
   * @returns {string} why Accept is impossible for it now, "" when it is possible.
   */
  function acceptBlock(card) {
    if (lapsedCard(card)) {
      return `${expiredWords(card)}: it can no longer be granted`;
    }
    if (card.blocked) {
      return `not possible now: ${card.blocked}`;
    }
    if (card.stale) {
      return `the card is stale: ${card.stale_reason}`;
    }
    return needsPick(card) || pickOnly(card) ? "pick one of its options" : "";
  }

  function menuEntry(words, mark, why, act) {
    return h("button", {type: "button", class: "menu-item", disabled: Boolean(why), title: why ? revealed(`${words}: ${why}`) : revealed(words), on: {click: (event) => {
      event.currentTarget.closest("details").open = false;
      act();
    }}}, icon(mark), revealed(words), why ? h("span", {class: "muted match-verdict-why"}, revealed(why)) : null);
  }

  /**
   * @param {object} card a card on the release card, not withdrawn.
   * @param {object} decision its decision.
   * @returns {HTMLElement} its verdict pill as a menu: each option of a decision card, Accept, Reject (Drop for an
   * expired card) and Back to the stack, an impossible entry greyed with its reason.
   */
  function verdictMenu(card, decision) {
    const [word, tone, mark] = MATCH_VERDICTS[decision.verdict];
    const lapsed = lapsedCard(card);
    const options = card.kind === "decision" && !card.multi && Array.isArray(card.options) ? card.options.map((option) => menuEntry(`Pick: ${shownPick(option.label)}`, "bi-signpost-split", lapsed ? acceptBlock(card) : "", () => decide(card, "accept", "", option.label))) : [];
    const accept = card.kind === "decision" && Array.isArray(card.options) ? null : menuEntry("Accept", "bi-check-lg", acceptBlock(card), () => acceptCard(card));
    const rejectWhy = card.blocked && !lapsed ? `not possible now: ${card.blocked}` : pickOnly(card) && !lapsed ? "a choice is answered with one of its options" : "";
    return h("details", {class: "menu match-verdict-menu"},
      h("summary", {class: "pill match-verdict", "data-tone": tone, ...named(`${word}: change`, "Change this decision")}, icon(mark), decision.label ? revealed(`${word}: ${shownPick(decision.label)}`) : word, caret()),
      h("div", {class: "menu-box end", role: "group", "aria-label": "Change the decision"}, options, accept, droppable(card) ? menuEntry("Drop (expired)", "bi-trash", "", () => dropCard(card)) : menuEntry("Reject …", "bi-x-lg", rejectWhy, () => rejectCard(card)), menuEntry("Back to the stack", "bi-stack", "", () => backToStack(card))));
  }

  function overviewRow(card, decision) {
    const [kindName, kindTone, kindIcon] = MATCH_KINDS[card.kind] || [card.kind, "neutral", "bi-collection"];
    const [word, tone, mark] = MATCH_VERDICTS[decision.verdict];
    const back = iconBtn("bi-arrow-counterclockwise", card.withdrawn ? "Drop the reject" : "Back to the stack", "btn small ghost match-undecide", () => backToStack(card), card.withdrawn ? "Drop the reject: nothing is sent" : "Back to the stack: the card goes behind the release card, last in the deck");
    const risk = risky(card, decision);
    const held = risk && !decision.risk;
    const bad = unreleasable(card, decision);
    const dropped = decision.verdict === "drop";
    const note = bad ? `Cannot be released: ${bad}.` : card.withdrawn ? "Card withdrawn: the feedback goes to its agent by radio call at the release." : dropped ? "Dismissed in the hub for every browser at the release; its agent gets no message." : decision.verdict === "reject" && decision.hash !== card.hash ? "Card changed since your reject." : held ? "Accept its risk or send it back to the stack: the release waits until you do." : "";
    const verdict = card.withdrawn || dropped ? h("span", {class: "pill match-verdict", "data-tone": tone}, icon(mark), word) : verdictMenu(card, decision);
    return h("li", {class: "match-decision", "data-card": card.id, "data-verdict": decision.verdict, "data-withdrawn": String(Boolean(card.withdrawn)), "data-held": String(held), "data-bad": String(Boolean(bad))},
      h("div", {class: "row"}, agentFace(card.agent || "-", false), h("span", {class: "pill", "data-tone": kindTone}, icon(kindIcon), kindName), h("strong", {class: "match-decision-title"}, revealed(card.title)), h("span", {class: "spacer"}),
        risk && !bad ? riskButton(decision) : verdict, decision.verdict === "reject" && !card.withdrawn ? iconBtn("bi-pencil", "Edit feedback", "btn small ghost match-edit", () => rejectCard(card)) : null, back),
      note ? h("p", {class: `muted match-decision-note${bad ? " match-decision-bad" : ""}`}, icon(bad ? "bi-exclamation-octagon" : "bi-info-circle"), revealed(note)) : null,
      decision.verdict === "reject" ? h("pre", {class: "match-decision-feedback"}, revealedLines(decision.feedback === "" ? "no feedback text" : decision.feedback)) : null);
  }

  /**
   * @param {string} cls the button's classes after match-act: its tone and its role.
   * @param {string} iconName the icon on its round face.
   * @param {string} word the label under the face.
   * @param {string} hint its tooltip.
   * @param {boolean} disabled whether it is greyed and takes no click.
   * @param {Function} run what a click runs.
   * @returns {HTMLElement} one button of the deck's action row; every card's row holds three of the same width.
   */
  function matchAct(cls, iconName, word, hint, disabled, run) {
    return h("button", {type: "button", class: `match-act ${cls}`, disabled, ...named(word, hint), on: {click: run}},
      h("span", {class: "match-act-face", "aria-hidden": "true"}, icon(iconName)), h("span", {class: "match-act-label"}, word));
  }

  /**
   * @param {Array<object>} cards the cards in stack order.
   * @param {number} open how many cards wait undecided behind it.
   * @returns {object} card: the release card, front card of the deck with every decision; actions: its row of the
   * deck, Cancel on the left, Skip, Release on the right; its moves (D or a right swipe releases, A, W or a left
   * swipe skips to the next card) mirrored in matchView.release for the keys.
   */
  function releaseCard(cards, open) {
    const picked = decided(cards);
    const plan = releasePlan(picked);
    const held = plan.held.length;
    const bad = plan.bad.length;
    const count = held || bad ? 0 : plan.lone.length + plan.rest.length + plan.dismissals.length + plan.gone.length;
    const badWhy = plan.bad.map(([card, decision]) => `${card.title}: ${unreleasable(card, decision)}`).join("\n");
    const heldWhy = `Release waits: ${held === 1 ? "one red-gate commit waits" : `${held} red-gate commits wait`} for your risk accept or its way back to the stack.\n${plan.held.map(([card]) => card.title).join("\n")}`;
    const signatures = plan.lone.length ? `${plan.lone.length === 1 ? "The risk-accepted commit gets its own" : `Each of the ${plan.lone.length} risk-accepted commits gets its own`} passkey signature first, then one signature releases the rest` : "One passkey signature releases every decision";
    const run = () => releaseMatch(cards);
    const skip = open ? () => {
      logStep(RELEASE);
      toBack(RELEASE);
      drawMatch(true);
    } : null;
    const releaseHint = held ? heldWhy : bad ? `Release waits: drop or change ${bad === 1 ? "this row" : `these ${bad} rows`} first.\n${badWhy}` : count ? `Release (D, right arrow, swipe right): ${signatures}; after each signature ${undoWords()}.` : "Nothing to release yet.";
    const release = matchAct("match-release", "bi-key", "Release", revealed(releaseHint), !(count || bad), run);
    release.setAttribute("aria-disabled", String(Boolean(bad)));
    const skipHint = open ? `Skip: on to the next card, the release card to the back (A, W, left or up arrow, swipe left); S undoes the last step` : "Skip: no other card waits";
    const cancel = matchAct("match-drop", "bi-x-lg", "Cancel", revealed(bad ? `Cancel: drop the ${bad === 1 ? "row" : `${bad} rows`} that cannot be released, and their cards leave the deck.\n${badWhy}` : "Cancel: no row is blocked, nothing to drop."), !bad, () => dropUnreleasable(plan.bad));
    const article = h("article", {class: "card match-card front match-release-card match-overview", "data-card": "release", "aria-label": "Release card: the decisions"},
      h("header", {class: "match-head"}, widenToggle(), h("h2", {class: "match-title"}, icon("bi-key"), "Release"),
        h("p", {class: "muted match-release-hint"}, [count ? "D, → or a right swipe releases" : "", open ? "A, W, ← or a left swipe skips to the next card" : "", "S undoes the last step."].filter(Boolean).join("; "))),
      h("div", {class: "match-body"},
        h("p", {class: "muted"}, "Nothing has run yet. Accepted commits get the operator's signature for their exact tree, accepted commands run once as jobs under Waits on Operator, accepted asks are granted, every picked option and every rejection goes to its agent by radio call, every dropped expired card is dismissed in the hub for every browser without a message."),
        picked.length ? h("ol", {class: "match-decisions"}, picked.map(([card, decision]) => overviewRow(card, decision))) : h("p", {class: "muted"}, "No decision yet.")));
    paint(article, "release");
    matchView.release = {accept: count || bad ? run : null, reject: skip, later: skip};
    draggable(article, matchView.release, () => false);
    return {card: article, actions: h("div", {class: "match-actions"}, cancel, matchAct("match-skip", "bi-arrow-up", "Skip", skipHint, !skip, skip), release)};
  }

  /**
   * @param {Array<object>} rest the cards lying behind the front card.
   * @returns {Array<HTMLElement>} at most MATCH_PEEKS pile layers, deepest first.
   */
  function layersOf(rest) {
    return rest.slice(0, MATCH_PEEKS).map((card, index) => {
      const layer = h("div", {class: "match-layer", "data-card": card.id, "data-depth": String(index + 1), "data-stale": String(Boolean(card.stale)), "aria-hidden": "true", inert: ""});
      paint(layer, card.id);
      return layer;
    }).reverse();
  }

  function matchScreen() {
    const stack = h("div", {class: "match-stack"});
    const count = h("span", {class: "muted"});
    const tally = h("span", {class: "match-tally"}, "0");
    const decisions = h("button", {type: "button", class: "btn small soft match-open-overview", ...named("Decisions", "Decisions: the release card with every decision, to change and release them"), on: {click: () => {
      toFront(RELEASE);
      drawMatch(true);
    }}}, icon("bi-card-checklist"), tally);
    const peeks = h("button", {type: "button", class: "btn small soft match-peeks-toggle", "aria-pressed": String(peeksShown()), ...named("Next cards", "Next cards: show or hide the row of waiting cards below the buttons"), on: {click: () => {
      keep(STORE.peeks, !peeksShown());
      drawMatch(true);
    }}}, icon("bi-collection"));
    const hiddenCount = h("span", {class: "match-hidden-count"});
    const hidden = h("button", {type: "button", class: "btn small soft match-hidden", hidden: true, "aria-haspopup": "menu", ...named("Hidden cards", "Hidden cards: the Show filter hides them; a click opens the menu to show them again"), on: {click: openShowMenu}}, icon("bi-eye-slash"), hiddenCount);
    matchView.dom = {stack, count, decisions, tally, peeks, hidden, hiddenCount};
    matchView.sig = "";
    if (matchView.drag) {
      matchView.drag.end();
    }
    const bar = boxHead("Match", "task-toolbar", h("strong", {class: "box-title"}, icon("bi-stack"), "Match"), count, hidden, h("span", {class: "spacer"}), decisions, peeks,
      iconBtn("bi-list-check", "Tasks", "btn small soft", () => go("tasks", null), "Tasks: back to the task list"));
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
    homeView.heads.set("tasks/match", h("div", {role: "toolbar", "aria-label": "Match"}, matchView.dom.count, matchView.dom.hidden, matchView.dom.decisions, matchView.dom.peeks));
    homeView.hosts.set("tasks/match", host);
    window.setTimeout(() => drawMatch(true), 0);
    return host;
  }

  function drawMatch(force) {
    const dom = matchView.dom;
    if (!dom || !dom.stack.isConnected) {
      return;
    }
    if (!matchView.loading && MatchClock.due(Date.now(), matchView.fetched, matchRefresh())) {
      fetchMatch();
    }
    if (matchView.cards === null) {
      fadeSwap(dom.stack, [h("p", {class: "muted"}, "Loading cards …")]);
      return;
    }
    const cards = matchOrder(matchView.cards);
    const byId = new Map(cards.map((card) => [card.id, card]));
    [...matchView.decisions].forEach(([id, decision]) => {
      const card = byId.get(id);
      const lapsedAway = decision.verdict === "drop" && !card;
      if (lapsedAway || (decision.verdict === "accept" && (!card || card.stale || card.hash !== decision.hash))) {
        matchView.decisions.delete(id);
        if (card && card.hash !== decision.hash) {
          toast(`Accept dropped: ${card.title}`, ["The card changed since your accept: decide it again."], false);
        }
      }
    });
    const filter = matchHidden();
    const split = showSplit(cards, filter);
    const open = split.open;
    const waiting = open.filter((card) => !card.stale && !card.blocked);
    if (!matchView.decisions.size) {
      matchView.order = matchView.order.filter((id) => id !== RELEASE);
    } else if (!matchView.order.includes(RELEASE)) {
      matchView.order.push(RELEASE);
    }
    const cleared = matchView.openBefore > 0 && !waiting.length && matchView.decisions.size > 0;
    if (cleared) {
      toFront(RELEASE);
    }
    const byOpen = new Map(split.shown.map((card) => [card.id, card]));
    const rotation = matchView.order.filter((id) => id === RELEASE || byOpen.has(id));
    const releasing = rotation[0] === RELEASE;
    const sig = JSON.stringify([cards.map((card) => [card.id, card.hash, card.live_hash, card.stale, card.born, card.gate, card.files ? card.files.length : null, card.merge ? [card.merge.kind, card.merge.target, card.merge.error] : null]), [...matchView.decisions].map(([id, decision]) => [id, decision.verdict, decision.feedback, decision.label, decision.hash, decision.risk]), rotation, [...filter], Math.floor(state.now / DAY)]);
    if (!force && sig === matchView.sig && !cleared) {
      matchView.openBefore = waiting.length;
      return;
    }
    const before = dom.stack.querySelector(".match-card.front");
    if (before && !before.dataset.fly && before.dataset.card !== (rotation[0] || null)) {
      Object.assign(matchView, {front: null, release: null});
      vanish(before, () => drawMatch(true));
      return;
    }
    matchView.openBefore = waiting.length;
    matchView.sig = sig;
    dom.count.textContent = split.shown.length === 1 ? "1 card waits" : `${split.shown.length} cards wait`;
    dom.hidden.hidden = !split.hidden;
    dom.hiddenCount.textContent = hiddenWords(split.hidden);
    dom.tally.textContent = String(matchView.decisions.size);
    dom.peeks.setAttribute("aria-pressed", String(peeksShown()));
    dom.decisions.hidden = !matchView.decisions.size || releasing;
    matchView.release = null;
    if (!rotation.length && split.hidden) {
      matchView.front = null;
      const empty = emptyState(allHiddenWords(split.hidden), "The Show filter of the right-click menu hides them; Show all brings every card back.");
      empty.classList.add("match-empty", "match-all-hidden");
      empty.querySelector(".empty-mark").replaceWith(h("span", {class: "match-hidden-mark", "aria-hidden": "true", title: allHiddenWords(split.hidden)}, icon("bi-eye-slash")));
      empty.append(h("button", {type: "button", class: "btn primary match-show-all", ...named("Show all", "Show all: every card kind and state back in the deck"), on: {click: showAll}}, icon("bi-eye"), "Show all"));
      fadeSwap(dom.stack, [h("div", {class: "match-deck"}, empty)]);
      return;
    }
    if (!rotation.length) {
      matchView.front = null;
      const empty = emptyState("No card waits", "Nothing waits on the operator.");
      empty.classList.add("match-empty");
      empty.querySelector(".empty-mark").replaceWith(matchGlass());
      fadeSwap(dom.stack, [h("div", {class: "match-deck"}, empty)]);
      return;
    }
    const behind = rotation.slice(1).filter((id) => id !== RELEASE).map((id) => byOpen.get(id));
    dom.stack.dataset.wide = String(matchWide());
    const peekRow = (rest) => (rest.length && peeksShown() ? h("div", {class: "match-peeks", role: "group", "aria-label": `${rest.length} more cards`}, rest.map(peekTab)) : null);
    if (releasing) {
      matchView.front = null;
      const scrolledRelease = before && before.dataset.card === "release" ? before.querySelector(".match-body").scrollTop : 0;
      const {card: shown, actions} = releaseCard(cards, behind.length);
      shown.dataset.fresh = String(!before || before.dataset.card !== "release");
      if (cleared) {
        confetti();
      }
      const peeksBelow = peekRow(behind);
      fadeSwap(dom.stack, [h("div", {class: "match-deck"}, layersOf(behind), shown), actions, ...(peeksBelow ? [peeksBelow] : [])], (root, swap) => {
        swap();
        shown.querySelector(".match-body").scrollTop = scrolledRelease;
      });
      return;
    }
    const front = byOpen.get(rotation[0]);
    const rest = behind;
    matchView.front = front;
    const hint = front.blocked ? `Accept: not possible now. ${front.blocked}` : front.stale ? `Accept: refused while the card is stale (${front.stale_reason})` : front.kind === "rule" ? "Accept: opens its row, where the passkey signs exactly this rule" : front.kind === "decision" ? (needsPick(front) ? "Accept: pick one of its options" : `Accept: ${shownPick(acceptLabel(front))} (D, right arrow, swipe right)`) : "Accept (D, right arrow, swipe right)";
    const accept = matchAct("match-accept", "bi-check-lg", "Accept", revealed(hint), Boolean(front.blocked || front.stale) || needsPick(front), () => acceptCard(front));
    const declining = front.kind === "decision" && Answers.pair(front) ? `Reject: ${shownPick(Answers.pair(front).no)}, with an optional comment on what to do instead (A, left arrow, swipe left)` : "Reject with feedback (A, left arrow, swipe left)";
    const lapsed = lapsedCard(front);
    const lapseHint = front.blocked_kind === "claude" ? "Reject: its dialog is open in Claude, answer it there; a reject here sends your feedback to its agent by radio (A, left arrow, swipe left)" : "Reject: it expired before you decided; it leaves the deck at once, without feedback or a message, and the release dismisses it for every browser (A, left arrow, swipe left; S undoes)";
    const rejectHint = lapsed ? lapseHint : front.blocked ? `Reject: not possible now. ${front.blocked}` : pickOnly(front) ? "Reject: a choice is answered with one of its options" : declining;
    const reject = matchAct("match-reject", "bi-x-lg", "Reject", revealed(rejectHint), !lapsed && (Boolean(front.blocked) || pickOnly(front)), () => rejectCard(front));
    const later = matchAct("match-later", "bi-arrow-up", "Later", "Later: on to the next card, this one to the back (W, up arrow, swipe up); S undoes the last step", rotation.length < 2, () => laterCard(front));
    const peeks = peekRow(rest);
    const scrolled = before && before.dataset.card === front.id ? before.querySelector(".match-body").scrollTop : 0;
    const shown = matchCard(front);
    shown.dataset.fresh = String(!before || before.dataset.card !== front.id);
    draggable(shown, {accept: lapsed ? null : () => acceptCard(front), reject: () => rejectCard(front), later: () => laterCard(front)}, (swiped) => (swiped === "accept" && flies(front)) || swiped === "later");
    fadeSwap(dom.stack, [h("div", {class: "match-deck"}, layersOf(rest), shown), h("div", {class: "match-actions"}, reject, later, accept), ...(peeks ? [peeks] : [])], (root, swap) => {
      keepTyping(root, swap);
      shown.querySelector(".match-body").scrollTop = scrolled;
    });
  }
