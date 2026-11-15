  const MATCH_REFRESH = 2000;
  const MATCH_PEEKS = 2;
  const LONG_PRESS = 550;
  const PRESS_SLOP = 10;
  const MATCH_KINDS = {commit: ["Commit", "info", "bi-git"], command: ["Command", "warn", "bi-terminal"]};
  const matchView = {cards: null, order: [], marks: new Map(), opened: new Map(), dom: null, sig: "", fetched: 0, loading: false, press: null};

  async function fetchMatch() {
    if (matchView.loading) {
      return;
    }
    matchView.loading = true;
    matchView.fetched = Date.now();
    try {
      const response = await fetch("/api/match", {cache: "no-store"});
      if (response.ok) {
        const data = await response.json();
        matchView.cards = Array.isArray(data.cards) ? data.cards : [];
      }
    } catch {
      matchView.cards = matchView.cards || [];
    } finally {
      matchView.loading = false;
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

  function marksOf(card) {
    const key = `${card.id}@${card.hash}`;
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

  function matchFileRows(card, file) {
    const commit = card.kind === "commit";
    const rows = commit ? (file.patch ? Diffs.rows(file.patch).map(patchRow) : []) : file.state === "read" ? contentRows(file.content) : [];
    const columns = commit ? 4 : 2;
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
    if (card.kind === "commit") {
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
    const table = rows.length ? h("div", {class: "diff-scroll"}, h("table", {class: "diff"}, h("tbody", {}, rows))) : h("p", {class: "muted"}, card.kind === "commit" ? "No patch shipped for this file." : "Not read.");
    const block = h("details", {class: "match-file", "data-path": file.path, "data-state": card.kind === "command" ? file.state : null, open: opened}, fileHead(card, file), table);
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

  function openOnScroll(body) {
    const files = [...body.querySelectorAll(".match-file")];
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
      drawMatch(true);
    }}}, icon("bi-bookmark-fill"), "Save");
    const cancel = h("button", {type: "button", class: "btn small ghost", ...named("Cancel"), on: {click: () => closeComment(article)}}, "Cancel");
    const columns = row.children.length;
    const field = h("tr", {class: "match-comment"}, h("td", {colspan: columns}, h("div", {class: "match-comment-box"}, h("code", {}, `${file.dataset.path}:${row.dataset.line}`), words, h("div", {class: "actions"}, cancel, save))));
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

  function matchHead(card) {
    const [kindName, kindTone, kindIcon] = MATCH_KINDS[card.kind] || [card.kind, "neutral", "bi-collection"];
    return h("header", {class: "match-head"},
      h("div", {class: "match-who"}, face(card.agent || "-", true), h("strong", {class: "match-name"}, revealed(card.agent || "unknown agent")), h("span", {class: "match-age"}, ageWords(card.born))),
      h("div", {class: "states"}, h("span", {class: "pill", "data-tone": kindTone}, icon(kindIcon), kindName), card.gate ? pill(`gate ${card.gate}`, card.gate === "pass" ? "ok" : "bad") : null,
        card.score ? h("span", {class: "pill", "data-tone": "neutral"}, revealed(card.score)) : null, card.stale ? h("span", {class: "pill match-stale-pill", "data-tone": "bad"}, icon("bi-hourglass-split"), "stale") : null),
      h("dl", {class: "meta match-place"}, [["Repository", card.repo], ["Branch", card.branch], ["Worktree", card.worktree]].map(([label, value]) => h("div", {}, h("dt", {}, label), h("dd", {}, h("code", {title: value ? revealed(value) : null}, revealed(dash(value))))))),
      h("h2", {class: "match-title"}, revealed(card.title)),
      card.stale ? h("p", {class: "match-stale"}, icon("bi-exclamation-triangle"), revealed(card.stale_reason)) : null);
  }

  function matchCommand(card) {
    if (card.kind !== "command") {
      return null;
    }
    return h("section", {class: "match-payload"},
      h("pre", {class: "match-command"}, h("code", {}, revealed(card.command))),
      h("p", {class: "match-directory"}, revealed(card.directory)),
      card.reason && card.reason !== "-" ? h("p", {class: "match-reason"}, revealed(card.reason)) : null);
  }

  function matchCard(card) {
    const files = card.files || [];
    const list = files.length ? h("ol", {class: "match-files", "aria-label": `Files: ${files.length}`}, files.map((file, index) => fileBlock(card, file, index))) : h("p", {class: "muted"}, card.kind === "commit" ? "No diff shipped with this stage." : "Its command names no file.");
    const body = h("div", {class: "match-body"}, matchCommand(card), list);
    body.addEventListener("scroll", () => openOnScroll(body), {passive: true});
    const article = h("article", {class: "card match-card front", "data-card": card.id, "data-kind": card.kind, "data-stale": String(Boolean(card.stale)), "aria-label": `${card.kind} card of ${card.agent || "an agent"}`},
      matchHead(card), body);
    markable(article, card);
    window.setTimeout(() => openOnScroll(body), 0);
    return article;
  }

  function peekTab(card) {
    const [kindName, kindTone] = MATCH_KINDS[card.kind] || [card.kind, "neutral"];
    return h("button", {type: "button", class: "match-peek", "data-card": card.id, "data-stale": String(Boolean(card.stale)), ...named(`Show ${kindName.toLowerCase()} card: ${card.title}`), on: {click: () => {
      matchView.order = [card.id, ...matchView.order.filter((id) => id !== card.id)];
      drawMatch(true);
    }}}, face(card.agent || "-", false), h("span", {class: "pill", "data-tone": kindTone}, kindName), card.stale ? h("span", {class: "pill", "data-tone": "bad"}, "stale") : null, h("span", {class: "match-peek-title"}, revealed(card.title)));
  }

  function matchScreen() {
    const stack = h("div", {class: "match-stack"});
    const count = h("span", {class: "muted"});
    matchView.dom = {stack, count};
    matchView.sig = "";
    const bar = h("div", {class: "card controls task-toolbar", role: "toolbar", "aria-label": "Match"}, h("strong", {}, icon("bi-stack"), "Match"), count, h("span", {class: "spacer"}),
      iconBtn("bi-list-check", "Tasks", "btn small soft", () => go("tasks", null), "Tasks: back to the task list"));
    fetchMatch();
    return h("div", {class: "graph tasks match"}, bar, stack);
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
    const sig = JSON.stringify([cards.map((card) => [card.id, card.hash, card.live_hash, card.stale, card.born, card.files ? card.files.length : null]), Math.floor(state.now / DAY)]);
    if (!force && sig === matchView.sig) {
      return;
    }
    matchView.sig = sig;
    dom.count.textContent = cards.length === 1 ? "1 card waits" : `${cards.length} cards wait`;
    if (!cards.length) {
      dom.stack.replaceChildren(emptyState("No card waits", "No staged commit and no operator command waits for a decision."));
      return;
    }
    const [front, ...rest] = cards;
    const accept = h("button", {type: "button", class: "btn match-accept", disabled: Boolean(front.stale), ...named("Accept", front.stale ? `Accept: refused while the card is stale (${front.stale_reason})` : "Accept")}, icon("bi-check-lg"));
    const reject = h("button", {type: "button", class: "btn match-reject", ...named("Reject")}, icon("bi-x-lg"));
    const peeks = rest.length ? h("div", {class: "match-peeks", role: "group", "aria-label": `${rest.length} more cards`}, rest.map(peekTab)) : null;
    const behind = rest.slice(0, MATCH_PEEKS).map((card, index) => {
      const sheet = h("div", {class: "match-behind", "aria-hidden": "true"});
      sheet.style.setProperty("--depth", String(index + 1));
      return sheet;
    });
    const before = dom.stack.querySelector(".match-card.front");
    const scrolled = before && before.dataset.card === front.id ? before.querySelector(".match-body").scrollTop : 0;
    const shown = matchCard(front);
    dom.stack.replaceChildren(peeks, h("div", {class: "match-deck"}, behind, shown), h("div", {class: "match-actions"}, reject, accept));
    shown.querySelector(".match-body").scrollTop = scrolled;
  }
