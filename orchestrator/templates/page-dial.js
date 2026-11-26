  const DIAL_MAX = 60;
  const DIAL_PAGE = 5;
  const DIAL_SIZE = 140;
  const DIAL_RADIUS = 58;

  /**
   * @param {number} second a value on the dial, 0 to DIAL_MAX.
   * @param {number} radius how far from the centre.
   * @returns {number[]} the point [x, y] for that second, 0 and 60 at the top, clockwise.
   */
  function dialPoint(second, radius) {
    const angle = (second / DIAL_MAX) * 2 * Math.PI;
    const centre = DIAL_SIZE / 2;
    return [centre + Math.sin(angle) * radius, centre - Math.cos(angle) * radius];
  }

  /**
   * @param {number} value the undo window in whole seconds the dial starts at.
   * @param {string} label the slider's accessible name.
   * @returns {root, value}: an analog clock face with 60 ticks and one hand, an ARIA slider:
   * dragging the hand or clicking a tick sets it, the arrows step 1 s, Page Up and Down 5 s, Home and End the ends.
   */
  function undoDial(value, label) {
    let seconds = value;
    const ticks = Array.from({length: DIAL_MAX}, (_, second) => {
      const long = second % DIAL_PAGE === 0;
      const [x1, y1] = dialPoint(second, DIAL_RADIUS - (long ? 10 : 5));
      const [x2, y2] = dialPoint(second, DIAL_RADIUS);
      return s("line", {class: `dial-tick${long ? " long" : ""}`, x1: fixed(x1), y1: fixed(y1), x2: fixed(x2), y2: fixed(y2)});
    });
    const centre = DIAL_SIZE / 2;
    const hand = s("line", {class: "dial-hand", x1: centre, y1: centre});
    const face = s("svg", {class: "dial-face", viewBox: `0 0 ${DIAL_SIZE} ${DIAL_SIZE}`, "aria-hidden": "true", focusable: "false"},
      s("circle", {class: "dial-rim", cx: centre, cy: centre, r: DIAL_RADIUS + 4}), ticks, hand, s("circle", {class: "dial-pin", cx: centre, cy: centre, r: 4}));
    const readout = h("output", {class: "dial-readout"});
    const root = h("div", {class: "undo-dial", role: "slider", tabindex: "0", "aria-label": label, "aria-valuemin": "0", "aria-valuemax": String(DIAL_MAX)}, face, readout);
    const set = (next) => {
      seconds = Math.max(0, Math.min(DIAL_MAX, Math.round(next)));
      const [x2, y2] = dialPoint(seconds, DIAL_RADIUS - 14);
      hand.setAttribute("x2", fixed(x2));
      hand.setAttribute("y2", fixed(y2));
      readout.textContent = `${seconds} s`;
      root.setAttribute("aria-valuenow", String(seconds));
      root.setAttribute("aria-valuetext", seconds ? `${seconds} seconds to undo` : "0 seconds: takes effect at once");
    };
    const pointed = (event) => {
      const box = face.getBoundingClientRect();
      const degrees = (Math.atan2(event.clientX - box.left - box.width / 2, box.top + box.height / 2 - event.clientY) * 180) / Math.PI;
      set(((degrees + 360) % 360) / (360 / DIAL_MAX));
    };
    root.addEventListener("keydown", (event) => {
      const steps = {ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: DIAL_PAGE, PageDown: -DIAL_PAGE};
      if (event.key in steps) {
        set(seconds + steps[event.key]);
      } else if (event.key === "Home" || event.key === "End") {
        set(event.key === "Home" ? 0 : DIAL_MAX);
      } else {
        return;
      }
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
    set(seconds);
    return {root, value: () => seconds};
  }
