  const CHANNELS = [...TO_ONE, ...TO_ALL];
  const CHANNEL_HINTS = {
    post: "Post arrives at the end of the turn.",
    call: "Call arrives at once, with a read receipt.",
    newsletter: "Newsletter arrives as post to all, at the end of their turn.",
    broadcast: "Broadcast reaches all at once.",
    "pan-pan": "PAN-PAN: urgent, to all, at once.",
    security: "Sécurité: safety notice to all stations, now.",
    mayday: "MAYDAY: all agents pause writing steps until you cancel it.",
  };
  const VOICE_POLL = 700;
  const HOLD_MS = 350;
  const composer = {live: null};

  function confirmMayday() {
    return window.confirm("Send a mayday to all? All agents pause writing steps until you cancel it.");
  }

  async function radioSend(message) {
    const label = `${CLASSES[message.cls] || message.cls} to ${message.to === "*" ? "all" : message.to}`;
    const fields = {to: message.to, text: message.text, upload: message.upload, class: message.cls, voice: message.voice};
    const signed = await signedProof("/api/messages/sign", fields, label);
    if (!signed) {
      return false;
    }
    const {proof} = signed;
    const result = message.to === "*"
      ? await sendJson("/api/board/broadcast", {text: fields.text, class: fields.class, voice: fields.voice, proof})
      : await sendJson("/api/messages", {...fields, proof});
    if (!result.ok || !result.data) {
      toast(`${label} failed`, fail(result), false);
      return false;
    }
    toast(`${label}: ${result.data.ok ? "sent" : "stored, sending failed"}`, [...(result.data.id ? [`kvb-orchestrator msg ${result.data.id}`] : []), ...runLines(result.data)], result.data.ok);
    await load();
    return true;
  }

  function attachVoice(parts, note) {
    parts.voice = note;
    parts.attach.checked = false;
    parts.replay.hidden = !note;
    const audio = note ? voiceReplay(note) : null;
    parts.replay.replaceChildren(...(note ? [icon("bi-soundwave"), h("span", {class: "muted voice-words"}, "Voice message"), audio, playToggle(audio), h("label", {class: "check"}, parts.attach, h("span", {}, "Attach", h("span", {class: "voice-words"}, " recording"))), iconBtn("bi-trash", "Remove recording", "btn small ghost", () => attachVoice(parts, ""))] : []));
  }

  function playToggle(audio) {
    const button = iconBtn("bi-play-fill", "Play voice message", "btn small ghost voice-play", () => (audio.paused ? audio.play().catch((error) => toast("Playback failed", [String(error)], false)) : audio.pause()));
    const show = () => {
      const label = audio.paused ? "Play voice message" : "Pause voice message";
      button.setAttribute("aria-label", label);
      button.title = label;
      button.querySelector("use").setAttribute("href", audio.paused ? "#bi-play-fill" : "#bi-pause-fill");
    };
    for (const kind of ["play", "pause", "ended"]) {
      audio.addEventListener(kind, show);
    }
    return button;
  }

  async function heardNote(note) {
    const until = Date.now() + (state.speech.seconds + 60) * 1000;
    while (Date.now() < until) {
      const response = await fetch(`/api/voice/${note}`, {cache: "no-store"});
      const data = response.ok ? await response.json() : {status: "failed", error: `${response.status} ${(await response.text()).trim()}`};
      if (data.status !== "pending") {
        return data;
      }
      await new Promise((resolve) => window.setTimeout(resolve, VOICE_POLL));
    }
    return {status: "failed", error: "no transcript in the expected time"};
  }

  async function keepRecording(blob, parts) {
    const held = parts.ptt === "released";
    parts.ptt = "";
    parts.record.disabled = true;
    try {
      const sound = context();
      if (!sound || !blob.size) {
        throw new Error("no recording");
      }
      parts.status.textContent = "Converting …";
      const stored = await send("/api/voice", await wavOf(blob, sound, state.speech.seconds), "audio/wav");
      if (!stored.ok || !stored.data) {
        throw new Error(`${stored.status} ${stored.text}`.trim());
      }
      attachVoice(parts, stored.data.id);
      parts.status.textContent = "Transcribing …";
      const note = await heardNote(stored.data.id);
      if (note.status === "failed") {
        parts.status.textContent = "No transcript: write the text yourself.";
        toast("Transcript failed", [note.error], false);
        return;
      }
      parts.text.value = [parts.text.value.trim(), note.text].filter(Boolean).join(" ");
      parts.text.dispatchEvent(new Event("input", {bubbles: true}));
      parts.text.focus();
      parts.status.textContent = note.text ? "Check the text, then send." : "Nothing understood: write the text yourself.";
      if (held && note.text) {
        parts.text.form.requestSubmit();
      }
    } catch (error) {
      parts.status.textContent = "";
      toast("Recording failed", [String(error.message || error)], false);
    } finally {
      parts.record.disabled = false;
    }
  }

  function recordLabel(parts, on) {
    parts.record.setAttribute("aria-pressed", String(on));
    parts.record.replaceChildren(icon(on ? "bi-stop-fill" : "bi-record-circle"), on ? "Stop" : "Record");
  }

  function stopRecording(parts) {
    if (parts && parts.recorder && parts.recorder.state === "recording") {
      parts.recorder.stop();
    }
  }

  function freeMicrophone(parts) {
    if (composer.live && composer.live !== parts) {
      stopRecording(composer.live);
    }
  }

  async function startRecording(parts) {
    freeMicrophone(parts);
    let media = null;
    try {
      media = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true}});
    } catch (error) {
      toast("Microphone unavailable", [String(error.message || error)], false);
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
      window.clearInterval(parts.timer);
      parts.recorder = null;
      if (composer.live === parts) {
        composer.live = null;
      }
      recordLabel(parts, false);
      keepRecording(new Blob(chunks, {type: recorder.mimeType}), parts);
    }, {once: true});
    freeMicrophone(parts);
    Object.assign(parts, {recorder, started: Date.now()});
    composer.live = parts;
    recorder.start();
    recordLabel(parts, true);
    if (parts.ptt === "released") {
      stopRecording(parts);
    }
    parts.timer = window.setInterval(() => {
      const seconds = Math.floor((Date.now() - parts.started) / 1000);
      parts.status.textContent = `Recording ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")} of at most ${state.speech.seconds} s`;
      if (seconds >= state.speech.seconds) {
        stopRecording(parts);
      }
    }, 250);
  }

  function composerForm() {
    const channel = h("select", {class: "field"}, CHANNELS.map(([id, label]) => h("option", {value: id}, label)));
    const recipient = h("select", {class: "field"});
    const toField = h("label", {}, "To", recipient);
    const text = h("textarea", {"aria-label": "Message", placeholder: "Message to the agents …", maxlength: 20000});
    const replay = h("div", {class: "voice-note", hidden: true});
    const hint = h("span", {class: "muted composer-hint"});
    const status = h("span", {class: "muted composer-status", "aria-live": "polite"});
    const record = h("button", {type: "button", class: "btn small", "aria-pressed": "false", title: "Record: one click starts, another stops, you check the text before sending; hold it to talk, release to send"});
    const submit = h("button", {type: "submit", class: "btn primary ptt", title: "PTT: push to transmit the message; your passkey signs it"}, icon("bi-broadcast-pin"), "PTT");
    const attach = h("input", {type: "checkbox", title: "Attach recording: the agents get the path of the sound file; otherwise only the checked text goes out"});
    const parts = {record, status, text, replay, attach, voice: "", recorder: null, timer: 0, started: 0, ptt: "", hold: 0, swallow: false};
    recordLabel(parts, false);
    const gap = micGap();
    if (gap) {
      record.disabled = true;
      record.title = `Record: ${gap}`;
    }
    holdToTalk(parts);
    record.addEventListener("click", () => {
      if (parts.swallow) {
        parts.swallow = false;
        return;
      }
      parts.ptt = "";
      if (parts.recorder) {
        stopRecording(parts);
      } else {
        startRecording(parts);
      }
    });
    const [, cancel, , cancelHint] = actionOf("clear-mayday");
    const clear = h("button", {type: "button", class: "btn small danger radio-cancel", hidden: !state.silence, ...named(cancel, cancelHint), on: {click: () => confirmAct("clear-mayday", [])}}, icon("bi-life-preserver"), cancel);
    const sync = () => {
      const direct = TO_ONE.some(([id]) => id === channel.value);
      toField.hidden = !direct;
      hint.textContent = `${CHANNEL_HINTS[channel.value]} Your passkey signs every message.`;
      channel.title = hint.textContent;
    };
    channel.addEventListener("change", sync);
    sync();
    const form = h("form", {class: "composer"}, h("div", {class: "composer-grid"}, h("label", {}, "Channel", channel), toField), text, replay,
      h("div", {class: "actions"}, record, micButton(text, false), status, hint, clear, h("div", {class: "ptt-split", role: "group", "aria-label": "Send"}, submit, testMenu(text, channel))));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const direct = TO_ONE.some(([id]) => id === channel.value);
      if (!text.value.trim()) {
        toast("Nothing to send", ["Write a text or record one; the transcript lands in the field for checking."], false);
        return;
      }
      if ((direct && !recipient.value) || (channel.value === "mayday" && !confirmMayday())) {
        return;
      }
      submit.disabled = true;
      if (await radioSend({to: direct ? recipient.value : "*", text: text.value, upload: "", cls: channel.value, voice: attach.checked ? parts.voice : ""})) {
        text.value = "";
        status.textContent = "";
        attachVoice(parts, "");
      }
      submit.disabled = false;
    });
    attachVoice(parts, "");
    return {form, recipient, text, channel, clear};
  }

  function holdToTalk(parts) {
    const {record} = parts;
    record.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || record.disabled || parts.recorder) {
        return;
      }
      parts.hold = window.setTimeout(() => {
        parts.ptt = "holding";
        startRecording(parts);
      }, HOLD_MS);
    });
    const release = () => {
      window.clearTimeout(parts.hold);
      if (parts.ptt === "holding") {
        Object.assign(parts, {ptt: "released", swallow: true});
        stopRecording(parts);
      }
    };
    for (const kind of ["pointerup", "pointercancel", "pointerleave"]) {
      record.addEventListener(kind, release);
    }
  }

  /**
   * @param {Element} text the message field.
   * @param {Element} channel the class select.
   * @returns {Element} the ▾ of PTT: a menu whose item reads the message, or a sample line, aloud here only, so nothing leaves the browser.
   */
  function testMenu(text, channel) {
    const item = h("button", {type: "button", class: "menu-item", ...named("Test message", "Test message: hear it here as the radio reads it aloud; nothing is sent, nothing is signed"), on: {click: (event) => {
      event.currentTarget.closest("details").open = false;
      if (!state.speech.tts) {
        toast("No test message", [`The hub speaks no line: ${state.speech.tts_off}.`], false);
        return;
      }
      say({steps: [{kind: "speech", text: text.value.trim() || state.speech.sample}], voice: state.speech.operator, tone: "direct", cls: channel.value, who: HUMAN, sent: true, line: "test message"});
    }}}, icon("bi-play-fill"), "Test message");
    return h("details", {class: "menu ptt-menu"}, h("summary", {class: "btn primary ptt-more", ...named("More send options", "More: send a test message only you hear")}, caret()), h("div", {class: "menu-box end"}, item));
  }
