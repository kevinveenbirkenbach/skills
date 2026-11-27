"""Exercise requirement 084: the order check and the tighter-or-looser rule of the page, and the hub's limits endpoint with its passkey."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import unittest

from hub_case import HubCase
from hub_support import HUB, REPO_ROOT, key, signing
from kvb_orchestrator import limiting

MODULE = HUB / "templates" / "limits.js"
LIMITS_PY = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "limits.py"
CALM = {metric: dict(zip(("lower", "upper", "stop", "mayday"), values, strict=True)) for metric, values in limiting.PROFILE_TABLE["calm"].items()}
BALANCED = {metric: dict(zip(("lower", "upper", "stop", "mayday"), values, strict=True)) for metric, values in limiting.PROFILE_TABLE["balanced"].items()}


def load_limits():
    spec = importlib.util.spec_from_file_location("kvb_test_limits_board", LIMITS_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def changed(base: dict, metric: str, level: str, value: object) -> dict:
    data = copy.deepcopy(base)
    data[metric][level] = value
    return data


BROKEN = {
    "upper below lower": changed(BALANCED, "cpu", "upper", 60),
    "stop equals upper": changed(BALANCED, "ram", "stop", 90),
    "mayday below stop": changed(BALANCED, "psi", "mayday", 20),
    "above 100": changed(BALANCED, "disk", "mayday", 101),
    "negative": changed(BALANCED, "swap", "lower", -1),
    "text value": changed(BALANCED, "cpu", "lower", "70"),
    "bool value": changed(BALANCED, "cpu", "lower", True),
    "missing level": {**copy.deepcopy(BALANCED), "cpu": {"lower": 70, "upper": 90, "stop": 95}},
    "extra level": changed(BALANCED, "cpu", "panic", 99),
    "missing metric": {metric: levels for metric, levels in BALANCED.items() if metric != "psi"},
    "extra metric": {**copy.deepcopy(BALANCED), "gpu": {"lower": 1, "upper": 2, "stop": 3, "mayday": 4}},
    "no object": [1, 2, 3],
}
PROBE = """
const L = require(process.argv[1]);
const [calm, balanced, broken] = JSON.parse(process.argv[2]);
const profiles = {calm, balanced};
console.log(JSON.stringify({
  valid: [L.problem(calm), L.problem(balanced)],
  broken: Object.fromEntries(Object.entries(broken).map(([name, value]) => [name, L.problem(value)])),
  tighter: L.loosened(calm, balanced),
  looser: L.loosened(balanced, calm).map((change) => `${change.metric}.${change.level}`),
  one: L.loosened(L.withValue(calm, "cpu", "upper", 71), calm),
  lower: L.loosened(L.withValue(calm, "cpu", "lower", 49), calm),
  equal: L.loosened(calm, calm),
  unset: L.loosened(calm, null).length,
  said: L.loosened(L.withValue(calm, "ram", "mayday", 96), calm).map(L.said),
  profile: [L.profileOf(calm, profiles), L.profileOf(L.withValue(calm, "cpu", "lower", 49), profiles), L.profileOf(null, profiles)],
  untouched: calm.cpu.upper,
}));
"""


@unittest.skipUnless(shutil.which("node"), "no node")
class TestLimitsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        args = json.dumps([CALM, BALANCED, BROKEN])
        done = subprocess.run(["node", "-e", PROBE, str(MODULE), args], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)
        cls.limits = load_limits()

    def test_the_profiles_pass_and_every_broken_object_is_named(self):
        self.assertEqual(self.data["valid"], [None, None])
        for name, why in self.data["broken"].items():
            with self.subTest(name=name):
                self.assertIsInstance(why, str)
        self.assertIn("breaks lower < upper < STOP < MAYDAY", self.data["broken"]["upper below lower"])

    def test_the_page_and_limits_py_refuse_the_same_objects(self):
        for name, value in BROKEN.items():
            with self.subTest(name=name):
                self.assertIsNotNone(self.limits.problem(value))
                self.assertIsNotNone(self.data["broken"][name])
        self.assertIsNone(self.limits.problem(CALM))

    def test_a_lower_or_equal_value_is_tighter_and_a_higher_one_looser(self):
        self.assertEqual(self.data["tighter"], [])
        self.assertEqual(self.data["equal"], [])
        self.assertEqual(self.data["lower"], [])
        self.assertEqual(self.data["one"], [{"metric": "cpu", "level": "upper", "from": 70, "to": 71}])
        higher = [f"{metric}.{level}" for metric, levels in BALANCED.items() for level, value in levels.items() if value > CALM[metric][level]]
        self.assertEqual(self.data["looser"], higher)
        self.assertNotIn("psi.lower", higher)
        self.assertEqual(self.data["unset"], 20)
        self.assertEqual(self.data["said"], ["RAM MAYDAY 95 → 96 %"])

    def test_a_profile_is_named_only_while_every_value_matches_and_with_value_copies(self):
        self.assertEqual(self.data["profile"], ["calm", None, None])
        self.assertEqual(self.data["untouched"], 70)


class TestHubLimits(HubCase):
    def setUp(self):
        super().setUp()
        self.limits = load_limits()

    def stored(self) -> object:
        file = self.council / "limits.json"
        return json.loads(file.read_text(encoding="utf-8")) if file.exists() else None

    def view(self) -> dict:
        status, _, body = self.get("/api/limits")
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def request(self, limits: object) -> tuple[int, bytes]:
        status, _, body = self.post_json("/api/limits/sign", {"limits": limits}, self.guard(self.host))
        return status, body

    def save(self, limits: object, proof: object) -> tuple[int, bytes]:
        status, _, body = self.post_json("/api/limits", {"limits": limits, "proof": proof}, self.guard(self.host))
        return status, body

    def test_the_view_names_the_profiles_the_levels_and_no_limits_without_a_file(self):
        found = self.view()
        self.assertEqual((found["limits"], found["why"], found["target"]), (None, None, None))
        self.assertEqual((found["metrics"], found["levels"]), (list(self.limits.METRICS), list(self.limits.LEVELS)))
        self.assertEqual(sorted(found["profiles"]), ["balanced", "calm", "max"])
        for name, values in found["profiles"].items():
            with self.subTest(profile=name):
                self.assertIsNone(self.limits.problem(values))
        self.assertEqual((found["profiles"]["calm"]["cpu"]["lower"], found["profiles"]["calm"]["cpu"]["upper"]), (50, 70))
        self.assertEqual((found["profiles"]["balanced"]["ram"]["lower"], found["profiles"]["balanced"]["ram"]["upper"]), (70, 90))
        self.assertEqual((found["profiles"]["max"]["cpu"]["lower"], found["profiles"]["max"]["cpu"]["upper"]), (80, 95))

    def test_every_profile_value_grows_from_calm_over_balanced_to_max(self):
        table = limiting.PROFILE_TABLE
        for metric in self.limits.METRICS:
            for index in range(len(self.limits.LEVELS)):
                with self.subTest(metric=metric, level=self.limits.LEVELS[index]):
                    self.assertLessEqual(table["calm"][metric][index], table["balanced"][metric][index])
                    self.assertLessEqual(table["balanced"][metric][index], table["max"][metric][index])

    def test_the_view_carries_the_live_target_of_cpu_and_ram(self):
        self.write_council({"limits.json": BALANCED, "limits-target.json": {"ram": 80.5, "cpu": 84, "psi": 0.2, "stepped": 1, "samples": []}})
        found = self.view()
        self.assertEqual((found["limits"], found["target"]), (BALANCED, {"ram": 80.5, "cpu": 84}))

    def test_a_tighter_value_saves_without_a_signature(self):
        self.write_council({"limits.json": BALANCED})
        status, body = self.request(CALM)
        self.assertEqual((status, json.loads(body)["payload"]), (200, None), body)
        status, body = self.save(CALM, None)
        self.assertEqual(status, 200, body)
        self.assertEqual((self.stored(), json.loads(body)["limits"]), (CALM, CALM))
        self.assertEqual(self.limits.read(self.council), (CALM, None))

    def test_a_looser_value_is_refused_without_a_proof_and_saved_with_one(self):
        self.write_council({"limits.json": CALM})
        looser = changed(CALM, "cpu", "upper", 75)
        self.assertEqual(self.save(looser, None), (400, b"not signed: no signature\n"))
        self.assertEqual(self.stored(), CALM)
        signer = self.pin()
        status, body = self.request(looser)
        self.assertEqual(status, 200, body)
        payload = json.loads(body)["payload"]
        self.assertEqual(payload["items"], [signing.item_hash(signing.limits_item(looser))])
        self.assertEqual(self.save(looser, key(-7, "stranger").proof(payload, self.origin)), (400, b"not signed: the signing key is not pinned\n"))
        other = changed(CALM, "cpu", "upper", 80)
        self.assertEqual(self.save(other, signer.proof(payload, self.origin)), (400, b"not signed: the signature does not list this item\n"))
        self.assertEqual(self.stored(), CALM)
        proof = signer.proof(payload, self.origin)
        status, body = self.save(looser, proof)
        self.assertEqual(status, 200, body)
        self.assertEqual(self.stored(), looser)
        self.save(CALM, None)
        status, body = self.save(looser, proof)
        self.assertEqual(status, 400, body)
        self.assertEqual(self.stored(), CALM)

    def test_a_first_save_without_a_file_needs_the_passkey_even_for_calm(self):
        self.assertEqual(self.save(CALM, None), (400, b"not signed: no signature\n"))
        self.assertIsNone(self.stored())
        signer = self.pin()
        status, body = self.request(CALM)
        self.assertEqual(status, 200, body)
        status, body = self.save(CALM, signer.proof(json.loads(body)["payload"], self.origin))
        self.assertEqual((status, self.stored()), (200, CALM), body)

    def test_the_hub_refuses_exactly_what_limits_py_refuses_and_writes_nothing(self):
        self.write_council({"limits.json": BALANCED})
        for name, value in BROKEN.items():
            with self.subTest(name=name):
                why = self.limits.problem(value)
                self.assertEqual(self.request(value), (400, f"{why}\n".encode()))
                self.assertEqual(self.save(value, None), (400, f"{why}\n".encode()))
                self.assertEqual(self.stored(), BALANCED)

    def test_the_routes_take_only_their_fields_and_the_page_guard(self):
        self.assertEqual(self.post_json("/api/limits", {"limits": CALM, "proof": None}, {"Host": self.host})[0], 403)
        self.assertEqual(self.save(CALM, None)[0], 400)
        status, _, body = self.post_json("/api/limits", {"limits": CALM}, self.guard(self.host))
        self.assertEqual((status, body), (400, b"missing argument proof\n"))
        status, _, body = self.post_json("/api/limits/sign", {"limits": CALM, "extra": 1}, self.guard(self.host))
        self.assertEqual((status, body), (400, b"unknown argument extra\n"))


if __name__ == "__main__":
    unittest.main()
