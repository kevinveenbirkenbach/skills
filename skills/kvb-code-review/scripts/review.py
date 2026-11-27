#!/usr/bin/env python3
"""Review a change against every standard and lens, remember what was reviewed, and gate its push.

Args:
    target --repo <root>: prints the recommended target: staged, pr <n>,
        branch <default>, range <a>..<b>, or range for the operator to name.
    plan --repo <root> --target <spec> [--harness <name>]...: prints as JSON
        what the memory holds and what still has to run: per lens its
        status, the files a judging lens lacks, and every finding with the
        skeptic roles it still needs.
    run --repo <root> --target <spec> [--task <register task>]
        [--measure <command>]: runs every script lens the memory lacks at
        once, heavy ones through queue.py hold when --task names the
        register task, records their findings and prints per lens its
        start time and outcome as JSON.
    brief --repo <root> --target <spec> --lens <name>: prints the brief of
        a judging lens's subagent for the files the memory lacks.
    record --repo <root> --target <spec> --lens <name> --findings <file>
        [--harness <name>]...: records a judging or harness lens's JSON
        array of findings.
    judge --repo <root> --target <spec> --verdicts <file>: records skeptic
        verdicts, a JSON array of {key, role: lens|blocker, verdict:
        confirmed|refuted, evidence}.
    verdict --repo <root> --target <spec> [--harness <name>]...: prints the
        ranked table, the standards read, every skipped or unreviewed lens,
        the harness lenses and `verdict: clean|blocked|pending`.
    stamp --repo <root> --target <spec> [--harness <name>]...: records that
        verdict for HEAD^{tree} in kvb-review.json of the git common dir.
    status --repo <root>: prints `review: clean|blocked|waived|missing` for
        HEAD^{tree}.
    question --repo <root>: prints the waiver card's question, options and
        recommended option as JSON for the hub's decision_request.
    waive --repo <root> --message <id> --answer <text> --agent <name>:
        records the operator's signed waiver once operator_message of the
        installed hub, on the port of its .env, matches it.
    hook: the pre-bash handler of kvb-org-organize/scripts/hooks.py: refuses
        every push row, `operator.py add ... --check pushed:<dir>` or one
        whose --command runs git push, gipsn or git-sign-push in --dir,
        while that directory's HEAD^{tree} has neither a clean stamp nor a
        waiver the hub verifies again.

Returns:
    Exit 0 on success, a clean verdict, or a clean or waived status; 1 for a
    blocked or pending verdict, or a blocked or missing status; 2 for a
    usage error or a refused stamp, waiver or push row.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review_lenses
import review_memory
import review_scope
import review_stamp

ROLES = ("lens", "blocker")
OK = 0
NOT_CLEAN = 1
REFUSED = 2


def file_state(lens: review_lenses.Lens, version: str, remembered: dict, files: dict[str, str], extra: str) -> dict:
    keys = {path: review_memory.file_key(lens.name, version, path, blob, extra) for path, blob in files.items()}
    stored = {path: remembered[key] for path, key in keys.items() if key in remembered}
    found = [item for entries in stored.values() for item in entries]
    return {"lens": lens, "version": version, "keys": keys, "missing": [path for path in keys if path not in stored], "findings": found, "skipped": None}


def diff_state(lens: review_lenses.Lens, version: str, key: str, stored: dict | None, files: dict[str, str]) -> dict:
    held = stored if stored is not None else {}
    missing = sorted(files) if stored is None else []
    return {"lens": lens, "version": version, "key": key, "missing": missing, "findings": held.get("findings", []), "skipped": held.get("skipped")}


def lens_state(lens: review_lenses.Lens, data: dict, files: dict[str, str], patch: str, context: str) -> dict:
    version = review_lenses.version(lens)
    extra = context if lens.standards else ""
    if lens.scope == "file":
        return file_state(lens, version, data["files"], files, extra)
    key = review_memory.diff_key(lens.name, version, patch, extra)
    return diff_state(lens, version, key, data["diffs"].get(key), files)


def keyed(repo: Path, files: dict[str, str], findings: list[dict]) -> list[dict]:
    out = []
    for entry in findings:
        blob = files.get(entry["path"], "")
        flagged = review_scope.line_text(repo, blob, entry["line"]) if blob else ""
        out.append({**entry, "key": review_memory.finding_key(entry, blob, flagged)})
    return out


def state(repo: Path, spec: str, harness: list[str]) -> dict:
    """Returns:
        The change's scope, files, patch id and standards, per lens what the
        memory holds, every remembered finding with its key, and the
        remembered skeptic verdicts.
    """
    scope = review_scope.resolve(repo, spec)
    files = review_scope.changed(repo, scope)
    patch = review_scope.patch_id(repo, scope)
    names = review_lenses.standards(repo, list(files))
    context = review_lenses.standards_digest(repo, names)
    data = review_memory.sections(review_memory.read(review_scope.common_dir(repo) / review_memory.CACHE))
    lenses = [lens_state(lens, data, files, patch, context) for lens in review_lenses.every(harness)]
    found = keyed(repo, files, [entry for item in lenses for entry in item["findings"]])
    return {"repo": repo, "scope": scope, "files": files, "standards": names, "lenses": lenses, "findings": found, "verdicts": data["verdicts"]}


def item_of(found: dict, name: str) -> dict:
    matches = [item for item in found["lenses"] if item["lens"].name == name]
    if not matches:
        raise ValueError(f"no lens {name}; lenses: {', '.join(item['lens'].name for item in found['lenses'])}")
    return matches[0]


def needed(entry: dict, verdicts: dict) -> list[str]:
    roles = ROLES if entry["severity"] in review_lenses.BLOCKING else ROLES[:1]
    return [role for role in roles if f"{entry['key']}:{role}" not in verdicts]


def cmd_target(args: argparse.Namespace) -> int:
    print(review_scope.detect(args.repo))
    return OK


def cmd_plan(args: argparse.Namespace) -> int:
    found = state(args.repo, args.target, args.harness)
    lenses = [{
        "lens": item["lens"].name, "script": item["lens"].script, "version": item["version"],
        "status": "skipped" if item["skipped"] else "run" if item["missing"] else "cached",
        "missing": item["missing"], **({"reason": item["skipped"]} if item["skipped"] else {}),
    } for item in found["lenses"]]
    skeptics = [{**{key: entry[key] for key in ("key", "lens", "severity", "path", "line", "message")}, "roles": roles}
                for entry in found["findings"] if (roles := needed(entry, found["verdicts"]))]
    print(json.dumps({"target": args.target, "files": len(found["files"]), "standards": found["standards"], "lenses": lenses, "skeptics": skeptics}, indent=1))
    return OK


def due(item: dict, files: dict[str, str]) -> bool:
    return bool(item["lens"].script and files and (item["missing"] or item["skipped"] is not None))


def lens_jobs(found: dict, args: argparse.Namespace) -> tuple[list[tuple[review_lenses.Lens, list[str]]], dict[str, str]]:
    """Returns:
        The argv of every script lens the memory lacks or skipped before,
        heavy ones held in the queue when --task names the register task,
        and per lens that cannot run the reason it is skipped.
    """
    measure = shlex.split(args.measure) if args.measure else []
    jobs, skipped = [], {}
    for item in (entry for entry in found["lenses"] if due(entry, found["files"])):
        lens = item["lens"]
        argv = review_lenses.command(lens, args.repo, found["scope"], sorted(found["files"]), measure)
        if isinstance(argv, str):
            skipped[lens.name] = argv
            continue
        jobs.append((lens, review_lenses.queued(argv, args.task) if lens.heavy and args.task else argv))
    return jobs, skipped


def ran(name: str, result: dict) -> tuple[dict, dict]:
    findings, problem = review_lenses.parsed(name, result)
    if problem:
        return {"skipped": f"failed: {problem}"}, {"status": "failed", "started": result["started"], "findings": 0, "reason": problem}
    return {"findings": findings}, {"status": "ran", "started": result["started"], "findings": len(findings)}


def recorded(data: dict, found: dict, skipped: dict[str, str], results: dict[str, dict]) -> dict:
    report = {}
    for item in found["lenses"]:
        name = item["lens"].name
        if name in skipped:
            data["diffs"][item["key"]], report[name] = {"skipped": skipped[name]}, {"status": "skipped", "reason": skipped[name]}
        elif name in results:
            data["diffs"][item["key"]], report[name] = ran(name, results[name])
        elif item["lens"].script:
            report[name] = {"status": "cached"}
    return report


def cmd_run(args: argparse.Namespace) -> int:
    found = state(args.repo, args.target, [])
    jobs, skipped = lens_jobs(found, args)
    results = review_lenses.run_all(args.repo, jobs)
    with review_memory.cache(review_scope.common_dir(args.repo)) as data:
        report = recorded(review_memory.sections(data), found, skipped, results)
    print(json.dumps(report, indent=1))
    return OK


def cmd_brief(args: argparse.Namespace) -> int:
    found = state(args.repo, args.target, [])
    item = item_of(found, args.lens)
    if item["lens"].script:
        raise ValueError(f"{args.lens} is a script lens: run it with review.py run")
    print(review_lenses.brief(item["lens"], args.repo, found["scope"], item["missing"], found["standards"]))
    return OK


def loaded(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(entry, dict) for entry in data):
        raise ValueError(f"{path} must hold a JSON array of objects")
    return data


def cmd_record(args: argparse.Namespace) -> int:
    found = state(args.repo, args.target, args.harness)
    item = item_of(found, args.lens)
    if item["lens"].script:
        raise ValueError(f"{args.lens} is a script lens: review.py run records it")
    entries = [{**review_lenses.finding(args.lens, entry, str(entry.get("severity", "")).lower(), str(entry.get("rule") or ""), str(entry.get("message") or "")), "evidence": str(entry.get("evidence") or "")}
               for entry in loaded(args.findings)]
    with review_memory.cache(review_scope.common_dir(args.repo)) as data:
        review_memory.sections(data)
        if item["lens"].scope == "file":
            for path in item["missing"]:
                data["files"][item["keys"][path]] = [entry for entry in entries if entry["path"] == path]
        else:
            data["diffs"][item["key"]] = {"findings": entries}
    print(f"recorded {len(entries)} finding(s) of {args.lens}")
    return OK


def cmd_judge(args: argparse.Namespace) -> int:
    entries = loaded(args.verdicts)
    for entry in entries:
        if entry.get("role") not in ROLES or entry.get("verdict") not in (review_stamp.CONFIRMED, review_stamp.REFUTED) or not isinstance(entry.get("key"), str):
            raise ValueError(f"a verdict needs key, role lens|blocker and verdict confirmed|refuted: {entry}")
    with review_memory.cache(review_scope.common_dir(args.repo)) as data:
        review_memory.sections(data)
        for entry in entries:
            data["verdicts"][f"{entry['key']}:{entry['role']}"] = {"verdict": entry["verdict"], "evidence": str(entry.get("evidence") or "")}
    print(f"recorded {len(entries)} verdict(s)")
    return OK


def shown(item: dict) -> str:
    name = item["lens"].name
    status = "skipped" if item["skipped"] else "unreviewed" if item["missing"] else "ran"
    return f"{name} ({review_lenses.CHECKS[name]}) {status}" if name in review_lenses.CHECKS else f"{name} {status}"


def summary(found: dict, harness: list[str]) -> tuple[str, str]:
    unreviewed = [item["lens"].name for item in found["lenses"] if item["missing"]]
    verdict = review_stamp.decide(found["findings"], found["verdicts"], unreviewed)
    lines = [
        review_stamp.table(found["findings"], found["verdicts"]),
        "",
        f"lenses: {', '.join(shown(item) for item in found['lenses'])}",
        f"score block (step 5): {', '.join(review_lenses.SCORE_BLOCK)}",
        f"standards: {', '.join(found['standards']) or 'none'}",
        *(f"skipped: {item['lens'].name}: {item['skipped']}" for item in found["lenses"] if item["skipped"]),
        *(f"unreviewed: {name}" for name in unreviewed),
        f"harness: {', '.join(harness) or 'none'}",
        f"verdict: {verdict}",
    ]
    return verdict, "\n".join(lines)


def cmd_verdict(args: argparse.Namespace) -> int:
    verdict, text = summary(state(args.repo, args.target, args.harness), args.harness)
    print(text)
    return OK if verdict == review_stamp.CLEAN else NOT_CLEAN


def cmd_stamp(args: argparse.Namespace) -> int:
    found = state(args.repo, args.target, args.harness)
    verdict, _ = summary(found, args.harness)
    tree = review_stamp.stamp(args.repo, found["scope"], verdict, {item["lens"].name: item["version"] for item in found["lenses"]})
    print(f"stamped {verdict} for tree {tree}")
    return OK


def cmd_status(args: argparse.Namespace) -> int:
    _, entry = review_stamp.entry_of(args.repo)
    verdict = entry["verdict"] if entry else review_stamp.MISSING
    print(f"review: {verdict}")
    return OK if verdict in (review_stamp.CLEAN, review_stamp.WAIVED) else NOT_CLEAN


def cmd_question(args: argparse.Namespace) -> int:
    options = [
        {"label": review_stamp.KEEP, "description": "The push waits for a clean review."},
        {"label": review_stamp.WAIVE, "description": "This one push goes ahead without a clean review; the hook lets its row through."},
    ]
    print(json.dumps({"question": review_stamp.question(args.repo), "options": options, "recommended": review_stamp.KEEP}, indent=1))
    return OK


def cmd_waive(args: argparse.Namespace) -> int:
    print(f"waived tree {review_stamp.waive(args.repo, args.message, args.answer, args.agent)}")
    return OK


def cmd_hook(_args: argparse.Namespace) -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return OK
    tool_input = event.get("tool_input") if isinstance(event, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    for directory in review_stamp.pushed_dirs(command if isinstance(command, str) else ""):
        reason = review_stamp.refusal(directory)
        if reason is not None:
            print(f"kvb-code-review: {reason}; review {directory} with kvb-code-review or get the operator's signed waiver first", file=sys.stderr)
            return REFUSED
    return OK


def repository(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"{value} is no directory")
    return path


def parser() -> argparse.ArgumentParser:
    main_parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = main_parser.add_subparsers(dest="cmd", required=True)
    for name, func, flags in (
        ("target", cmd_target, ()), ("plan", cmd_plan, ("target", "harness")), ("run", cmd_run, ("target", "task", "measure")),
        ("brief", cmd_brief, ("target", "lens")), ("record", cmd_record, ("target", "lens", "findings", "harness")),
        ("judge", cmd_judge, ("target", "verdicts")), ("verdict", cmd_verdict, ("target", "harness")),
        ("stamp", cmd_stamp, ("target", "harness")), ("status", cmd_status, ()), ("question", cmd_question, ()),
        ("waive", cmd_waive, ("message", "answer", "agent")),
    ):
        command = sub.add_parser(name)
        command.add_argument("--repo", type=repository, required=True)
        for flag in flags:
            if flag == "harness":
                command.add_argument("--harness", action="append", default=[])
            elif flag in ("task", "measure"):
                command.add_argument(f"--{flag}", default="")
            elif flag in ("findings", "verdicts"):
                command.add_argument(f"--{flag}", type=Path, required=True)
            else:
                command.add_argument(f"--{flag}", required=True)
        command.set_defaults(func=func)
    sub.add_parser("hook").set_defaults(func=cmd_hook)
    return main_parser


def main() -> int:
    args = parser().parse_args()
    try:
        return args.func(args)
    except (review_stamp.Refused, review_scope.ScopeError, ValueError, TypeError, OSError) as error:
        print(f"review: {error}", file=sys.stderr)
        return REFUSED


if __name__ == "__main__":
    sys.exit(main())
