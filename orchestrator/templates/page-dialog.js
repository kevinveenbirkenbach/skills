  const OTHER_PROMPT = "Other: type your own answer …";
  const ALLOW = "Yes";
  const TELL = "Tell Claude what to do instead";
  const askDialog = (id) => ({id, options: [{label: ALLOW, description: "allow this one call"}, {label: "No", description: "deny it"}], recommended: "", multi: false});
  const drafts = new Map();
  const forgetDraft = (id) => drafts.delete(id);

  /**
   * @param {HTMLElement} root the element draw() rebuilds.
   * @param {Function} draw replaces root's children; the text field the operator types in keeps focus and caret when draw() rebuilds it under the same aria-label.
   */
  function keepTyping(root, draw) {
    const field = document.activeElement;
    const held = field && field.tagName === "INPUT" && typeof field.selectionStart === "number" && root.contains(field) && field.getAttribute("aria-label") ? [field.getAttribute("aria-label"), field.selectionStart, field.selectionEnd] : null;
    draw();
    const again = held && [...root.querySelectorAll("input")].find((node) => node.getAttribute("aria-label") === held[0]);
    if (again && document.activeElement !== again) {
      again.focus({preventScroll: true});
      again.setSelectionRange(held[1], held[2]);
    }
  }

  /**
   * @param {HTMLElement} root the element draw() rebuilds.
   * @param {Function} draw replaces root's children; an element scrolled inside a row with data-item gets its offsets back when draw() rebuilds it in the same row as the same nth element of its tag and class, so stars that Panels.decorate adds later do not shift it.
   */
  function keepScroll(root, draw) {
    const twins = (row, tag, name) => [...row.getElementsByTagName(tag)].filter((node) => node.className === name);
    const held = [...root.querySelectorAll("[data-item] *")].filter((node) => node.scrollTop || node.scrollLeft).map((node) => {
      const row = node.closest("[data-item]");
      return [row.dataset.item, node.tagName, node.className, twins(row, node.tagName, node.className).indexOf(node), node.scrollTop, node.scrollLeft];
    });
    draw();
    held.forEach(([item, tag, name, index, top, left]) => {
      const row = root.querySelector(`[data-item="${CSS.escape(item)}"]`);
      const node = row ? twins(row, tag, name)[index] : null;
      if (node) {
        node.scrollTop = top;
        node.scrollLeft = left;
      }
    });
  }

  /**
   * @param {Object} item a decision, a decision row, a decision card or a permission ask: id, options [{label, description, preview}], recommended (labels joined by PICKED), multi.
   * @param {Object} how pick: called with the answer, one label, the toggled labels in option order joined by PICKED, or the trimmed Other text, and true for the Other text only; other: the Other field's placeholder; toggled: the Set of toggled labels of a multi decision, kept by the caller across redraws; chosen: the answer given so far, "" for none; locked: whether the dialog takes no answer; hint: what an answer does, shown in the titles; group: an extra class of the option list.
   * @returns {HTMLElement} the dialog an AskUserQuestion shows: numbered options with their description, the recommended ones tagged, a free-text Other row, Send for a multi decision, and a preview pane beside them once an option has one. The keys 1 to n pick or toggle an option, n + 1 focuses Other.
   */
  function choiceDialog(item, how) {
    const recommended = item.recommended ? item.recommended.split(PICKED) : [];
    const chosen = how.chosen ? how.chosen.split(PICKED) : [];
    const pane = item.options.some((option) => option.preview) ? h("pre", {class: "choice-preview", "aria-label": "Preview"}) : null;
    const show = (option) => {
      if (pane) {
        pane.textContent = revealedLines(option.preview || "");
      }
    };
    const send = item.multi ? h("button", {type: "button", class: "btn small primary choice-send", disabled: how.locked || !how.toggled.size, ...named("Send", revealed(`Send the toggled options: ${how.hint}`))}, icon("bi-check2-square"), "Send") : null;
    const buttons = item.options.map((option) => {
      const marked = recommended.includes(option.label);
      const button = h("button", {
        type: "button", class: `option${marked ? " recommended" : ""}`, disabled: how.locked, "aria-pressed": String(item.multi ? how.toggled.has(option.label) : chosen.includes(option.label)),
        title: revealed(`${option.label}: ${how.hint}`),
        on: {click: () => {
          if (!item.multi) {
            how.pick(option.label, false);
            return;
          }
          how.toggled.has(option.label) ? how.toggled.delete(option.label) : how.toggled.add(option.label);
          button.setAttribute("aria-pressed", String(how.toggled.has(option.label)));
          send.disabled = !how.toggled.size;
        }, focus: () => show(option), mouseenter: () => show(option)},
      }, h("strong", {}, revealed(option.label)), marked && !option.label.includes("(Recommended)") ? h("em", {class: "option-tag"}, "Recommended") : null,
      option.description ? h("span", {}, revealed(option.description)) : null);
      return button;
    });
    if (send) {
      send.addEventListener("click", () => how.pick(item.options.filter((option) => how.toggled.has(option.label)).map((option) => option.label).join(PICKED), false));
    }
    const typed = chosen.length === 1 && !item.options.some((option) => option.label === chosen[0]) ? chosen[0] : null;
    const input = h("input", {class: "field", type: "text", maxlength: OTHER_LIMIT, placeholder: how.other, "aria-label": `Other answer to ${item.id}`, value: typed || drafts.get(item.id) || null, disabled: how.locked});
    input.addEventListener("input", () => drafts.set(item.id, input.value));
    const other = h("form", {class: "option other"}, input,
      h("button", {type: "submit", class: "btn small", disabled: how.locked, ...named("Send", revealed(`Send this text: ${how.hint}`))}, icon("bi-send"), "Send"));
    other.addEventListener("submit", (event) => {
      event.preventDefault();
      if (input.value.trim()) {
        how.pick(input.value.trim(), true);
      }
    });
    const list = h("div", {class: `options dialog${how.group ? ` ${how.group}` : ""}`, role: "group", "aria-label": "Options", "data-multi": item.multi ? "" : null}, buttons, other, send);
    list.addEventListener("keydown", (event) => {
      const index = Number(event.key) - 1;
      if (event.target === input || event.altKey || event.ctrlKey || event.metaKey || !Number.isInteger(index) || index < 0 || index > buttons.length) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      index < buttons.length ? buttons[index].click() : input.focus();
    });
    show(item.options.find((option) => recommended.includes(option.label)) || item.options[0] || {});
    return pane ? h("div", {class: "choice"}, list, pane) : list;
  }
