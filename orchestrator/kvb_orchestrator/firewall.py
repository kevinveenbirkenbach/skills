from __future__ import annotations

import difflib
import json
import re
import secrets
import time

from .errors import Conflict, Missing, ToolError
from .fields import decode, expect, visible
from .ledger import Ledger
from .records import read_json, stamp
from .requesting import RECENT_DAYS, matched
from .rules import EVERY_AGENT, RULE_KINDS
from .signed import signing

VIEW = "view.json"
JOB_VERSION = 1
ITEM_LIMIT = 10
SET_LIMIT = 50
DAY_LIMIT = 366
NAME = re.compile(r"(?=[^\x00-\x1f\x7f]*\S)[^\x00-\x1f\x7f]{1,80}")
RULE_TEXT = re.compile(r"(?P<tool>[^()]+?)(?:\((?P<spec>.*)\))?", re.DOTALL)
WORD = re.compile(r"[\s:]")
HASH = re.compile(r"[0-9a-f]{64}")
PERMISSION_LISTS = ("allow", "ask", "deny")
SET_KEYS = ("kind", "tool", "pattern", "scope")
CHAINED = "chains, pipes, redirects or substitutions"
COUNT_ID = "0" * 16
UNSEEN = {"hits": None, "never": ""}


def settings_request(raw: object) -> bool:
    return isinstance(raw, list) and bool(raw) and all(isinstance(entry, dict) and entry.get("kind") == "settings" for entry in raw)


def tool_and_spec(entry: str) -> tuple[str, str]:
    """Returns:
        The tool of a permission rule such as Bash(git push:*) and its
        specifier, git push:*; "" without specifier.
    """
    found = RULE_TEXT.fullmatch(entry)
    if found is None:
        return entry.strip(), ""
    return found.group("tool").strip(), (found.group("spec") or "").strip()


def tool_and_prefix(entry: str) -> tuple[str, str]:
    """Returns:
        The tool of a permission rule such as Bash(git push:*) and the first
        word of its specifier, for Bash the command; "" without specifier.
    """
    tool, spec = tool_and_spec(entry)
    return tool, WORD.split(spec, maxsplit=1)[0]


def entry_rule(entry: str) -> dict:
    """Returns:
        A permissions.ask entry as the fields of an ask rule for every agent
        in every directory: its tool, and its specifier as pattern, where a
        trailing :* or no specifier matches any rest.
    """
    tool, spec = tool_and_spec(entry)
    pattern = f"{spec.removesuffix(':*')}*" if spec.endswith(":*") or not spec else spec
    return {"kind": "ask", "tool": tool, "pattern": pattern, "scope": "*"}


def hits(rule: dict, asks: list[dict], now: float) -> dict:
    """Args:
        rule: kind ask, tool, pattern and scope of a rule, with agents when
            it applies to one agent or group only.
        asks: the asks of the last RECENT_DAYS as recent_subjects() lists
            them.
        now: the current time in epoch seconds.

    Returns:
        {"hits": how many of the asks the rule matches, on or off, expired or
        not, "never": ""}; hits None and never the warning when the pattern
        itself names a command the matcher never grants.
    """
    pattern = rule["pattern"]
    never = [*signing.warnings(pattern), *([CHAINED] if signing.CHAINED.search(pattern) else [])]
    if never:
        return {"hits": None, "never": never[0]}
    return {"hits": matched({**rule, "id": COUNT_ID, "expires": now + RECENT_DAYS * 86400}, asks, now), "never": ""}


def counted(groups: list[dict], asks: list[dict], now: float) -> list[dict]:
    """Returns:
        groups with each entry's specifier and hits: counted for an ask
        entry, UNSEEN for an allow or deny entry.
    """
    def shown(entry: dict) -> dict:
        found = hits(entry_rule(entry["entry"]), asks, now) if entry["list"] == "ask" else UNSEEN
        return {**entry, "spec": tool_and_spec(entry["entry"])[1], **found}

    return [{**group, "entries": [shown(entry) for entry in group["entries"]]} for group in groups]


def stored_hits(rule: dict, asks: list[dict], now: float) -> dict:
    """Returns:
        hits() of a stored ask rule for the agents it is signed for, UNSEEN
        for a review or decision rule.
    """
    if rule["kind"] != "ask":
        return UNSEEN
    fields = {key: rule[key] for key in ("kind", "tool", "pattern", "scope")}
    return hits({**fields, "agents": rule["agents"]} if "agents" in rule else fields, asks, now)


