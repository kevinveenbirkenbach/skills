  const AGENT_SWITCHES = [
    ["sound", "bi-bell", "Sound", "its tones, Morse and Gibberlink on the radio"],
    ["aloud", "bi-megaphone", "Read aloud", "the radio speaks its rows"],
    ["bubbles", "bi-chat-quote", "Bubbles", "a speech bubble beside its face"],
  ];
  let agentSaves = Promise.resolve();

  const agentOn = (key, what) => RadioSet.heard({class: "", source: key}, settings.agents, what);

  function setAgent(key, what) {
    agentSaves = agentSaves.then(async () => {
      const entry = {...Object.fromEntries(AGENT_SWITCHES.map(([name]) => [name, agentOn(key, name)])), [what]: !agentOn(key, what)};
      if (!await saveSettings({...settings, space: savedSpace(), agents: {...settings.agents, [key]: entry}})) {
        drawAgentSettings();
      }
    });
  }

  function agentSettings(key) {
    return h("div", {class: "agent-settings", role: "group", "aria-label": `${nameOf(key)}: radio and bubbles`, "data-agent": key},
      AGENT_SWITCHES.map(([what, glyph, label]) => h("button", {type: "button", class: "btn small agent-switch", "data-switch": what, on: {click: () => setAgent(key, what)}}, icon(glyph), label)),
      h("p", {class: "muted"}, "For this agent only; a MAYDAY always sounds, speaks and shows."));
  }

  function paintAgentSettings(group) {
    const key = group.dataset.agent;
    const name = nameOf(key);
    for (const button of group.querySelectorAll("[data-switch]")) {
      const [what, , label, hint] = AGENT_SWITCHES.find(([id]) => id === button.dataset.switch);
      const on = agentOn(key, what);
      button.setAttribute("aria-pressed", String(on));
      button.title = `${label} for ${name}: ${on ? "on" : "off"}, ${hint}; a press turns it ${on ? "off" : "on"}`;
    }
  }

  function drawAgentSettings() {
    document.querySelectorAll(".agent-settings[data-agent]").forEach(paintAgentSettings);
  }
