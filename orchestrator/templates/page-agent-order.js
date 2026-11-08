  const orderDom = {box: null, dragged: null, focus: null};

  function openAgentOrder() {
    go("agents", "hierarchy");
    window.setTimeout(() => {
      const title = document.getElementById("agent-order-title");
      if (title) {
        title.scrollIntoView({block: "nearest"});
        title.focus();
      }
    }, 50);
  }

  function syncOrder() {
    const stored = state.agent_order;
    if (ui.order === null || ui.order.length !== stored.length || ui.order.some((name) => !stored.includes(name))) {
      ui.order = [...stored];
    }
  }

  function placeAgent(next, focus) {
    ui.order = next;
    orderDom.focus = focus;
    drawAgentOrder();
  }

  function moveAgent(name, step) {
    const from = ui.order.indexOf(name);
    const to = from + step;
    if (from < 0 || to < 0 || to >= ui.order.length) {
      return;
    }
    const next = ui.order.filter((entry) => entry !== name);
    next.splice(to, 0, name);
    placeAgent(next, `${step < 0 ? "up" : "down"}:${name}`);
  }

  function dropAgent(name) {
    const dragged = orderDom.dragged;
    orderDom.dragged = null;
    if (dragged === null || dragged === name) {
      return;
    }
    const next = ui.order.filter((entry) => entry !== dragged);
    next.splice(next.indexOf(name) + (ui.order.indexOf(dragged) < ui.order.indexOf(name) ? 1 : 0), 0, dragged);
    placeAgent(next, null);
  }

  function orderItem(name, index) {
    const up = officeBtn("bi-arrow-up", `Move ${name} up`, `Move ${name} up: higher priority`, () => moveAgent(name, -1), `up:${name}`);
    const down = officeBtn("bi-arrow-down", `Move ${name} down`, `Move ${name} down: lower priority`, () => moveAgent(name, 1), `down:${name}`);
    up.disabled = index === 0;
    down.disabled = index === ui.order.length - 1;
    const item = h("li", {draggable: "true", "data-name": name}, icon("bi-grip-vertical", "grip"), h("span", {class: "rank"}, `${index + 1}.`), face(name, false), person(name), h("span", {class: "spacer"}), up, down);
    item.addEventListener("dragstart", (event) => {
      orderDom.dragged = name;
      item.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", name);
    });
    item.addEventListener("dragend", () => item.classList.remove("dragging"));
    item.addEventListener("dragover", (event) => event.preventDefault());
    item.addEventListener("drop", (event) => {
      event.preventDefault();
      dropAgent(name);
    });
    return item;
  }

  async function saveAgentOrder() {
    if (await act("order", "Priority", {agents: ui.order})) {
      ui.order = null;
      drawAgentOrder();
    }
  }

  function drawAgentOrder() {
    const box = orderDom.box;
    if (!box || !box.isConnected) {
      orderDom.box = null;
      return;
    }
    syncOrder();
    const key = orderDom.focus || focusKey(box);
    orderDom.focus = null;
    const changed = JSON.stringify(ui.order) !== JSON.stringify(state.agent_order);
    box.replaceChildren(
      h("div", {class: "inbox-head"}, h("h2", {class: "group-title", id: "agent-order-title", tabindex: "-1", "data-focus": "order:title"}, "Agent priority", counter(ui.order.length))),
      h("p", {class: "muted"}, "Orders the chair's grants and decides only between equal task priorities; the tasks' --prio pins stay unchanged."),
      ui.order.length ? h("ol", {class: "order-list", "aria-label": "Agent order"}, ui.order.map(orderItem)) : h("p", {class: "muted"}, "No agent with an office or an open task."),
      h("div", {class: "actions"},
        h("span", {class: "muted"}, "Drag or use the arrows to reorder"),
        h("span", {class: "spacer"}),
        h("button", {type: "button", class: "btn ghost", "data-focus": "order:reset", disabled: !changed, on: {click: () => placeAgent([...state.agent_order], "order:reset")}}, "Reset"),
        h("button", {type: "button", class: "btn primary", "data-focus": "order:save", disabled: !changed, on: {click: saveAgentOrder}}, "Save order")));
    const target = key && [...box.querySelectorAll("[data-focus]")].find((element) => element.dataset.focus === key);
    if (target && target.disabled) {
      refocus(box, key.startsWith("up:") ? `down:${key.slice(3)}` : key.startsWith("down:") ? `up:${key.slice(5)}` : "order:title");
    } else {
      refocus(box, key);
    }
  }
