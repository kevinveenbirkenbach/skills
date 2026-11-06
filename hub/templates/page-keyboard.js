  function helpSheet() {
    openSheet("Tastenkürzel", [h("dl", {class: "keys"}, KEYS.map(([key, text]) => [h("dt", {}, key), h("dd", {}, text)])),
      h("p", {class: "muted"}, "Leitstand: Vollbild mit großem Status für den zweiten Bildschirm. Auf schmalen Bildschirmen öffnet die Leiste unten die Inbox.")], false);
  }

  function overlayOpen() {
    return !document.getElementById("palette").hidden || !document.getElementById("sheet").hidden;
  }

  function moveCursor(delta) {
    const items = visibleInbox();
    if (!items.length) {
      return;
    }
    ui.cursor = Math.min(Math.max(ui.cursor + delta, 0), items.length - 1);
    drawInbox();
    const current = document.querySelector(`#rail .item[data-index="${ui.cursor}"]`);
    if (current) {
      current.scrollIntoView({block: "nearest"});
    }
  }

  function keyboard(event) {
    const target = event.target;
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (document.getElementById("palette").hidden) {
        openPalette();
      } else {
        closePalette();
      }
      return;
    }
    if (event.key === "Escape") {
      if (!document.getElementById("palette").hidden) {
        closePalette();
      } else if (!document.getElementById("sheet").hidden) {
        closeSheet();
      } else if (space.look) {
        skyLook(false);
      } else if (ui.agent !== null) {
        closeAgent();
      } else {
        document.body.classList.remove("inbox-open");
      }
      return;
    }
    if (event.altKey || event.ctrlKey || event.metaKey || event.isComposing || overlayOpen()) {
      return;
    }
    if (target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) {
      return;
    }
    const current = visibleInbox()[ui.cursor];
    const index = Number(event.key) - 1;
    if (/^[1-3]$/.test(event.key)) {
      event.preventDefault();
      go(SCREENS[index][0], null);
    } else if (event.key === "j" || event.key === "k") {
      event.preventDefault();
      moveCursor(event.key === "j" ? 1 : -1);
    } else if (event.key === "x") {
      event.preventDefault();
      toggle(current);
    } else if (event.key === "a") {
      event.preventDefault();
      if (current && !current.held) {
        approveOne(current);
      }
    } else if (event.key === "Enter" && current && target === document.body) {
      event.preventDefault();
      openItem(current);
    } else if (event.key === "/") {
      event.preventDefault();
      if (ui.screen !== "stream") {
        go("stream", null);
      }
      window.setTimeout(() => stream.dom && stream.dom.search.focus(), 0);
    } else if (event.key === "?") {
      event.preventDefault();
      helpSheet();
    } else if (event.key === "h") {
      event.preventDefault();
      skyLook(!space.look);
    }
  }
