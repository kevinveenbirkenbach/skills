  const DIAL_MAX = 60;
  const DIAL_PAGE = 5;

  /**
   * @param {Object} options value: the whole value the dial starts at; label: the slider's accessible name; name: the
   * root's own class; min, max: the ends, max a full turn; page: the Page Up and Down step and the long-tick spacing;
   * unit: the readout's unit; spoken: (value) => the aria-valuetext; readonly: true for a dial only the caller moves.
   * @returns {root, value, set}: an analog clock face with Dial.TICKS ticks and one hand, an ARIA slider: dragging the
   * hand or clicking a tick sets it, the arrows step 1, Page Up and Down page, Home and End the ends; set(value) moves it.
   */
  function dial(options) {
    let current = options.value;
    const centre = Dial.SIZE / 2;
    const ticks = Dial.ticks(options.page).map(({at, long}) => {
      const [x1, y1] = Dial.point(at, Dial.TICKS, Dial.RADIUS - (long ? 10 : 5));
      const [x2, y2] = Dial.point(at, Dial.TICKS, Dial.RADIUS);
      return s("line", {class: `dial-tick${long ? " long" : ""}`, x1: fixed(x1), y1: fixed(y1), x2: fixed(x2), y2: fixed(y2)});
    });
    const hand = s("line", {class: "dial-hand", x1: centre, y1: centre});
    const face = s("svg", {class: "dial-face", viewBox: `0 0 ${Dial.SIZE} ${Dial.SIZE}`, "aria-hidden": "true", focusable: "false"},
      s("circle", {class: "dial-rim", cx: centre, cy: centre, r: Dial.RADIUS + 4}), ticks, hand, s("circle", {class: "dial-pin", cx: centre, cy: centre, r: 4}));
    const readout = h("output", {class: "dial-readout"});
    const root = h("div", {class: `dial ${options.name}`, role: "slider", tabindex: "0", "aria-label": options.label, "aria-valuemin": String(options.min), "aria-valuemax": String(options.max),
      "aria-readonly": options.readonly ? "true" : null}, face, readout);
    const set = (next) => {
      current = Dial.clamp(next, options);
      const [x2, y2] = Dial.point(current, options.max, Dial.RADIUS - 14);
      hand.setAttribute("x2", fixed(x2));
      hand.setAttribute("y2", fixed(y2));
      readout.textContent = `${current} ${options.unit}`;
      root.setAttribute("aria-valuenow", String(current));
      root.setAttribute("aria-valuetext", options.spoken(current));
    };
    set(current);
    if (options.readonly) {
      return {root, value: () => current, set};
    }
    const pointed = (event) => {
      const box = face.getBoundingClientRect();
      set(Dial.fromAngle((Math.atan2(event.clientX - box.left - box.width / 2, box.top + box.height / 2 - event.clientY) * 180) / Math.PI, options.max));
    };
    root.addEventListener("keydown", (event) => {
      const next = Dial.stepped(event.key, current, options);
      if (next === null) {
        return;
      }
      set(next);
      event.preventDefault();
      event.stopPropagation();
    });
    face.addEventListener("pointerdown", (event) => {
      face.setPointerCapture(event.pointerId);
      pointed(event);
      root.focus({preventScroll: true});
    });
    face.addEventListener("pointermove", (event) => {
      if (face.hasPointerCapture(event.pointerId)) {
        pointed(event);
      }
    });
    return {root, value: () => current, set};
  }

  /**
   * @param {number} value the undo window in whole seconds the dial starts at.
   * @param {string} label the slider's accessible name.
   * @returns {root, value, set}: dial() over 0 to DIAL_MAX seconds, Page Up and Down 5 s.
   */
  function undoDial(value, label) {
    const spoken = (seconds) => (seconds ? `${seconds} seconds to undo` : "0 seconds: takes effect at once");
    return dial({value, label, name: "undo-dial", min: 0, max: DIAL_MAX, page: DIAL_PAGE, unit: "s", spoken, readonly: false});
  }
