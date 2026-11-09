const Nav = (() => {
  "use strict";
  const TABS = [["stream", "Stream"], ["agents", "Agents"], ["artifacts", "Artifacts"], ["tasks", "Tasks"]];
  const SUBS = {stream: [["inbox", "Inbox"], ["rules", "Firewall"], ["radio", "Radio"]]};
  const VIEWS = [["orbit", "Orbit"], ["chord", "Chord"], ["swimlane", "Swimlane"], ["tree", "Tree"], ["3d", "3D"]];
  const TASK_VIEWS = [["list", "List"], ["board", "Board"], ["rasci", "RASCI"], ["gantt", "Gantt"], ["burn", "Burndown and burnup"], ["3d", "3D"]];
  const OWN = {agents: [["hierarchy", "Hierarchy"]]};
  const ICONS = {
    stream: "bi-activity", inbox: "bi-inbox", rules: "bi-card-checklist", radio: "bi-boombox", agents: "bi-people", artifacts: "bi-git", tasks: "bi-list-check",
    orbit: "bi-globe2", chord: "bi-bezier2", swimlane: "bi-bar-chart-steps", tree: "bi-diagram-3", "3d": "bi-badge-3d", hierarchy: "bi-diagram-2",
    list: "bi-list-task", board: "bi-kanban", rasci: "bi-grid-3x3", gantt: "bi-calendar-range", burn: "bi-graph-down-arrow",
  };
  const OLD = {graph: ["agents", "orbit"], tree: ["artifacts", "tree"]};
  const viewsOf = (screen) => (screen === "tasks" ? TASK_VIEWS : [...VIEWS, ...(OWN[screen] || [])]);
  const known = (screen, view) => viewsOf(screen).some(([id]) => id === view);

  function tabOf(screen) {
    return Object.keys(SUBS).find((tab) => SUBS[tab].some(([id]) => id === screen)) || screen;
  }

  function hashOf(screen, view) {
    return tabOf(screen) === screen ? (view ? `#${screen}/${view}` : `#${screen}`) : `#${tabOf(screen)}/${screen}`;
  }

  function route(hash) {
    const [head, sub] = decodeURIComponent(String(hash).replace(/^#/, "")).split("/");
    if (Object.hasOwn(OLD, head)) {
      const [screen, fallback] = OLD[head];
      const view = known(screen, sub) ? sub : fallback;
      return {screen, view, redirect: hashOf(screen, view)};
    }
    if (Object.hasOwn(SUBS, head) && SUBS[head].some(([id]) => id === sub)) {
      return {screen: sub, view: null, redirect: null};
    }
    if (TABS.some(([id]) => id === head) && head !== "stream") {
      return {screen: head, view: known(head, sub) ? sub : null, redirect: null};
    }
    return {screen: "stream", view: null, redirect: null};
  }

  return {TABS, SUBS, VIEWS, TASK_VIEWS, ICONS, viewsOf, route, hashOf, tabOf};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Nav;
}
