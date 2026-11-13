from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from http import HTTPStatus
from urllib.parse import urlsplit

from .diffs import DIFF_BODY_LIMIT
from .engines import STT_LIMIT
from .exchange import PLAIN_CSP, Exchange
from .resources import RESOURCES, sampled
from .scores import scored

BODY_LIMIT = 1 << 20
UPLOAD_LIMIT = 50 << 20
PAGE_CSP = "sandbox allow-scripts"
SETTINGS_ROUTE = "/api/settings"
TTS_ROUTE = "/api/tts"
WAV_TYPE = "audio/wav"
STT_ROUTE = "/api/stt"
ROUTE = re.compile(r"/reviews/([0-9a-f]{16})/(page|files|approve|reject)")
ITEM = re.compile(r"/api/(asks|decisions)/([0-9a-f]{16})(?:/(allow|deny))?")
ENTRY = re.compile(r"/api/stream/([0-9]{1,12})")
BOARD = re.compile(r"/api/board/([a-z-]{1,32})")
UPLOADS = "/api/uploads"
POSTS = ("/api/asks", UPLOADS, "/api/messages")
STORED = {
    "page": (".html", "text/html; charset=utf-8", PAGE_CSP),
    "files": (".json", "application/json", PLAIN_CSP),
}
DECISIONS = {"approve": "approved", "reject": "rejected"}
INBOX_ROUTE = re.compile(r"/api/inbox/(approve|mark|dismiss)")
UNDO_ROUTE = re.compile(r"/api/inbox/undo/([0-9a-f]{16})")
RULE_ROUTE = re.compile(r"/api/rules/([0-9a-f]{16})/(enable|disable|delete)")
REQUEST_ROUTE = re.compile(r"/api/rule-requests/([0-9a-f]{16})/(sign|accept)")
RUNNER_ROUTE = re.compile(r"/api/runner/([0-9a-f]{16})/(claim|report)")
PROOF_ROUTE = re.compile(r"/api/reviews/([0-9a-f]{16})")
SIGN_ROUTE = "/api/sign"
RULE_SIGN_ROUTE = "/api/rules/sign"
CLEANUP_ROUTE = "/api/cleanup"
CLEANUP_STATE = re.compile(r"/api/cleanup/([0-9a-f]{16})")
OFFICES_ROUTE = "/api/offices"
OFFICE_STATE = re.compile(r"/api/offices/([0-9a-f]{16})")
TASKS_ROUTE = "/api/tasks"
GATES_ROUTE = "/api/gates"
TOKEN_ROUTE = "/api/cleanup/token"
VENDOR_ROUTE = re.compile(r"/vendor/([a-z0-9.-]{1,64})")
SCRIPT_TYPE = "text/javascript; charset=utf-8"
FONT_TYPE = "font/woff2"
VENDOR = {
    "3d-force-graph.min.js": ("3d-force-graph/3d-force-graph.min.js", SCRIPT_TYPE),
    "three.module.js": ("three/three.module.js", SCRIPT_TYPE),
    "three.core.js": ("three/three.core.js", SCRIPT_TYPE),
    "comic-neue.woff2": ("comic-neue/comic-neue-latin-400-normal.woff2", FONT_TYPE),
}
VOICE_ROUTE = "/api/voice"
VOICE_ITEM = re.compile(r"/api/voice/([0-9a-f]{16})(\.wav)?")
MESSAGE_SIGN_ROUTE = "/api/messages/sign"
BOARD_SIGN_ROUTE = "/api/board/sign"
SETTINGS_SIGN_ROUTE = "/api/settings/sign"
CHOICES_ROUTE = "/api/choices"
CHOICES_SIGN_ROUTE = "/api/choices/sign"
DIFF_ROUTE = re.compile(r"/api/diffs/(review|ask)/([0-9a-f]{16})")
WAV_POSTS = (STT_ROUTE, VOICE_ROUTE)
ACTION_POSTS = ("/api/rules", "/api/nl", SETTINGS_ROUTE, TTS_ROUTE, STT_ROUTE, SIGN_ROUTE, RULE_SIGN_ROUTE, CLEANUP_ROUTE, OFFICES_ROUTE, TASKS_ROUTE, VOICE_ROUTE, MESSAGE_SIGN_ROUTE, SETTINGS_SIGN_ROUTE, CHOICES_ROUTE, CHOICES_SIGN_ROUTE, GATES_ROUTE, TOKEN_ROUTE)


