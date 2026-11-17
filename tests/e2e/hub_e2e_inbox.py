from __future__ import annotations

from hub_e2e_kit import HELPERS, LABELS

RUN_START = """(async () => {@HELPERS@@LABELS@
  const row = await until(() => rowOf("Row"), 8000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  press(row, "Run");
  const toast = await until(() => all("#toasts .toast.wait").find((box) => box.textContent.includes("Run")), 8000);
  const queued = await until(() => out() && line(), 15000);
  await until(() => out().textContent.includes("Row 60"), 20000);
  return {toast: text(toast), queued, running: line(), overflows: out().scrollHeight > out().clientHeight, followed: atEnd()};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
RUN_HELD = """(async () => {@HELPERS@@LABELS@
  out().scrollTop = 0;
  await sleep(300);
  await until(() => out().textContent.includes("Row 80"), 20000);
  await sleep(300);
  return {held: out().scrollTop, running: line()};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
RUN_DONE = """(async () => {@HELPERS@@LABELS@
  out().scrollTop = out().scrollHeight;
  await until(() => document.querySelector("#main .console").dataset.status === "done", 20000);
  await sleep(500);
  const lines = out().textContent.trim().split("\\n");
  return {done: line(), last: lines[lines.length - 1], lines: lines.length, followed: atEnd(), actions: all(".item-actions button", out().closest("li")).map(name)};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
INBOX_PICK = """(async () => {@HELPERS@
  navigator.credentials.get = @SIGNS@ ? navigator.credentials.get.bind(navigator.credentials) : () => Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (["/api/sign", "/api/inbox/approve"].includes(String(path))) {
      posted.push([String(path), JSON.parse(init.body).items.map((item) => [item.id, item.verb, item.channel || null, item.reason])]);
    }
    return send(path, init);
  };
  const list = await until(() => document.querySelector("#main .inbox-list"), 8000);
  if (!list) {
    return {error: text(document.getElementById("main"))};
  }
  let scroller = list;
  while (scroller && !(scroller.scrollHeight > scroller.clientHeight + 4 && getComputedStyle(scroller).overflowY !== "visible")) {
    scroller = scroller.parentElement;
  }
  scroller = scroller || document.scrollingElement;
  const last = all("#main .inbox-list > li").filter((li) => li.textContent.includes("echo row")).pop();
  last.scrollIntoView({block: "center"});
  await sleep(300);
  const title = text(last.querySelector(".command code"));
  const before = scroller.scrollTop;
  last.querySelector("input").click();
  await sleep(300);
  const after = scroller.scrollTop;
  const holder = document.activeElement && document.activeElement.closest("li");
  const focused = Boolean(holder && text(holder.querySelector(".command code")) === title && document.activeElement.checked);
  all("#main .inbox-list > li").find((li) => li.textContent.includes("pick a name")).querySelector("input").click();
  await sleep(300);
  const buttons = all("#main .inbox-actions button").map(name);
  all("#main .inbox-actions button").find((button) => name(button).startsWith("Deny selection")).click();
  await until(() => document.querySelector(".sheet-box .actions"), 4000);
  const listed = all(".sheet-box ul.mini > li strong").map(text);
  const reason = document.querySelector(".sheet-box .deny-reason textarea");
  const reasoned = Boolean(reason && document.activeElement === reason);
  reason.value = "rebase first";
  const confirm = all(".sheet-box .actions button").find((button) => text(button).startsWith("Deny "));
  const label = text(confirm);
  const shown = new Set(all("#toasts .toast"));
  confirm.click();
  const toast = await until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((entry) => entry.startsWith("Deny selection")), 15000);
  return {title, before, moved: Math.abs(after - before), focused, buttons, listed, label, reasoned, toast, posted, wide: document.documentElement.scrollWidth > window.innerWidth + 1};
})()""".replace("@HELPERS@", HELPERS)
LAYOUT = """(async () => {@HELPERS@@LABELS@
  await until(() => document.querySelector("#main .console") && rowOf("Rule request"), 8000);
  const rule = rowOf("Rule request");
  return {
    kinds: all("#main .inbox-list > li").map((li) => text(li.querySelector(".pill"))),
    splits: all("#main .deny-split").map((group) => all("button", group).map(name)),
    console: line(),
    followed: atEnd(),
    fits: out().getBoundingClientRect().right <= window.innerWidth,
    dry: text(rule.querySelector(".dry-run-count")),
    fields: all(".rule-request dt", rule).map(text),
    accept: all("button", rule).filter((button) => name(button) === "Accept").length,
    unlabelled: unlabelled(document),
    wide: wide(),
  };
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
DENY_SHEET = """(async () => {@HELPERS@@LABELS@
  const row = await until(() => rowOf("git push"), 8000);
  press(row, "Deny via …");
  const box = await until(() => document.querySelector(".sheet-box"), 4000);
  return {
    title: text(box.querySelector(".panel-title")),
    channels: all(".deny-channels input[type=radio]", box).map((input) => [input.value, input.checked]),
    hints: all(".deny-channel small", box).map(text),
    reason: Boolean(box.querySelector("textarea")),
    unlabelled: unlabelled(box),
    wide: wide(),
  };
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
DENY = """(async () => {@HELPERS@@LABELS@
  const row = await until(() => askOf("make deploy"), 8000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  press(row, "Deny via …");
  const box = await until(() => document.querySelector(".sheet-box"), 4000);
  box.querySelector('input[value="call"]').click();
  box.querySelector("textarea").value = "make the gate green first";
  press(box.querySelector(".actions"), "Deny");
  const undo = await until(() => all("#toasts .toast.wait").find((toast) => toast.textContent.includes("Denial")), 8000);
  return {undo: text(undo), sheet: !document.getElementById("sheet").hidden};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
DENIED = """(async () => {@HELPERS@@LABELS@
  return {gone: Boolean(await until(() => !askOf("make deploy"), 20000))};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
ACCEPT = """(async () => {@HELPERS@@LABELS@
  press(rowOf("Rule request"), "Accept");
  const toast = await until(() => all("#toasts .toast").find((box) => box.textContent.includes("Created: Rule")), 15000);
  await until(() => !rowOf("Rule request"), 8000);
  return {toast: text(toast), left: Boolean(rowOf("Rule request"))};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
WATCH = """
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
    if (["/api/choices/sign", "/api/choices", "/api/sign", "/api/inbox/approve"].includes(String(path))) {
      const body = JSON.parse(init.body);
      posted.push([String(path), Object.keys(body).sort(), body.class || null, body.to || null]);
    }
    return send(path, init);
  };
  const bar = () => document.getElementById("choice-request");
  const fresh = async (shown, prefix) => until(() => all("#toasts .toast").filter((box) => !shown.has(box)).map(text).find((entry) => entry.startsWith(prefix)), 20000);
  const fits = () => ({tall: document.documentElement.scrollHeight > window.innerHeight, wide: document.documentElement.scrollWidth > window.innerWidth + 1});
"""
CHOICE_VIEW = """(async () => {@HELPERS@@LABELS@
  const found = await until(() => document.getElementById("choice-request") && all("#main .inbox-list > li .options").length === @CARDS@ && document.querySelector('#choice-request input[type="checkbox"]'), 8000);
  if (!found) {
    return {error: text(document.getElementById("main"))};
  }
  const box = document.getElementById("choice-request");
  const chip = document.querySelector('#main [aria-label="Task filters"] button[data-filter="operator"]');
  const closed = all("button[data-channel]", box).filter((button) => button.checkVisibility()).length;
  return {
    kinds: [...new Set(all("#main .inbox-list > li").map((li) => text(li.querySelector(".pill"))))].sort(),
    filter: [text(chip).replace(/[0-9]+$/, ""), chip.getAttribute("aria-pressed")],
    channels: all("button[data-channel]", box).map((button) => [button.dataset.channel, name(button), button.disabled]),
    fields: all("textarea, input:not([type=checkbox])", box).length,
    agents: all('input[type="checkbox"]', box).map((input) => input.value),
    multi: [name(box.querySelector("summary")), box.open, closed, text(box.querySelector(".menu-box h3 .count")), all('input[type="checkbox"]', box).filter((input) => input.checked).length],
    bar: [box.parentElement.getAttribute("aria-label"), toolbarRows(), taskLayout()],
    cards: all("#main .inbox-list > li").filter((li) => li.querySelector(".options")).map((li) => [text(li.querySelector(".pill")), all(".option strong", li).map(text)]),
    choices: all("#main [data-column], #main .group-title, #main h2, #main h3").filter((node) => node.dataset.column === "choices" || text(node) === "Choices").length,
    unlabelled: unlabelled(document),
    tall: document.documentElement.scrollHeight > window.innerHeight,
    wide: wide(),
  };
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
CHOICE_SEND = """(async () => {@HELPERS@@WATCH@
  const menu = bar();
  menu.querySelector("summary").click();
  await sleep(200);
  const boxes = all('input[type="checkbox"]', menu).slice(0, 2);
  boxes.forEach((box) => box.click());
  const counted = text(menu.querySelector(".menu-box h3 .count"));
  const opened = [menu.open, all("button[data-channel]", menu).filter((button) => button.checkVisibility()).length];
  const picked = boxes.map((box) => box.value).sort((a, b) => a.localeCompare(b));
  const runs = [];
  for (const button of all("button[data-channel]", bar())) {
    const [before, prompts, sent] = [asked, questions.length, posted.length];
    const shown = new Set(all("#toasts .toast"));
    const disabled = button.disabled;
    button.click();
    const toast = await fresh(shown, "Choice request");
    runs.push({channel: button.dataset.channel, disabled, asked: asked - before, question: questions.slice(prompts), posted: posted.slice(sent), toast});
  }
  return {picked, counted, opened, runs, fields: all("textarea, input:not([type=checkbox])", bar()).length, ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@WATCH@", WATCH)
CHOICE_ANSWER = """(async () => {@HELPERS@@WATCH@
  bar().querySelector("summary").click();
  await sleep(200);
  const closed = [bar().open, all("button[data-channel]", bar()).filter((button) => button.checkVisibility()).length];
  const card = await until(() => all("#main .inbox-list > li").find((li) => li.textContent.includes("@QUESTION@")), 8000);
  if (!card) {
    return {error: text(document.getElementById("main"))};
  }
  const option = all(".option", card).find((button) => text(button.querySelector("strong")) === "Wait");
  const title = option.title;
  const shown = new Set(all("#toasts .toast"));
  option.click();
  const toast = await fresh(shown, "Choice: Wait");
  const gone = @SIGNS@ ? Boolean(await until(() => !all("#main .inbox-list > li").some((li) => li.textContent.includes("@QUESTION@")), 20000)) : null;
  return {title, asked, posted, toast, gone, closed, ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@WATCH@", WATCH)
TASKS_FIT = """(async () => {@HELPERS@
  await until(() => document.getElementById("choice-request") && document.querySelector("#main .tasks-body > *"), 8000);
  document.getElementById("toasts").replaceChildren();
  await sleep(300);
  return {
    hash: location.hash,
    bar: all("#choice-request button[data-channel]").map((button) => button.dataset.channel),
    rows: toolbarRows(),
    layout: taskLayout(),
    columns: all("#main .task-column").map((column) => column.dataset.column),
    choices: all("#main [data-column], #main .group-title, #main h2, #main h3").filter((node) => node.dataset.column === "choices" || text(node) === "Choices").length,
    tall: document.documentElement.scrollHeight > window.innerHeight,
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()""".replace("@HELPERS@", HELPERS)
CHOICE_REQUEST = "send me your open decisions as choices"
SLOW ="seq -f 'Row %g' 1 60; sleep 4; seq -f 'Row %g' 61 80; sleep 4; echo finished"
