const Dial = (() => {
  "use strict";
  const SIZE = 140;
  const RADIUS = 58;
  const TICKS = 60;
  const READOUT = 24;
  const MINUTE = 60;
  const SECOND = 1000;

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

  /**
   * @param value - a value on the dial, fractions allowed.
   * @param max - the value a full turn stands for.
   * @returns the hand's angle from the top, clockwise, in degrees.
   */
  function angle(value, max) {
    return (value * 360) / max;
  }

  /**
   * @param seconds - seconds left, rounded up to whole seconds and never below 0.
   * @returns them as m:ss, the readout of a clock that runs out.
   */
  function countdown(seconds) {
    const whole = Math.max(0, Math.ceil(seconds));
    return `${Math.floor(whole / MINUTE)}:${String(whole % MINUTE).padStart(2, "0")}`;
  }

  /**
   * @param epoch - a moment in epoch milliseconds.
   * @returns its local time of day as HH:MM:SS, the readout of a wall clock.
   */
  function wall(epoch) {
    const at = new Date(epoch);
    return [at.getHours(), at.getMinutes(), at.getSeconds()].map((part) => String(part).padStart(2, "0")).join(":");
  }

  /**
   * @param until - the epoch seconds the clock runs out at.
   * @param per - how many seconds one value of the dial stands for: 60 on a face of minutes, 1 on one of seconds.
   * @returns (epoch milliseconds) => {at, value, text}: at the hand's exact place in dial values, value the whole
   * values left rounded up, text the seconds left as m:ss; all three stop at 0.
   */
  function counting(until, per) {
    return (epoch) => {
      const left = Math.max(0, until - epoch / SECOND);
      return {at: left / per, value: Math.ceil(left / per), text: countdown(left)};
    };
  }

  /**
   * @returns (epoch milliseconds) => {at, value, text}: a wall clock on a face of 60, its hand sweeping the seconds
   * of the minute, value the whole second and text the local time of day as HH:MM:SS.
   */
  function walled() {
    return (epoch) => {
      const at = new Date(epoch);
      return {at: at.getSeconds() + at.getMilliseconds() / SECOND, value: at.getSeconds(), text: wall(epoch)};
    };
  }

  /**
   * @param progress - how far a sweep is, 0 to 1.
   * @returns the share of the way the hand has turned: fast at first, slowing into its place.
   */
  function eased(progress) {
    return 1 - (1 - progress) ** 3;
  }

  return {SIZE, RADIUS, TICKS, READOUT, point, clamp, fromAngle, stepped, ticks, angle, countdown, wall, counting, walled, eased};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Dial;
}
