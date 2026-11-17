  const GIBBER = {gap: 0.3, timeout: 15000, route: "/gibberlink"};
  const gibber = {frame: null, ready: null, pending: new Map(), next: 0};

  function gibberFrame() {
    if (!gibber.frame) {
      const frame = h("iframe", {class: "gibberlink-encoder", src: GIBBER.route, sandbox: "allow-scripts", title: "Gibberlink encoder", "aria-hidden": "true", tabindex: "-1", hidden: true});
      gibber.ready = new Promise((resolve) => frame.addEventListener("load", resolve, {once: true}));
      window.addEventListener("message", gibberAnswer);
      document.body.append(frame);
      gibber.frame = frame;
    }
    return gibber;
  }

  function gibberAnswer(event) {
    const waiting = gibber.frame && event.source === gibber.frame.contentWindow && event.data ? gibber.pending.get(event.data.id) : null;
    if (!waiting) {
      return;
    }
    gibber.pending.delete(event.data.id);
    window.clearTimeout(waiting.timer);
    const {rate, samples, error} = event.data;
    if (error) {
      waiting.reject(new Error(String(error)));
    } else if (Number.isFinite(rate) && rate > 0 && Array.isArray(samples) && samples.every((part) => part instanceof Float32Array)) {
      waiting.resolve({rate, samples});
    } else {
      waiting.reject(new Error("the Gibberlink encoder answered no samples"));
    }
  }

  /**
   * @param {object} step a Gibberlink step with frames and protocol.
   * @returns {Promise<object>} rate and samples: the samples of each frame from the sandboxed encoder frame, at its rate.
   */
  function gibberEncode(step) {
    const {frame, ready, pending} = gibberFrame();
    gibber.next += 1;
    const id = gibber.next;
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        pending.delete(id);
        reject(new Error("the Gibberlink encoder did not answer"));
      }, GIBBER.timeout);
      pending.set(id, {resolve, reject, timer});
      ready.then(() => frame.contentWindow.postMessage({id, protocol: step.protocol, frames: step.frames}, "*"));
    });
  }

  /**
   * @param {AudioContext} sound the page's audio context.
   * @param {object} item the row that sounds.
   * @param {object} step its Gibberlink step: frames, protocol and pan.
   * @returns {Promise<boolean>} whether the whole row sounded uncut: the frames one after another with a short gap, at the row's tone volume times the squelch, in the sender's stereo position.
   */
  async function keyGibberlink(sound, item, step) {
    const level = loudness(item.tone);
    if (level <= 0 || !step.frames.length) {
      return false;
    }
    const {rate, samples: parts} = await gibberEncode(step);
    if (speech.item !== item) {
      return false;
    }
    if (!allows(rendered(item, item.at), "gibberlink")) {
      item.cut = true;
      return false;
    }
    const gap = Math.round(rate * GIBBER.gap);
    const buffer = sound.createBuffer(1, parts.reduce((sum, part) => sum + part.length + gap, 0), rate);
    const data = buffer.getChannelData(0);
    parts.reduce((at, part) => {
      data.set(part, at);
      return at + part.length + gap;
    }, 0);
    const source = sound.createBufferSource();
    const gain = sound.createGain();
    const pan = sound.createStereoPanner();
    gain.gain.value = level;
    pan.pan.value = step.pan;
    source.buffer = buffer;
    source.connect(gain).connect(pan).connect(sound.destination);
    voicePace(item, Infinity, buffer.duration);
    const ended = sounded(item, source, buffer.duration);
    source.start();
    return ended.then(() => speech.item === item && !item.cut);
  }
