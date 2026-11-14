#!/usr/bin/env python3
"""Args:
    add --repo <worktree> --title <subject> --score <line> --gate <pass|fail>
        --agent <name> [--pages <dir>] [--rules <dir>]: adds the staged
        change of the worktree as a commit card: a review of the hub queue
        whose page holds the patch git diff --cached prints and whose tree is
        the one git write-tree prints; <dir> is the hub's pages folder,
        /tmp/kvb-git-diff by default, and --rules the MEDUSA rules the
        masked card diff is built with, as approval.py request takes them.
    add --task <operator/slug>: takes the payload files of an open operator
        row again, so its stale card turns fresh.
    list: prints one line per card; a commit card whose worktree's staged
        tree changed is reported to the hub, which marks it stale.
    show <card>: prints a commit card's patch, or a command card's command,
        directory, reason and payload files.
    --port <port>: the hub's port, 8737 by default.
    --client <dir>: the hub's client folder, by default
        ~/.local/share/kvb-orchestrator/client.

Returns:
    Exit code 0 with the result on stdout; 1 with the reason on stderr.
"""

from __future__ import annotations

import argparse
import html
import importlib
import json
import os
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

PORT = 8737
CLIENT = Path.home() / ".local" / "share" / "kvb-orchestrator" / "client"
PAGES = Path("/tmp/kvb-git-diff")
PATCH = re.compile(r'<pre id="patch">(.*)</pre>', re.DOTALL)
REVIEW = re.compile(r"[0-9a-f]{16}")
UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class Refused(Exception):
    pass


def client_modules(folder: Path) -> dict:
    sys.path.insert(0, str(folder))
    return {name: importlib.import_module(name) for name in ("hub_api", "staged_diff", "approval")}


def git_text(client: dict, cwd: Path, args: list[str]) -> str:
    try:
        return client["staged_diff"].git(cwd, args, None).decode("utf-8", "surrogateescape")
    except client["staged_diff"].DiffError as error:
        raise Refused(str(error)) from error


def hub(client: dict, port: int, path: str, body: dict | None) -> object:
    api = client["hub_api"]
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {**api.GUARD, **({} if body is None else {"Content-Type": "application/json"})}
    try:
        return api.load(urllib.request.Request(f"{api.base_url(port)}{path}", data=data, headers=headers, method="GET" if body is None else "POST"), api.SLACK)
    except (OSError, ValueError) as error:
        raise Refused(f"the Agent Orchestrator did not answer {path}: {error}") from error


def page_text(client: dict, port: int, review_id: str) -> str:
    api = client["hub_api"]
    request = urllib.request.Request(f"{api.base_url(port)}/reviews/{review_id}/page", headers=api.GUARD)
    try:
        with api.OPENER.open(request, timeout=api.SLACK) as response:
            return response.read().decode("utf-8", "replace")
    except OSError as error:
        raise Refused(f"the review page did not load: {error}") from error


def cards(client: dict, port: int) -> list[dict]:
    data = hub(client, port, "/api/match", None)
    if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
        raise Refused("the Agent Orchestrator answered no cards")
    return data["cards"]


def add_commit(args: argparse.Namespace, client: dict) -> str:
    repo = args.repo.resolve()
    tree = git_text(client, repo, ["write-tree"]).strip()
    branch = git_text(client, repo, ["symbolic-ref", "--short", "HEAD"]).strip()
    patch = git_text(client, repo, ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-color"])
    if not patch.strip():
        raise Refused(f"nothing staged in {repo}")
    shown = patch.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    page = args.pages / f"match-{UNSAFE.sub('-', branch)}-{tree[:12]}.html"
    page.write_text(f'<!doctype html><meta charset="utf-8"><title>{html.escape(args.title)}</title><pre id="patch">{html.escape(shown)}</pre>\n', encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as notes:
        notes.write(f"{args.score}\n")
    try:
        os.chdir(repo)
        request = argparse.Namespace(port=args.port, title=args.title, page=page, notes=Path(notes.name), gate=args.gate, score=args.score, agent=args.agent, rules=args.rules)
        return client["approval"].request_review(request)
    except client["approval"].Refused as error:
        raise Refused(str(error)) from error
    finally:
        os.unlink(notes.name)


def add_task(args: argparse.Namespace, client: dict) -> str:
    return json.dumps(hub(client, args.port, "/api/match/snapshot", {"task": args.task}))


def checked(client: dict, port: int, card: dict) -> dict:
    worktree = Path(card["worktree"])
    if card["kind"] != "commit" or card["stale"] or not worktree.is_dir():
        return card
    try:
        live = git_text(client, worktree, ["write-tree"]).strip()
    except Refused:
        return card
    if live == card["hash"]:
        return card
    hub(client, port, "/api/match/stale", {"id": card["ref"], "tree": live})
    return {**card, "stale": True, "stale_reason": "the staged tree changed since it was added"}


def list_cards(args: argparse.Namespace, client: dict) -> str:
    lines = []
    for card in (checked(client, args.port, card) for card in cards(client, args.port)):
        where = card["branch"] or card["directory"]
        lines.append("\t".join([card["id"], card["kind"], "stale" if card["stale"] else "fresh", card["agent"] or "-", where or "-", card["title"]]))
    return "\n".join(lines) if lines else "no cards"


def card_id(text: str) -> str:
    return f"review:{text}" if REVIEW.fullmatch(text) else text


def show_card(args: argparse.Namespace, client: dict) -> str:
    wanted = card_id(args.card)
    card = next((card for card in cards(client, args.port) if card["id"] == wanted), None)
    if card is None:
        raise Refused(f"no card {wanted}")
    if card["kind"] == "commit":
        found = PATCH.search(page_text(client, args.port, card["ref"]))
        if found:
            return html.unescape(found.group(1))
        return "".join(f"--- {entry['path']}\n{entry['patch']}\n" for entry in card["files"] or [])
    lines = [f"$ {card['command']}", f"  in {card['directory']}", f"  reason: {card['reason']}"]
    for entry in card["files"]:
        lines.append(f"--- {entry['path']} ({entry['state']}{': ' + entry['reason'] if entry['reason'] else ''})")
        lines.append(entry["content"].rstrip("\n"))
    return "\n".join(lines) + "\n"


def parser() -> argparse.ArgumentParser:
    found = argparse.ArgumentParser(prog="match")
    commands = found.add_subparsers(dest="command", required=True)
    adding = commands.add_parser("add")
    target = adding.add_mutually_exclusive_group(required=True)
    target.add_argument("--repo", type=Path)
    target.add_argument("--task")
    for name in ("--title", "--score", "--agent"):
        adding.add_argument(name)
    adding.add_argument("--gate", choices=("pass", "fail"))
    adding.add_argument("--pages", type=Path, default=PAGES)
    adding.add_argument("--rules", type=Path)
    commands.add_parser("list")
    showing = commands.add_parser("show")
    showing.add_argument("card")
    for sub in (adding, commands.choices["list"], showing):
        sub.add_argument("--port", type=int, default=PORT)
        sub.add_argument("--client", type=Path, default=CLIENT)
    return found


def main() -> int:
    args = parser().parse_args()
    if args.command == "add" and args.repo and not all((args.title, args.score, args.agent, args.gate)):
        print("refused: add --repo needs --title, --score, --gate and --agent", file=sys.stderr)
        return 1
    try:
        client = client_modules(args.client)
        run = {"list": list_cards, "show": show_card}.get(args.command) or (add_commit if args.repo else add_task)
        output = run(args, client)
    except (Refused, OSError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(output if output.endswith("\n") or args.command == "show" else f"{output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
