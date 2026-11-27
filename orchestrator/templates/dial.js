const Dial = (() => {
  "use strict";
  const SIZE = 140;
  const RADIUS = 58;
  const TICKS = 60;

  /**
   * @param value - a value on the dial, min to max.
   * @param max - the value a full turn stands for.
   * @param radius - how far from the centre.
   * @returns the point [x, y] for that value, 0 and max at the top, clockwise.
   */
  function point(value, max, radius) {
    const angle = (value / max) * 2 * Math.PI;
    const centre = SIZE / 2;
    return [centre + Math.sin(angle) * radius, centre - Math.cos(angle) * radius];
  }

  /**
   * @param value - any number.
   * @param range - {min, max}: the dial's ends.
   * @returns value rounded to a whole number and held between min and max.
   */
  function clamp(value, range) {
    return Math.max(range.min, Math.min(range.max, Math.round(value)));
  }

  /**
   * @param degrees - the pointer's angle from the top, clockwise, in degrees.
   * @param max - the value a full turn stands for.
   * @returns the value at that angle, unrounded.
   */
  function fromAngle(degrees, max) {
    return ((degrees + 360) % 360) / (360 / max);
  }

  /**
   * @param key - a KeyboardEvent key.
   * @param value - the dial's value.
   * @param options - {min, max, page}: the ends and the Page Up and Down step.
   * @returns the value the key sets, held to the ends, or null for a key the dial ignores: the arrows step 1, Page Up and
   * Down step page, Home and End go to min and max.
   */
  function stepped(key, value, options) {
    const steps = {ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: options.page, PageDown: -options.page};
    if (key in steps) {
      return clamp(value + steps[key], options);
    }
    return key === "Home" ? options.min : key === "End" ? options.max : null;
  }

  /**
   * @param page - every page-th tick is long.
   * @returns the TICKS ticks of the face, each {at, long}: at its place on a turn of TICKS.
   */
  function ticks(page) {
    return Array.from({length: TICKS}, (_, at) => ({at, long: at % page === 0}));
  }

  return {SIZE, RADIUS, TICKS, point, clamp, fromAngle, stepped, ticks};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Dial;
}
