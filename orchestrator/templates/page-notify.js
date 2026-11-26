  const POPUP_CHOICES = [
    ["resources", "Resource warnings", "watch.py: RAM, disk and queue warnings"],
    ["mayday", "MAYDAY calls", "radio.py: a MAYDAY on the radio"],
    ["dream", "Dream reminder", "kvb-dream: the daily dream reminder"],
  ];
  const SNOOZE_HOUR = 3600;
  let notifySaves = Promise.resolve();

  function notifyFold(part) {
    part.notify = h("div", {class: "notify-sets"});
    part.notifySig = "";
    return h("details", {class: "radio-notify", on: {toggle: (event) => placeStation(event.currentTarget)}},
      h("summary", {title: "Notifications: the hub's channels and the GNOME desktop popups"}, caret(), h("h3", {class: "group-title"}, "Notifications")),
      h("div", {class: "station-body"}, part.notify));
  }

  /**
   * @param {function(object): object} change the keys to save, built from the
   *     settings current when the save runs, so quick clicks queue and none
   *     overwrites the one before it.
   */
  function saveNotify(change) {
    notifySaves = notifySaves.then(async () => {
      if (!await saveSettings({...settings, space: savedSpace(), ...change(settings)})) {
        liveParts("devices").forEach((part) => {
          part.notifySig = "";
        });
        drawNotify();
      }
    });
  }

  function channelBox(id, label) {
    const box = h("input", {type: "checkbox", name: `channel-${id}`, "data-focus": `channel-${id}`, checked: settings.channels[id]});
    box.addEventListener("change", () => {
      const on = box.checked;
      saveNotify((now) => ({channels: {...now.channels, [id]: on}}));
    });
    return h("label", {class: "check"}, box, label);
  }

  function popupRow([id, label, hint], now) {
    const entry = settings.popups[id];
    const put = (next) => saveNotify((current) => ({popups: {...current.popups, [id]: next}}));
    const snoozed = entry.on && entry.until > now;
    const state = entry.on ? (snoozed ? "snoozed" : "on") : "off";
    const box = h("input", {type: "checkbox", name: `popup-${id}`, "data-focus": `popup-${id}`, checked: entry.on});
    box.addEventListener("change", () => put({on: box.checked, until: 0}));
    const act = (key, text, title, next) => h("button", {type: "button", class: "btn small ghost", "data-focus": `${key}-${id}`, title: `${label}: ${title}`, on: {click: () => put(next())}}, text);
    return h("div", {class: "notify-source", "data-source": id, "data-state": state},
      h("label", {class: "check", title: hint}, box, label),
      h("span", {class: "muted notify-state"}, snoozed ? `snoozed until ${clock.format(stampOf(entry.until))}` : state),
      snoozed ? act("resume", "Resume", "popups again from now", () => ({on: true, until: 0})) : null,
      entry.on ? act("hour", "1 h", "no popup for 1 hour", () => ({on: true, until: Math.floor(nowSeconds()) + SNOOZE_HOUR})) : null,
      entry.on ? act("morning", "8:00", "no popup until 8 am tomorrow", () => ({on: true, until: tomorrow()})) : null);
  }

  function drawNotify() {
    const now = nowSeconds();
    const sig = JSON.stringify([settings.channels, settings.popups, Math.floor(now / 60)]);
    for (const part of liveParts("devices")) {
      if (sig === part.notifySig) {
        continue;
      }
      part.notifySig = sig;
      const focused = part.notify.contains(document.activeElement) ? document.activeElement.dataset.focus : "";
      part.notify.replaceChildren(
        h("fieldset", {class: "channels"}, h("legend", {}, "Notification channels"), CHANNEL_CHOICES.map(([id, label]) => channelBox(id, label))),
        h("fieldset", {class: "popups"}, h("legend", {}, "GNOME popups"),
          h("p", {class: "muted"}, "A muted source still reaches the Stream and the radio; only its desktop popup stays away. Your passkey signs every change."),
          POPUP_CHOICES.map((choice) => popupRow(choice, now))));
      const again = focused ? part.notify.querySelector(`[data-focus="${focused}"]`) : null;
      if (again) {
        again.focus();
      }
    }
  }
