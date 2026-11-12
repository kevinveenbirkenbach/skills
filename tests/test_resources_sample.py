from __future__ import annotations

import fcntl
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
    {"mount": "/", "used": 512000000 * 1024, "total": 976762584 * 1024},
    {"mount": "/boot/efi", "used": 12000 * 1024, "total": 523248 * 1024},
    {"mount": "/mnt/Backup Disk", "used": 100000000 * 1024, "total": 1953514584 * 1024},
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


class TestCpu(unittest.TestCase):
    def test_cpu_is_the_busy_share_since_the_ticks_the_run_before_kept_and_the_sampler_never_sleeps(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, state = Path(tmp) / "proc", Path(tmp) / "state"
            proc.mkdir()
            state.mkdir()
            (proc / "stat").write_text(STAT_BEFORE, encoding="utf-8")
            with mock.patch.object(sampler.time, "sleep", side_effect=AssertionError("slept")), mock.patch.object(sampler.time, "time", return_value=NOW - 60):
                self.assertIsNone(sampler.sample(proc, Path(tmp) / "sys", Path(tmp), lambda argv: None, state)["cpu"])
            (proc / "stat").write_text(STAT_AFTER, encoding="utf-8")
            self.assertEqual(sampler.cpu_since(proc, state, NOW), 61.5)
            (proc / "stat").write_text(STAT_LATER, encoding="utf-8")
            self.assertIsNone(sampler.cpu_since(proc, state, NOW + sampler.BUCKET + 1))
            self.assertEqual(json.loads((state / "cpu.json").read_text(encoding="utf-8")), [NOW + sampler.BUCKET + 1, 9300, 12200])


class TestGpus(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.calls = []

    def run_smi(self, argv: list[str]) -> str:
        self.calls.append(argv)
        return NVIDIA_SMI

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
        self.assertEqual(sampler.gpus(host_sys(self.root), lambda argv: None), [unknown, {"name": ASLEEP, "asleep": True}])
        self.assertEqual(sampler.gpus(self.root, lambda argv: NVIDIA_SMI.splitlines()[1]), [unknown, {"name": ASLEEP, "asleep": True}])
        self.assertEqual(sampler.mean_row(NOW, [row(NOW + 60, 1.0, 1, 0, unknown), row(NOW + 120, 1.0, 1, 0, unknown)])["gpus"], [unknown])

    def test_no_nvidia_gpu_means_no_gpu_row_and_no_call(self):
        device(self.root, "0000:00:02.0", "0x8086", "0x030000", "active")
        self.assertEqual(sampler.gpus(self.root, self.run_smi), [])
        self.assertEqual(sampler.gpus(self.root / "missing", self.run_smi), [])
        self.assertEqual(self.calls, [])


class TestRetention(unittest.TestCase):
    def test_rows_older_than_seven_days_fold_into_fifteen_minute_means_and_means_past_ninety_days_drop(self):
        bucket = NOW - 8 * DAY
        asleep, awake = {"name": AWAKE, "asleep": True}, {"name": AWAKE, "util": 50.0, "vram_used": 300, "vram_total": 1000}
        mean = {**row(NOW - 30 * DAY, 12.0, 100, 0, asleep)}
        rows = [
            row(NOW - 91 * DAY, 5.0, 1, 0, asleep),
            mean,
            row(bucket, 10.0, 100, 0, asleep),
            row(bucket + 60, 20.0, 200, 1, asleep),
            {**row(bucket + 120, 60.0, 300, 2, awake), "disks": [{"mount": "/", "used": 300, "total": 1000}, {"mount": "/mnt", "used": 10, "total": 20}]},
            row(bucket + 1000, 40.0, 400, 0, awake),
            row(NOW - 60, 70.0, 700, 3, awake),
        ]
        kept = sampler.retain(rows, NOW)
        self.assertEqual([entry["t"] for entry in kept], [NOW - 30 * DAY, bucket, bucket + 900, NOW - 60])
        self.assertIs(kept[0], mean)
        self.assertEqual(kept[1], {
            "t": bucket, "disks": [{"mount": "/", "used": 200, "total": 1000}, {"mount": "/mnt", "used": 10, "total": 20}], "cpu": 30.0, "ram": 15.0, "swap": 0.0, "load": 3.0,
            "gpus": [{"name": AWAKE, "util": 50.0, "vram_used": 300, "vram_total": 1000}], "queue": {"waiting": 1.0, "active": 1.0},
        })
        self.assertEqual((kept[2]["cpu"], kept[2]["disks"]), (40.0, [{"mount": "/", "used": 400, "total": 1000}]))
        self.assertEqual(kept[3], rows[-1])
        self.assertEqual(sampler.retain(kept, NOW), kept)

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
        self.sys = host_sys(base / "sys")
        self.log = base / "calls.jsonl"
        (self.council / "queue.json").write_text(json.dumps({"entries": [{"status": status, "enqueued": NOW} for status in ("waiting", "active", "active")]}), encoding="utf-8")
        self.env = {
            **os.environ, "HOME": str(self.home), "PATH": f"{stubs}:/usr/bin:/bin",
            "STUB_LOG": str(self.log), "STUB_DF": DF, "STUB_NVIDIA_SMI": NVIDIA_SMI.splitlines()[0] + "\n",
        }
        self.resources = self.home / ".local" / "state" / "agents-council" / "resources"

    def sample(self) -> None:
        argv = [sys.executable, str(SCRIPT), "sample", "--state", str(self.resources), "--council", str(self.council), "--proc", str(self.proc), "--sys", str(self.sys)]
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
                self.assertEqual(sorted(found), ["cpu", "disks", "gpus", "load", "queue", "ram", "swap", "t"])
                self.assertEqual(found["disks"], DISKS)
                self.assertEqual(found["gpus"], [{"name": AWAKE, "util": 37.0, "vram_used": 2048 * MIB, "vram_total": 8188 * MIB}, {"name": ASLEEP, "asleep": True}])
                self.assertEqual(found["queue"], {"waiting": 1, "active": 2})
                self.assertEqual((found["ram"], found["swap"], found["load"]), (25.0, 25.0, 1.25))
        self.assertEqual([found["cpu"] for found in rows], [None, 61.5])
        self.assertLessEqual(rows[0]["t"], rows[1]["t"])
        calls = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([call[0] for call in calls], ["df", "nvidia-smi"] * 2)
        self.assertTrue(all(ASLEEP not in " ".join(call) for call in calls), calls)
        self.assertEqual(sorted(path.name for path in samples.parent.iterdir()), ["cpu.json", "samples.jsonl"])


class TestTimer(unittest.TestCase):
    def test_a_user_timer_runs_sample_and_tokens_every_minute_without_a_page_condition(self):
        timer = (UNITS / "kvb-orchestrator-resources.timer").read_text(encoding="utf-8").splitlines()
        service = (UNITS / "kvb-orchestrator-resources.service").read_text(encoding="utf-8").splitlines()
        self.assertIn("OnCalendar=*-*-* *:*:00", timer)
        self.assertIn("WantedBy=timers.target", timer)
        script = "/usr/bin/env python3 %h/.local/share/kvb-orchestrator/client/resources.py"
        shared = "--state ${KVB_ORCHESTRATOR_KEPT}/resources --council ${KVB_ORCHESTRATOR_COUNCIL}"
        self.assertEqual([line for line in service if line.startswith("ExecStart=")], [
            f"ExecStart={script} sample {shared} --proc /proc --sys /sys",
            f"ExecStart={script} tokens {shared} --transcripts ${{KVB_ORCHESTRATOR_PROJECTS}}",
        ])
        self.assertIn("EnvironmentFile=%h/.local/share/kvb-orchestrator/.env", service)
        self.assertIn("Type=oneshot", service)
        self.assertFalse(any(line.startswith("ExecCondition=") for line in service))

    def test_orchestrator_install_enables_the_resources_timer(self):
        script = (hub_support.REPO_ROOT / "scripts" / "orchestrator.sh").read_text(encoding="utf-8")
        self.assertIn('RESOURCES_UNIT="${NAME}-resources"', script)
        self.assertIn('systemctl --user enable --now "${RESOURCES_UNIT}.timer"', script)
        self.assertIn('"${HUB}/client/resources.py"', script)


if __name__ == "__main__":
    unittest.main()
