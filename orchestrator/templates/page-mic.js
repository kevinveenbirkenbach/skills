  const MIC_HINT = "Voice input: tap to record, tap again to insert the text at the cursor; Escape cancels";
  const MIC_NODES = `${Voice.FIELDS}, button.mic`;
  const micButtons = new WeakMap();
  const micFields = new WeakMap();
  let micCount = 0;

  function micLive() {
    let live = document.getElementById("mic-live");
    if (!live) {
      live = h("div", {id: "mic-live", class: "mic-live", role: "status", "aria-live": "polite", hidden: true});
      document.body.append(live);
    }
    return live;
  }

  function micState(button) {
    const reason = micGap();
    button.disabled = Boolean(reason);
    button.title = reason || MIC_HINT;
  }

  /**
   * @param {HTMLButtonElement} button a recording control: a field's mic or the composer's Record.
   * @param {string} look idle, recording or busy; busy is the spinning hourglass every recording control shows while its sound becomes text.
   * @param {string} idle the icon at rest.
   * @param {Node[]} label what follows the icon; [] for an icon-only control.
   */
  function recLook(button, look, idle, label) {
    button.dataset.rec = look;
    button.setAttribute("aria-pressed", String(look === "recording"));
    button.setAttribute("aria-busy", String(look === "busy"));
    button.replaceChildren(icon(look === "recording" ? "bi-stop-fill" : look === "busy" ? "bi-hourglass-split" : idle), ...label);
  }

  const micKey = (field) => field.getAttribute("aria-label") || "";

  function micLook(button, look) {
    const recording = look === "recording";
    recLook(button, look, "bi-mic", []);
    button.setAttribute("aria-label", recording ? "Stop voice input" : look === "busy" ? "Voice input: transcribing" : "Voice input");
    micLive().hidden = !recording;
    if (look === "busy") {
      button.disabled = true;
    } else {
      micState(button);
    }
  }

  /**
   * @param {HTMLInputElement|HTMLTextAreaElement} field the text field the transcript lands in.
   * @returns {HTMLButtonElement} the microphone button of the field, made once and kept.
   */
  function micButton(field) {
    const kept = micButtons.get(field);
    if (kept) {
      return kept;
    }
    if (!field.id) {
      micCount += 1;
      field.id = `mic-field-${micCount}`;
    }
    const button = h("button", {type: "button", class: "mic", "aria-controls": field.id}, icon("bi-mic"));
    micButtons.set(field, button);
    micFields.set(button, field);
    field.dataset.mic = "on";
    // Trip-wire: polled views (choice dialogs, cards) rebuild a field while it records; its rebuilt twin under the same aria-label takes over the recording, or the new mic stays dead and the text lands in a detached field.
    const twin = mic.field && mic.field !== field && !mic.field.isConnected && micKey(field) && micKey(mic.field) === micKey(field);
    if (twin) {
      Object.assign(mic, {field, button});
    }
    micLook(button, twin ? (mic.busy ? "busy" : "recording") : "idle");
    button.addEventListener("click", () => toggleMic(field, button));
    return button;
  }

  const micFramed = (field) => Boolean(field.parentElement && field.parentElement.classList.contains("mic-frame"));

  /**
   * @param {HTMLInputElement|HTMLTextAreaElement} field the text field; it moves into the frame.
   * @param {Node[]} extras for a textarea what belongs to it besides its mic, on the footer's left (Record, a count); for a
   * one-line field the segments after the mic (its form's submit button); [] for none.
   * @returns {HTMLElement} one frame around field and mic, which takes pasted and dropped files: for a one-line field the
   * mic and then the extras as its last segments, for a textarea its chip row of attachments and a footer row below it
   * whose last child is the mic, the 📎 picker right before it.
   */
  function micFrame(field, extras) {
    const button = micButton(field);
    attachWire(field);
    if (field.tagName === "TEXTAREA") {
      return h("div", {class: "mic-frame mic-area"}, field, attachRow(field), h("div", {class: "mic-foot"}, extras, h("span", {class: "spacer"}), attachPicker(field), button));
    }
    return h("span", {class: "mic-frame mic-line"}, field, button, extras);
  }

  /**
   * @param {HTMLInputElement|HTMLTextAreaElement} field a text field the sweep frames.
   * @returns {HTMLButtonElement[]} the submit button right after a one-line field, which joins its frame behind the mic; [] otherwise.
   */
  function micSend(field) {
    const next = field.nextElementSibling;
    return field.tagName !== "TEXTAREA" && next && next.matches("button[type=submit]") ? [next] : [];
  }

  function micWrap(field) {
    const focused = document.activeElement === field;
    const [start, end] = [field.selectionStart, field.selectionEnd];
    const send = micSend(field);
    const [parent, next] = [field.parentNode, (send[0] || field).nextSibling];
    parent.insertBefore(micFrame(field, send), next);
    if (focused) {
      field.focus({preventScroll: true});
      field.setSelectionRange(start, end);
    }
  }

  function micSweep() {
    for (const field of document.querySelectorAll(Voice.FIELDS)) {
      if (!field.readOnly && !micFramed(field) && field.parentNode) {
        micWrap(field);
      }
    }
    for (const frame of document.querySelectorAll(".mic-frame")) {
      const button = frame.querySelector(":scope > button.mic, :scope > .mic-foot > button.mic");
      if (!button || micFields.get(button).parentElement !== frame) {
        frame.remove();
      }
    }
  }

  function micTouched(records) {
    return records.some((record) => [...record.addedNodes, ...record.removedNodes].some((node) => node instanceof Element && (node.matches(MIC_NODES) || Boolean(node.querySelector(MIC_NODES)))));
  }

  function micWatch() {
    micSweep();
    new MutationObserver((records) => micTouched(records) && micSweep()).observe(document.body, {childList: true, subtree: true});
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && mic.button && !mic.busy) {
        event.preventDefault();
        event.stopImmediatePropagation();
        stopMic(true);
      }
    }, true);
  }

  function stopMic(cancel) {
    mic.cancel = cancel;
    window.clearInterval(mic.timer);
    if (mic.recorder && mic.recorder.state === "recording") {
      mic.recorder.stop();
    }
  }

  function micTick() {
    const seconds = Math.floor((Date.now() - mic.started) / 1000);
    micLive().textContent = `Recording ${seconds} s of at most ${state.speech.input} s: tap the microphone again to insert, Escape cancels`;
    if (seconds >= state.speech.input) {
      stopMic(false);
    }
  }

  function micDone() {
    Object.assign(mic, {recorder: null, button: null, field: null, busy: false, cancel: false});
  }

  async function toggleMic(field, button) {
    if (mic.button) {
      if (!mic.button.isConnected) {
        Object.assign(mic, {field, button});
        micLook(button, mic.busy ? "busy" : "recording");
      }
      if (mic.button === button && mic.recorder) {
        stopMic(false);
      }
      return;
    }
    Object.assign(mic, {button, field, cancel: false});
    let media = null;
    try {
      media = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true}});
    } catch (error) {
      micDone();
      toast("Microphone not available", [String(error.message || error)], false);
      return;
    }
    if (mic.cancel) {
      media.getTracks().forEach((track) => track.stop());
      micDone();
      return;
    }
    const recorder = new MediaRecorder(media);
    const chunks = [];
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) {
        chunks.push(event.data);
      }
    });
    recorder.addEventListener("stop", () => {
      media.getTracks().forEach((track) => track.stop());
      window.clearInterval(mic.timer);
      mic.recorder = null;
      if (mic.cancel) {
        micLook(mic.button, "idle");
        micDone();
        return;
      }
      micTranscribe(new Blob(chunks, {type: recorder.mimeType}));
    }, {once: true});
    Object.assign(mic, {recorder, started: Date.now()});
    recorder.start();
    micLook(button, "recording");
    micTick();
    mic.timer = window.setInterval(micTick, 250);
  }

  function micInsert(field, text) {
    const start = field.selectionStart ?? field.value.length;
    const spliced = Voice.spliced(field.value, start, field.selectionEnd ?? start, text);
    field.value = spliced.value;
    field.focus();
    field.setSelectionRange(spliced.caret, spliced.caret);
    field.dispatchEvent(new Event("input", {bubbles: true}));
  }

  /**
   * @param {Blob} blob the recorded sound; its text lands in mic.field, which a rebuilt twin may have replaced meanwhile.
   */
  async function micTranscribe(blob) {
    const sound = context();
    if (!sound || !blob.size) {
      micLook(mic.button, "idle");
      micDone();
      return;
    }
    mic.busy = true;
    micLook(mic.button, "busy");
    try {
      const result = await send("/api/stt", await wavOf(blob, sound, state.speech.input), "audio/wav");
      if (!result.ok || !result.data) {
        throw new Error(`${result.status} ${result.text}`.trim());
      }
      micInsert(mic.field, result.data.text || "");
    } catch (error) {
      toast("Voice input failed", [String(error.message || error)], false);
    } finally {
      const button = mic.button;
      micDone();
      micLook(button, "idle");
    }
  }
