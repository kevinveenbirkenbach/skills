  const NS = "http://www.w3.org/2000/svg";
  const NONCE = document.currentScript ? document.currentScript.nonce : "";
  const ACTIVE_BEAT = 900;
  const DAY = 86400;
  const HUMAN = "Operator";
  const PRESETS = [[3600, "1 h"], [21600, "6 h"], [DAY, "24 h"], [7 * DAY, "7 d"], [0, "alle"], [-1, "eigener"]];
  const EMOJI = ["🦊", "🐙", "🦉", "🐝", "🐢", "🦄", "🐳", "🦋", "🐧", "🦁", "🐼", "🐨", "🦜", "🐬", "🦀", "🐸", "🦔", "🦩", "🐞", "🌵", "🍀", "🌻", "🍄", "🌙", "⭐", "🔥", "🌊", "⚡", "🎈", "🎲", "🧭", "🚀", "🪐", "🔭", "🧩", "🎯", "🪁", "🧪", "🔮", "🗿", "🌋", "🍉", "🍋", "🥨", "🐋", "🦚", "🐌", "🌈"];
  const PARTS = [["user", "Nutzer"], ["assistant", "Assistent"], ["tool_call", "Werkzeugaufruf"], ["tool_result", "Werkzeugergebnis"], ["system", "System"]];
  const PART_TONES = {user: "info", assistant: "ok", tool_call: "violet", tool_result: "teal", system: "neutral"};
  const KIND_TONES = {radio: "teal", review: "info", ask: "warn", decision: "violet", operator: "bad", register: "neutral", rename: "info", cron: "teal", rule: "ok", approval: "ok", run: "info", transcript: "neutral"};
  const VIEW_ICONS = {"fuer-dich": "bi-person-check", funk: "bi-broadcast", arbeit: "bi-briefcase", transkripte: "bi-chat-left-text"};
  const ITEM_LABELS = {review: "Review", ask: "Ask", decision: "Entscheidung", operator: "Operator", rule: "Regelwunsch"};
  const NIGHT = {day: ["Tag", "ok"], evening: ["Abend", "warn"], sunset: ["Nacht", "violet"]};
  const ACTIONS = [["clear-mayday", "Mayday aufheben", "Die Funkstille des aktiven Maydays aufheben?"], ["evening", "Abend", "Alle Agenten in den Abend schicken (kvb-agent-relax)?"], ["sunset", "Sonnenuntergang", "Alle Agenten schlafen legen (kvb-agent-sleep)?"], ["sunrise", "Sonnenaufgang", "Alle Agenten wecken (kvb-agent-wakeup)?"]];
  const UPLOAD_LIMIT = 50 * 1024 * 1024;
  const STREAM_KEEP = 5000;
  const CLASSES = {post: "Post", call: "Call", newsletter: "Newsletter", broadcast: "Broadcast", mayday: "Mayday", "pan-pan": "Pan-Pan", security: "Security", receipt: "Gelesen", grant: "Freigabe"};
  const PILLS = {post: "info", call: "info", newsletter: "teal", broadcast: "teal", mayday: "bad", "pan-pan": "warn", security: "violet", receipt: "neutral", grant: "ok"};
  const LEGEND = [["direct", "Post / Call"], ["broadcast", "Newsletter / Broadcast"], ["alarm", "Mayday / Pan-Pan"], ["security", "Security"], ["grant", "Queue-Freigabe"]];
  const TO_ALL = [["newsletter", "Newsletter"], ["broadcast", "Broadcast"], ["pan-pan", "Pan-Pan"], ["security", "Security"], ["mayday", "Mayday"]];
  const TO_ONE = [["post", "Post"], ["call", "Call"]];
  const STATUS = {
    running: ["läuft", "ok"], queued: ["wartet", "info"], blocked: ["blockiert", "bad"], stale: ["veraltet", "warn"], pending: ["offen", "warn"], done: ["erledigt", "neutral"], stopped: ["gestoppt", "neutral"],
    approved: ["freigegeben", "ok"], rejected: ["abgelehnt", "bad"], allowed: ["erlaubt", "ok"], denied: ["abgelehnt", "bad"], expired: ["abgelaufen", "neutral"], decided: ["entschieden", "ok"], failed: ["fehlgeschlagen", "bad"], refused: ["verweigert", "bad"],
  };
  const SECTIONS = {staged: "Gestaged", unstaged: "Nicht gestaged", untracked: "Unversioniert"};
  const FILE_STATUS = {added: ["A", "ok"], deleted: ["D", "bad"], modified: ["M", "info"], renamed: ["R", "violet"], copied: ["C", "violet"], untracked: ["U", "warn"]};
  const SIGNS = {add: "+", del: "-", ctx: " ", meta: " "};
  const NODE_KINDS = {operator: "Operator", chair: "Chair", session: "Session", subagent: "Subagent"};
  const RADIUS = {operator: 30, chair: 22, session: 15, subagent: 6};
  const RINGS = [150, 300];
  const FEED_LIMIT = 300;
  const MOVE = 2000;
  const RELAYOUT = 60000;
  const SESSION_ID = /^[A-Za-z0-9_-]{1,128}$/;
  const STORE = {views: "kvb-orchestrator.views"};
  const SOUND_KINDS = [["mayday", "MAYDAY / PAN-PAN"], ["review", "Reviews, Asks, Entscheidungen"], ["direct", "Post und Calls an dich"], ["radio", "Aller Funk"]];
  const SPEECH_CLASSES = [["post", "Post"], ["call", "Call"], ["newsletter", "Newsletter"], ["broadcast", "Broadcast"], ["mayday", "MAYDAY"], ["pan-pan", "PAN-PAN"], ["security", "SECURITE"]];
  const SPEECH_QUEUE = 20;
  const SPEECH_QUIET = 60000;
  const SPEECH_FRESH = 300;
  const THEME_CHOICES = [["sky", "Himmel (folgt dem Licht draußen)"], ["light", "Immer hell"], ["dark", "Immer dunkel"], ["custom", "Eigene Farben"]];
  const COLOR_FIELDS = [["top", "Himmel oben"], ["bottom", "Himmel am Horizont"], ["accent", "Akzent"]];
  const STAGE_LABELS = {night: "Nacht", astronomical: "Astronomische Dämmerung", nautical: "Nautische Dämmerung", civil: "Bürgerliche Dämmerung", golden: "Goldene Stunde", day: "Tag"};
  const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
  const COMPASS = [["N", "Norden"], ["NO", "Nordosten"], ["O", "Osten"], ["SO", "Südosten"], ["S", "Süden"], ["SW", "Südwesten"], ["W", "Westen"], ["NW", "Nordwesten"]];
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
  const KEYS = [["Strg+K", "Befehle, Ansichten, Agenten und KI-Befehl"], ["1 · 2 · 3", "Stream · Agents · Artifacts"], ["j / k", "Inbox: nächster / vorheriger Eintrag"], ["x", "Inbox: Eintrag auswählen"], ["a", "Inbox: Eintrag freigeben (3 s rückgängig)"], ["Enter", "Inbox: Eintrag öffnen"], ["/", "Stream durchsuchen"], ["h", "Himmel ansehen: ziehen dreht den Blick, Rad oder zwei Finger zoomen, Esc beendet"], ["Pfeile · + / − · 0", "Himmel (fokussiert): drehen · zoomen · zurücksetzen"], ["Ziehen · Rad", "3D: drehen, rechts ziehen verschiebt, Rad zoomt"],["🎙 halten", "Spracheingabe ins Agentenfeld oder die Befehlszeile, nie automatisch gesendet"], ["?", "Diese Hilfe"], ["Esc", "Schließen"]];
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
  const relative = new Intl.RelativeTimeFormat("de", {numeric: "auto"});
  const absolute = new Intl.DateTimeFormat("de-DE", {dateStyle: "medium", timeStyle: "short"});
  const clock = new Intl.DateTimeFormat("de-DE", {hour: "2-digit", minute: "2-digit"});
