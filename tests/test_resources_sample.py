from __future__ import annotations

import fcntl
import functools
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hub_support
import resources as sampler

SCRIPT = hub_support.HUB / "client" / "resources.py"
UNITS = hub_support.HUB / "systemd"
NOW = 1_800_000_000
DAY = 86400
MIB = 1 << 20
DF = """Filesystem     1024-blocks      Used Available Capacity Mounted on
/dev/nvme0n1p2   976762584 512000000 460000000      53% /
devtmpfs           8000000         0   8000000       0% /dev
tmpfs              8000000      1000   7999000       1% /dev/shm
/dev/nvme0n1p2   976762584 512000000 460000000      53% /home
/dev/nvme0n1p1      523248     12000    511248       3% /boot/efi
/dev/loop3           65536     65536         0     100% /snap/core/1
/dev/sda1       1953514584 100000000 1853514584       6% /mnt/Backup Disk
overlay          976762584 512000000 460000000      53% /var/lib/docker/overlay2/x/merged
"""
DISKS = [
    {"mount": "/", "used": 512000000 * 1024, "total": (512000000 + 460000000) * 1024},
    {"mount": "/boot/efi", "used": 12000 * 1024, "total": (12000 + 511248) * 1024},
    {"mount": "/mnt/Backup Disk", "used": 100000000 * 1024, "total": (100000000 + 1853514584) * 1024},
]
MEMINFO = """MemTotal:       32000000 kB
MemFree:         2000000 kB
MemAvailable:   24000000 kB
Buffers:          500000 kB
SwapTotal:       8000000 kB
SwapFree:        6000000 kB
HugePages_Total:       0
"""
STAT_BEFORE = "cpu  1000 0 500 8000 500 0 0 0 0 0\ncpu0 500 0 250 4000 250 0 0 0 0 0\n"
STAT_AFTER = "cpu  1600 0 700 8400 600 0 0 0 0 0\ncpu0 800 0 350 4200 300 0 0 0 0 0\n"
STAT_LATER = "cpu  2000 0 900 8600 700 0 0 0 0 0\n"
LOADAVG = "1.25 0.80 0.50 2/1234 56789\n"
NVIDIA_SMI = "00000000:01:00.0, 37, 2048, 8188\n00000000:03:00.0, [N/A], [N/A], 4096\n"
AWAKE, ASLEEP = "0000:01:00.0", "0000:02:00.0"
STUB = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
with Path(os.environ["STUB_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]) + "\\n")
sys.stdout.write(os.environ["STUB_" + Path(sys.argv[0]).name.replace("-", "_").upper()])
"""
QUEUE_STUB = """import json, os, sys
from pathlib import Path
with Path(os.environ["STUB_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:], os.environ["AGENTS_COUNCIL_ROOT"]]) + "\\n")
sys.stdout.write(os.environ["STUB_QUEUE"])
"""
REASON = "escalated post: quality-high runs only beside test-nostack, but test runs"
QUEUE_ROWS = [
    {"position": None, "id": "test-1001", "status": "active", "kind": "test", "task": "t", "waited_s": 30, "eta_s": None, "reason": "suspect hung (95 min); granted beside deploy-1000", "trace": []},
    {"position": None, "id": "deploy-1000", "status": "active", "kind": "deploy", "task": "t", "waited_s": 0, "eta_s": 600, "reason": "-", "trace": []},
    {"position": 1, "id": "quality-high-1002", "status": "waiting", "kind": "quality-high", "task": "t", "waited_s": 2880, "eta_s": None, "reason": REASON, "trace": ["step"]},
    {"position": 2, "id": "build-1004", "status": "waiting", "kind": "build", "task": "t", "waited_s": 60, "eta_s": None, "reason": "waits in line behind quality-high-1002", "trace": []},
]
HEAD = {"id": "quality-high-1002", "kind": "quality-high", "waited_s": 2880, "reason": REASON}


def device(root: Path, address: str, vendor: str, kind: str, status: str | None) -> None:
    folder = root / "bus" / "pci" / "devices" / address
    (folder / "power").mkdir(parents=True)
    (folder / "vendor").write_text(f"{vendor}\n", encoding="utf-8")
    (folder / "class").write_text(f"{kind}\n", encoding="utf-8")
    if status is not None:
        (folder / "power" / "runtime_status").write_text(f"{status}\n", encoding="utf-8")


def host_sys(root: Path) -> Path:
    device(root, AWAKE, "0x10de", "0x030000", "active")
    device(root, "0000:01:00.1", "0x10de", "0x040300", "active")
    device(root, ASLEEP, "0x10de", "0x030200", "suspended")
    device(root, "0000:00:02.0", "0x8086", "0x030000", "active")
    return root


NO_PRESSURE = {"psi_some": None, "psi_full": None, "swap_out_mb_min": None}


def row(t: int, cpu: float, used: int, waiting: int, gpu: dict) -> dict:
    return {"t": t, "disks": [{"mount": "/", "used": used, "total": 1000}], "cpu": cpu, "ram": cpu / 2, "swap": 0.0, "load": cpu / 10, "gpus": [gpu], "queue": {"waiting": waiting, "active": 1}}


class TestParsing(unittest.TestCase):
    def test_df_keeps_each_local_block_device_once_with_its_first_mount_in_bytes(self):
        self.assertEqual(sampler.parse_df(DF), DISKS)
        self.assertEqual(sampler.parse_df(""), [])

    def test_meminfo_gives_ram_and_swap_in_percent_and_no_swap_as_zero(self):
        self.assertEqual(sampler.memory(sampler.parse_meminfo(MEMINFO)), (25.0, 25.0))
        without = MEMINFO.replace("SwapTotal:       8000000", "SwapTotal:             0").replace("SwapFree:        6000000", "SwapFree:              0")
        self.assertEqual(sampler.memory(sampler.parse_meminfo(without)), (25.0, 0.0))
        self.assertEqual(sampler.memory({}), (None, None))

    def test_cpu_percent_is_the_busy_share_of_the_ticks_between_two_reads(self):
        before, after = sampler.cpu_ticks(STAT_BEFORE), sampler.cpu_ticks(STAT_AFTER)
        self.assertEqual((before, after), ((8500, 10000), (9000, 11300)))
        self.assertEqual(sampler.cpu_percent(before, after), 61.5)
        self.assertIsNone(sampler.cpu_percent(after, after))
        self.assertIsNone(sampler.cpu_ticks("intr 1 2 3\n"))

    def test_loadavg_is_the_one_minute_load(self):
        self.assertEqual(sampler.parse_loadavg(LOADAVG), 1.25)
        self.assertIsNone(sampler.parse_loadavg(""))

    def test_nvidia_smi_csv_gives_util_and_vram_in_bytes_per_pci_address(self):
        self.assertEqual(sampler.parse_nvidia(NVIDIA_SMI), {
            AWAKE: {"util": 37.0, "vram_used": 2048 * MIB, "vram_total": 8188 * MIB},
            "0000:03:00.0": {"util": None, "vram_used": None, "vram_total": 4096 * MIB},
        })

    def test_the_queue_counts_waiting_and_active_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            council = Path(tmp)
            self.assertEqual(sampler.queue(council), {"waiting": 0, "active": 0})
            entries = [{"status": status, "enqueued": NOW} for status in ("waiting", "waiting", "active", "done")] + [{"status": "active"}, "junk"]
            (council / "queue.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
            self.assertEqual(sampler.queue(council), {"waiting": 2, "active": 1})

    def test_the_queue_counts_only_live_entries_as_the_hub_settles_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            council = Path(tmp)
            (council / "holds").mkdir()
            handles = [(council / "holds" / f"7-{n}.lock").open("w", encoding="utf-8") for n in (1, 2, 3)]
            for handle in handles:
                self.addCleanup(handle.close)
                fcntl.flock(handle, fcntl.LOCK_EX)
            entries = [
                {"id": "test-1", "status": "waiting", "lock": "7-1", "enqueued": NOW},
                {"id": "test-2", "status": "active", "lock": "7-2", "enqueued": NOW},
                {"id": "quality-high-3", "status": "active", "lock": "7-3", "enqueued": NOW},
                {"id": "test-4", "status": "waiting", "lock": "7-4", "enqueued": NOW},
                {"id": "test-5", "status": "active", "lock": "7-5", "enqueued": NOW},
            ]
            (council / "queue.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
            (council / "queue-history.jsonl").write_text(json.dumps({"id": "quality-high-3-1794514233361361126", "start": NOW + 10, "end": NOW + 20, "exit": 2}) + "\n", encoding="utf-8")
            self.assertEqual(sampler.queue(council), {"waiting": 1, "active": 1})


class TestQueueView(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def answer(self, output: str | None):
        def run(argv: list[str]) -> str | None:
            self.calls.append(argv)
            return output

        return run

    def test_the_head_is_the_first_waiting_row_and_hung_the_active_rows_queue_py_suspects(self):
        found = sampler.queue_view(Path("/council"), Path("/skills/kvb-org-queue/scripts/queue.py"), self.answer(json.dumps(QUEUE_ROWS, indent=1)))
        self.assertEqual(found, {"head": HEAD, "hung": ["test-1001"]})
        self.assertEqual(self.calls, [["env", "AGENTS_COUNCIL_ROOT=/council", sys.executable, "-I", "-B", "/skills/kvb-org-queue/scripts/queue.py", "list", "--json"]])

    def test_a_stamped_reason_still_says_suspect_hung_and_long_texts_are_cut(self):
        rows = [
            {"id": "test-7", "status": "active", "reason": "queue code abc, the host runs def: suspect hung (12 min)"},
            {"id": "test-8", "status": "active", "reason": "granted; not suspect hung yet"},
            {"id": "x" * 100, "status": "waiting", "kind": "k" * 100, "waited_s": 700.5, "reason": "r" * 1000},
        ]
        found = sampler.queue_view(Path("/council"), Path("/queue.py"), self.answer(json.dumps(rows)))
        self.assertEqual(found, {"head": {"id": "x" * sampler.ID_TEXT, "kind": "k" * sampler.ID_TEXT, "waited_s": 700.5, "reason": "r" * sampler.REASON_TEXT}, "hung": ["test-7"]})

    def test_a_head_without_an_id_or_a_wait_is_no_head_and_a_quiet_queue_adds_nothing(self):
        for rows in ([{"status": "waiting", "waited_s": 900}, {"id": "next", "status": "waiting", "waited_s": 900}], [{"id": "w", "status": "waiting", "waited_s": True}], [QUEUE_ROWS[1]], []):
            with self.subTest(rows=rows):
                self.assertEqual(sampler.queue_view(Path("/council"), Path("/queue.py"), self.answer(json.dumps(rows))), {})

    def test_a_failing_or_silent_queue_py_leaves_the_counts_alone(self):
        for output in (None, "", "Traceback (most recent call last):", '{"entries": []}', "[1, 2"):
            with self.subTest(output=output):
                self.assertEqual(sampler.queue_view(Path("/council"), Path("/queue.py"), self.answer(output)), {})
        with tempfile.TemporaryDirectory() as tmp:
            council, state = Path(tmp), Path(tmp) / "state"
            state.mkdir()
            (council / "queue.json").write_text(json.dumps({"entries": [{"status": "waiting", "enqueued": NOW}]}), encoding="utf-8")
            self.calls.clear()
            silent = self.answer(None)
            found = sampler.sample(council, council / "sys", functools.partial(sampler.queue_state, council, council / "missing.py", silent), silent, lambda _argv: (None, ""), state)
            self.assertEqual(found["queue"], {"waiting": 1, "active": 0})
            self.assertEqual([argv[0] for argv in self.calls], ["df", "env"])

    def test_the_bucket_mean_keeps_the_last_head_and_every_hung_id_once(self):
        asleep = {"name": ASLEEP, "asleep": True}
        first = {**HEAD, "waited_s": 600, "reason": "quality-high runs only beside test-nostack, but test runs"}
        last = {**HEAD, "waited_s": 660, "reason": "RAM 56 % used + 37 % still to come reach the limit 85 %"}
        rows = [
            row(NOW + 60, 1.0, 1, 1, asleep) | {"queue": {"waiting": 1, "active": 1, "head": first, "hung": ["test-1001"]}},
            row(NOW + 120, 1.0, 1, 1, asleep) | {"queue": {"waiting": 1, "active": 1, "head": last, "hung": ["deploy-1003", "test-1001"]}},
            row(NOW + 180, 1.0, 1, 0, asleep),
        ]
        self.assertEqual(sampler.mean_row(NOW, sampler.BUCKET, rows)["queue"], {"waiting": 0.67, "active": 1.0, "head": last, "hung": ["test-1001", "deploy-1003"]})
        day = sampler.mean_row(NOW - NOW % DAY, DAY, [sampler.mean_row(NOW, sampler.BUCKET, rows), row(NOW + sampler.BUCKET, 1.0, 1, 0, asleep)])
        self.assertEqual((day["queue"]["head"], day["queue"]["hung"]), (last, ["test-1001", "deploy-1003"]))
        self.assertEqual(sampler.queue_mean(rows[2:]), {"waiting": 0.0, "active": 1.0})


class TestCpu(unittest.TestCase):
    def test_cpu_is_the_busy_share_since_the_ticks_the_run_before_kept_and_the_sampler_never_sleeps(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, state = Path(tmp) / "proc", Path(tmp) / "state"
            proc.mkdir()
            state.mkdir()
            (proc / "stat").write_text(STAT_BEFORE, encoding="utf-8")
            with mock.patch.object(sampler.time, "sleep", side_effect=AssertionError("slept")), mock.patch.object(sampler.time, "time", return_value=NOW - 60):
                self.assertIsNone(sampler.sample(proc, Path(tmp) / "sys", functools.partial(sampler.queue_state, Path(tmp), Path(tmp) / "queue.py", lambda _argv: None), lambda _argv: None, lambda _argv: (None, ""), state)["cpu"])
            (proc / "stat").write_text(STAT_AFTER, encoding="utf-8")
            self.assertEqual(sampler.cpu_since(proc, state, NOW), 61.5)
            (proc / "stat").write_text(STAT_LATER, encoding="utf-8")
            self.assertIsNone(sampler.cpu_since(proc, state, NOW + sampler.BUCKET + 1))
            self.assertEqual(json.loads((state / "cpu.json").read_text(encoding="utf-8")), [NOW + sampler.BUCKET + 1, 9300, 12200])


class TestPressure(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.proc, self.state = Path(tmp.name) / "proc", Path(tmp.name) / "state"
        (self.proc / "pressure").mkdir(parents=True)
        self.state.mkdir()

    def vmstat(self, pages: int) -> None:
        (self.proc / "vmstat").write_text(f"pgpgin 5\npswpin 3\npswpout {pages}\n", encoding="utf-8")

    def test_psi_gives_some_and_full_avg10_and_none_without_pressure(self):
        text = "some avg10=12.50 avg60=1.00 avg300=0.50 total=1\nfull avg10=6.25 avg60=0.80 avg300=0.10 total=1\n"
        self.assertEqual((sampler.psi_avg10(text, "some"), sampler.psi_avg10(text, "full")), (12.5, 6.25))
        self.assertEqual((sampler.psi_avg10("", "some"), sampler.psi_avg10(text.splitlines()[0], "full")), (None, None))
        self.assertIsNone(sampler.swapped_pages("pgpgin 5\n"))

    def test_swap_out_is_none_first_then_mb_per_minute_and_none_after_a_reset_or_a_gap(self):
        with mock.patch.object(sampler, "PAGE_BYTES", 4096):
            self.assertIsNone(sampler.swap_out_since(self.proc, self.state, NOW))
            self.assertFalse((self.state / "swap.json").exists())
            self.vmstat(1000)
            self.assertIsNone(sampler.swap_out_since(self.proc, self.state, NOW))
            self.vmstat(1000 + 1_400_000_000 // 4096)
            self.assertEqual(sampler.swap_out_since(self.proc, self.state, NOW + 60), 1400.0)
            self.vmstat(10)
            self.assertIsNone(sampler.swap_out_since(self.proc, self.state, NOW + 120))
            self.assertEqual(json.loads((self.state / "swap.json").read_text(encoding="utf-8")), [NOW + 120, 10])
            self.assertIsNone(sampler.swap_out_since(self.proc, self.state, NOW + 120))
            self.assertIsNone(sampler.swap_out_since(self.proc, self.state, NOW + 120 + sampler.BUCKET + 1))

    def test_a_sample_row_adds_the_pressure_keys_and_keeps_every_other_key(self):
        (self.proc / "pressure" / "memory").write_text("some avg10=3.00 avg60=0 avg300=0 total=1\n", encoding="utf-8")
        found = sampler.sample(self.proc, self.proc / "sys", functools.partial(sampler.queue_state, self.proc, self.proc / "queue.py", lambda _argv: None), lambda _argv: None, lambda _argv: (None, ""), self.state)
        self.assertEqual(sorted(found), ["cpu", "disks", "gpus", "load", "psi_full", "psi_some", "queue", "ram", "swap", "swap_out_mb_min", "t"])
        self.assertEqual((found["psi_some"], found["psi_full"], found["swap_out_mb_min"]), (3.0, None, None))

    def test_the_fifteen_minute_mean_keeps_the_pressure_keys(self):
        asleep = {"name": ASLEEP, "asleep": True}
        rows = [
            row(NOW + 60, 1.0, 1, 0, asleep) | {"psi_some": 2.0, "psi_full": 1.004, "swap_out_mb_min": 100.0},
            row(NOW + 120, 1.0, 1, 0, asleep) | {"psi_some": 4.5, "psi_full": None, "swap_out_mb_min": 301.0},
        ]
        mean = sampler.mean_row(NOW, sampler.BUCKET, rows)
        self.assertEqual((mean["psi_some"], mean["psi_full"], mean["swap_out_mb_min"]), (3.25, 1.0, 200.5))


class TestGpus(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.calls = []

    def run_smi(self, argv: list[str]) -> tuple[str | None, str]:
        self.calls.append(argv)
        return NVIDIA_SMI, ""

    def test_an_asleep_gpu_is_recorded_asleep_and_nvidia_smi_queries_only_the_awake_one(self):
        found = sampler.gpus(host_sys(self.root), self.run_smi)
        self.assertEqual(found, [{"name": AWAKE, "util": 37.0, "vram_used": 2048 * MIB, "vram_total": 8188 * MIB}, {"name": ASLEEP, "asleep": True}])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], "nvidia-smi")
        self.assertIn(f"--id={AWAKE}", self.calls[0])
        self.assertNotIn(ASLEEP, " ".join(self.calls[0]))

    def test_nvidia_smi_never_runs_while_every_nvidia_gpu_sleeps_or_lacks_a_runtime_status(self):
        device(self.root, ASLEEP, "0x10de", "0x030000", "suspended")
        device(self.root, "0000:04:00.0", "0x10de", "0x030000", None)
        self.assertEqual(sampler.gpus(self.root, self.run_smi), [{"name": ASLEEP, "asleep": True}, {"name": "0000:04:00.0", "asleep": True}])
        self.assertEqual(self.calls, [])

    def test_an_awake_gpu_nvidia_smi_gives_no_reading_for_is_recorded_unknown(self):
        unknown = {"name": AWAKE, "util": None, "vram_used": None, "vram_total": None}
        self.assertEqual(sampler.gpus(host_sys(self.root), lambda argv: (None, "")), [unknown, {"name": ASLEEP, "asleep": True}])
        self.assertEqual(sampler.gpus(self.root, lambda argv: (NVIDIA_SMI.splitlines()[1], "")), [unknown, {"name": ASLEEP, "asleep": True}])
        self.assertEqual(sampler.mean_row(NOW, sampler.BUCKET, [row(NOW + 60, 1.0, 1, 0, unknown), row(NOW + 120, 1.0, 1, 0, unknown)])["gpus"], [unknown])

    def test_a_failed_nvidia_smi_read_keeps_its_first_error_line_in_the_sample_and_the_mean(self):
        mismatch = "Failed to initialize NVML: Driver/library version mismatch"
        failed = {"name": AWAKE, "util": None, "vram_used": None, "vram_total": None, "error": mismatch}
        self.assertEqual(sampler.gpus(host_sys(self.root), lambda argv: (None, mismatch)), [failed, {"name": ASLEEP, "asleep": True}])
        rows = [row(NOW + 60, 1.0, 1, 0, failed), row(NOW + 120, 1.0, 1, 0, {**failed, "error": "NVIDIA-SMI has failed"})]
        self.assertEqual(sampler.mean_row(NOW, sampler.BUCKET, rows)["gpus"], [{**failed, "error": "NVIDIA-SMI has failed"}])
        read = {"name": AWAKE, "util": 40.0, "vram_used": 10, "vram_total": 100}
        self.assertEqual(sampler.mean_row(NOW, sampler.BUCKET, [row(NOW + 60, 1.0, 1, 0, failed), row(NOW + 120, 1.0, 1, 0, read)])["gpus"], [read])

    def test_attempt_names_the_first_stderr_line_else_the_first_stdout_line_of_a_failed_command(self):
        script = "import sys; print(); print('  Failed to initialize NVML: Driver/library version mismatch  '); print('NVML library version: 620.70', file=sys.stderr); sys.exit(9)"
        self.assertEqual(sampler.attempt([sys.executable, "-c", script]), (None, "NVML library version: 620.70"))
        quiet = "print('\\n\\nFailed to initialize NVML: Driver/library version mismatch'); raise SystemExit(18)"
        self.assertEqual(sampler.attempt([sys.executable, "-c", quiet]), (None, "Failed to initialize NVML: Driver/library version mismatch"))
        self.assertEqual(sampler.attempt([sys.executable, "-c", "raise SystemExit(3)"]), (None, f"{sys.executable} exited 3"))
        self.assertEqual(sampler.attempt([sys.executable, "-c", "print('x' * 500); raise SystemExit(1)"]), (None, "x" * sampler.ERROR_TEXT))
        self.assertEqual(sampler.attempt([sys.executable, "-c", "print('ok')"]), ("ok\n", ""))
        self.assertEqual(sampler.attempt(["kvb-no-such-tool-091"]), (None, "kvb-no-such-tool-091 not found"))
        self.assertIsNone(sampler.command([sys.executable, "-c", "raise SystemExit(1)"]))

    def test_no_nvidia_gpu_means_no_gpu_row_and_no_call(self):
        device(self.root, "0000:00:02.0", "0x8086", "0x030000", "active")
        self.assertEqual(sampler.gpus(self.root, self.run_smi), [])
        self.assertEqual(sampler.gpus(self.root / "missing", self.run_smi), [])
        self.assertEqual(self.calls, [])


class TestRetention(unittest.TestCase):
    def test_rows_older_than_seven_days_fold_into_fifteen_minute_means_and_rows_past_ninety_days_into_their_day(self):
        bucket = NOW - 8 * DAY
        day = NOW - 91 * DAY - NOW % DAY
        asleep, awake = {"name": AWAKE, "asleep": True}, {"name": AWAKE, "util": 50.0, "vram_used": 300, "vram_total": 1000}
        mean = {**row(NOW - 30 * DAY, 12.0, 100, 0, asleep)}
        rows = [
            row(NOW - 91 * DAY + 60, 5.0, 1, 0, asleep),
            mean,
            row(bucket, 10.0, 100, 0, asleep),
            row(bucket + 60, 20.0, 200, 1, asleep),
            {**row(bucket + 120, 60.0, 300, 2, awake), "disks": [{"mount": "/", "used": 300, "total": 1000}, {"mount": "/mnt", "used": 10, "total": 20}]},
            row(bucket + 1000, 40.0, 400, 0, awake),
            row(NOW - 60, 70.0, 700, 3, awake),
        ]
        kept = sampler.retain(rows, NOW)
        self.assertEqual([entry["t"] for entry in kept], [day, NOW - 30 * DAY, bucket, bucket + 900, NOW - 60])
        self.assertEqual(kept[0], {**row(day, 5.0, 1, 0, asleep), **NO_PRESSURE, "queue": {"waiting": 0.0, "active": 1.0}, "span": 60, "width": DAY})
        self.assertEqual(kept[1], {**mean, "span": sampler.BUCKET, "width": sampler.BUCKET})
        self.assertEqual(kept[2], {
            "t": bucket, "disks": [{"mount": "/", "used": 200, "total": 1000}, {"mount": "/mnt", "used": 10, "total": 20}], "cpu": 30.0, "ram": 15.0, "swap": 0.0, "load": 3.0,
            "psi_some": None, "psi_full": None, "swap_out_mb_min": None,
            "gpus": [{"name": AWAKE, "util": 50.0, "vram_used": 300, "vram_total": 1000}], "queue": {"waiting": 1.0, "active": 1.0}, "span": 180, "width": sampler.BUCKET,
        })
        self.assertEqual((kept[3]["cpu"], kept[3]["disks"], kept[3]["span"], kept[3]["width"]), (40.0, [{"mount": "/", "used": 400, "total": 1000}], 60, sampler.BUCKET))
        self.assertEqual(kept[4], rows[-1])
        self.assertEqual(sampler.retain(kept, NOW), kept)

    def test_days_that_ended_more_than_ninety_days_ago_fold_into_one_mean_each_kept_forever(self):
        asleep = {"name": AWAKE, "asleep": True}
        day = NOW - NOW % DAY - 100 * DAY
        edge = NOW - NOW % DAY - 90 * DAY
        ancient = {**row(day - 1000 * DAY, 7.0, 7, 0, asleep), "span": 3600, "width": DAY}
        means = [{**row(day + index * sampler.BUCKET, cpu, 100, 0, asleep), "span": sampler.BUCKET, "width": sampler.BUCKET} for index, cpu in enumerate((10.0, 20.0, 60.0))]
        late = {**row(edge + sampler.BUCKET, 40.0, 400, 0, asleep), "span": sampler.BUCKET, "width": sampler.BUCKET}
        recent = row(NOW - 60, 70.0, 700, 3, asleep)
        kept = sampler.retain([ancient, *means, late, recent], NOW)
        self.assertEqual([entry["t"] for entry in kept], [day - 1000 * DAY, day, edge + sampler.BUCKET, NOW - 60])
        self.assertEqual(kept[0], ancient)
        self.assertEqual(kept[1], {**row(day, 30.0, 100, 0, asleep), **NO_PRESSURE, "load": 3.0, "queue": {"waiting": 0.0, "active": 1.0}, "span": 3 * sampler.BUCKET, "width": DAY})
        self.assertEqual(kept[2:], [late, recent])
        self.assertEqual(sampler.retain(kept, NOW), kept)
        later = sampler.retain(kept, NOW + 2 * DAY)
        self.assertEqual([entry["t"] for entry in later], [day - 1000 * DAY, day, edge, NOW - 60])
        self.assertEqual(later[:2], kept[:2])
        self.assertEqual((later[2]["cpu"], later[2]["span"], later[2]["width"]), (40.0, sampler.BUCKET, DAY))
        self.assertEqual(sampler.retain(later, NOW + 400 * DAY)[:3], later[:3])

    def test_a_bucket_still_reaching_into_the_last_seven_days_stays_raw_and_asleep_buckets_stay_asleep(self):
        now = NOW + 300
        asleep = {"name": ASLEEP, "asleep": True}
        rows = [row(NOW - 7 * DAY - 890, 10.0, 1, 0, asleep), row(NOW - 7 * DAY - 830, 30.0, 3, 0, asleep), row(NOW - 7 * DAY + 10, 50.0, 5, 0, asleep)]
        kept = sampler.retain(rows, now)
        self.assertEqual([entry["t"] for entry in kept], [NOW - 7 * DAY - 900, NOW - 7 * DAY + 10])
        self.assertEqual((kept[0]["cpu"], kept[0]["gpus"]), (20.0, [asleep]))
        self.assertEqual(kept[1], rows[2])

    def test_record_appends_and_folds_only_on_the_first_minute_of_a_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            asleep = {"name": AWAKE, "asleep": True}
            old = [row(NOW - 8 * DAY, 10.0, 1, 0, asleep), row(NOW - 8 * DAY + 60, 30.0, 1, 0, asleep)]
            (state / "samples.jsonl").write_text("".join(json.dumps(entry) + "\n" for entry in old), encoding="utf-8")
            later = row(NOW + 400, 1.0, 1, 0, asleep)
            sampler.record(state, later, NOW + 400)
            lines = [json.loads(line) for line in (state / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(lines, [*old, later])
            first = row(NOW + 930, 2.0, 1, 0, asleep)
            sampler.record(state, first, NOW + 930)
            lines = [json.loads(line) for line in (state / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([entry["t"] for entry in lines], [NOW - 8 * DAY, NOW + 400, NOW + 930])
            self.assertEqual(lines[0]["cpu"], 20.0)


class TestSamplerInScratchHome(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.home, self.council, stubs, self.proc = base / "home", base / "council", base / "bin", base / "proc"
        for folder in (self.home, self.council, stubs, self.proc):
            folder.mkdir()
        for name, text in (("stat", STAT_BEFORE), ("meminfo", MEMINFO), ("loadavg", LOADAVG)):
            (self.proc / name).write_text(text, encoding="utf-8")
        for tool in ("df", "nvidia-smi"):
            (stubs / tool).write_text(STUB, encoding="utf-8")
            (stubs / tool).chmod(0o755)
        self.queue = base / "skills" / "kvb-org-queue" / "scripts" / "queue.py"
        self.queue.parent.mkdir(parents=True)
        self.queue.write_text(QUEUE_STUB, encoding="utf-8")
        self.sys = host_sys(base / "sys")
        self.log = base / "calls.jsonl"
        (self.council / "queue.json").write_text(json.dumps({"entries": [{"status": status, "enqueued": NOW} for status in ("waiting", "active", "active")]}), encoding="utf-8")
        self.env = {
            **os.environ, "HOME": str(self.home), "PATH": f"{stubs}:/usr/bin:/bin",
            "STUB_LOG": str(self.log), "STUB_DF": DF, "STUB_NVIDIA_SMI": NVIDIA_SMI.splitlines()[0] + "\n", "STUB_QUEUE": json.dumps(QUEUE_ROWS, indent=1),
        }
        self.resources = self.home / ".local" / "state" / "agents-council" / "resources"

    def sample(self) -> None:
        argv = [sys.executable, str(SCRIPT), "sample", "--state", str(self.resources), "--council", str(self.council), "--proc", str(self.proc), "--sys", str(self.sys), "--queue", str(self.queue)]
        done = subprocess.run(argv, env=self.env, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_sampler_appends_one_row_per_run_under_the_scratch_home(self):
        self.sample()
        (self.proc / "stat").write_text(STAT_AFTER, encoding="utf-8")
        self.sample()
        samples = self.resources / "samples.jsonl"
        rows = [json.loads(line) for line in samples.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 2)
        for found in rows:
            with self.subTest(t=found["t"]):
                self.assertEqual(sorted(found), ["cpu", "disks", "gpus", "load", "psi_full", "psi_some", "queue", "ram", "swap", "swap_out_mb_min", "t"])
                self.assertEqual(found["disks"], DISKS)
                self.assertEqual(found["gpus"], [{"name": AWAKE, "util": 37.0, "vram_used": 2048 * MIB, "vram_total": 8188 * MIB}, {"name": ASLEEP, "asleep": True}])
                self.assertEqual(found["queue"], {"waiting": 1, "active": 2, "head": HEAD, "hung": ["test-1001"]})
                self.assertEqual((found["ram"], found["swap"], found["load"]), (25.0, 25.0, 1.25))
        self.assertEqual([found["cpu"] for found in rows], [None, 61.5])
        self.assertLessEqual(rows[0]["t"], rows[1]["t"])
        calls = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([call[0] for call in calls], ["df", "nvidia-smi", "queue.py"] * 2)
        self.assertEqual(calls[2], ["queue.py", "list", "--json", str(self.council)])
        self.assertTrue(all(ASLEEP not in " ".join(call) for call in calls), calls)
        self.assertEqual(sorted(path.name for path in samples.parent.iterdir()), ["cpu.json", "samples.jsonl"])

    def test_an_empty_queue_starts_no_queue_script(self):
        (self.council / "queue.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
        self.sample()
        (found,) = [json.loads(line) for line in (self.resources / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(found["queue"], {"waiting": 0, "active": 0})
        self.assertEqual([json.loads(line)[0] for line in self.log.read_text(encoding="utf-8").splitlines()], ["df", "nvidia-smi"])


class TestTimer(unittest.TestCase):
    def test_a_user_timer_runs_sample_every_minute_and_tokens_every_ten_without_a_page_condition(self):
        script = "/usr/bin/env python3 %h/.local/share/kvb-orchestrator/client/resources.py"
        shared = "--state ${KVB_ORCHESTRATOR_KEPT}/resources --council ${KVB_ORCHESTRATOR_COUNCIL}"
        for unit, calendar, starts in (
            ("resources", "OnCalendar=*-*-* *:*:00", [f"ExecStart={script} sample {shared} --proc /proc --sys /sys --queue ${{KVB_ORCHESTRATOR_SKILLS}}/kvb-org-queue/scripts/queue.py"]),
            ("tokens", "OnCalendar=*-*-* *:00/10:00", [f"ExecStart={script} tokens {shared} --transcripts ${{KVB_ORCHESTRATOR_PROJECTS}}"]),
        ):
            with self.subTest(unit=unit):
                timer = (UNITS / f"kvb-orchestrator-{unit}.timer").read_text(encoding="utf-8").splitlines()
                service = (UNITS / f"kvb-orchestrator-{unit}.service").read_text(encoding="utf-8").splitlines()
                self.assertIn(calendar, timer)
                self.assertIn("WantedBy=timers.target", timer)
                self.assertEqual([line for line in service if line.startswith("ExecStart=")], starts)
                self.assertIn("EnvironmentFile=%h/.local/share/kvb-orchestrator/.env", service)
                self.assertIn("Type=oneshot", service)
                self.assertFalse(any(line.startswith("ExecCondition=") for line in service))

    def test_orchestrator_install_enables_the_resources_and_tokens_timers(self):
        script = (hub_support.REPO_ROOT / "scripts" / "orchestrator.sh").read_text(encoding="utf-8")
        self.assertIn('RESOURCES_UNIT="${NAME}-resources"', script)
        self.assertIn('TOKENS_UNIT="${NAME}-tokens"', script)
        self.assertIn('systemctl --user enable --now "${RESOURCES_UNIT}.timer"\n\tsystemctl --user enable --now "${TOKENS_UNIT}.timer"', script)
        self.assertIn('"${HUB}/client/resources.py"', script)
        self.assertIn("KVB_ORCHESTRATOR_SKILLS=%s", script)


class TestHostUnitPins(unittest.TestCase):
    def test_the_firewall_sessions_and_graph_units_hold_their_intervals_and_conditions(self):
        firewall = (UNITS / "kvb-orchestrator-firewall.service").read_text(encoding="utf-8")
        self.assertIn("tree-heartbeat -mmin -5", firewall)
        self.assertIn("firewall/jobs", firewall.split("ExecCondition=", 1)[1].splitlines()[0])
        self.assertIn("OnUnitInactiveSec=30s", (UNITS / "kvb-orchestrator-sessions.timer").read_text(encoding="utf-8").splitlines())
        graph = (hub_support.REPO_ROOT / "skills" / "kvb-agent-optimize" / "scripts" / "graph.py").read_text(encoding="utf-8")
        self.assertIn("SUPERVISE_SECONDS = 120\n", graph)


if __name__ == "__main__":
    unittest.main()
