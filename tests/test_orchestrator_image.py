from __future__ import annotations

import re
import unittest

from hub_support import HUB

NAME = "INFINITO_ARTEFACT_BASE"
EXPRESSION = re.compile(r"\$\{([A-Za-z_]\w*)(?::([-+])([^}]*))?\}")
COMMIT = "d1be6fde11ac6e0407606b4e42fe72d34add8037"
VOICE = "huggingface.co/rhasspy/piper-voices/resolve/e7229f7d33a10e145e109b886d661984201ac3c4/en/en_US/libritts/high/en_US-libritts-high.onnx"
PINNED = {
    VOICE: "9127a559e11603f10b366d1a20ac7426826081dbc521de4c2420c57728d73f0f",
    f"{VOICE}.json": "2efdc6d7f954588b8180132cbd9b8001933fdd00932c92bc92fd0d2028a9eb3d",
    "huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base-q8_0.bin": "c577b9a86e7e048a0b7eada054f4dd79a56bbfa911fbdacf900ac5b567cbb7d9",
}
ARCHIVE = (f"codeload.github.com/ggml-org/whisper.cpp/tar.gz/{COMMIT}", "645445da884df6dbd52b30f82d7be7c01d1767c938714e477e786b88d529e9f4")
CLONE = ("clone", "https://github.com/ggml-org/whisper.cpp", f"v1.9.5@{COMMIT}")


def expand(text: str, values: dict[str, str]) -> str:
    """Args:
        text: one instruction.
        values: the build args in scope; any other name expands as unset.

    Returns:
        text with every ${name}, ${name:-word} and ${name:+word} expanded as
        BuildKit does, an empty value counting as unset.
    """

    def value(match: re.Match) -> str:
        name, operator, word = match.groups()
        current = values.get(name, "")
        if operator == "-":
            return current or word
        if operator == "+":
            return word if current else ""
        return current

    return EXPRESSION.sub(value, text)


