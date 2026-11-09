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
  const composer = {voice: "", recorder: null, timer: 0, started: 0};

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
    composer.voice = note;
    parts.attach.checked = false;
    parts.replay.hidden = !note;
    parts.replay.replaceChildren(...(note ? [icon("bi-soundwave"), h("span", {class: "muted"}, "Voice message"), voiceReplay(note), h("label", {class: "check"}, parts.attach, "Attach recording"), iconBtn("bi-trash", "Remove recording", "btn small ghost", () => attachVoice(parts, ""))] : []));
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
    parts.record.disabled = true;
    try {
      const sound = context();
      if (!sound || !blob.size) {
        throw new Error("no recording");
      }
      parts.status.textContent = "Converting …";
      const stored = await send("/api/voice", await wavOf(blob, sound), "audio/wav");
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

  function stopRecording() {
    if (composer.recorder && composer.recorder.state === "recording") {
      composer.recorder.stop();
    }
  }

  async function startRecording(parts) {
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
      window.clearInterval(composer.timer);
      composer.recorder = null;
      recordLabel(parts, false);
      keepRecording(new Blob(chunks, {type: recorder.mimeType}), parts);
    }, {once: true});
    Object.assign(composer, {recorder, started: Date.now()});
    recorder.start();
    recordLabel(parts, true);
    composer.timer = window.setInterval(() => {
      const seconds = Math.floor((Date.now() - composer.started) / 1000);
      parts.status.textContent = `Recording ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")} of at most ${state.speech.seconds} s`;
      if (seconds >= state.speech.seconds) {
        stopRecording();
      }
    }, 250);
  }

  function composerForm() {
    const channel = h("select", {class: "field"}, CHANNELS.map(([id, label]) => h("option", {value: id}, label)));
    const recipient = h("select", {class: "field"});
    const toField = h("label", {}, "To", recipient);
    const text = h("textarea", {"aria-label": "Message", placeholder: "Message to the agents …", maxlength: 20000});
    const replay = h("div", {class: "voice-note", hidden: true});
    const hint = h("p", {class: "muted"});
    const status = h("span", {class: "muted composer-status", "aria-live": "polite"});
    const record = h("button", {type: "button", class: "btn small", "aria-pressed": "false", title: "Record: one click starts, another stops; the hub transcribes, you check the text before sending"});
    const submit = h("button", {type: "submit", class: "btn primary"}, icon("bi-send"), "Send");
    const attach = h("input", {type: "checkbox", title: "Attach recording: the agents get the path of the sound file; otherwise only the checked text goes out"});
    const parts = {record, status, text, replay, attach};
    recordLabel(parts, false);
    const gap = micGap();
    if (gap) {
      record.disabled = true;
      record.title = `Record: ${gap}`;
    }
    record.addEventListener("click", () => (composer.recorder ? stopRecording() : startRecording(parts)));
    const sync = () => {
      const direct = TO_ONE.some(([id]) => id === channel.value);
      toField.hidden = !direct;
      hint.textContent = `${CHANNEL_HINTS[channel.value]} Your passkey signs every message.`;
    };
    channel.addEventListener("change", sync);
    sync();
    const form = h("form", {class: "composer"}, h("div", {class: "composer-grid"}, h("label", {}, "Channel", channel), toField), text, replay, hint,
      h("div", {class: "actions"}, record, status, h("span", {class: "spacer"}), submit));
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
      if (await radioSend({to: direct ? recipient.value : "*", text: text.value, upload: "", cls: channel.value, voice: attach.checked ? composer.voice : ""})) {
        text.value = "";
        status.textContent = "";
        attachVoice(parts, "");
      }
      submit.disabled = false;
    });
    attachVoice(parts, composer.voice);
    return {form, recipient};
  }
