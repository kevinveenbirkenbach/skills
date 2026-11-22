  /**
   * @param {Object} item a decision, a decision row or a decision card: id, options [{label, description, preview}], recommended (labels joined by PICKED), multi.
   * @param {Object} how pick: called with the answer, one label, the toggled labels in option order joined by PICKED, or the trimmed Other text; toggled: the Set of toggled labels of a multi decision, kept by the caller across redraws; chosen: the answer given so far, "" for none; locked: whether the dialog takes no answer; hint: what an answer does, shown in the titles; group: an extra class of the option list.
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
            how.pick(option.label);
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
      send.addEventListener("click", () => how.pick(item.options.filter((option) => how.toggled.has(option.label)).map((option) => option.label).join(PICKED)));
    }
    const typed = chosen.length === 1 && !item.options.some((option) => option.label === chosen[0]) ? chosen[0] : null;
    const input = h("input", {class: "field", type: "text", maxlength: OTHER_LIMIT, placeholder: "Other: type your own answer …", "aria-label": `Other answer to ${item.id}`, value: typed, disabled: how.locked});
    const other = h("form", {class: "option other"}, input,
      h("button", {type: "submit", class: "btn small", disabled: how.locked, ...named("Send", revealed(`Send this text: ${how.hint}`))}, icon("bi-send"), "Send"));
    other.addEventListener("submit", (event) => {
      event.preventDefault();
      if (input.value.trim()) {
        how.pick(input.value.trim());
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