def instructions(text: str) -> list[str]:
    joined = text.replace("\\\n", " ")
    return [" ".join(line.split()) for line in joined.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def stages(text: str) -> tuple[set[str], list[dict]]:
    """Returns:
        The global ARG names and every stage as {"name", "base", "steps"} in
        file order; a stage without AS is named by its index.
    """
    shared: set[str] = set()
    found: list[dict] = []
    for step in instructions(text):
        word, _, rest = step.partition(" ")
        if word == "FROM":
            parts = rest.split()
            found.append({"name": parts[2] if parts[1:2] == ["AS"] else str(len(found)), "base": parts[0], "steps": []})
        elif found:
            found[-1]["steps"].append(step)
        elif word == "ARG":
            shared.add(rest.split("=")[0])
    return shared, found


def rendered(build_args: dict[str, str]) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Args:
        build_args: the --build-arg values; a missing name is unset.

    Returns:
        Every fetch of the stages the final image needs, as (kind, url, pin),
        sorted, and every step of those stages after expansion.
    """
    shared, found = stages((HUB / "Dockerfile").read_text(encoding="utf-8"))
    index = {stage["name"]: number for number, stage in enumerate(found)}
    wanted, seen, fetches, steps = [len(found) - 1], set(), [], []
    while wanted:
        number = wanted.pop()
        if number in seen:
            continue
        seen.add(number)
        stage = found[number]
        base = expand(stage["base"], {name: build_args[name] for name in shared if name in build_args})
        wanted += [index[base]] if base in index else []
        scope: dict[str, str] = {}
        for raw in stage["steps"]:
            if raw.startswith("ARG "):
                name = raw[4:].split("=")[0]
                scope[name] = build_args.get(name, "")
                continue
            step = expand(raw, scope)
            steps.append(step)
            source = re.search(r"--from=(\S+)", step)
            wanted += [index[source[1]]] if step.startswith("COPY ") and source else []
            added = re.fullmatch(r"ADD --checksum=sha256:([0-9a-f]{64}) (?:--chmod=\S+ )?(\S+) (\S+)", step)
            if added:
                fetches.append(("add", added[2], added[1]))
            cloned = re.search(r"git clone --depth 1 --branch (\S+) (\S+) /src && test \"\$\(cd /src && git rev-parse HEAD\)\" = ([0-9a-f]{40})", step)
            if cloned:
                fetches.append(("clone", cloned[2], f"{cloned[1]}@{cloned[3]}"))
    return sorted(fetches), steps


def through(base: str) -> list[tuple[str, str, str]]:
    return sorted([("add", f"{base}/{ARCHIVE[0]}", ARCHIVE[1]), *(("add", f"{base}/{path}", pin) for path, pin in PINNED.items())])


class TestArtefactBase(unittest.TestCase):
    def test_unset_the_build_fetches_the_upstream_urls_and_clones_as_before(self):
        upstream = sorted([CLONE, *(("add", f"https://{path}", pin) for path, pin in PINNED.items())])
        for build_args in ({}, {NAME: ""}):
            with self.subTest(build_args=build_args):
                self.assertEqual(rendered(build_args)[0], upstream)

    def test_set_every_fetch_goes_through_the_base_with_the_same_pins(self):
        for base in ("http://10.0.0.5", "http://10.0.0.5:8081/cache", "https://cache.example"):
            with self.subTest(base=base):
                fetches, steps = rendered({NAME: base})
                self.assertEqual(fetches, through(base))
                self.assertEqual([step for step in steps if "https://" in step.replace(base, "") or "git clone" in step], [])
        self.assertEqual(rendered({NAME: "https:/"})[0], through("https:/"))
        self.assertEqual(through("https:/"), sorted([("add", f"https://{ARCHIVE[0]}", ARCHIVE[1]), *(("add", f"https://{path}", pin) for path, pin in PINNED.items())]))

    def test_every_add_is_pinned_and_reads_the_base_and_each_stage_declares_it(self):
        shared, found = stages((HUB / "Dockerfile").read_text(encoding="utf-8"))
        self.assertIn(NAME, shared)
        for stage in found:
            adds = [step for step in stage["steps"] if step.startswith("ADD ")]
            with self.subTest(stage=stage["name"]):
                for step in adds:
                    self.assertRegex(step, r"^ADD --checksum=sha256:[0-9a-f]{64} (?:--chmod=\S+ )?\$\{" + NAME + r":-https:/\}/\S+ /\S+$")
                    declared = [number for number, other in enumerate(stage["steps"]) if other == f"ARG {NAME}"]
                    self.assertTrue(declared and declared[0] < stage["steps"].index(step), step)
        self.assertEqual(sum(step.startswith("ADD ") for stage in found for step in stage["steps"]), len(PINNED) + 1)


class TestComposeWiring(unittest.TestCase):
    def test_compose_hands_the_base_to_the_build_and_the_speech_service_to_the_hub(self):
        compose = (HUB / "compose.yml").read_text(encoding="utf-8")
        self.assertRegex(compose, r"(?m)^    build:\n      context: \.\n      args:\n        - " + NAME + "$")
        self.assertIn('      - --speech-url\n      - "${KVB_ORCHESTRATOR_SPEECH_URL}"\n      - --speech-key-file\n      - /run/kvb-orchestrator/speech.key\n', compose)
        self.assertIn('        source: "${KVB_ORCHESTRATOR_SPEECH_KEY_FILE:-/dev/null}"\n        target: /run/kvb-orchestrator/speech.key\n        read_only: true\n', compose)
        env = (HUB / ".env").read_text(encoding="utf-8").splitlines()
        self.assertLessEqual({"KVB_ORCHESTRATOR_SPEECH_URL=", "KVB_ORCHESTRATOR_SPEECH_KEY_FILE="}, set(env))
        self.assertNotIn(NAME, "\n".join(env))


if __name__ == "__main__":
    unittest.main()
