from __future__ import annotations

from hub_e2e_kit import HELPERS

ORG_OPEN = """(async () => {@HELPERS@
  const row = await until(() => document.querySelector('#main .org-row[data-office="identity/oidc"]'), 8000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  const toggle = all("#main .org-toggle").find((button) => name(button) === "Collapse: identity");
  toggle.focus();
  return {focused: document.activeElement.dataset.focus, offices: all("#main .org-row[data-office]").map((entry) => entry.dataset.office)};
})()""".replace("@HELPERS@", HELPERS)
ORG_FOLDED = """(async () => {@HELPERS@
  const toggle = document.activeElement;
  const folded = {focused: toggle.dataset.focus, expanded: toggle.getAttribute("aria-expanded"), label: name(toggle), hidden: document.getElementById(toggle.getAttribute("aria-controls")).hidden, seen: all("#main .org-row[data-office]").filter((entry) => entry.offsetParent !== null).map((entry) => entry.dataset.office)};
  toggle.click();
  await sleep(200);
  const before = all("#main .agent-order li").map((item) => item.dataset.name);
  all("#main .agent-order li")[1].querySelector('[data-focus^="up:"]').focus();
  return {...folded, again: toggle.getAttribute("aria-expanded"), before};
})()""".replace("@HELPERS@", HELPERS)
ORDER_MOVED = """(async () => {@HELPERS@
  const after = all("#main .agent-order li").map((item) => item.dataset.name);
  const focused = document.activeElement.dataset.focus || null;
  const save = all("#main .agent-order button").find((button) => text(button) === "Save order");
  const disabled = save.disabled;
  save.click();
  const toast = await until(() => all("#toasts .toast").find((box) => text(box).startsWith("Priority")), 8000);
  return {after, focused, disabled, toast: text(toast)};
})()""".replace("@HELPERS@", HELPERS)
OPEN_TAKEOVER = """(async () => {@HELPERS@
  document.querySelector('#main [data-focus="takeover:identity/oidc"]').click();
  await sleep(400);
  return {title: text(document.querySelector(".sheet-head .panel-title")), options: all(".sheet-box select option").map((option) => option.value), work: document.querySelector('.sheet-box input[aria-label="Work"]').value, focused: document.activeElement.tagName};
})()""".replace("@HELPERS@", HELPERS)
CONFIRM_TAKEOVER = """(async () => {@HELPERS@
  all(".sheet-box button").find((button) => name(button) === "Hand over").click();
  const done = await until(() => document.querySelector(".sheet-box [data-result]"), 30000);
  return {result: done ? done.dataset.result : null, text: text(done), toasts: all("#toasts .toast").map(text)};
})()""".replace("@HELPERS@", HELPERS)
AFTER_TAKEOVER = """(async () => {@HELPERS@
  document.querySelector(".sheet-head button").click();
  const row = await until(() => {
    const found = document.querySelector('#main .org-row[data-office="identity/oidc"] .org-holder');
    return found && !text(found).endsWith("Stage") ? found : null;
  }, 15000);
  return {holder: text(row)};
})()""".replace("@HELPERS@", HELPERS)
PIN = """(async () => {@HELPERS@
  const row = await until(() => all("#main .task-row").find((item) => item.dataset.task === "work/docs"), 8000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  row.querySelector('button[aria-label="Priority"]').click();
  await sleep(400);
  const field = document.querySelector('.sheet-box input[aria-label="Priority"]');
  field.value = "2";
  field.dispatchEvent(new Event("input", {bubbles: true}));
  const preview = all(".sheet-box .task-edit .command code").map(text);
  all(".sheet-box button").find((button) => name(button) === "Pin").click();
  const done = await until(() => document.querySelector(".sheet-box [data-jobs]"), 20000);
  return {title: text(document.querySelector(".sheet-head .panel-title")), preview, jobs: done ? done.dataset.jobs : null, toasts: all("#toasts .toast").map(text)};
})()""".replace("@HELPERS@", HELPERS)
OPEN_DELETE = """(async () => {@HELPERS@
  const card = await until(() => all("#main details.repo").find((details) => details.textContent.includes("github.com/me/demo")), 8000);
  if (!card) {
    return {error: text(document.getElementById("main"))};
  }
  card.open = true;
  await sleep(300);
  const every = document.querySelector('#main button[aria-label="Delete all merged"]');
  const buttons = all('button[aria-label="Delete"]', card);
  const states = all("span.state", card).map(name);
  buttons.find((button) => !button.disabled).click();
  await sleep(500);
  return {states, every: [every.disabled, every.title], buttons: buttons.map((button) => [button.disabled, button.title]), title: text(document.querySelector(".sheet-head .panel-title")), dry: all('.sheet-box [aria-label="Dry run"] pre').map(text)};
})()""".replace("@HELPERS@", HELPERS)
CONFIRM = """(async () => {@HELPERS@
  all(".sheet-box button").find((button) => name(button) === "Delete").click();
  const done = await until(() => document.querySelector(".sheet-box [data-result]"), 30000);
  const job = document.querySelector(".sheet-box [data-cleanup]");
  return {job: job ? job.dataset.cleanup : null, result: done ? done.dataset.result : null, text: text(done), toasts: all("#toasts .toast").map(text)};
})()""".replace("@HELPERS@", HELPERS)
AFTER = """(async () => {@HELPERS@
  document.querySelector(".sheet-head button").click();
  const past = await until(() => all("#main details.repo").find((details) => details.textContent.includes("Recently deleted")), 15000);
  return {past: past ? [past.querySelector("[data-result]").dataset.result, name(past.querySelector("span.state"))] : null, branches: all("#main details.repo").filter((details) => details !== past).flatMap((details) => all(".branch-name strong", details)).map(text)};
})()""".replace("@HELPERS@", HELPERS)
KEPT_TREE = """(async () => {@HELPERS@
  const card = await until(() => all("#main details.repo").find((details) => details.textContent.includes("github.com/me/demo")), 8000);
  if (!card) {
    return {error: text(document.getElementById("main"))};
  }
  card.open = true;
  await sleep(300);
  const row = all(".branch-row", card).find((entry) => text(entry.querySelector(".branch-name strong")) === "feature/squashed");
  const kept = row ? row.querySelector(".hint.kept") : null;
  const deletes = all('button[aria-label="Delete"]', card).map((button) => text(button.closest(".branch-row").querySelector(".branch-name strong")));
  const header = all("#main .delete-all span.state").map(name);
  document.querySelector('#main button[aria-label="Delete all merged"]').click();
  const sheet = await until(() => document.querySelector("#sheet:not([hidden]) li.dry-run") && document.getElementById("sheet"), 8000);
  const kind = (li) => (li.dataset.token ? "token" : li.dataset.held ? "held" : li.dataset.kept ? "kept" : null);
  const rows = sheet ? all("li.dry-run", sheet).map((li) => [text(li.querySelector("code")), kind(li), all("button", li).length, text(li.querySelector("pre"))]) : null;
  const confirms = sheet ? all("#sheet button").filter((button) => name(button) === "Delete").length : null;
  const title = text(document.querySelector(".sheet-head .panel-title"));
  document.querySelector(".sheet-head button").click();
  return {kept: kept ? [kept.title, name(kept.querySelector("span.state"))] : null, rowDeletes: row ? all('button[aria-label="Delete"]', row).length : null, deletes, header, rows, confirms, title};
})()""".replace("@HELPERS@", HELPERS)
KEPT_POPUP = """(async () => {@HELPERS@
  await screenShown(8000);
  const picker = await until(() => document.querySelector('#main select[aria-label="Repository"]'), 8000);
  if (picker && picker.value !== @REPO@) {
    picker.value = @REPO@;
    picker.dispatchEvent(new Event("change", {bubbles: true}));
  }
  const id = `branch:${@REPO@}\\u0000feature/squashed`;
  const target = await until(() => all("#main svg [data-pick]").find((node) => node.dataset.pick === id), 8000);
  if (!target) {
    return {error: text(document.getElementById("main"))};
  }
  target.dispatchEvent(new MouseEvent("click", {bubbles: true, cancelable: true}));
  const dialog = document.getElementById("popup");
  const dry = await until(() => dialog.open && dialog.querySelector(".popup-box pre.notes"), 6000);
  const kept = dialog.querySelector(".popup-box .actions .hint.kept");
  return {title: text(dialog.querySelector(".popup-box .panel-title")), heading: dry ? text(dry.previousElementSibling) : null, dry: dry ? dry.textContent : null,
    deletes: all('#popup button[aria-label="Delete"]').length, kept: kept ? kept.title : null};
})()""".replace("@HELPERS@", HELPERS)
NIGHT_MENU = """(async () => {@HELPERS@
  const questions = [];
  window.confirm = (question) => {
    questions.push(question);
    return true;
  };
  let asked = 0;
  const get = navigator.credentials.get.bind(navigator.credentials);
  navigator.credentials.get = (options) => {
    asked += 1;
    return @SIGNS@ ? get(options) : Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  };
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path).startsWith("/api/board/")) {
      const body = JSON.parse(init.body);
      posted.push([String(path), Object.keys(body), body.action || null]);
    }
    return send(path, init);
  };
  const menu = await until(() => all('#main [role="toolbar"] details.menu').find((node) => name(node.querySelector("summary")) === "Day/Night"), 8000);
  if (!menu) {
    return {error: text(document.getElementById("main"))};
  }
  menu.open = true;
  const buttons = all(".actions button", menu);
  const runs = [];
  for (const button of buttons) {
    const label = name(button);
    const [before, prompts, sent] = [asked, questions.length, posted.length];
    const shown = new Set(all("#toasts .toast"));
    button.click();
    const toast = await until(() => all("#toasts .toast").filter((box) => !shown.has(box)).map(text).find((entry) => entry.startsWith(`${label}:`)), 15000);
    runs.push({label, question: questions.slice(prompts), asked: asked - before, posted: posted.slice(sent), toast});
  }
  return {labels: buttons.map(name), runs};
})()""".replace("@HELPERS@", HELPERS)
NIGHT_LOOK = """(async () => {@HELPERS@
  const menu = await until(() => all('#main [role="toolbar"] details.menu').find((node) => name(node.querySelector("summary")) === "Day/Night"), 8000);
  if (!menu) {
    return {error: text(document.getElementById("main"))};
  }
  menu.open = true;
  await sleep(200);
  const box = menu.querySelector(".menu-box");
  return {
    children: [...box.children].map((node) => [node.tagName.toLowerCase(), node.className]),
    badge: all(".pill", box).map(text),
    picks: all(".night-picks label", box).map((label) => [text(label), label.querySelector("input").checked]),
    buttons: all("button", box).map((button) => [name(button), button.title]),
    paragraphs: all("p", box).length,
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()""".replace("@HELPERS@", HELPERS)
NIGHT_PICK = """(async () => {@HELPERS@
  const questions = [];
  window.confirm = (question) => {
    questions.push(question);
    return true;
  };
  navigator.credentials.get = @SIGNS@ ? navigator.credentials.get.bind(navigator.credentials) : () => Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path).startsWith("/api/board/")) {
      const body = JSON.parse(init.body);
      posted.push([String(path), Object.keys(body), body.action || null, body.agents || null]);
    }
    return send(path, init);
  };
  const menu = await until(() => all('#main [role="toolbar"] details.menu').find((node) => name(node.querySelector("summary")) === "Day/Night"), 8000);
  if (!menu) {
    return {error: text(document.getElementById("main"))};
  }
  menu.open = true;
  await sleep(200);
  const box = menu.querySelector(".menu-box");
  const picks = () => all(".night-picks label", box).map((label) => [text(label), label.querySelector("input").checked]);
  const enabled = () => all(".actions button", box).map((button) => !button.disabled);
  const tick = (label) => all(".night-picks label", box).find((node) => text(node) === label).querySelector("input").click();
  const fresh = async (label, click) => {
    const shown = new Set(all("#toasts .toast"));
    click();
    return until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((entry) => entry.startsWith(`${label}:`)), 15000);
  };
  const found = {badge: all(".pill", box).map(text), start: picks()};
  tick("Skills");
  found.one = [picks(), enabled()];
  found.drain = await fresh("Drain", () => all(".actions button", box).find((button) => name(button) === "Drain").click());
  found.kept = picks();
  tick("Stage");
  found.none = [picks(), enabled()];
  tick("All");
  found.all = [picks(), enabled()];
  menu.open = false;
  document.getElementById("palette-open").click();
  const item = await until(() => all(".palette-list li").find((li) => text(li.querySelector("span")) === "Stage"), 4000);
  item.click();
  const row = await until(() => document.querySelector("#popup .agent-night"), 4000);
  found.popup = {badge: all(".pill", row).map(text), buttons: all("button", row).map(name)};
  found.suspend = await fresh("Suspend", () => all("button", row).find((button) => name(button) === "Suspend").click());
  return {...found, questions, posted, wide: document.documentElement.scrollWidth > window.innerWidth + 1};
})()""".replace("@HELPERS@", HELPERS)
NIGHT_HINTS = [
    ("Drain", "Drain: the agents finish their task and take nothing new; your passkey signs it"),
    ("Suspend", "Suspend: the agents park their work, write the handover and idle; your passkey signs it"),
    ("Resume", "Resume: all agents continue from their handover; your passkey signs it"),
]
