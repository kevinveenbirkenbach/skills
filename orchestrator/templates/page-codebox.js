  const CODE_OPEN = {preview: false, open: true, closed: false};
  const codeView = {open: new Map()};

  /**
   * @param {string} key what the box shows, such as an item key; its open state survives every redraw.
   * @param {string} place preview (Stream, Waits on Operator: 12 lines until the eye shows all), open (Match: the whole
   * code, the card body scrolls) or closed (Tasks: one line, the eye opens the whole code in a sheet).
   * @param {Array} parts the command and diff nodes the box holds; null entries are skipped.
   * @param {string} copy the text the copy button copies, "" for no copy button.
   * @param {Array} actions the Grant and Deny nodes for the right end of the foot, [] for none.
   * @param {Function|null} load runs after the eye opened the box, such as a redraw that fetches a review's diff; null
   * when the box already holds everything.
   * @returns {HTMLElement} the .code-box: its .code-body, then its .code-foot.
   */
  function codeBox(key, place, parts, copy, actions, load) {
    const id = `${place}:${key}`;
    const body = h("div", {class: "code-body"}, parts.filter(Boolean));
    const eye = h("button", {type: "button", class: "btn small ghost icon-only code-eye", on: {click: () => {
      if (place === "closed") {
        openSheet("Code", [h("div", {class: "code-box", "data-place": "sheet"}, body.cloneNode(true))], true);
        return;
      }
      codeView.open.set(id, eye.getAttribute("aria-expanded") !== "true");
      paintEye();
      if (load) {
        load();
      }
    }}}, icon("bi-eye"));
    const root = h("div", {class: "code-box", "data-place": place}, body,
      h("div", {class: "code-foot"}, copy ? copyButton(copy) : null, eye, h("span", {class: "spacer"}), actions));
    const paintEye = () => {
      const open = place !== "closed" && (codeView.open.has(id) ? codeView.open.get(id) : CODE_OPEN[place]);
      const words = place === "closed" ? "Show all: the whole code in a sheet" : open ? "Show less: back to the preview" : "Show all: the whole code in place";
      root.dataset.open = String(open);
      eye.setAttribute("aria-expanded", String(open));
      eye.setAttribute("aria-label", open ? "Show less" : "Show all");
      eye.title = words;
    };
    paintEye();
    return root;
  }

  const codeOpened = (key, place) => codeView.open.get(`${place}:${key}`) === true;