def grouped(permissions: object) -> list[dict]:
    """Returns:
        The allow, ask and deny entries of a permissions section grouped by
        tool and prefix, sorted: [{"tool", "prefix", "entries": [{"list",
        "entry"}]}].
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    lists = permissions if isinstance(permissions, dict) else {}
    for name in PERMISSION_LISTS:
        values = lists.get(name)
        for entry in values if isinstance(values, list) else []:
            if isinstance(entry, str):
                groups.setdefault(tool_and_prefix(entry), []).append({"list": name, "entry": entry})
    return [{"tool": tool, "prefix": prefix, "entries": entries} for (tool, prefix), entries in sorted(groups.items())]


def sandbox_entries(section: object, path: str) -> list[dict]:
    """Returns:
        Every leaf of a sandbox section under the dotted path, a list as
        {"key", "values"} and any other value as {"key", "value"}.
    """
    found: list[dict] = []
    for name, value in section.items() if isinstance(section, dict) else ():
        key = f"{path}.{name}"
        if isinstance(value, dict):
            found += sandbox_entries(value, key)
        elif isinstance(value, list):
            found.append({"key": key, "values": [entry if isinstance(entry, str) else json.dumps(entry) for entry in value]})
        else:
            found.append({"key": key, "value": value})
    return found


def shaped_file(entry: object) -> bool:
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("exists"), bool):
        return False
    return isinstance(entry.get("settings"), dict) and isinstance(entry.get("sha256"), str) and (entry["sha256"] == "" or bool(HASH.fullmatch(entry["sha256"])))


def tool_state(settings: dict, name: str, entry: str) -> bool | None:
    """Args:
        settings: a file's settings as signing.settings_view() keeps them.
        name: a signing.CAPABILITIES key.
        entry: the server name, plugin id or switch.

    Returns:
        What the file sets for entry: False for a server it blocks or a
        switch it turns off, the boolean of a plugin, None where it sets
        nothing that counts. Claude Code merges the deny lists of every
        file, a false switch anywhere wins, and a project's plugin switch
        overrides the user's.
    """
    if name == "deniedMcpServers":
        return False if {"serverName": entry} in (settings.get(name) or []) else None
    if name == "enabledPlugins":
        on = (settings.get(name) or {}).get(entry)
        return on if isinstance(on, bool) else None
    return False if settings.get(entry) is False else None


def tool_names(every: list[dict], known: dict) -> dict:
    """Args:
        every: the shown settings files.
        known: the view's {"servers", "plugins"} names.

    Returns:
        Per signing.CAPABILITIES key the names its rows show: the known
        servers and plugins plus every one a file blocks or switches, and the
        fixed switches.
    """
    blocked = {rule["serverName"] for entry in every for rule in entry["settings"].get("deniedMcpServers") or []}
    enabled = [name for entry in every for name in entry["settings"].get("enabledPlugins") or {}]
    return {
        "deniedMcpServers": signing.names_of([*signing.names_of(known.get("servers"), signing.MCP_NAME), *blocked], signing.MCP_NAME),
        "enabledPlugins": signing.names_of([*signing.names_of(known.get("plugins"), signing.PLUGIN_ID), *enabled], signing.PLUGIN_ID),
        "switches": list(signing.SWITCHES),
    }


def tools_of(files: list[dict], known: object) -> dict | None:
    """Args:
        files: the shown settings files.
        known: the view's {"servers", "plugins"} names.

    Returns:
        {"file", "error", "groups"} for the file the view marks as
        ~/.claude/settings.json, each group {"list", "label", "off", "rows"}
        with off the op that turns a row off, each row {"name", "on",
        "overrides"}: on as that file sets it, overrides every other listed
        file that sets it differently as {"file", "on"}; None while no file
        is marked.
    """
    own = next((entry for entry in files if entry.get("own") is True), None)
    if own is None:
        return None
    settings = own["settings"]
    others = [entry for entry in files if entry is not own]
    names = tool_names([own, *others], known if isinstance(known, dict) else {})

    def row(name: str, entry: str) -> dict:
        state = tool_state(settings, name, entry)
        on = state is True if name == "enabledPlugins" else state is None
        overrides = [{"file": other["path"], "on": found} for other in others if (found := tool_state(other["settings"], name, entry)) is not None and found != on]
        return {"name": entry, "on": on, "overrides": overrides}

    labels = (("deniedMcpServers", "MCP servers", "add"), ("enabledPlugins", "Plugins", "remove"), ("switches", "Features", "remove"))
    return {"file": own["path"], "error": own["error"], "groups": [{"list": name, "label": label, "off": off, "rows": [row(name, entry) for entry in names[name]]} for name, label, off in labels]}


def section_diff(path: str, before: dict, after: dict) -> str:
    """Returns:
        The unified diff of the part of the settings the view shows before
        and after the change, as the host writer applies it.
    """
    lines = difflib.unified_diff(json.dumps(before, indent=2).splitlines(), json.dumps(after, indent=2).splitlines(), fromfile=path, tofile=path, lineterm="", n=3)
    return "\n".join(lines)


def unique_name(payload: dict, ledger: Ledger) -> str:
    name = payload["name"]
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ToolError("name must be one line of 1 to 80 characters")
    visible({"name": name})
    if any(record["name"] == name for record in ledger.listed()):
        raise Conflict({"name": name, "status": "exists"})
    return name


def dropped(ledger: Ledger, record_id: str) -> dict:
    if not ledger.remove(record_id):
        raise Missing(record_id)
    return {"id": record_id, "deleted": True}


def deny_patterns() -> list[dict]:
    """Returns:
        The commands no ask rule ever grants, as {"label", "pattern"}.
    """
    return [*({"label": label, "pattern": pattern.pattern} for label, pattern in signing.WARNINGS), {"label": CHAINED, "pattern": signing.CHAINED.pattern}]


class Firewall:
    def settings_files(self) -> tuple[list[dict], dict]:
        """Returns:
            The listed settings files the host writer last read, each
            {"path", "exists", "folder", "sha256", "error", "settings", "own"}
            with settings only the part signing.settings_view() keeps and
            folder False only when the writer found no directory for the
            path, and the view's written time, error and tools_of().
        """
        view = read_json(self.firewall_spool.root / VIEW)
        files = view.get("files") if isinstance(view, dict) else None
        if not isinstance(files, list):
            return [], {"written": None, "error": "no settings view yet: the kvb-orchestrator-firewall unit writes it on the host", "tools": None}
        shown = [{**entry, "settings": signing.settings_view(entry["settings"]), "error": str(entry.get("error") or ""), "folder": entry.get("folder") is not False, "own": entry.get("own") is True} for entry in files if shaped_file(entry)]
        return shown, {"written": view.get("written"), "error": "", "tools": tools_of(shown, view.get("known"))}

    def firewall(self) -> dict:
        files, meta = self.settings_files()
        now = time.time()
        asks = self.recent_subjects("ask", now)
        listed = [{key: entry[key] for key in ("path", "exists", "folder", "sha256", "error")} | {"groups": counted(grouped(entry["settings"].get("permissions")), asks, now), "sandbox": sandbox_entries(entry["settings"].get("sandbox"), "sandbox")} for entry in files]
        rules = {rule["id"]: stored_hits(rule, asks, now) for rule in self.rules.listed()}
        return {**meta, "files": listed, "lists": list(signing.SETTINGS_LISTS), "patterns": deny_patterns(), "groups": self.groups.listed(), "sets": self.rule_sets.listed(), "days": RECENT_DAYS, "rules": rules}

    def settings_changes(self, raw: object) -> list[dict]:
        """Args:
            raw: the page's items, each {"kind": "settings", "file", "base",
                "changes"} for one listed file at the sha256 the view shows.

        Returns:
            The signed items, each one file whose changes apply to the
            sections the view shows.
        """
        if not isinstance(raw, list) or not 1 <= len(raw) <= ITEM_LIMIT:
            raise ToolError(f"items must be a list of 1 to {ITEM_LIMIT} settings changes")
        files = {entry["path"]: entry for entry in self.settings_files()[0]}
        signed: list[dict] = []
        for entry in raw:
            order = self.settings_order(files, entry)
            if any(item["file"] == order["file"] for item in signed):
                raise ToolError("one item per file: list every change of a file in its changes")
            signed.append(signing.settings_item(**order))
        return signed

    def settings_order(self, files: dict[str, dict], entry: object) -> dict:
        """Args:
            files: the listed settings files by path.
            entry: one item of the page.

        Returns:
            Its file, base and changes once they apply to the listed file;
            ToolError otherwise.
        """
        if not isinstance(entry, dict):
            raise ToolError("every item must be an object with kind, file, base and changes")
        expect(entry, ("kind", *signing.SETTINGS_KEYS))
        order = {name: entry[name] for name in signing.SETTINGS_KEYS}
        problem = signing.settings_problem(order)
        if problem:
            raise ToolError(problem)
        self.applicable(files, order)
        if not files[order["file"]]["own"] and any(change["list"] in signing.CAPABILITIES for change in order["changes"]):
            raise ToolError("MCP servers, plugins and switches change only in ~/.claude/settings.json")
        return order

    def applicable(self, files: dict[str, dict], order: dict) -> dict:
        shown = files.get(order["file"])
        if shown is None:
            raise ToolError(f"{order['file'][:300]} is no settings file the Firewall lists")
        if shown["sha256"] != order["base"]:
            raise Conflict({"file": order["file"], "status": "changed", "sha256": shown["sha256"]})
        try:
            return signing.apply_changes(shown["settings"], order["changes"])
        except signing.Refused as error:
            raise ToolError(str(error)) from None

    def settings_preview(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("items",))
        items = self.settings_changes(payload["items"])
        files = {entry["path"]: entry for entry in self.settings_files()[0]}
        return {"diffs": [{"file": item["file"], "diff": section_diff(item["file"], files[item["file"]]["settings"], self.applicable(files, item))} for item in items]}

    def change_settings(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("items", "proof"))
        items = self.settings_changes(payload["items"])
        proof = self.covered(payload["proof"], items, time.time())
        for item in items:
            self.operator_proven(proof, item)
        job_id = secrets.token_hex(8)
        job = {"v": JOB_VERSION, "id": job_id, "created": stamp(), "items": [{name: item[name] for name in signing.SETTINGS_KEYS} for item in items], "proof": proof}
        self.firewall_spool.put(job_id, job)
        lines = [f"{item['file']}: {change['op']} {change['list']} {change['entry']}" for item in items for change in item["changes"]]
        self.log.add({"kind": "run", "title": f"Settings change signed: {len(lines)}"[:200], "text": "\n".join(lines), "ref": {"firewall": job_id, "status": "queued"}})
        return {"id": job_id, "status": "queued", "items": job["items"]}

    def settings_state(self, job_id: str) -> dict:
        result = read_json(self.firewall_spool.results / f"{job_id}.json")
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            return {**result, "id": job_id, "status": "done"}
        if (self.firewall_spool.jobs / f"{job_id}.json").is_file():
            return {"id": job_id, "status": "queued", "items": []}
        raise Missing(job_id)

    def add_group(self, body: bytes) -> dict:
        """Args:
            body: {"name", "members"}: members 1 to signing.AGENT_LIMIT
                sorted session ids the Agent Orchestrator knows.
        """
        payload = decode(body)
        expect(payload, ("name", "members"))
        members = payload["members"]
        problem = signing.agents_problem(members) if members != EVERY_AGENT else "members must name sessions, not every agent"
        if problem:
            raise ToolError(problem)
        self.known_agents(members)
        record = self.groups.add({"name": unique_name(payload, self.groups), "members": members})
        self.log.add({"kind": "rule", "title": f"Agent group {record['name']}: {len(members)} agents", "text": ", ".join(members), "ref": {"group": record["id"]}})
        return record

    def add_set(self, body: bytes) -> dict:
        """Args:
            body: {"name", "days", "rules"}: the ids of 1 to SET_LIMIT stored
                rules whose kind, tool, pattern and scope the set keeps, and
                the lifetime in days each rule gets when the set is taken
                over and signed for an agent, a group or every agent.
        """
        payload = decode(body)
        expect(payload, ("name", "days", "rules"))
        days = payload["days"]
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= DAY_LIMIT:
            raise ToolError(f"days must be a whole number from 1 to {DAY_LIMIT}")
        chosen = self.stored_rules(payload["rules"])
        record = self.rule_sets.add({"name": unique_name(payload, self.rule_sets), "days": days, "rules": [{key: rule[key] for key in SET_KEYS} for rule in chosen]})
        self.log.add({"kind": "rule", "title": f"Rule set {record['name']}: {len(chosen)} rules", "text": "\n".join(f"{rule['kind']} {rule['tool']} {rule['pattern']}".replace("  ", " ") for rule in chosen), "ref": {"set": record["id"]}})
        return record

    def stored_rules(self, ids: object) -> list[dict]:
        if not isinstance(ids, list) or not 1 <= len(ids) <= SET_LIMIT or len(set(map(str, ids))) != len(ids):
            raise ToolError(f"rules must list 1 to {SET_LIMIT} distinct rule ids")
        chosen = [self.rules.get(rule_id) if isinstance(rule_id, str) else None for rule_id in ids]
        if None in chosen or any(rule["kind"] not in RULE_KINDS for rule in chosen):
            raise ToolError("rules must name stored rules")
        return chosen

    def drop_group(self, group_id: str) -> dict:
        return dropped(self.groups, group_id)

    def drop_set(self, set_id: str) -> dict:
        return dropped(self.rule_sets, set_id)
