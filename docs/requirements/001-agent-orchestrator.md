# 001 - Agent Orchestrator

## User Story

As the operator of many parallel agents, I want one simple Agent Orchestrator
surface and a radio that only interrupts for urgent calls, so that agents
spend few tokens on talk, urgent news reaches them at once, and I can drill
from three views down to any agent, branch or artefact.

## Decisions (operator-confirmed 2026-11-06; do not re-litigate)

1. **One document**: radio model, surface, pkgmgr branch tree and views live in
   this one requirement as phases. Rejected: one document per feature (the
   operator wants the whole picture in one place).
2. **Location**: `docs/requirements/NNN-slug.md`, numbered per repository.
   Rejected: a file next to the code (no index, no numbering).
3. **Radio classes**: `post`, `call`, `newsletter`, `broadcast`, `mayday`,
   `pan-pan`, `security`. Rejected: `broadcast` only as the umbrella of the
   three alarms (the operator wants an immediate call to all without alarm).
4. **Mailbox**: `post` (one agent) and `newsletter` (all agents) are
   delivered only when the agent ends its turn and goes idle, batched; an
   agent already idle is not woken and sees its mailbox at the end of its next
   turn. Rejected: next prompt, next tool step (interrupts work), batched
   wake-ups (one turn per wake).
5. **Immediate classes**: `call`, `broadcast`, `pan-pan`, `mayday` and
   `security` reach the agent at its next tool step and wake an idle agent.
6. **Call receipt**: the caller gets a delivered/read receipt and does not
   wait; an answer is a call of its own. Rejected: the caller blocks until
   the answer (costs the caller), delivery without feedback.
7. **Mayday pause**: while a mayday holds, a PreToolUse hook blocks every
   writing action until `radio.py clear`; reading, the radio and teardown
   stay allowed. The sender and every agent that joins with `radio.py
   assist` to help keep working. Rejected: an instruction only (not
   enforced), heavy jobs only (today's behaviour, too weak), a full blockade
   that also stops the helpers.
8. **Radio and post**: two channels. `radio.py send` is the radio and always
   immediate (`call`, `broadcast`, `pan-pan`, `mayday`, `security`);
   `radio.py post` is mail and always delayed (`post` with `--to`,
   `newsletter` without). `send direct` stays as an alias so running peers
   keep working: with `--wake` it becomes `call`, without it `post`. Rows
   stored before the change carry no version mark and are read as before:
   `direct` as `post`, `broadcast` as `newsletter`. Rejected: `send
   broadcast` as an alias of `newsletter` (makes the immediate broadcast
   unreachable).
9. **Name**: kvb-hub is renamed in full, with a one-time migration: visible
   "Agent Orchestrator", technical `kvb-orchestrator` / `kvb_orchestrator`
   (directory, module, container, systemd unit, MCP server, environment
   `KVB_ORCHESTRATOR_*`, make targets). Rejected: visible name only (two names
   for one thing).
10. **Navigation**: Stream (sub-items Inbox and Firewall) · Agents (ex Graph) ·
    Artifacts (ex Tree). Agents and Artifacts each offer Orbit, Chord,
    Swimlane, Tree and 3D.
11. **Header**: title · ⌘K · ⚙ only. The status pills become navigation
    badges (Inbox: waiting items, Agents: active agents, Artifacts: runner
    jobs); Mayday shows only as a red banner with "cancel" while active; the
    background shows day and night. Rejected: one status dot with a popover
    (an extra click), a status block in a side bar, a "Situation" screen
    (effort), no header at all.
12. **Tools**: Controls (Radio to all, Cancel mayday, Priority, Day/Night)
    moves to the Agents toolbar, Firewall under Inbox, Sky, Music,
    Control room and Notifications to ⚙ "Ambience"; ⌘K reaches every one.
    Rejected: one ⋯ menu (hides instead of ordering).
13. **Stream**: four category chips For you · Radio · Work · Transcripts;
    one search line with `agent:`, `kind:`, `since:`; sub-filters, saved views
    and a custom range under "Filter ▾"; the time bar becomes "24 h ▾" with
    the replay inside; transcripts are off by default. Rejected: a
    self-grouping stream, a Kibana-like query language (effort), preset
    chips only.
14. **3D**: `3d-force-graph` 1.80.1 on `three` 0.186.1, vendored as in
    meta.infinito.nexus; the Canvas depth axes Time and Spawn depth become 3D
    options. Rejected: keeping the Orbit-only Canvas depth.
15. **Artifacts scope**: git (repositories → branches → worktrees with their
    agents and reviews) plus the kvb-org-rasci register artefacts (images,
    volumes, logs) as leaves of the task or worktree that owns them.
    Rejected: git only.
16. **Artifacts views**: Orbit: repository sun, branch planets (size = commits
    ahead), worktree moons, agent satellites. Chord: branch overlap (same
    files touched, merges) as conflict risk. Swimlane: one lane per branch
    with commits, reviews, gates and pushes. Tree: the pkgmgr branch tree.
17. **Tree data**: the scan moves from `hub/kvb_hub/tree.py` into pkgmgr as
    `pkgmgr branch tree --format json|yaml --output FILE`, rewritten by a
    systemd user timer every minute and after every pkgmgr branch action; the
    orchestrator only reads the file, no git runs in its container. Rejected:
    the hub keeps scanning (pkgmgr is not the single source, git runs in the
    container), a live websocket daemon (effort). Hardened through
    kvb-think-dialectic before it is built.
18. **Order**: 1 radio → 2 surface and rename → 3 pkgmgr branch tree → 4 views
    and 3D; one bundle per phase, each change set through kvb-code-refactor.
19. **Icons over text**: every HTML surface a skill renders (the
    orchestrator, the review pages, the meditation page) shows Bootstrap
    Icons instead of text labels wherever an icon carries the meaning, each
    with a tooltip and an `aria-label`; terminal output and `SKILL.md` keep
    emoji. Rejected: Font Awesome Free (icons under CC BY 4.0, core loads it
    from a kit CDN), emoji in HTML (look differs per platform).
20. **Branch state**: `pkgmgr branch tree` covers every repository pkgmgr
    manages and gives each branch and worktree the classification of
    `pkgmgr branch gc` (one implementation, no second copy): merged and by
    what, clean or uncommitted changes, unpushed commits, gone upstream,
    locked, stale, protected and the gc skip reason. The Artifacts Tree shows
    it as icons. Phase 3 builds the data, phase 4 the icons.
21. **Delete from the tree**: merged, orphaned branches are deleted by click
    in the Artifacts Tree (phase 4), per item and as "Delete all merged":
    - **Credentials**: only while the Secret Service hands pkgmgr the GitHub
      token, which proves the merge and the missing open pull request; no
      secret passes the orchestrator container. Rejected: the master password
      typed into the dialog (secret crosses container and browser), the SSH
      key through the KeePassXC agent (a local delete pushes nothing;
      operator 2026-11-06).
    - **Scope**: local only (operator 2026-11-06): the worktree, the local
      branch, the compose stack without its volumes and its images of a
      `merged-clean` item, never a remote branch; a gc skip reason locks the
      button, and the dry run lists ignored files, any beyond known caches
      (`__pycache__`, `node_modules`, `.venv`) locking it too. Rejected: what
      `pkgmgr branch gc --apply` deletes today (remote branch and
      `compose down -v`).
    - **Confirmation**: the click shows the gc dry-run lines of the chosen
      items, and "Delete" needs the operator signature (`/api/sign`).
      Rejected: a second click without signature, one click without preview.
    - **Execution**: the orchestrator writes a signed job into a host
      directory; a systemd user path unit runs `pkgmgr branch cleanup --apply
      --local` for exactly those items and writes the result back. Rejected: an
      `operator.py` row (not direct).
22. **Organisation update**: a new skill `kvb-org-update` tells every agent
    and client which skills changed and how to use them, as one
    `newsletter` per update; phase 1 announces the radio change through it.
23. **Phase 5** (23 to 43 operator-confirmed 2026-11-07): the console
    output shows under "Run"; a deny picks its channel (default
    `post`); agents request auto-approval rules through the
    inbox; the rules form and the Location fields never overlap; the radio plays
    with one line per station and highlights the speaking agent; the
    operator composer sends text or voice, recorded, transcribed locally with
    whisper in the container and kept as audio, to a recipient by `post` or
    `call`; a Hierarchy view shows the council offices with appoint and
    recall; the agent order (drag list) is separate from task priority (WSJF
    plus the operator's pin) and only breaks ties; one Tasks tab holds list,
    board and RASCI matrix, the inbox as its "waits on Operator" filter and
    the queue state; the merge flow, a pkgmgr-managed YAML per worktree with
    several pull sources and push targets, shows in Artifacts and Tasks.
24. **Firewall**: the rules tab becomes Firewall and holds every form of
    allow-listing: the hub's auto-approval rules (ask, review, decision),
    allow and deny command patterns, and the Claude settings permissions
    (`allow`, `ask`, `deny`) and sandbox entries. Rejected: a separate
    settings page.
25. **Settings writes**: a change to a Claude settings file shows as a diff,
    is signed with the passkey and applied by a host executor that verifies
    the signature, writes only files of a fixed list (`~/.claude/settings.json`
    and `<project>/.claude/settings.json` of the known projects) and keeps a
    backup. Rejected: an `operator.py` row only (no one-click path); an agent
    writing settings (never).
26. **Groups**: a rule applies to one agent, a named agent group or all
    agents; rules form named rule sets that are taken over as a whole for an
    agent, a group or all. The Firewall reads the existing settings files and
    groups their entries by tool and command prefix by itself.
27. **Decisions are tasks**: asks, rule requests, operator rows and choices
    appear only in the Tasks tab, under its "waits on Operator" filter.
    Rejected: a Choices column of its own (a choice is a decision the operator
    takes, so it is a task).
28. **Request choices**: the Tasks tab has one button per channel, `post` and
    `call` with a multi-select of agents, `newsletter`, `broadcast`,
    `security`, `mayday` and `pan-pan`, that sends the fixed request "send me
    your open decisions as choices" without free text. Agents answer with
    `kvb-think-choice` items, shown as choice cards; the operator's click on
    an option is the passkey-signed answer.
29. **Night commands**: evening, sunset and sunrise become `drain` (finish the
    current task, accept nothing new), `suspend` (park work, write the
    handover, idle) and `resume` (continue from the handover). Skills:
    `kvb-org-evening` → `kvb-org-drain`, `kvb-org-sunset` → `kvb-org-suspend`,
    `kvb-org-sunrise` → `kvb-org-resume`, `kvb-agent-relax` →
    `kvb-agent-drain`, `kvb-agent-sleep` → `kvb-agent-suspend`,
    `kvb-agent-wakeup` → `kvb-agent-resume`; `night.py` and the Controls
    menu follow, `kvb-skill-cleanup` removes the old names. Rejected:
    sleep / hibernate / wakeup, pause / park / resume.
30. **Agent popup**: a click on an agent opens a fading popup with a simple,
    clear layout (face, name, earlier names, offices, tasks, claims,
    composer) instead of the Details side panel, which goes.
31. **Node popup**: a click on a node in any graph view enlarges it, marks it
    red and opens a slightly transparent popup in the foreground, tied to the
    node by a leader line. A search field with suggestions replaces the list
    of every node.
32. **Faces**: agents get simple animated 2D faces instead of emojis, built
    from independent attributes (shape, colour, eyes, brows, mouth, hair or
    headwear, accessory) with at least 1000 combinations, chosen
    deterministically from the agent's stable id; the mouth moves while the
    agent speaks.
33. **Fit to window**: every view sizes to the window height; no page
    scrollbar on `#agents/orbit`.
34. **Rename once**: a name change appears once in the Stream per session
    and name pair, never again per state build; earlier names show in the
    agent popup.
35. **Radio**: the configured Deutschlandfunk stream
    `https://st01.sslstream.dlf.de/dlf/01/high/aac/stream.aac?aggregator=web`
    plays (root cause proven first, redirects and `media-src` included). A
    squelch control suppresses the radio beep; at 0 no beep plays, music on
    or off.
36. **Tree cause**: the tree timer builds pkgmgr from the newest signed tag,
    and v2.3.0 has no `branch tree`, so no tree file exists. The Tree names
    that cause and the operator step (the pkgmgr release) instead of a bare
    "No tree"; with pkgmgr 2.4.0 released the timer writes the file.
37. **Resources**: a tab Resources shows charts on the shared time axis:
    tokens per agent and accumulated (from the usage fields of the session
    transcripts), and CPU, RAM, disk and load of the host, sampled by a host
    unit into the state directory; several values per chart.
38. **Order of phase 6**: serial subtrees, each in its own worktree under
    `kvb-org-robot`, merged into master before the next starts: S0 English
    and radio speech → S1 fixes (fit, rename once, radio, squelch, tree
    cause) → S2 popups and search → S3 faces → S4 night commands → S5 Tasks
    with asks and choices → S6 Firewall → S7 Resources.
39. **Sécurité**: the class `security` keeps its id and shows as "Sécurité";
    the radio speaks it as in maritime radio, "say-cure-ee-tay", three times.
40. **Hashes spoken**: a hex run of 7 or more characters with at least one
    letter and one digit (commit, session and message ids) is spoken in the
    NATO alphabet, one character at a time (alfa, bravo, charlie, delta,
    echo, foxtrot and the digits of decision 41).
41. **Digits spoken**: every digit is spoken on its own in ICAO radio
    pronunciation: zero, one, two, tree, four, fife, six, seven, eight,
    niner; `42305` is "four two tree zero fife". Only the spoken text
    changes; the displayed text keeps the digits and hashes.
42. **English**: the whole skills repository is English: every orchestrator
    label, message, spoken text, script output, document and test string
    (Regeln → Firewall, Hierarchie → Hierarchy, Ressourcen → Resources,
    Steuerung → Controls, Ausführen → Run). Kept: trigger phrases in skill
    descriptions that quote what the operator says in German, and the rule
    that agents answer the operator in the operator's language.
43. **Shared cache** (core concept settled by the operator 2026-11-07
    18:40, owner IAM, report `/tmp/shared-model-cache-base-20261107.md`):
    the image build fetches every model, voice and source archive from
    `${INFINITO_ARTEFACT_BASE}/<host>/<path>` with the same sha256 pins, and
    from the real upstream when the build arg is unset. Speech uses the
    core role `svc-ai-speech` when its URL is configured, else the
    in-container whisper and piper. `make orchestrator-install` without any
    core stack stays the standalone path. Subtree S8, after S7.
44. **Gantt** (operator 2026-11-08, decisions 44 to 51): the Tasks tab gets
    a Gantt view next to List, Board and Matrix, one bar per task from its
    start to its end, a running task to now. Arrows come from three sources:
    an explicit `rasci.py set <task> --after <task>` (repeatable), the
    branch base (a task whose base branch is another task's branch follows
    it) and the queue order (each waiting `queue.py` job follows the one
    ahead of it). Rejected: branches only (tasks without a branch hang
    loose), the explicit field only, the queue position as a mere badge.
45. **Forecast**: a selector sets how the Gantt draws tasks not yet
    started: `always` (default; with no estimate the median duration of done
    tasks, with story points the points times the median hours per point of
    done tasks), `points only` (a dot behind the predecessors without
    estimate) or `real only` (no forecast). Forecast bars are hatched.
46. **Estimation modes**: a toggle in the Tasks toolbar, stored in the hub
    settings: `No estimate` (default, every task counts 1) and `Story
    points` (the Fibonacci complexity of `rasci.py estimate`, the median over
    its estimators).
47. **Burndown and burnup**: one view in the Tasks tab with both curves.
    A selector sets the scope: the whole register over the whole time
    (default), the active list filter within the header time window, or one
    agent or line. With no estimate it counts tasks, with story points it
    sums complexity and draws unestimated tasks as a line of their own.
48. **Estimate request**: only in story points mode, and only on a click on
    "Request estimates" or on `/kvb-org-queue-estimate`, never by itself, to
    save tokens. It sends one `newsletter` to all agents listing every
    unestimated task with its parties; every agent holding any RASCI role in
    a task (R, A, S, C or I) records business value and complexity
    (Fibonacci) for it with `rasci.py estimate`. Rejected: every agent
    estimates every task, the Accountable alone.
49. **Operator business value**: the operator overrides the agents'
    business value, and WSJF uses that value instead of the median. It is set
    in the hub per task or as one bulk change over a selection in the list;
    one passkey assertion over the exact task ids and values covers the
    whole batch. Rejected: the origin guard alone (a forged request could
    reorder the queue), one signature per task.
50. **Sort modes**: the task list sorts by prio (default), WSJF, business
    value, complexity, status, start, end, agent and title, each ascending
    or descending.
51. **Subtree**: decisions 44 to 50 join subtree S5, Tasks with asks and
    choices, in its one worktree. Rejected: a subtree of their own after S8
    or right after S1.
52. **Radio spot** (operator 2026-11-09, decisions 52 to 58): the radio
    button of the Agents toolbar is the one place to send. It expands inline
    and shows the full composer below the toolbar (every channel, the
    recipients for post and call, Record, Send), a gear button with every
    radio setting (tones per class, squelch, read aloud with its classes and
    speakers, moved out of the general settings) and Cancel mayday, which
    leaves the toolbar. The Radio tab keeps the stations and the message log
    without a composer. Rejected: the Radio tab as the spot, removing the
    Radio tab.
53. **Day/Night menu**: only the status badge and the Drain, Suspend and
    Resume buttons; each button's explanation is its hover tooltip.
54. **Tasks toolbar**: views, filter, estimation toggle, sort and business
    value in one row that wraps on narrow screens; the request choices
    become one "Request choices" dropdown in that row; the status chips stay
    the second and last row. Rejected: moving the request choices into the
    radio spot.
55. **Trend and forecast**: burndown and burnup get a trend selector, `off`
    (default), `linear regression` (least squares over the points in the
    shown window) and `velocity` (the mean burn rate of the last N days, N
    set freely, default 7), stored in the hub settings. The trend is drawn
    until remaining reaches 0 (burndown) or done meets scope (burnup); that
    date is the forecast, shown on the chart. Hovering a point lists the
    work packages that started, ended or joined the scope at that step.
56. **ETA**: every work package in the list carries an ETA: its end when
    done, else its start (or now) plus the forecast length of decision 45
    for the active estimation mode, behind the latest ETA of its
    predecessors.
57. **Tasks 3D**: a sixth Tasks view on the 3D engine of the Agents tab:
    tasks as nodes, the dependency edges of decision 44 in the Gantt colors,
    layouts Force and Time, the same tooltips and popups. Rejected: a fixed
    time-agent-depth layout.
58. **Steady 3D camera**: the 3D view fits the graph once per build; state
    refreshes keep the operator's camera.
59. **Radio in the header** (operator 2026-11-10, replaces the toolbar button
    of decision 52 and the Radio tab): a radio icon button at the top right,
    next to Commands and Settings, opens the radio spot above the main area
    of whichever tab is open. The spot holds the composer, the gear, an
    icon-only Cancel mayday with its tooltip, who is speaking, the last five
    sent messages and the internet radio stations. The Agents toolbar loses
    its radio button, the Radio tab and its "Send …" button go away, and an
    old `#stream/radio` link opens the Stream with the spot open. Rejected:
    keeping the Radio tab, the speaker chips (every Agents view already marks
    the speaker).
60. **Radio numbers and paths** (operator 2026-11-10): only the spoken line
    changes, the displayed text stays as written. Digits are spoken in ICAO
    words in Title Case, Ze-ro, One, Two, Tree, Fow-er, Fife, Six, Seven,
    Eight, Ni-ner, and the NATO letters of hashes too (Alfa to Foxtrot);
    this replaces the words of decisions 40 and 41. A time is four digits,
    hour padded, no colon, seconds as two more digits; a UTC time ("08:15
    UTC", "08:15Z", "0815Z", "08:15 Zulu") ends in one "Zulu", another zone
    word follows the digits as written. A date with a time is the DTG
    DDHHMM, "Zulu" when zoned, the full month name and the two-digit year
    ("One Ze-ro One Fow-er Tree Ze-ro Zulu November Two Six"); an explicit
    offset is converted to UTC first, no zone drops "Zulu", a date alone is
    day, month and year. A dot between digits is "Decimal" and the "v" of a
    version is dropped. An absolute, home or relative path (the relative one
    with a slash and an extension on its last segment) is "file <name> in
    <parent>" when the last segment has an extension (a dot and 1 to 5
    alphanumerics), else "folder <name> in <parent>"; a trailing slash means
    folder, "." is "dot", "-" and "_" a space, `tmp` at the root "temp", `~`
    "home"; a URL is no path. Paths go first, then date-times, times and the
    remaining digits and hashes. Rejected for paths: every segment with
    "slash", the file name only, mapping to known repositories, not speaking
    paths.
61. **Agent states** (operator 2026-11-10, decisions 61 to 64): the hub
    derives six states per agent session: sleeping (drain or suspend part,
    idle),
    suspending (drain or suspend part, still busy), working (process alive,
    busy), alive (process alive, idle), dead (process gone while a claim or
    task still names it) and unreachable (busy without an update for 15
    minutes, or a call without a receipt for 10 minutes). Inputs: the Claude
    Code session files (status, pid and its start tick), the night state and
    the radio receipts; a runtime without a session file shows alive or dead
    by its claim heartbeat. The hub's container sees neither the session
    files nor the host's processes, so a host timer
    (`kvb-orchestrator-sessions.timer`, every 15 seconds while the page
    polls) writes a snapshot with each process checked into the hub's
    state; one older than 5 minutes counts as absent. Rejected: an agent
    hook reporting its own state (a hook and a reinstall on every agent),
    the claim heartbeat alone (no working versus alive), the host's PID
    namespace or `/proc` in the container (every process's command line in
    reach of the web-facing hub).
62. **State symbol**: an animated Bootstrap icon from the vendored sprite
    next to every agent in Orbit, Chord, Swimlane, Tree and 3D and in the
    agent panel; `prefers-reduced-motion` stops the animation. Rejected:
    emoji (font-dependent), a colored ring only (six states hard to tell
    apart).
63. **Status menu**: a "Status" menu in the Agents toolbar holds one checkbox
    per state and "Faces in 3D", stored per browser like the saved views,
    no passkey. Rejected: hub-wide settings with a signature.
64. **3D faces**: agent nodes in the 3D view show their face, on by default
    and switchable; repositories and branches stay spheres.
65. **Day/Night per agent** (operator 2026-11-10, decisions 65 and 66): the
    Day/Night menu lists "All" and one checkbox per claimed agent. All ticked
    runs the global drain, suspend or resume as before; a subset runs it only
    for the ticked sessions (`night.py --target`), the passkey signs the
    board item with those sessions, and the radio call reaches only them.
    Rejected: a second menu for single agents.
66. **Agent panel Day/Night**: every agent panel shows the agent's part and,
    for a claimed agent, Drain, Suspend and Resume for that agent alone, by
    day too. Rejected: single-agent parts only during a night.

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes" --> R1
    subgraph R["📻 1 · Radio model"]
        R1["🔴 Red tests: classes, mailbox, receipt, mayday block"] --> R2["🛠️ radio.py, Stop mailbox hook, PreToolUse mayday hook, SKILL.md"]
        R2 --> R3{"🧪 Tests and make test green?"}
        R3 -- "🔴 no: fix" --> R2
        R3 -- "🟢 yes" --> R4["🧹 kvb-code-refactor"]
        R4 --> RF{"💬 Operator feedback?"}
        RF -- "✏️ changes" --> R2
    end
    RF -- "👍 commit word" --> S0
    subgraph S["🧭 2 · Surface and rename"]
        S0["🔀 Rebase feature/kvb-hub onto origin/master"] --> S1["🔴 Red tests: nav, header, badges, stream, migration"]
        S1 --> S2["🛠️ Nav, header, badges, banner, stream, inbox, tools, rename + migration"]
        S2 --> S3{"🧪 Tests green?"}
        S3 -- "🔴 no: fix" --> S2
        S3 -- "🟢 yes" --> S4["📸 Screenshots 1920 / 1366 / 390 px"]
        S4 --> SF{"💬 Operator feedback?"}
        SF -- "✏️ changes" --> S2
    end
    SF -- "👍 commit word" --> T0
    subgraph T["🌳 3 · pkgmgr branch tree"]
        T0["⚖️ kvb-think-dialectic on the data path"] --> T1["🔴 Red tests on fixture repositories"]
        T1 --> T2["🛠️ pkgmgr branch tree with gc states, timer, orchestrator reads the file"]
        T2 --> T3{"🧪 Tests green, no git in the container?"}
        T3 -- "🔴 no: fix" --> T2
        T3 -- "🟢 yes" --> TF{"💬 Operator feedback?"}
        TF -- "✏️ changes" --> T2
    end
    TF -- "👍 commit word" --> V1
    subgraph V["🪐 4 · Agents and Artifacts views"]
        V1["🔴 Red tests: five views per tab, artefact leaves, delete job"] --> V2["🛠️ Orbit, Chord, Swimlane, Tree with state icons and delete, 3D (3d-force-graph), host gc unit"]
        V2 --> V3{"🧪 Tests green?"}
        V3 -- "🔴 no: fix" --> V2
        V3 -- "🟢 yes" --> V4["📸 Screenshots of every view"]
        V4 --> VF{"💬 Operator feedback?"}
        VF -- "✏️ changes" --> V2
    end
    VF -- "👍 fits" --> D1["🏁 Full gate, commit with operator OK, push hand-over"]
```

Phases 5 and 6 (decisions 23 to 42):

```mermaid
flowchart TD
    subgraph W["🧩 5 · Inbox, UI, Hierarchy, Tasks"]
        W1["🛠️ W1 to W4 in own worktrees"] --> W2["🕵️ Skeptic round, fix round per worktree"]
        W2 --> W3{"🧪 Suite, e2e, MEDUSA, score green?"}
        W3 -- "🔴 no: fix" --> W2
        W3 -- "🟢 yes" --> W4["🔀 Rebase on master, commit, merge one by one"]
    end
    W4 --> L1
    subgraph L["👂 6.0 · Listen and record"]
        L1["❓ kvb-think-listen: names, Firewall writes, choices, groups"] --> L2["📋 Decisions 24 to 42 in this file on master"]
    end
    L2 --> S0
    subgraph S["🤖 6.0 to 6.7 · Serial subtrees under kvb-org-robot"]
        S0["🇬🇧 S0 English, Sécurité, NATO hashes, ICAO digits"] --> S1["🩹 S1 fit, rename once, radio, squelch, tree cause"]
        S1 --> S2["🪟 S2 agent and node popups, search"]
        S2 --> S3["🙂 S3 animated faces"]
        S3 --> S4["🌙 S4 drain, suspend, resume"]
        S4 --> S5["🗳️ S5 Tasks: asks, choices, Gantt, estimates, burn charts"]
        S5 --> S6["🧱 S6 Firewall and settings writes"]
        S6 --> S7["📈 S7 Resources charts"]
        S7 --> S8["🗄️ S8 artefact base URL, optional core speech"]
    end
    subgraph G["🔁 Each subtree"]
        G1["🔴 Red tests"] --> G2["🛠️ Change"]
        G2 --> G3{"🧪 Suite, e2e, MEDUSA, score green?"}
        G3 -- "🔴 no: fix" --> G2
        G3 -- "🟢 yes" --> G4["📸 Screenshots 1920 / 1366 / 390 px"]
        G4 --> GF{"💬 Operator feedback?"}
        GF -- "✏️ changes" --> G2
        GF -- "👍 fits" --> G5["🔀 Commit, merge into master, next subtree"]
    end
    S8 --> D2["🏁 install-skills-master row, push hand-over"]
```

## Acceptance Criteria

### Radio model

- [x] `radio.py send` accepts exactly `call`, `broadcast`, `pan-pan`,
      `mayday`, `security` and the alias `direct`; `post`, `newsletter` and
      any other class exit 2.
- [x] `radio.py post --to X` stores `post`; `radio.py post` without `--to`
      stores `newsletter`.
- [x] `call` and `send direct` require `--to`; `broadcast`, `pan-pan`,
      `mayday` and `security` exit 2 with `--to`.
- [x] `send direct --wake` is stored as `call`, `send direct` as `post`.
- [x] New rows carry a version mark; rows without it are read as before:
      `direct` as `post` (as `call` when it woke), `broadcast` as
      `newsletter`.
- [x] The UserPromptSubmit hook (`radio.py hook`) and the PostToolBatch hook
      (`radio.py tool`) never print a `post` or `newsletter` row.
- [x] A new Stop hook `radio.py mailbox`, registered in
      `scripts/enable-plugins.js`, prints the unseen `post` and `newsletter`
      rows of the session at most 10 at a time with a "N more" line, marks
      them seen and exits 2; with nothing unseen it exits 0 and prints
      nothing.
- [x] `radio.py listen` wakes an idle session only for `call`, `broadcast`,
      `pan-pan`, `mayday` and `security`, never for `post` or `newsletter`.
- [x] `radio.py tool` delivers `call` (to its addressee), `broadcast`,
      `pan-pan`, `mayday` and `security` at the next tool step.
- [x] When a call reaches the callee's context, a receipt row (callee, call
      time, read time) is stored; the caller's mailbox shows
      "CALL <to> read <time>". The receipt never wakes the caller.
- [x] While `radio-silence.json` holds an active mayday, a PreToolUse hook
      (matcher `Edit|Write|MultiEdit|NotebookEdit|Bash`) exits 2 for Edit,
      Write, MultiEdit and NotebookEdit and for every Bash command that
      matches neither the config's `never_block` nor its new `mayday_allow`
      regexes nor a plain call of `radio.py`.
- [x] The mayday's sender passes; `radio.py assist` adds the caller to the
      mayday's helpers, who pass too, and the mayday line names them.
- [x] After `radio.py clear` the same calls pass again.
- [x] `skills/kvb-org-radio/SKILL.md` separates the radio (`send`,
      immediate) and the post (`post`, delayed), each class with when to use
      it and how it is delivered; post is the default; markdownlint stays
      green.

### Organisation update

- [x] A skill `kvb-org-update` with `scripts/update.py` exists.
- [x] `update.py --repo <skills repo> --dry-run` prints every skill whose
      files changed between the last announced revision (kept in the council
      directory) and `HEAD`, with the subjects of the commits that touched it.
- [x] Without `--dry-run` it sends one `newsletter` through `radio.py post`
      that names each changed skill and tells every agent to re-read its
      `SKILL.md` before the next use, then records `HEAD` as announced; a
      second run without new commits sends nothing.
- [ ] The radio change of phase 1 is announced through it.
      Obsolete (operator 2026-11-12): a past event no record proves any more.

### Orchestrator surface and rename

- [x] The page title and heading read "Agent Orchestrator".
- [x] `grep -rnE 'kvb-hub|kvb_hub|KVB_HUB'` over the repository finds only the
      migration code and its tests.
- [x] The install migrates `~/.local/share/kvb-hub`, `~/.config/kvb-hub`,
      `~/.local/state/kvb-hub-approvals`, the `kvb-hub` MCP registration, the
      settings hook entries, the systemd unit and the container to the
      `kvb-orchestrator` names. A second run changes nothing (scratch-HOME
      test).
- [ ] The navigation has exactly three top-level entries Stream, Agents and
      Artifacts; Stream has the sub-items Inbox and Firewall.
      Obsolete: decision 23 adds Tasks, 003 decision 2 removes Inbox.
- [x] Every agent appears once under its current name: a register worker
      such as "Stage (this session)" or "infinito-nexus-core-c8 (Production)"
      maps to the agent named before the bracket.
- [x] The keys 1 to 3 switch the top-level entries.
- [x] The hashes `#stream`, `#stream/inbox`, `#stream/rules`,
      `#agents/<view>` and `#artifacts/<view>` route; `#graph…` and `#tree`
      redirect to their successors.
- [x] Agents and Artifacts show a switch with Orbit, Chord, Swimlane, Tree and
      3D in this order, and each view has its own hash.
- [ ] The header holds exactly the title, the ⌘K button and the ⚙ button.
      Obsolete: decision 59 adds Radio, 003 decision 17 the bubbles switch.
- [x] Badges:
  - [x] Inbox shows the waiting items that are not snoozed.
  - [x] Agents shows the agents with a heartbeat in the last 900 s.
  - [x] Artifacts shows the runner jobs that are queued or running.
  - [x] A badge at 0 is hidden.
- [ ] A red Mayday banner with "cancel" exists if and only if a mayday is
      active; "cancel" runs `radio.py clear`.
- [ ] The Agents toolbar holds:
  - [ ] Radio to all, with the class choice Newsletter, Broadcast, Pan-Pan,
        Security, Mayday and Newsletter preselected.
  - [ ] Cancel mayday, Priority and Day/Night.
  Obsolete: decisions 52 and 59 move the composer and Cancel mayday into
  the header radio spot; Priority and Day/Night ship.
- [x] The agent panel sends with the choice Post (preselected) or Call.
- [x] ⚙ "Ambience" holds Sky, Music, Control room and Notifications;
      ⌘K lists every former header tool.
- [x] The Stream shows exactly four category chips For you, Radio, Work and
      Transcripts, and one search line that filters by `agent:`, `kind:` and
      `since:`.
- [ ] "Filter ▾" holds the kind sub-filters, the transcript parts, the saved
      views and the custom range.
- [x] The time control reads "24 h ▾" and holds the replay.
- [x] Transcripts are off by default.
- [x] The Inbox renders in the main area under `#stream/inbox`; the right
      rail `#rail` no longer exists, at any width.
- [x] The read-aloud class choice lists exactly the seven classes of
      decision 3; Mayday stays checked and locked.

### pkgmgr branch tree

- [x] The kvb-think-dialectic result on the data path is recorded in the
      phase 3 commit body before any code of phase 3 is written.
- [x] `pkgmgr branch tree --format json` prints, for every repository pkgmgr
      knows and every worktree under `<repo>/.worktrees` and
      `~/.local/share/worktrees`, these fields:
  - [x] the repository's path, remote and default branch;
  - [x] per branch: upstream, ahead, behind and gone;
  - [x] per worktree: path, HEAD and its state, one of `clean`, `changed` or
        `missing`;
  - [x] detached worktrees, and `generated_at`.
- [x] It lists every repository `pkgmgr list` names, also one without extra
      branches or worktrees.
- [x] Per branch and worktree it carries the gc state (`merged-clean`,
      `unmerged`, `dirty`, `protected`, `stale`), what merged it (ancestor,
      `pr#N`, `line:X`), the counts of staged, unstaged and untracked files,
      ahead, behind, gone, locked and the gc skip reason.
- [x] Tree and gc share one classification function; on a fixture
      `pkgmgr branch tree --format json` and `pkgmgr branch gc --json` agree
      on every item's state.
- [x] Forge facts (open and merged pull requests) are fetched at most once
      per 10 min per repository, only with a token from the Secret Service;
      without one the file says `forge: unavailable` and "merged by" falls
      back to ancestor and line.
- [x] `delete_ready` is true only while the token resolves through the
      Secret Service, which the scan never unlocks; otherwise it is false
      with the reason.
- [x] `--format yaml` prints the same data.
- [x] `--output FILE` writes it atomically.
- [x] The scan starts no hook, filter, fsmonitor, pager or external diff of a
      scanned repository and never lazy-fetches (fixture test with a planted
      `core.fsmonitor`).
- [x] `pkgmgr branch open|close|drop|gc` rewrite the file when it exists.
- [x] The orchestrator install enables a systemd user timer that writes it
      60 s after its previous run ended while the page polled within the
      last 5 min, on at most half a core, with pkgmgr built from the newest
      signed tag.
- [x] The orchestrator mounts the file read-only and reads only it.
- [x] `orchestrator/kvb_orchestrator/tree.py`'s git scan is gone and no
      module of the orchestrator starts `git`.

### Agents and Artifacts views

- [x] Artifacts:
  - [x] Orbit, Chord, Swimlane and Tree draw what decision 16 names, from the
        pkgmgr tree file.
  - [x] Register artefacts (images, volumes, logs) appear as leaves of their
        task or worktree.
- [x] Agents:
  - [x] Orbit, Chord and Swimlane keep today's content.
  - [x] Tree shows the operator → chair → sessions → subagents spawn tree
        with running and finished states.
- [x] 3D in both tabs runs on the vendored `3d-force-graph` 1.80.1 and
      `three` 0.186.1, with their MIT licence texts beside them and no CDN
      request (CSP unchanged).
- [x] 3D offers the layouts Force, Time and Spawn depth.
- [x] A click on a 3D node opens the same panel as in 2D.
- [x] 3D respects `prefers-reduced-motion`.

### Delete merged branches

- [ ] The Artifacts Tree marks every branch and worktree with icons for
      merged (with what merged it), clean, uncommitted changes (with counts),
      unpushed commits, gone upstream, locked, stale and protected.
- [x] A `merged-clean` item without a gc skip reason shows a delete button,
      and the Tree header shows "Delete all merged"; both are disabled,
      with the reason as tooltip, while `delete_ready` is false.
- [x] A click shows the gc dry-run lines of exactly the chosen items;
      "Delete" requires the operator signature through `/api/sign`.
- [x] The orchestrator writes the signed job (repository, branch, worktree
      and tip sha per item, no command) into a host-mounted job directory and
      holds no git, token or key.
- [ ] A systemd user path unit verifies the signature on the host and runs
      `pkgmgr branch cleanup --apply --local` for exactly the signed items,
      matched exactly, never as a pattern; `--local` removes the worktree, the local
      branch, the compose stack without `-v` and its images, never a remote
      branch, and needs no SSH key.
- [x] The unit refuses, and changes nothing for, an item whose tip or state
      differs from the signed one, an unknown repository, a non-`merged-clean`
      item and a job with a bad or missing signature, and reports why.
- [x] The unit writes each item's result back and rewrites the tree file; the
      Tree shows the result.

### Icons

- [x] Bootstrap Icons 1.13.1 is vendored once as an SVG sprite with its MIT
      licence text beside it; no page loads it from a CDN.
- [x] The navigation, the header, the view switches, the toolbars, the
      Stream chips and the Inbox actions of the orchestrator show icons
      instead of text labels.
- [ ] The review pages and the meditation page show icons instead of text
      labels on their buttons.
- [x] Every icon element has a `title` and an `aria-label` that carry the
      former text (DOM test over every page).

### Phase 5: inbox, UI, Hierarchy, Tasks

- [x] A deny is refused by the hub unless its passkey proof verifies; the
      PermissionRequest hook quotes a deny reason only when it verifies.
- [x] A rule, also one an agent requested, is stored only with a passkey
      assertion the hub verified against the pinned keys.
- [x] `operator_message(id, text, to)` answers `match` only for a verified
      proof whose signed text and recipient equal the arguments.
- [x] The offices unit and the runner stay off while the installed
      `council.py`, `nofollow.py` or `rasci.py` differ from the tree.
- [x] `rasci.py agents order` writes only `agent-order.json` and no `--prio`.
- [x] W1 to W4 are merged into master, each commit with its score block.

### Phase 6: English and radio speech (S0)

- [x] The text handed to the speech engine for a `security` row starts with
      "say-cure-ee-tay" three times; the page shows "Sécurité".
- [x] `8e180be` is spoken "eight echo one eight zero bravo echo" and
      `42305` "four two tree zero fife" (unit test on the pronunciation step);
      the displayed line is unchanged.
- [x] A scan of the tree finds no German UI, message or document text
      outside quoted trigger phrases (test with an allowlist of those
      phrases).

### Phase 6: fixes (S1)

- [x] `#agents/orbit` at 1920, 1366 and 390 px has
      `document.documentElement.scrollHeight <= innerHeight` (e2e probe).
- [x] Two state builds with the same claims add no second rename event to
      the Stream (unit test on the timeline).
- [x] The Deutschlandfunk AAC stream plays in Chromium and Firefox through
      the radio (e2e with a recorded fixture of its redirect chain) and the
      root cause is named in the commit message.
- [x] With squelch at 0 no beep plays, music on or off (unit test on the
      audio scheduler).
- [x] Without a tree file the Tree names the missing `pkgmgr branch tree`
      and the release step.

### Phase 6: popups and search (S2)

- [x] A click on an agent opens the popup with a fade; Escape and a click
      outside close it; the Details side panel no longer exists.
- [x] A click on a node enlarges it, marks it red and draws a leader line to
      a translucent popup; a second click elsewhere restores the node.
- [x] A search field with suggestions replaces the node chip list; no view
      renders more than one chip per search hit.

### Phase 6: faces (S3)

- [x] The face generator yields at least 1000 distinct attribute
      combinations and the same face for the same agent id (unit test).
- [x] A speaking agent's face animates its mouth; a silent one does not
      (DOM test on the class while the radio plays).

### Phase 6: night commands (S4)

- [x] `kvb-org-drain`, `kvb-org-suspend`, `kvb-org-resume`,
      `kvb-agent-drain`, `kvb-agent-suspend` and `kvb-agent-resume` exist;
      the old six names exist nowhere in the tree except in the migration
      and `kvb-skill-cleanup` history (grep test).
- [x] The Controls menu shows Drain, Suspend and Resume and each needs the
      passkey, like the board actions today.

### Phase 6: Tasks with asks and choices (S5)

- [x] Every pending ask, rule request, operator row and choice card shows in
      the Tasks tab under "waits on Operator"; no Choices column exists.
- [x] Each channel button sends the fixed choice request with no text field;
      `post` and `call` take a multi-select of agents.
- [x] A click on a choice option sends a passkey-signed answer the agent can
      check with `operator_message`.

### Phase 6: Firewall (S6)

- [ ] The tab is called Firewall and lists hub rules, allow and deny
      patterns and the settings permissions, grouped by tool and prefix as
      read from the settings files.
- [ ] A rule or rule set applies to one agent, a named group or all agents.
- [ ] A settings change is written only by the host executor after the
      passkey check, only to a listed file, with a backup beside it; a forged,
      replayed or unlisted-file job changes nothing (unit tests).

### Phase 6: Resources (S7)

- [ ] The tab shows tokens per agent and accumulated, and CPU, RAM, disk and
      load, on the shared time axis, several values per chart.
- [ ] Token counts equal the sum of the transcript usage fields of a fixture
      (unit test); host samples come from the host unit's file, not from the
      container.

### Phase 6: shared cache (S8)

- [ ] With `INFINITO_ARTEFACT_BASE` set, every `ADD` and clone of the image
      build uses `<base>/<host>/<path>` and the unchanged sha256 pins; unset,
      the build uses the upstream URLs (test over the rendered Dockerfile).
- [ ] With a configured `svc-ai-speech` URL the hub sends STT and TTS there;
      without it the in-container engines answer (unit test with a stub).
- [ ] `make orchestrator-install` succeeds in a scratch HOME without any core
      stack.

### Phase 6: Gantt, estimates, burndown and burnup (S5)

- [x] `rasci.py set <task> --after <other>` stores the dependency and
      `--drop-after <other>` removes it; an unknown task and a cycle are
      refused.
- [x] The Gantt view draws one bar per task from start to end, a running
      task to now, and one arrow per explicit, branch-base and queue-order
      edge of a fixture register and queue.
- [x] The forecast selector offers `always` (default), `points only` and
      `real only`; a hatched bar is as long as the median duration of done
      tasks (no estimate) or points times median hours per point (story
      points).
- [x] The estimation toggle defaults to `No estimate`, is stored in the hub
      settings and survives a reload.
- [x] Burndown and burnup offer the scopes whole register (default), list
      filter within the time window, and one agent or line; with no estimate
      they count tasks, with story points they sum complexity and draw the
      unestimated tasks as a line of their own.
- [x] "Request estimates" shows only in story points mode; a click or
      `/kvb-org-queue-estimate` sends exactly one newsletter to all agents
      that lists every unestimated task with every party holding a RASCI
      role in it; a state build or a mode switch sends none.
- [x] A per-task or bulk business value change is stored only with a
      verified passkey assertion over the exact task ids and values; a
      forged, replayed or altered batch changes nothing, and WSJF uses the
      operator value instead of the median.
- [x] The task list sorts by each mode of decision 50 in both directions.

### Phase 6: radio spot, compact menus, trend, ETA, Tasks 3D (S5.1)

- [x] The toolbar radio button expands inline and sends a post, a call to
      chosen agents and each to-all class, Record included; the Radio tab
      shows no composer.
- [x] The radio gear holds the tones, squelch and read-aloud settings, the
      general settings no longer do, and a changed value survives a reload.
- [x] Cancel mayday sits in the expanded radio spot and no longer in the
      toolbar; it still needs its confirmation.
- [x] The Day/Night menu shows only the badge and three buttons; hovering
      each shows its explanation.
- [x] The Tasks toolbar is one row at 1920 and 1366 px; "Request choices" is
      a dropdown sending the same signed choice requests as before.
- [x] The trend selector offers off (default), linear regression and
      velocity over N days; the line and the forecast date match the
      fixture's computed values, and the choice survives a reload.
- [x] Hovering a burn chart point lists exactly the fixture work packages of
      that step.
- [x] Every list row shows an ETA, which equals the end for done tasks and
      start or now plus the forecast length otherwise, in both estimation
      modes.
- [x] The Tasks 3D view draws one node per task and one edge per dependency
      of the fixture, in Force and Time layouts.
- [x] Two state refreshes after a manual camera move leave the 3D camera
      where the operator put it.

### Phase 6: radio in the header (S5.4)

- [x] The header shows Radio, Commands and Settings as icon buttons; Radio
      opens the spot above the main area on Stream, Inbox, Agents, Artifacts
      and Tasks, and closes it again.
- [x] No Radio tab, no "Send …" button and no radio button in the Agents
      toolbar remain; `#stream/radio` lands on `#stream` with the spot open
      and the message field focused.
- [x] Cancel mayday shows only its icon, keeps its tooltip, its confirmation
      and its passkey signature.
- [ ] The spot shows the speaking caption, the last five sent messages and
      the stations with play and stop.

### Phase 6: agent states and 3D faces (S5.3)

- [x] The state of every fixture session matches decision 61 for each of the
      six states and for a session without a session file (unit test).
- [x] Orbit, Chord, Swimlane, Tree, 3D and the agent panel show the state
      symbol of each fixture agent.
- [x] Unticking a state in the Status menu hides its symbols in every view;
      the choice survives a reload.
- [x] The 3D view shows agent faces by default and spheres after unticking
      "Faces in 3D".
- [ ] `make orchestrator-install` enables `kvb-orchestrator-sessions.timer`,
      and `make orchestrator-check` reports it active.

### Phase 6: Day/Night per agent (S5.2)

- [x] `night.py drain|suspend|resume --target=<id>` sets and lifts one
      session's part by day and during a mode, and `night.py status` prints
      it as the `you:` line (`tests/test_night.py`).
- [x] The Day/Night menu lists "All" and one checkbox per claimed agent; all
      ticked sends the unchanged board item, a subset signs and runs only for
      the ticked sessions, and none ticked disables the three buttons.
- [x] A proof for one set of agents is refused for another set and for all,
      and an unclaimed session is refused before anything runs
      (`tests/test_hub_board.py`).
- [x] Every agent panel shows the agent's part and Drain, Suspend and Resume
      for that agent alone.

### Tests

- **Unit**
  - [x] Radio: class mapping, `--to` rules, the mailbox Stop hook, the
        receipt and the mayday block hook, each red before and green after.
  - [x] Organisation update on a fixture repository: changed skills with
        their subjects, nothing new sends nothing.
  - [x] pkgmgr branch tree on fixture repositories: ahead, behind, gone,
        detached and missing worktree, JSON and YAML, the planted fsmonitor,
        staged, unstaged and untracked counts, tree and gc states agreeing.
  - [x] Delete job: a bad signature, a changed tip, a non-`merged-clean`
        item and a branch name with pattern characters are each refused.
  - [x] Orchestrator: the scratch-HOME migration, routing including old
        hashes, badge counts.
  - [ ] Phase 6: pronunciation (Sécurité, NATO hashes, ICAO digits),
        rename-once timeline, squelch scheduler, face generator, settings
        writer (forged, replayed, unlisted file), token sums, German text
        scan.
  - [x] S5 Gantt and estimates: dependency edges and cycle refusal, forecast lengths, burn
        sums per mode and scope, newsletter body and its single send, bulk
        business value signature (forged, replayed, altered), sort orders.
  - [x] S5.1: regression and velocity trend with their forecast dates, point
        tooltips, ETA in both modes, radio settings stored from the gear.
  - [x] S5.4: the navigation without the Radio tab, `#stream/radio`
        redirecting to `#stream` with the spot flag.
  - [x] S5.5: ICAO digit words, Zulu times, DTG with offset conversion,
        dates, decimals and spoken paths.
  - [x] S5.3: each agent state from a fixture snapshot, night state and
        receipts, a session without a record; the host client's snapshot
        from fixture session files with a reused pid; a stale or malformed
        snapshot read as absent.
  - [x] S5.2: night.py targets by day and during a mode, the signed board
        item with agents (forged set, unclaimed session), the parts in the
        state.
- **Integration**
  - [x] Two scratch sessions exchange `post` and `call` through the real hook
        entry points (JSON on stdin): the post appears only on the callee's
        Stop and the call at its next tool step with a receipt to the caller.
  - [x] A mayday blocks an Edit until `clear`.
  - [ ] The orchestrator's `/api/tree` serves a pkgmgr-written file.
  - [ ] On a fixture repository with a file remote and a test token source, a
        signed job through the path unit removes the merged worktree, the
        local and the remote branch, and the rewritten tree no longer lists
        them. Obsolete: contradicts decision 21; 003 decision 10 replaces it.
  - [ ] `make test` green on the HEAD that carries every phase (operator
        2026-11-12).
- **E2E**
  - [x] A headless Chromium and Firefox run opens Stream, Inbox, Firewall and
        every view of Agents and Artifacts at 1920, 1366 and 390 px wide and
        saves the screenshots shown at each operator checkpoint.
  - [x] It sends a Call from the agent panel and sees its receipt in the
        Stream.
  - [x] On fixture data it shows the state icons in the Artifacts Tree and
        runs the delete flow: dry-run dialog, signature, result.
  - [ ] Phase 6: no page scrollbar on any view, agent and node popups,
        choice request and signed answer, Firewall settings diff and
        signature, Resources charts, each at 1920, 1366 and 390 px.
  - [x] S5: Gantt with arrows, burndown and burnup, the estimation toggle,
        "Request estimates" and a signed bulk business value change, each at
        1920, 1366 and 390 px.
  - [x] S5.1: radio spot (send, gear, cancel mayday), Day/Night tooltips,
        one-row Tasks toolbar, trend and point tooltips, ETA column, Tasks
        3D and a steady 3D camera, each at 1920, 1366 and 390 px.
  - [ ] S5.4: the header radio button opens the spot on every tab, every
        class sends from it, the icon-only Cancel mayday, the speaking
        caption and the stations inside the spot, in Chromium and Firefox at
        1920, 1366 and 390 px.
  - [x] S5.3: state symbols in every Agents view and the panel, the Status
        menu toggles through a reload, 3D faces on and off, in Chromium and
        Firefox at 1920, 1366 and 390 px.
  - [x] S5.2: agent checkboxes in the Day/Night menu and the agent panel's
        buttons, signed in Chromium and refused unsigned in Firefox, each at
        1920, 1366 and 390 px.
