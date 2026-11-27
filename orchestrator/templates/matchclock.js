const MatchClock = (() => {
  "use strict";
  const MIN = 1;
  const MAX = 60;
  const PAGE = 5;
  const SECOND = 1000;

  /**
   * @param seconds - the refresh interval the hub settings hold.
   * @returns seconds rounded to whole seconds and held between MIN and MAX.
   */
  function bounded(seconds) {
    return Math.max(MIN, Math.min(MAX, Math.round(seconds)));
  }

  /**
   * @param fetched - when the last /api/match fetch started, epoch milliseconds.
   * @param seconds - the refresh interval.
   * @returns when the next fetch is due, epoch milliseconds.
   */
  function next(fetched, seconds) {
    return fetched + bounded(seconds) * SECOND;
  }

  /**
   * @param now - the time now, epoch milliseconds.
   * @param fetched - when the last fetch started, epoch milliseconds.
   * @param seconds - the refresh interval.
   * @returns how many milliseconds the timer waits for the next fetch, never below 0.
   */
  function wait(now, fetched, seconds) {
    return Math.max(0, next(fetched, seconds) - now);
  }

  /**
   * @param now - the time now, epoch milliseconds.
   * @param fetched - when the last fetch started, epoch milliseconds.
   * @param seconds - the refresh interval.
   * @returns true once the next fetch is due.
   */
  function due(now, fetched, seconds) {
    return wait(now, fetched, seconds) === 0;
  }

  return {MIN, MAX, PAGE, SECOND, bounded, next, wait, due};
})();
if (typeof module === "object" && module.exports) {
  module.exports = MatchClock;
}
