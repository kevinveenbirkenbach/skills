from __future__ import annotations

import io
import json
import sys
import wave
from pathlib import Path

from hub_support import server

VOICES = ["de_DE-solo-medium:0", "en_US-test-high:0", "en_US-test-high:1", "en_US-test-high:2", "en_US-test-high:3"]
OPERATOR_VOICE = "en_US-test-high:0"
FAKE_PIPER = """
import argparse, json, os, sys, wave
parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--config", required=True)
parser.add_argument("--output-file", required=True)
parser.add_argument("--speaker", type=int)
args = parser.parse_args()
text = sys.stdin.read()
with open(os.path.join(os.environ["HOME"], "piper.jsonl"), "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "text": text, "tmp": os.environ["TMPDIR"], "cwd": os.getcwd()}) + "\\n")
if "FAIL" in text:
    sys.exit(3)
with wave.open(args.output_file, "wb") as out:
    out.setnchannels(1)
    out.setsampwidth(2)
    out.setframerate(22050)
    out.writeframes(bytes(2 * len(text)))
"""
FAKE_WHISPER = """
import json, os, sys
data = sys.stdin.buffer.read()
with open(os.path.join(os.environ["HOME"], "whisper.jsonl"), "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "sha256": __import__("hashlib").sha256(data).hexdigest()}) + "\\n")
if b"FAIL" in data:
    sys.exit(4)
print(" hello  from the [BLANK_AUDIO] mic")
print("second line")
"""


def write_engines(base: Path) -> server.Engines:
    bin_dir, voices, scratch = base / "bin", base / "voices", base / "scratch"
    for folder in (bin_dir, voices, scratch):
        folder.mkdir()
    for name, body in (("piper", FAKE_PIPER), ("whisper-cli", FAKE_WHISPER)):
        path = bin_dir / name
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)
    for model, config in (("en_US-test-high", {"num_speakers": 4}), ("de_DE-solo-medium", {"num_speakers": 1}), ("zero", {"num_speakers": 0}), ("bad name!", {"num_speakers": 2})):
        (voices / f"{model}.onnx").write_bytes(b"onnx")
        (voices / f"{model}.onnx.json").write_text(json.dumps(config), encoding="utf-8")
    (voices / "broken.onnx").write_bytes(b"onnx")
    model = base / "ggml-base.bin"
    model.write_bytes(b"ggml")
    return server.Engines(piper=bin_dir / "piper", voices=voices, operator_voice=OPERATOR_VOICE, whisper=bin_dir / "whisper-cli", whisper_model=model, scratch=scratch, service=server.Service(url="", key=""))


def wav_bytes(channels: int, width: int, rate: int, frames: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        writer.writeframes(frames)
    return buffer.getvalue()


def log_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []
