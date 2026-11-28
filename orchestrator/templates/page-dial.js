  const DIAL_MAX = 60;
  const DIAL_PAGE = 5;
  const DIAL_SWEEP = 200;

  /**
   * @param {Object} options value: the whole value the dial starts at; label: the slider's accessible name; name: the
   * root's own class; min, max: the ends, max a full turn; page: the Page Up and Down step and the long-tick spacing;
   * readout: (value) => the text inside the face below the pivot; spoken: (value) => the aria-valuetext; readonly: true
   * for a dial only the caller moves; live: null, or the source of a running clock, (epoch milliseconds) => {at, value,
   * text} such as Dial.counting() or Dial.walled(), which then turns the hand and sets value and readout every frame.
   * @returns {root, value, set}: an analog clock face with Dial.TICKS ticks, one hand and the readout, an ARIA slider:
   * dragging the hand or clicking a tick sets it, the arrows step 1, Page Up and Down page, Home and End the ends;
   * set(value) moves it. The hand sweeps to each new value over DIAL_SWEEP ms and a live hand never stops; the frames end
   * on the first one that finds the root out of the page, so the caller attaches the root in the same task.
   */
  function dial(options) {
    let current = null;
    let shown = 0;
    let sweep = {from: 0, to: 0, start: 0};
    let frame = 0;
    const centre = Dial.SIZE / 2;
    const ticks = Dial.ticks(options.page).map(({at, long}) => {
      const [x1, y1] = Dial.point(at, Dial.TICKS, Dial.RADIUS - (long ? 10 : 5));
      const [x2, y2] = Dial.point(at, Dial.TICKS, Dial.RADIUS);
      return s("line", {class: `dial-tick${long ? " long" : ""}`, x1: fixed(x1), y1: fixed(y1), x2: fixed(x2), y2: fixed(y2)});
    });
    const hand = s("line", {class: "dial-hand", x1: centre, y1: centre, x2: centre, y2: fixed(centre - Dial.RADIUS + 14)});
    const readout = s("text", {class: "dial-readout", x: centre, y: centre + Dial.READOUT});
    const face = s("svg", {class: "dial-face", viewBox: `0 0 ${Dial.SIZE} ${Dial.SIZE}`, "aria-hidden": "true", focusable: "false"},
      s("circle", {class: "dial-rim", cx: centre, cy: centre, r: Dial.RADIUS + 4}), ticks, readout, hand, s("circle", {class: "dial-pin", cx: centre, cy: centre, r: 4}));
    const root = h("div", {class: `dial ${options.name}`, role: "slider", tabindex: "0", "aria-label": options.label, "aria-valuemin": String(options.min), "aria-valuemax": String(options.max),
      "aria-readonly": options.readonly || options.live ? "true" : null}, face);
    const turn = (degrees) => {
      shown = degrees;
      hand.setAttribute("transform", `rotate(${degrees.toFixed(3)} ${centre} ${centre})`);
    };
    const show = (value, words) => {
      if (value === current && readout.textContent === words) {
        return;
      }
      current = value;
      readout.textContent = words;
      root.setAttribute("aria-valuenow", String(value));
      root.setAttribute("aria-valuetext", options.spoken(value));
    };
    const running = () => {
      const at = options.live(Date.now());
      turn(Dial.angle(Math.min(at.at, options.max), options.max));
      show(Dial.clamp(at.value, options), at.text);
    };
    const step = (now) => {
      frame = 0;
      if (!root.isConnected) {
        return;
      }
      if (options.live) {
        running();
      } else {
        const progress = Math.max(0, Math.min(1, (now - sweep.start) / DIAL_SWEEP));
        turn(sweep.from + (sweep.to - sweep.from) * Dial.eased(progress));
        if (progress === 1) {
          return;
        }
      }
      frame = window.requestAnimationFrame(step);
    };
    const set = (next) => {
      const value = Dial.clamp(next, options);
      show(value, options.readout(value));
      sweep = {from: shown, to: Dial.angle(value, options.max), start: performance.now()};
      if (!frame) {
        frame = window.requestAnimationFrame(step);
      }
    };
    if (options.live) {
      running();
      frame = window.requestAnimationFrame(step);
    } else {
      const value = Dial.clamp(options.value, options);
      show(value, options.readout(value));
      turn(Dial.angle(value, options.max));
    }
    if (options.readonly || options.live) {
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
    return dial({value, label, name: "undo-dial", min: 0, max: DIAL_MAX, page: DIAL_PAGE, readout: Dial.countdown, spoken, readonly: false, live: null});
  }
