const Gibberlink = (() => {
  "use strict";
  const VOLUME = 50;
  const PREFIX = "GGWAVE_PROTOCOL_";

  /**
   * @param {object} ggwave the loaded ggwave module.
   * @param {object} request protocol, a ggwave protocol name without its prefix, and frames, the frame texts.
   * @returns {object} rate and samples: the samples of each frame at ggwave's own output rate; the vendored build's frames at 44.1 kHz do not decode, so the page resamples instead.
   */
  function encode(ggwave, request) {
    const {protocol, frames} = request;
    const key = `${PREFIX}${protocol}`;
    if (typeof protocol !== "string" || !Object.hasOwn(ggwave.ProtocolId, key) || !Array.isArray(frames) || !frames.every((frame) => typeof frame === "string")) {
      throw new Error("refused: the request needs a known protocol and text frames");
    }
    const parameters = ggwave.getDefaultParameters();
    const instance = ggwave.init(parameters);
    try {
      return {rate: parameters.sampleRateOut, samples: frames.map((frame) => {
        const wave = ggwave.encode(instance, frame, ggwave.ProtocolId[key], VOLUME);
        return new Float32Array(wave.buffer.slice(wave.byteOffset, wave.byteOffset + wave.length));
      })};
    } finally {
      ggwave.free(instance);
    }
  }

  /**
   * @param {Window} scope the encoder frame's window; it answers only its parent.
   * @param {Promise<object>} ready the ggwave module once loaded.
   */
  function serve(scope, ready) {
    scope.addEventListener("message", (event) => {
      if (event.source !== scope.parent || !event.data || typeof event.data.id !== "number") {
        return;
      }
      const {id} = event.data;
      ready.then((ggwave) => encode(ggwave, event.data)).then(
        ({rate, samples}) => scope.parent.postMessage({id, rate, samples}, "*", samples.map((part) => part.buffer)),
        (error) => scope.parent.postMessage({id, error: String((error && error.message) || error)}, "*"),
      );
    });
  }

  return {VOLUME, encode, serve};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Gibberlink;
}
