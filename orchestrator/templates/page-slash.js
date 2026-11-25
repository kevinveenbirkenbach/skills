  const SLASH_LIMIT = 8;
  const SLASH_FRESH = 60000;
  const SLASH_FIELDS = "textarea[data-skills], input[data-skills]";
  const SLASH_TOKEN = /(^|\s)\/([A-Za-z0-9:_.-]*)$/;
  const slash = {skills: [], fetched: 0, loading: null, bound: new WeakSet(), box: null, field: null, shown: [], active: 0, token: null};

  /**
   * @param {Array<{name: string, description: string, source: string}>} skills the rows /api/skills serves.
   * @param {string} prefix what follows the "/", case ignored.
   * @param {string} repo the repository the field's agent or card works in, "" for none.
   * @returns {Array} at most SLASH_LIMIT rows, one per name: names that start with prefix before names that hold it,
   * then the repository's own skills, then by name.
   */
  function slashRank(skills, prefix, repo) {
    const typed = prefix.toLowerCase();
    const hits = skills.map((skill) => ({skill, at: skill.name.toLowerCase().indexOf(typed)})).filter((hit) => hit.at >= 0);
    hits.sort((a, b) => Number(a.at !== 0) - Number(b.at !== 0) || Number(b.skill.source === repo) - Number(a.skill.source === repo) || a.skill.name.localeCompare(b.skill.name));
    const seen = new Set();
    return hits.map((hit) => hit.skill).filter((skill) => !seen.has(skill.name) && Boolean(seen.add(skill.name))).slice(0, SLASH_LIMIT);
  }

  /**
   * @param {string} text the field's value.
   * @param {number} caret where the caret stands.
   * @returns {Object|null} {start, prefix}: the "/" word the caret ends: a "/" at the start or after
   * whitespace, then skill name characters only; null inside a word or a path.
   */
  function slashToken(text, caret) {
    const found = SLASH_TOKEN.exec(text.slice(0, caret));
    return found ? {start: caret - found[2].length - 1, prefix: found[2]} : null;
  }

  /**
   * @returns {Object} {value, caret}: text with the token up to caret replaced by "/<name> ".
   */
  function slashInsert(text, token, caret, name) {
    const head = `${text.slice(0, token.start)}/${name} `;
    return {value: head + text.slice(caret), caret: head.length};
  }

  function slashLoad() {
    if (!slash.loading && Date.now() - slash.fetched > SLASH_FRESH) {
      slash.loading = fetch("/api/skills", {cache: "no-store"}).then((response) => (response.ok ? response.json() : {skills: []})).then((data) => {
        slash.skills = Array.isArray(data.skills) ? data.skills : [];
        slash.fetched = Date.now();
      }).catch(() => null).finally(() => {
        slash.loading = null;
        if (slash.field) {
          slashShow(slash.field);
        }
      });
    }
  }

  function slashClose() {
    if (slash.box) {
      slash.box.remove();
    }
    Object.assign(slash, {box: null, field: null, shown: [], active: 0, token: null});
  }

  function slashPick(field, skill) {
    const next = slashInsert(field.value, slash.token, field.selectionStart, skill.name);
    field.value = next.value;
    field.setSelectionRange(next.caret, next.caret);
    field.dispatchEvent(new Event("input", {bubbles: true}));
    slashClose();
    field.focus();
  }

  function slashPaint() {
    slash.box.replaceChildren(...slash.shown.map((skill, index) => {
      const option = h("div", {role: "option", class: "slash-option", id: `slash-option-${index}`, "aria-selected": String(index === slash.active), title: skill.source},
        h("strong", {}, `/${skill.name}`), h("span", {class: "muted"}, skill.description));
      option.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        slashPick(slash.field, skill);
      });
      return option;
    }));
    slash.field.setAttribute("aria-activedescendant", `slash-option-${slash.active}`);
  }

  function slashShow(field) {
    const token = field.selectionStart === field.selectionEnd ? slashToken(field.value, field.selectionStart) : null;
    slashLoad();
    const shown = token ? slashRank(slash.skills, token.prefix, field.dataset.skills) : [];
    if (!shown.length) {
      slashClose();
      slash.field = token && slash.loading ? field : null;
      return;
    }
    if (!slash.box || slash.field !== field) {
      slashClose();
      slash.box = h("div", {class: "slash-list", role: "listbox", "aria-label": "Skills"});
      document.body.append(slash.box);
    }
    const box = field.getBoundingClientRect();
    Object.assign(slash, {field, shown, token, active: Math.min(slash.active, shown.length - 1)});
    slash.box.style.left = `${Math.max(8, Math.min(box.left, window.innerWidth - 8 - Math.min(448, window.innerWidth - 16)))}px`;
    slash.box.style.top = `${box.bottom + 4}px`;
    slashPaint();
  }

  function slashKeys(event, field) {
    if (!slash.box || slash.field !== field) {
      return;
    }
    const moves = {ArrowDown: 1, ArrowUp: -1};
    if (Object.hasOwn(moves, event.key)) {
      slash.active = (slash.active + moves[event.key] + slash.shown.length) % slash.shown.length;
      slashPaint();
    } else if (event.key === "Enter" || event.key === "Tab") {
      slashPick(field, slash.shown[slash.active]);
    } else if (event.key === "Escape") {
      slashClose();
    } else {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
  }

  /**
   * @param {HTMLElement} field a text field whose text reaches an agent; data-skills names the repository of its agent or card.
   */
  function slashBind(field) {
    if (slash.bound.has(field)) {
      return;
    }
    slash.bound.add(field);
    field.setAttribute("aria-autocomplete", "list");
    field.addEventListener("input", () => slashShow(field));
    field.addEventListener("keydown", (event) => slashKeys(event, field));
    field.addEventListener("blur", () => window.setTimeout(() => slash.field === field && slashClose(), 0));
  }

  function slashWatch() {
    const sweep = () => document.querySelectorAll(SLASH_FIELDS).forEach(slashBind);
    sweep();
    new MutationObserver(sweep).observe(document.body, {childList: true, subtree: true});
  }
