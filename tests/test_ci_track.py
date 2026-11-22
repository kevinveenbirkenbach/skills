from __future__ import annotations

import importlib.util
import io
import itertools
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACK = REPO_ROOT / "skills" / "kvb-ci-track" / "scripts" / "track.py"
REPO = "owner/core"
ANSIBLE = 'TASK [web-app-a : Wait for health] ***\nfatal: [localhost]: FAILED! => {"msg": "timeout 120"}\n##[error]Process completed with exit code 2.\n'
PLAYWRIGHT = (
    "  ✘  3 [chromium] › roles/web-app-a/playwright/login.spec.js:98:5 › logs in (30.0s)\n"
    "  1) [chromium] › roles/web-app-a/playwright/login.spec.js:98:5 › logs in\n"
    "    Error: expect(locator).toBeVisible() failed\n"
    "##[error]Process completed with exit code 1.\n"
)
RULES = {
    "job_name": ["^roles / "],
    "lines": [
        {"id": "playwright", "match": r"✘ .*\.spec\.js:\d+:\d+", "pick": "first", "context": "^Error:", "side": "after"},
        {"id": "ansible", "match": r"fatal: \[[^]]*\]: FAILED!", "pick": "last", "context": r"^TASK \[", "side": "before"},
    ],
}


