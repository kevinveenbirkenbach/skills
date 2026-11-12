from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import Missing, ToolError
from .fields import decode, expect
from .records import read_json, stamp
from .register import OPERATOR
from .skill_scripts import OPERATOR_SCRIPT
from .tree import offered

ITEM_KEYS = ("kind", "repository", "branch", "worktree", "tip")
JOB_KEYS = ("repository", "branch", "worktree", "tip")
JOB_VERSION = 1
ITEM_LIMIT = 100
RESULTS_SHOWN = 20
TOKEN_ROW = "pkgmgr-github-token"
TOKEN_COMMAND = "env secret-tool store --label=pkgmgr-github service pkgmgr:github username 'github.com|-' </dev/tty"
TOKEN_REASON = "Store the GitHub token in the Secret Service under the key pkgmgr reads; Clean all merged then also deletes remote and squash-merged branches."
TOKEN_ADDER = "Operator"


@dataclass(frozen=True)
class Spool:
    """Args:
        root: the host-mounted directory; the hub writes signed jobs into
            jobs/ by rename, the host runner writes each result into
            results/<id>.json and removes the job.
    """

    root: Path

    @property
    def jobs(self) -> Path:
        return self.root / "jobs"

    @property
    def results(self) -> Path:
        return self.root / "results"

    def ready(self) -> Spool:
        for folder in (self.root, self.jobs, self.results):
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self

    def put(self, job_id: str, job: dict) -> None:
        # written beside jobs/ and renamed in: the path unit wakes on a non-empty jobs/, never on a half-written file
        with tempfile.NamedTemporaryFile("w", dir=self.root, prefix=f".{job_id}-", delete=False, encoding="utf-8") as handle:
            json.dump(job, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, self.jobs / f"{job_id}.json")


def cleanup_request(raw: object) -> bool:
    return isinstance(raw, list) and bool(raw) and all(isinstance(entry, dict) and entry.get("kind") == "cleanup" for entry in raw)


class Cleaning:
    def deletable(self, raw: object) -> list[dict]:
        """Args:
            raw: the items the page chose, each {"kind": "cleanup",
                "repository", "branch", "worktree", "tip"} as /api/tree
                offered it.

        Returns:
            The signed items, each still a merged-clean branch without a gc
            skip reason at the same tip in the current tree file; without
            the GitHub token (delete_ready false) each also token-free.
        """
        if not isinstance(raw, list) or not 1 <= len(raw) <= ITEM_LIMIT:
            raise ToolError(f"items must be a list of 1 to {ITEM_LIMIT} objects")
        scan = self.tree.get()
        ready = scan.get("delete_ready") is True
        if scan.get("error"):
            raise ToolError(f"delete blocked: {scan['error']}")
        known = offered(scan, ready)
        locked = [] if ready else offered(scan, True)
        chosen = []
        for entry in raw:
            if not isinstance(entry, dict):
                raise ToolError("every item must be an object with kind, repository, branch, worktree and tip")
            expect(entry, ITEM_KEYS)
            if entry in locked and entry not in known:
                raise ToolError(f"delete blocked: {scan.get('delete_reason') or 'delete_ready is false'}")
            if entry not in known:
                raise ToolError(f"{entry.get('branch')!s:.200} in {entry.get('repository')!s:.200} is no merged-clean branch without skip reason at that tip in the tree file")
            if entry in chosen:
                raise ToolError("items must be distinct")
            chosen.append(entry)
        return chosen

    def cleanup(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("items", "proof"))
        items = self.deletable(payload["items"])
        proof = self.covered(payload["proof"], items, time.time())
        job_id = secrets.token_hex(8)
        job = {"v": JOB_VERSION, "id": job_id, "created": stamp(), "items": [{key: item[key] for key in JOB_KEYS} for item in items], "proof": proof}
        self.spool.put(job_id, job)
        names = ", ".join(item["branch"] for item in items)
        self.log.add({"kind": "run", "title": f"Delete signed: {names}"[:200], "text": "\n".join(f"{item['repository']} {item['branch']} @ {item['tip'][:12]}" for item in items), "ref": {"cleanup": job_id, "status": "queued"}})
        return {"id": job_id, "status": "queued", "items": job["items"]}

    def token_row(self, body: bytes) -> dict:
        """Returns:
            The operator row that stores the GitHub token in the Secret
            Service under pkgmgr's key, added or refreshed through
            operator.py; it holds no secret, the operator types the token
            when running it.
        """
        expect(decode(body), ())
        done = self.scripts.run(OPERATOR_SCRIPT, ["add", TOKEN_ROW, "--dir", "/", "--command", TOKEN_COMMAND, "--reason", TOKEN_REASON, "--check", "manual", "--session", TOKEN_ADDER])
        if done["code"] != 0:
            raise ToolError(f"operator.py add failed ({done['code']}): {done['stderr'].strip()[-500:]}")
        return {"task": f"{OPERATOR}{TOKEN_ROW}", "status": "queued"}

    def cleanup_state(self, job_id: str) -> dict:
        result = read_json(self.spool.results / f"{job_id}.json")
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            return {**result, "id": job_id, "status": "done"}
        if (self.spool.jobs / f"{job_id}.json").is_file():
            return {"id": job_id, "status": "queued", "items": []}
        raise Missing(job_id)

    def cleanup_results(self) -> list[dict]:
        try:
            paths = sorted(self.spool.results.glob("*.json"), key=lambda path: path.stat().st_mtime)[-RESULTS_SHOWN:]
        except OSError:
            return []
        found = [read_json(path) for path in paths]
        return [result for result in found if isinstance(result, dict) and isinstance(result.get("items"), list)]
