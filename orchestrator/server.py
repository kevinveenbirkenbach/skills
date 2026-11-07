#!/usr/bin/env python3
"""Args:
    --bind: address the server listens on.
    --listen-port: port the server listens on.
    --public-port: port browsers and agents reach the hub on; the Host and
        Origin headers must name it.
    --council: directory holding rasci.json, news.jsonl, queue-history.jsonl,
        night.json, radio-silence.json and the claims under cluster/*/ and
        work/*/; a missing file leaves its part of the state empty. The board
        actions change it through the skill scripts.
    --pages: directory every review page must lie in.
    --state: writable directory for reviews.json, asks.json, decisions.json,
        messages.json, rules.json, jobs.json, marks.json, settings.json,
        log.jsonl, the page copies and uploads/<id>/<name>.
    --host-state: the state directory's path on the host, named in the radio
        rows that carry an upload.
    --skills: installed skills directory holding the kvb-org-radio,
        kvb-org-rasci and kvb-org-sunset scripts.
    --transcripts: directory the Claude Code transcripts (*.jsonl) lie under.
    --templates: directory holding index.html.j2 and the *.js modules it
        includes.
    --tree-file: the JSON file `pkgmgr branch tree --output` writes, mounted
        read-only; read again whenever it changes.
    --timers: directory holding the systemd user units (*.timer).
    --llm-url: base URL of an OpenAI-compatible chat endpoint; empty turns the
        natural-language command line off.
    --llm-model: model name sent to that endpoint; empty turns it off.
    --llm-key-file: file holding the endpoint's bearer key; empty file or
        unreadable means no key.
    --piper: the Piper executable, run as a separate process; missing turns
        speech output off.
    --voices: directory holding the Piper voices as <model>.onnx with
        <model>.onnx.json; every speaker of a model is a voice <model>:<id>.
    --operator-voice: the voice of the operator and the hub; it must be one of
        the installed voices when any is installed.
    --whisper: the whisper.cpp command line executable; missing turns speech
        input off.
    --whisper-model: the ggml model whisper.cpp loads.
    --scratch: writable directory the engines use as HOME and TMPDIR.
    --approvers: the pinned passkeys, mounted read-only; the hub only lists
        their ids and algorithms for the page and never verifies or pins.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from kvb_orchestrator import NAME
from kvb_orchestrator.engines import Engines
from kvb_orchestrator.errors import ToolError
from kvb_orchestrator.exchange import HubServer
from kvb_orchestrator.handler import Handler
from kvb_orchestrator.hub import Places, open_hub
from kvb_orchestrator.language import Model, read_key
from kvb_orchestrator.skill_scripts import Scripts


def main() -> int:
    parser = argparse.ArgumentParser(prog=NAME)
    parser.add_argument("--bind", required=True)
    for name in ("--listen-port", "--public-port"):
        parser.add_argument(name, type=int, required=True)
    paths = ("--council", "--pages", "--state", "--host-state", "--skills", "--transcripts", "--templates", "--tree-file", "--timers", "--llm-key-file", "--approvers")
    for name in (*paths, "--piper", "--voices", "--whisper", "--whisper-model", "--scratch"):
        parser.add_argument(name, type=Path, required=True)
    for name in ("--llm-url", "--llm-model", "--operator-voice"):
        parser.add_argument(name, required=True)
    args = parser.parse_args()
    try:
        hub = open_hub(
            council=args.council,
            pages=args.pages,
            public_port=args.public_port,
            state=args.state,
            host_state=args.host_state,
            transcripts=args.transcripts,
            scripts=Scripts(skills=args.skills, council=args.council, home=args.state),
            templates=args.templates,
            places=Places(tree_file=args.tree_file, timers=args.timers),
            model=Model(url=args.llm_url.strip(), model=args.llm_model.strip(), key=read_key(args.llm_key_file)),
            engines=Engines(piper=args.piper, voices=args.voices, operator_voice=args.operator_voice, whisper=args.whisper, whisper_model=args.whisper_model, scratch=args.scratch),
            approvers=args.approvers,
        )
    except ToolError as error:
        parser.error(str(error))
    server = HubServer((args.bind, args.listen_port), Handler)
    server.hub = hub
    print(f"{NAME}: listening on {args.bind}:{args.listen_port}, public port {args.public_port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
