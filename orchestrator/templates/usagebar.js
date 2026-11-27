const UsageBar = (() => {
  "use strict";
  const COLORS = {green: [0.72, 0.19, 145], yellow: [0.88, 0.18, 95], orange: [0.76, 0.17, 60], red: [0.63, 0.23, 27]};
  const STOPS = [[0, COLORS.green], [50, COLORS.yellow], [75, COLORS.orange], [100, COLORS.red]];
  const DAY = 86400000;
  const clamp = (value) => Math.min(100, Math.max(0, value));
  const tokensFrom = (entry, bound) => entry.hours.filter(([t]) => t * 1000 >= bound).reduce((sum, [, tokens]) => sum + tokens, 0);

  /**
   * @param share - percent of the limit used.
   * @returns [l, c, h] in OKLCH, linear between the stops 0 green, 50 yellow, 75 orange and 100 red; a share
   * outside 0 to 100 takes the nearest end.
   */
  function fillStop(share) {
    const at = clamp(share);
    const upper = STOPS.findIndex(([stop]) => stop >= at);
    const [to, high] = STOPS[upper];
    if (to === at) {
      return high;
    }
    const [from, low] = STOPS[upper - 1];
    const part = (at - from) / (to - from);
    return low.map((value, index) => value + (high[index] - value) * part);
  }

  const css = ([l, c, h]) => `oklch(${l.toFixed(3)} ${c.toFixed(3)} ${h.toFixed(1)})`;
  const fillColor = (share) => css(fillStop(share));

  /**
   * @param limit - the account's weekly token limit, a whole number from 0.
   * @param entry - the account's usage from /api/accounts: {total, hours: [[t, tokens]]}, t in epoch seconds.
   * @param calibration - {share, at} from /api/accounts, at in epoch seconds, or undefined.
   * @param last - the account's last reset, epoch milliseconds.
   * @returns {share, used, calibrated}: share the percent of the limit used since the last reset, the calibration's
   * share plus the tokens of the hours from its at when it is not older than the reset, else the tokens of the hours
   * from the reset; used the tokens that share stands for. An hour counts once its start is at or after the bound.
   */
  function usage(limit, entry, calibration, last) {
    const calibrated = Boolean(calibration) && calibration.at * 1000 >= last;
    const counted = tokensFrom(entry, calibrated ? calibration.at * 1000 : last);
    const percent = limit > 0 ? (100 * counted) / limit : counted > 0 ? 100 : 0;
    const share = (calibrated ? calibration.share : 0) + percent;
    return {share, used: Math.round((share * limit) / 100), calibrated};
  }

  /**
   * @param limit - the account's weekly token limit, above 0.
   * @param entry - the account's usage as usage() takes it.
   * @param share - usage().share now.
   * @param now - epoch milliseconds.
   * @param next - the account's next reset, epoch milliseconds.
   * @returns {share, full}: share the percent expected at next when the tokens of the hours of the last 24 h keep
   * their rate; full the epoch milliseconds the share reaches 100 % when that comes before next, else null.
   */
  function forecast(limit, entry, share, now, next) {
    const rate = (100 * tokensFrom(entry, now - DAY)) / limit / DAY;
    const full = share >= 100 ? now : rate > 0 ? now + (100 - share) / rate : Infinity;
    return {share: share + rate * (next - now), full: full < next ? full : null};
  }

  return {COLORS, STOPS, fillStop, fillColor, css, usage, forecast};
})();
if (typeof module === "object" && module.exports) {
  module.exports = UsageBar;
}