class Handler(Exchange):
    def speak(self, body: bytes) -> None:
        headers = {"Content-Security-Policy": PLAIN_CSP}
        hub = self.server.hub
        self.attempt(lambda: hub.speech.synthesize(body, hub.speech_gate.admit), lambda wav: self.send(HTTPStatus.OK, WAV_TYPE, wav, headers))

    def hear(self, body: bytes) -> None:
        self.answer(lambda: self.server.hub.speech.transcribe(body), HTTPStatus.OK)

    def replay_voice(self, note_id: str) -> None:
        headers = {"Content-Security-Policy": PLAIN_CSP}
        self.attempt(lambda: self.server.hub.voice_notes.audio(note_id), lambda wav: self.send(HTTPStatus.OK, WAV_TYPE, wav, headers))

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        hub = self.server.hub
        route = ROUTE.fullmatch(path)
        item = ITEM.fullmatch(path)
        entry = ENTRY.fullmatch(path)
        proof = PROOF_ROUTE.fullmatch(path)
        vendored = VENDOR_ROUTE.fullmatch(path)
        cleanup = CLEANUP_STATE.fullmatch(path)
        office = OFFICE_STATE.fullmatch(path)
        voice = VOICE_ITEM.fullmatch(path)
        diff = DIFF_ROUTE.fullmatch(path)
        if self.host() is None:
            self.send_text(HTTPStatus.FORBIDDEN, "forbidden host")
        elif path == "/":
            self.index()
        elif diff:
            self.answer(lambda: hub.diff_of(diff.group(1), diff.group(2)), HTTPStatus.OK)
        elif vendored and vendored.group(1) in VENDOR:
            self.vendored(*VENDOR[vendored.group(1)])
        elif voice and voice.group(2):
            self.replay_voice(voice.group(1))
        elif voice:
            self.answer(lambda: hub.voice_notes.get(voice.group(1)), HTTPStatus.OK)
        elif cleanup:
            self.answer(lambda: hub.cleanup_state(cleanup.group(1)), HTTPStatus.OK)
        elif office:
            self.answer(lambda: hub.office_state(office.group(1)), HTTPStatus.OK)
        elif proof:
            self.answer(lambda: hub.review_proof(proof.group(1)), HTTPStatus.OK)
        elif path == "/api/state":
            self.answer(lambda: hub.window(self.query()), HTTPStatus.OK)
        elif path == "/api/stream":
            self.answer(lambda: hub.stream(self.query()), HTTPStatus.OK)
        elif path == "/api/events":
            self.answer(lambda: hub.events(self.query()), HTTPStatus.OK)
        elif path == "/api/tree":
            self.answer(hub.repositories, HTTPStatus.OK)
        elif path == "/api/resources":
            self.answer(lambda: sampled(hub.kept / RESOURCES, hub.span(self.query(), time.time())), HTTPStatus.OK)
        elif path == "/api/scores":
            self.answer(lambda: scored(hub.council, hub.scripts.skills, hub.span(self.query(), time.time())), HTTPStatus.OK)
        elif path == "/api/subagents":
            self.answer(lambda: hub.subagents(self.query()), HTTPStatus.OK)
        elif path == "/api/runner/jobs":
            if self.client():
                self.answer(hub.runner_jobs, HTTPStatus.OK)
            else:
                self.send_text(HTTPStatus.FORBIDDEN, "forbidden: the runner calls with the X-Kvb-Orchestrator header and no origin only")
        elif entry:
            self.answer(lambda: hub.entry(int(entry.group(1))), HTTPStatus.OK)
        elif item and item.group(1) == "asks" and item.group(3) is None:
            self.answer(lambda: hub.ask_wait(item.group(2), self.query()), HTTPStatus.OK)
        elif route and route.group(2) in STORED:
            self.stored(route.group(1), route.group(2))
        elif route or item or path == "/mcp" or path in POSTS or path in ACTION_POSTS or BOARD.fullmatch(path) or self.posted(path):
            self.not_allowed()
        else:
            self.send_text(HTTPStatus.NOT_FOUND, "not found")

    def action(self, path: str) -> Callable[[bytes], None] | None:
        hub = self.server.hub
        route = ROUTE.fullmatch(path)
        item = ITEM.fullmatch(path)
        board = BOARD.fullmatch(path)
        if route and route.group(2) in DECISIONS:
            return lambda body: self.answer(lambda: hub.verdict(route.group(1), DECISIONS[route.group(2)], body), HTTPStatus.OK)
        if item and item.group(3):
            return lambda body: self.answer(lambda: hub.settle(item.group(1), item.group(2), item.group(3), body), HTTPStatus.OK)
        if path == UPLOADS:
            return lambda body: self.answer(lambda: hub.upload(self.query(), body), HTTPStatus.CREATED)
        if path == "/api/messages":
            return lambda body: self.answer(lambda: hub.message(body), HTTPStatus.CREATED)
        if path == BOARD_SIGN_ROUTE:
            return lambda body: self.answer(lambda: hub.sign_board(body), HTTPStatus.OK)
        if board:
            return lambda body: self.answer(lambda: hub.board(board.group(1), body), HTTPStatus.OK)
        return self.inbox_action(path)

    def inbox_action(self, path: str) -> Callable[[bytes], None] | None:
        hub = self.server.hub
        inbox = INBOX_ROUTE.fullmatch(path)
        undo = UNDO_ROUTE.fullmatch(path)
        rule = RULE_ROUTE.fullmatch(path)
        request = REQUEST_ROUTE.fullmatch(path)
        if inbox and inbox.group(1) == "approve":
            return lambda body: self.answer(lambda: hub.approve(body), HTTPStatus.ACCEPTED)
        if inbox and inbox.group(1) == "dismiss":
            return lambda body: self.answer(lambda: hub.dismiss(body), HTTPStatus.OK)
        if request and request.group(2) == "sign":
            return lambda _body: self.answer(lambda: hub.sign_request(request.group(1)), HTTPStatus.OK)
        if request:
            return lambda body: self.answer(lambda: hub.accept_request(request.group(1), body), HTTPStatus.CREATED)
        if path == SIGN_ROUTE:
            return lambda body: self.answer(lambda: hub.sign(body), HTTPStatus.OK)
        if path == RULE_SIGN_ROUTE:
            return lambda body: self.answer(lambda: hub.sign_rule(body), HTTPStatus.OK)
        if path == CLEANUP_ROUTE:
            return lambda body: self.answer(lambda: hub.cleanup(body), HTTPStatus.ACCEPTED)
        if path == OFFICES_ROUTE:
            return lambda body: self.answer(lambda: hub.appoint(body), HTTPStatus.ACCEPTED)
        if path == TASKS_ROUTE:
            return lambda body: self.answer(lambda: hub.change_tasks(body), HTTPStatus.ACCEPTED)
        if path == GATES_ROUTE:
            return lambda body: self.answer(lambda: hub.change_gates(body), HTTPStatus.ACCEPTED)
        if path == TOKEN_ROUTE:
            return lambda body: self.answer(lambda: hub.token_row(body), HTTPStatus.CREATED)
        if inbox:
            return lambda body: self.answer(lambda: hub.mark(body), HTTPStatus.OK)
        if undo:
            return lambda _body: self.answer(lambda: hub.undo(undo.group(1)), HTTPStatus.OK)
        if path == "/api/rules":
            return lambda body: self.answer(lambda: hub.add_rule(body), HTTPStatus.CREATED)
        if rule:
            return lambda _body: self.answer(lambda: hub.rule_action(rule.group(1), rule.group(2)), HTTPStatus.OK)
        if path == "/api/nl":
            return lambda body: self.answer(lambda: hub.nl(body), HTTPStatus.OK)
        if path == SETTINGS_ROUTE:
            return lambda body: self.answer(lambda: hub.save_settings(body), HTTPStatus.OK)
        if path == SETTINGS_SIGN_ROUTE:
            return lambda body: self.answer(lambda: hub.sign_settings(body), HTTPStatus.OK)
        if path == TTS_ROUTE:
            return self.speak
        if path == STT_ROUTE:
            return self.hear
        if path == VOICE_ROUTE:
            return lambda body: self.answer(lambda: hub.voice_notes.submit(body), HTTPStatus.ACCEPTED)
        if path == MESSAGE_SIGN_ROUTE:
            return lambda body: self.answer(lambda: hub.sign_message(body), HTTPStatus.OK)
        if path == CHOICES_SIGN_ROUTE:
            return lambda body: self.answer(lambda: hub.sign_choices(body), HTTPStatus.OK)
        if path == CHOICES_ROUTE:
            return lambda body: self.answer(lambda: hub.request_choices(body), HTTPStatus.CREATED)
        return None

    def posted(self, path: str) -> bool:
        return any(pattern.fullmatch(path) for pattern in (INBOX_ROUTE, UNDO_ROUTE, RULE_ROUTE, REQUEST_ROUTE, RUNNER_ROUTE))

    def runner(self, path: str, body: bytes) -> None:
        hub = self.server.hub
        route = RUNNER_ROUTE.fullmatch(path)
        if route.group(2) == "claim":
            self.answer(lambda: hub.claim(route.group(1)), HTTPStatus.OK)
        else:
            self.answer(lambda: hub.report(route.group(1), body), HTTPStatus.OK)

    def receiver(self, path: str, host: str) -> Callable[[bytes], None] | None:
        """Returns:
            What handles the body once every header guard let the request
            pass, or None after a guard answered it.
        """
        if path == "/mcp":
            return self.mcp_receiver(host)
        if path == "/api/asks":
            if self.local(host):
                return lambda body: self.answer(lambda: self.server.hub.ask(body), HTTPStatus.CREATED)
            self.send_text(HTTPStatus.FORBIDDEN, "forbidden: local POST with the X-Kvb-Orchestrator header and no foreign origin only")
            return None
        if RUNNER_ROUTE.fullmatch(path):
            if self.client():
                return lambda body: self.runner(path, body)
            self.send_text(HTTPStatus.FORBIDDEN, "forbidden: the runner calls with the X-Kvb-Orchestrator header and no origin only")
            return None
        action = self.action(path)
        if action is None:
            self.send_text(HTTPStatus.NOT_FOUND, "not found")
        elif not self.guarded(host):
            self.send_text(HTTPStatus.FORBIDDEN, "forbidden: same-origin POST with the X-Kvb-Orchestrator header only")
        elif path in WAV_POSTS and self.headers.get_content_type() != WAV_TYPE:
            self.send_text(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, f"use {WAV_TYPE}")
        else:
            return action
        return None

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        length = self.body_length({UPLOADS: UPLOAD_LIMIT, STT_ROUTE: STT_LIMIT, VOICE_ROUTE: STT_LIMIT, "/mcp": DIFF_BODY_LIMIT, "/api/asks": DIFF_BODY_LIMIT}.get(path, BODY_LIMIT))
        if length is None:
            return
        host = self.host()
        if host is None:
            self.send_text(HTTPStatus.FORBIDDEN, "forbidden host")
            return
        receive = self.receiver(path, host)
        if receive is not None:
            receive(self.rfile.read(length))

    def index(self) -> None:
        nonce = secrets.token_urlsafe(18)
        page, csp = self.server.hub.render(nonce)
        headers = {"Content-Security-Policy": csp, "X-Frame-Options": "DENY"}
        self.send(HTTPStatus.OK, "text/html; charset=utf-8", page.encode("utf-8"), headers)

    def vendored(self, name: str, content_type: str) -> None:
        headers = {"Content-Security-Policy": PLAIN_CSP, "Cache-Control": "private, max-age=86400"}
        self.attempt((self.server.hub.vendor / name).read_bytes, lambda data: self.send(HTTPStatus.OK, content_type, data, headers))

    def stored(self, review_id: str, name: str) -> None:
        suffix, content_type, csp = STORED[name]
        reviews = self.server.hub.reviews
        path = reviews.stored(review_id, suffix)
        if reviews.get(review_id) is None or not path.is_file():
            self.send_text(HTTPStatus.NOT_FOUND, "not found")
            return
        self.attempt(path.read_bytes, lambda data: self.send(HTTPStatus.OK, content_type, data, {"Content-Security-Policy": csp}))

    def mcp_receiver(self, host: str) -> Callable[[bytes], None] | None:
        origins = self.headers.get_all("Origin")
        if origins is not None and origins != [f"http://{host}"]:
            self.send_text(HTTPStatus.FORBIDDEN, "foreign origin")
        elif self.headers.get_content_type() != "application/json":
            self.send_text(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "use application/json")
        else:
            return self.mcp
        return None

    def mcp(self, body: bytes) -> None:
        status, reply = self.server.hub.rpc(body)
        if reply is not None:
            self.send_json(status, reply)
            return
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()
