  const NS = "http://www.w3.org/2000/svg";
  const NONCE = document.currentScript ? document.currentScript.nonce : "";
  const ACTIVE_BEAT = 900;
  const DAY = 86400;
  const HUMAN = "Operator";
  const PRESETS = [[3600, "1 h"], [21600, "6 h"], [DAY, "24 h"], [7 * DAY, "7 d"], [0, "all"], [-1, "custom"]];
  const PARTS = [["user", "User"], ["assistant", "Assistant"], ["tool_call", "Tool call"], ["tool_result", "Tool result"], ["system", "System"]];
  const PART_TONES = {user: "info", assistant: "ok", tool_call: "violet", tool_result: "teal", system: "neutral"};
  const KIND_TONES = {radio: "teal", review: "info", ask: "warn", decision: "violet", operator: "bad", register: "neutral", rename: "info", cron: "teal", rule: "ok", approval: "ok", run: "info", transcript: "neutral"};
  const VIEW_ICONS = {"fuer-dich": "bi-person-check", funk: "bi-broadcast", arbeit: "bi-briefcase", transkripte: "bi-chat-left-text"};
  const ITEM_LABELS = {review: "Review", ask: "Ask", decision: "Choice", operator: "Operator", rule: "Rule request"};
  const NIGHT = {day: ["Day", "ok"], drain: ["Draining", "warn"], suspend: ["Suspended", "violet"]};
  const ACTIONS = [
    ["clear-mayday", "Cancel mayday", "Lift the radio silence of the active mayday?", "Cancel mayday: lift the radio silence so the agents write again; your passkey signs it"],
    ["drain", "Drain", "Drain all agents: finish the current task, accept nothing new (kvb-agent-drain)?", "Drain: the agents finish their task and take nothing new; your passkey signs it"],
    ["suspend", "Suspend", "Suspend all agents: park work, write the handover, idle (kvb-agent-suspend)?", "Suspend: the agents park their work, write the handover and idle; your passkey signs it"],
    ["resume", "Resume", "Resume all agents from their handover (kvb-agent-resume)?", "Resume: all agents continue from their handover; your passkey signs it"],
  ];
  const UPLOAD_LIMIT = 50 * 1024 * 1024;
  const STREAM_KEEP = 5000;
  const CLASSES = {post: "Post", call: "Call", newsletter: "Newsletter", broadcast: "Broadcast", mayday: "Mayday", "pan-pan": "Pan-Pan", security: "Sécurité", receipt: "Read", grant: "Grant"};
  const PILLS = {post: "info", call: "info", newsletter: "teal", broadcast: "teal", mayday: "bad", "pan-pan": "warn", security: "violet", receipt: "neutral", grant: "ok"};
  const LEGEND = [["direct", "Post / Call"], ["broadcast", "Newsletter / Broadcast"], ["alarm", "Mayday / Pan-Pan"], ["security", "Sécurité"], ["grant", "Queue grant"]];
  const TO_ALL = [["newsletter", "Newsletter"], ["broadcast", "Broadcast"], ["pan-pan", "Pan-Pan"], ["security", "Sécurité"], ["mayday", "Mayday"]];
  const TO_ONE = [["post", "Post"], ["call", "Call"]];
  const STATUS = {
    running: ["running", "ok"], queued: ["waiting", "info"], blocked: ["blocked", "bad"], stale: ["stale", "warn"], pending: ["open", "warn"], done: ["done", "neutral"], stopped: ["stopped", "neutral"],
    approved: ["approved", "ok"], rejected: ["denied", "bad"], allowed: ["allowed", "ok"], denied: ["denied", "bad"], expired: ["expired", "neutral"], decided: ["decided", "ok"], failed: ["failed", "bad"], refused: ["refused", "bad"],
  };
  const SECTIONS = {staged: "Staged", unstaged: "Not staged", untracked: "Untracked"};
  const FILE_STATUS = {added: ["A", "ok"], deleted: ["D", "bad"], modified: ["M", "info"], renamed: ["R", "violet"], copied: ["C", "violet"], untracked: ["U", "warn"]};
  const SIGNS = {add: "+", del: "-", ctx: " ", meta: " "};
  const NODE_KINDS = {operator: "Operator", chair: "Chair", session: "Session", subagent: "Subagent"};
  const RADIUS = {operator: 30, chair: 22, session: 15, subagent: 6};
  const RINGS = [150, 300];
  const FEED_LIMIT = 300;
  const MOVE = 2000;
  const RELAYOUT = 60000;
  const SESSION_ID = /^[A-Za-z0-9_-]{1,128}$/;
  const STORE = {views: "kvb-orchestrator.views", status: "kvb-orchestrator.status"};
  const PRESENCE = {
    working: ["Working", "bi-gear-fill", "info"],
    alive: ["Alive", "bi-heart-pulse-fill", "ok"],
    sleeping: ["Sleeping", "bi-moon-stars-fill", "violet"],
    suspending: ["Suspending", "bi-hourglass-split", "warn"],
    unreachable: ["Unreachable", "bi-wifi-off", "bad"],
    dead: ["Dead", "bi-x-octagon-fill", "bad"],
  };
  const SOUND_KINDS = [["mayday", "MAYDAY / PAN-PAN"], ["review", "Reviews, asks, decisions"], ["direct", "Post and calls to you"], ["radio", "All radio"]];
  const SPEECH_CLASSES = [["post", "Post"], ["call", "Call"], ["newsletter", "Newsletter"], ["broadcast", "Broadcast"], ["mayday", "MAYDAY"], ["pan-pan", "PAN-PAN"], ["security", "Sécurité"]];
  const SPEECH_QUEUE = 20;
  const SPEECH_QUIET = 60000;
  const SPEECH_FRESH = 300;
  const THEME_CHOICES = [["sky", "Sky (follows the light outside)"], ["light", "Always light"], ["dark", "Always dark"], ["custom", "Custom colors"]];
  const COLOR_FIELDS = [["top", "Sky at the top"], ["bottom", "Sky at the horizon"], ["accent", "Accent"]];
  const STAGE_LABELS = {night: "Night", astronomical: "Astronomical twilight", nautical: "Nautical twilight", civil: "Civil twilight", golden: "Golden hour", day: "Day"};
  const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
  const COMPASS = [["N", "North"], ["NE", "Northeast"], ["E", "East"], ["SE", "Southeast"], ["S", "South"], ["SW", "Southwest"], ["W", "West"], ["NW", "Northwest"]];
  const SUBS_TTL = 60000;
  const TURN = 10;
  const ZOOM = 1.2;
  const GLIDE = 320;
  const SAVE_DELAY = 700;
  const CALM = [1, 9 / 8, 5 / 4, 3 / 2, 5 / 3, 2];
  const TENSE = [1, 16 / 15, 6 / 5, 45 / 32, 3 / 2, 8 / 5];
  const BASE = 110;
  const FADE = 3000;
  const DUCK = 0.2;
  const TONES = {
    mayday: [[880, 0, 0.18], [660, 0.22, 0.18], [880, 0.44, 0.18], [660, 0.66, 0.18], [880, 0.88, 0.32]],
    review: [[660, 0, 0.14], [990, 0.16, 0.24]],
    direct: [[740, 0, 0.2]],
    radio: [[520, 0, 0.07]],
  };
  const KEYS = [["Ctrl+K", "Commands, views, agents and AI command"], ["1 · 2 · 3 · 4", "Stream · Agents · Artifacts · Tasks"], ["j / k", "Inbox: next / previous entry"], ["x", "Inbox: select entry"], ["a", "Inbox: grant entry (3 s to undo)"], ["Enter", "Inbox: open entry"], ["/", "Search the stream"], ["h", "Look at the sky: drag turns the view, wheel or two fingers zoom, Esc ends"], ["Arrows · + / − · 0", "Sky (focused): turn · zoom · reset"], ["Drag · wheel", "3D: turn, right drag pans, wheel zooms"],["🎙 hold", "Voice input into the agent field or the command line, never sent automatically"], ["?", "This help"], ["Esc", "Close"]];
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
  const relative = new Intl.RelativeTimeFormat("en", {numeric: "auto"});
  const absolute = new Intl.DateTimeFormat("en-GB", {dateStyle: "medium", timeStyle: "short"});
  const clock = new Intl.DateTimeFormat("en-GB", {hour: "2-digit", minute: "2-digit"});