def _load():
    spec = importlib.util.spec_from_file_location("track", TRACK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


track = _load()


def job(number: int, name: str, conclusion: str) -> str:
    return json.dumps({"id": number, "name": name, "status": "completed", "conclusion": conclusion})


class FakeGh:
    def __init__(self, answers: dict[str, tuple[int, str, str]]):
        self.answers, self.calls = answers, []

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        self.calls.append(argv)
        key = next((item for item in argv if item.startswith("/repos/")), " ".join(argv[:2]))
        return self.answers[key]

    def logs(self) -> int:
        return sum(any(item.endswith("/logs") for item in argv) for argv in self.calls)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.hints = []

    def hint(self, line: str) -> str | None:
        self.hints.append(line)
        return "hotfix/wait-health (merged)" if "timeout" in line else None

    def add(self, *argv: str) -> str:
        return track.add(self.folder, track.parser().parse_args(["add", *argv]))

    def poll(self, gh: FakeGh, *targets: str) -> tuple[int, list[str], str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = track.poll(self.folder, list(targets), track.Clients(gh, self.hint))
        return code, stdout.getvalue().splitlines(), stderr.getvalue()

    def run_answers(self, status: str, jobs: list[str]) -> dict[str, tuple[int, str, str]]:
        return {
            f"/repos/{REPO}/actions/runs/7": (0, json.dumps({"status": status}), ""),
            f"/repos/{REPO}/actions/runs/7/jobs?per_page=30": (0, "\n".join(jobs), ""),
            f"/repos/{REPO}/actions/jobs/1/logs": (0, ANSIBLE, ""),
            f"/repos/{REPO}/actions/jobs/2/logs": (0, ANSIBLE.replace("120", "121"), ""),
        }


class TestRun(Base):
    def test_matrix_jobs_with_one_failing_line_are_one_cluster_reported_once(self):
        target = self.add("run", REPO, "7")
        jobs = [job(1, "deploy (web-app-a, compose)", "failure"), job(2, "deploy (web-app-a, swarm)", "failure"), job(3, "lint", "success")]
        gh = FakeGh(self.run_answers("in_progress", jobs))
        code, lines, _ = self.poll(gh, target)
        self.assertEqual(code, track.NEW)
        self.assertEqual(len(lines), 1)
        fp, name, label, count, text, hint = lines[0].split("\t")
        self.assertEqual((name, label, count, hint), (target, "deploy", "2", "hotfix/wait-health (merged)"))
        self.assertEqual(text, 'TASK [web-app-a : Wait for health] *** fatal: [localhost]: FAILED! => {"msg": "timeout <n>"}')
        self.assertIn("timeout 120", self.hints[0])
        self.assertEqual((self.poll(gh, target)[:2], gh.logs()), ((0, []), 2))
        gh.answers[f"/repos/{REPO}/actions/runs/7"] = (0, json.dumps({"status": "completed"}), "")
        self.assertEqual(self.poll(gh, target)[0], track.STUCK)
        track.ack(self.folder, fp, "fixed by hotfix/wait-health")
        calls = len(gh.calls)
        self.assertEqual(self.poll(gh, target)[0], track.TERMINAL)
        self.assertEqual(len(gh.calls), calls)

    def test_an_ack_silences_the_cluster_in_the_next_run_and_needs_a_known_fingerprint(self):
        first = self.add("run", REPO, "7")
        gh = FakeGh(self.run_answers("completed", [job(1, "deploy (web-app-a, compose)", "failure")]))
        fp = self.poll(gh, first)[1][0].split("\t")[0]
        with self.assertRaises(ValueError):
            track.ack(self.folder, "0" * 12, "nothing")
        with self.assertRaises(ValueError):
            track.ack(self.folder, fp, " ")
        track.ack(self.folder, fp, "flake, proven transient")
        second = self.add("run", "owner/fork", "7")
        answers = {key.replace(REPO, "owner/fork"): value for key, value in gh.answers.items()}
        self.assertEqual(self.poll(FakeGh(answers), second)[:2], (track.TERMINAL, []))

    def test_cancelled_jobs_are_not_fetched_and_a_gone_log_is_its_own_cluster(self):
        target = self.add("run", REPO, "7")
        answers = self.run_answers("in_progress", [job(1, "build", "cancelled"), job(2, "test", "timed_out")])
        answers[f"/repos/{REPO}/actions/jobs/2/logs"] = (1, "", "gh: Not Found (HTTP 404)")
        gh = FakeGh(answers)
        lines = self.poll(gh, target)[1]
        self.assertEqual(sorted(line.split("\t")[4] for line in lines), ["cancelled", "no log"])
        self.assertEqual(gh.logs(), 1)

    def test_a_gh_failure_is_exit_3_and_retried_on_the_next_poll(self):
        target = self.add("run", REPO, "7")
        answers = self.run_answers("in_progress", [job(1, "deploy", "failure")])
        answers[f"/repos/{REPO}/actions/jobs/1/logs"] = (1, "", "gh: Server Error (HTTP 502)\nmore")
        gh = FakeGh(answers)
        code, lines, stderr = self.poll(gh, target)
        self.assertEqual((code, lines, stderr.strip()), (track.BROKEN, [], f"track: {target}: gh: Server Error (HTTP 502)"))
        answers[f"/repos/{REPO}/actions/jobs/1/logs"] = (0, ANSIBLE, "")
        self.assertEqual(self.poll(gh, target)[0], track.NEW)


class TestPullRequest(Base):
    def test_every_run_of_the_head_counts_and_a_closed_pull_request_is_terminal(self):
        target = self.add("pr", REPO, "42")
        head = "a" * 40
        answers = self.run_answers("completed", [job(1, "deploy (web-app-a, compose)", "failure")])
        answers[f"/repos/{REPO}/pulls/42"] = (0, json.dumps({"state": "open", "head": {"sha": head}}), "")
        answers[f"/repos/{REPO}/actions/runs?head_sha={head}&per_page=100"] = (0, '{"id": 7, "status": "in_progress"}\n', "")
        gh = FakeGh(answers)
        self.assertEqual(self.poll(gh, target)[0], track.NEW)
        answers[f"/repos/{REPO}/pulls/42"] = (0, json.dumps({"state": "closed", "head": {"sha": head}}), "")
        self.assertEqual(self.poll(gh, target)[0], track.STUCK)


class TestRules(Base):
    def test_rules_pick_the_playwright_and_ansible_lines_and_cut_job_names(self):
        rules = dict(RULES)
        self.assertEqual(
            track.failing_line(PLAYWRIGHT, rules),
            "✘  3 [chromium] › roles/web-app-a/playwright/login.spec.js:98:5 › logs in (30.0s) Error: expect(locator).toBeVisible() failed",
        )
        self.assertEqual(track.failing_line(ANSIBLE, rules), 'TASK [web-app-a : Wait for health] *** fatal: [localhost]: FAILED! => {"msg": "timeout 120"}')
        self.assertEqual(track.failing_line("ok\nError: disk full\n", rules), track.CI.failing("ok\nError: disk full\n"))
        self.assertEqual(track.job_label("roles / deploy (web-app-a, compose) (debian)", rules), "deploy")

    def test_a_rules_file_is_checked_when_added(self):
        path = self.folder / "rules.json"
        path.write_text(json.dumps(RULES), encoding="utf-8")
        target = self.add("run", REPO, "7", "--rules", str(path))
        self.assertEqual(track.read(self.folder / f"{target}.json")["rules"], str(path.resolve()))
        for broken in ({"lines": [{"id": "x", "match": "(a+)+", "pick": "last"}]}, {"lines": [{"id": "x", "match": "a", "pick": "any"}]},
                       {"lines": [{"id": "x", "match": "a", "pick": "last", "context": "b"}]}, {"job_name": ["("]}, []):
            with self.subTest(rules=broken):
                path.write_text(json.dumps(broken), encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.add("run", REPO, "8", "--rules", str(path))

    def test_secrets_in_a_failing_line_are_masked_and_paths_kept(self):
        line = "curl https://bot:pa55@host/x token=abc123 ghp_ABCDEFGHIJKLMNOPQRSTUVWX1234 roles/web-app-a2/tasks/main.yml"
        self.assertEqual(track.masked(line), "curl https://<auth>@host/x token=<masked> <token> roles/web-app-a2/tasks/main.yml")

    def test_control_and_zero_width_characters_never_reach_a_cell(self):
        line = "fail\tfake\x1b]0;title\x07 ghp_ABCDEFGHIJKL\u200bMNOPQRSTUVWX1234"
        self.assertEqual(track.masked(line), "fail fake]0;title <token>")
        self.assertEqual(track.report(track.Clients(None, lambda _: None), "run:1", {"fp": "a" * 12, "label": "job\tforged", "text": "x\u200by", "line": None}, 1), "\t".join(["a" * 12, "run:1", "job forged", "1", "xy"]))

    def test_failing_keeps_the_raw_line_that_signature_normalises(self):
        self.assertEqual(track.CI.failing(ANSIBLE), 'TASK [web-app-a : Wait for health] *** fatal: [localhost]: FAILED! => {"msg": "timeout 120"}')
        self.assertEqual(track.CI.signature(ANSIBLE), track.CI.normalise(track.CI.failing(ANSIBLE)))


class TestAlertsAndIssues(Base):
    def test_alerts_carry_rule_type_and_place_and_secret_locations_are_read_once(self):
        target = self.add("alerts", REPO, "--codeql", "--secrets")
        gh = FakeGh({
            f"/repos/{REPO}/code-scanning/alerts?state=open&per_page=30": (0, '{"number": 5, "rule": "py/sql-injection", "path": "app.py", "line": 12}\n', ""),
            f"/repos/{REPO}/secret-scanning/alerts?state=open&per_page=30": (0, '{"number": 9, "type": "github_personal_access_token"}\n', ""),
            f"/repos/{REPO}/secret-scanning/alerts/9/locations": (0, '{"path": "config/.env", "line": 3}\n', ""),
        })
        code, lines, _ = self.poll(gh, target)
        self.assertEqual(code, track.NEW)
        self.assertEqual(sorted(line.split("\t", 2)[2] for line in lines), ["codeql py/sql-injection\t1\tapp.py:12", "secret github_personal_access_token\t1\tconfig/.env:3"])
        self.assertEqual(self.poll(gh, target)[:2], (0, []))
        self.assertEqual(sum(argv[1].endswith("/locations") for argv in gh.calls), 1)
        self.assertEqual(self.hints, [])

    def test_issues_pass_the_labels_and_mask_the_title(self):
        target = self.add("issues", REPO, "--label", "bug", "--label", "ci")
        gh = FakeGh({"issue list": (0, json.dumps([{"number": 12, "title": "Leak token=abc in log"}]), "")})
        code, lines, _ = self.poll(gh, target)
        self.assertEqual((code, lines[0].split("\t")[1:]), (track.NEW, [target, "#12", "1", "Leak token=<masked> in log"]))
        self.assertEqual(gh.calls[0][-4:], ["--label", "bug", "--label", "ci"])
        self.assertTrue(target.endswith("-bug+ci"))


class TestWait(Base):
    def test_wait_returns_on_news_after_repeated_errors_or_at_the_timeout(self):
        target = self.add("run", REPO, "7")
        quiet = FakeGh(self.run_answers("in_progress", []))
        with mock.patch.object(track.time, "monotonic", side_effect=itertools.count()), mock.patch.object(track.time, "sleep") as sleep:
            self.assertEqual(track.wait(self.folder, [target], track.Clients(quiet, self.hint), 1, 3), 0)
        self.assertEqual((len(quiet.calls), sleep.call_count), (6, 2))
        broken = FakeGh({f"/repos/{REPO}/actions/runs/7": (1, "", "HTTP 502")})
        with mock.patch.object(track.time, "sleep"), redirect_stderr(io.StringIO()):
            self.assertEqual(track.wait(self.folder, [target], track.Clients(broken, self.hint), 1, 3600), track.BROKEN)
        self.assertEqual(len(broken.calls), track.ERRORS)
        news = FakeGh(self.run_answers("in_progress", [job(1, "deploy", "failure")]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(track.wait(self.folder, [target], track.Clients(news, self.hint), 1, 3600), track.NEW)


class TestCommandLine(Base):
    def test_add_refuses_malformed_targets_and_unknown_targets_exit_2(self):
        for argv in (["run", "owner", "7"], ["pr", REPO, "x"], ["alerts", REPO]):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                self.add(*argv)
        with mock.patch.dict(os.environ, {"AGENTS_COUNCIL_ROOT": str(self.folder / "council")}), redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(track.main(["poll", "run-owner_core-7"]), track.USAGE)
            self.assertEqual(track.main(["poll", "../acks"]), track.USAGE)
        self.assertIn("unknown target", stderr.getvalue())

    def test_adding_again_keeps_the_clusters_and_polls_an_ended_target_again(self):
        target = self.add("run", REPO, "7")
        self.poll(FakeGh(self.run_answers("completed", [job(1, "deploy", "failure")])), target)
        self.assertEqual(self.add("run", REPO, "7"), target)
        state = track.read(self.folder / f"{target}.json")
        self.assertEqual((len(state["clusters"]), state["terminal"]), (1, False))


if __name__ == "__main__":
    unittest.main()
