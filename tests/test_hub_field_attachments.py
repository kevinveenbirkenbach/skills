from __future__ import annotations

import json
import subprocess
import unittest

from hub_case import HubCase
from hub_support import HOST_STATE, HUB

TEMPLATES = HUB / "templates"
ATTACHMENTS = TEMPLATES / "attachments.js"
PAGE_ATTACH = TEMPLATES / "page-attach.js"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(17)) + b"\x00\x00\x00\x00IEND\xaeB`\x82"
PURE = r"""
const Attachments = require(process.argv[1]);
const at = new Date(2026, 10, 27, 9, 5, 7);
const swap = (value, from, to, caret) => Attachments.swapped(value, from, to, caret);
const wait = Attachments.placeholder("shot.png");
console.log(JSON.stringify({
  line: Attachments.pathLine("/host/uploads/abc/shot.png"),
  wait,
  names: [
    Attachments.pastedName({name: "image.png", type: "image/png"}, at),
    Attachments.pastedName({name: "", type: "image/jpeg"}, at),
    Attachments.pastedName({name: "", type: ""}, at),
    Attachments.pastedName({name: "plan.md", type: "text/markdown"}, at),
  ],
  placed: [
    Attachments.placed("ab", 1, 1, "L", "\n"),
    Attachments.placed("a\nb", 2, 2, "L", "\n"),
    Attachments.placed("", 0, 0, "L", "\n"),
    Attachments.placed("ab", 1, 1, "L", " "),
  ],
  swaps: [
    swap(`a\n${wait}\nb`, wait, "📎 /p/shot.png", 0),
    swap(`a\n${wait}\nb`, wait, "📎 /p/shot.png", 30),
    swap("a\nb", wait, "📎 /p/shot.png", 1),
  ],
  failed: Attachments.failed("big.bin", "413\n  too\tlarge "),
  paths: Attachments.paths("x\n📎 /h/a.png\n📎 uploading b.png…\n⚠️ c.png: upload failed\n 📎 /not/own/line\n📎 /h/a.png.bak"),
  removed: Attachments.removed("x\n📎 /h/a.png.bak\n📎 /h/a.png\ny", "/h/a.png"),
  kept: Attachments.removed("x\n📎 /h/a.png.bak", "/h/a.png"),
}));
"""
DOM = r"""
const fs = require("fs");
const vm = require("vm");
const Attachments = require(process.argv[1]);
const code = fs.readFileSync(process.argv[2], "utf8");
const settle = async () => {
  for (let round = 0; round < 20; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};
function element(tag) {
  const handlers = {};
  return {
    tagName: tag, children: [], hidden: false, attrs: {},
    replaceChildren(...kids) { this.children = kids; },
    addEventListener: (kind, run) => { (handlers[kind] = handlers[kind] || []).push(run); },
    fire(event) { (handlers[event.type] || []).forEach((run) => run(event)); },
  };
}
function textarea(value) {
  const node = element("TEXTAREA");
  Object.assign(node, {value, selectionStart: value.length, selectionEnd: value.length, isConnected: true, id: "f1"});
  node.setSelectionRange = (start, end) => Object.assign(node, {selectionStart: start, selectionEnd: end});
  node.dispatchEvent = (event) => node.fire(event);
  node.getAttribute = () => "Feedback";
  node.focus = () => null;
  return node;
}
const sent = [];
const revoked = [];
const sandbox = {
  Attachments, Voice: {FIELDS: "textarea"}, UPLOAD_LIMIT: 50 * 1024 * 1024,
  h: (tag, attrs, ...kids) => {
    const made = Object.assign(element(tag.toUpperCase()), {attrs, hidden: Boolean(attrs.hidden), children: kids.flat()});
    Object.entries(attrs.on || {}).forEach(([kind, run]) => made.addEventListener(kind, run));
    return made;
  },
  icon: (name) => name, named: (label) => ({"aria-label": label}), micKey: (field) => field.getAttribute("aria-label") || "",
  document: {querySelectorAll: () => []},
  URL: {createObjectURL: (file) => `blob:${file.name}`, revokeObjectURL: (url) => revoked.push(url)},
  Event: class { constructor(type) { this.type = type; } },
  Date,
};
sandbox.send = async (path, file) => {
  sent.push({path, during: sandbox.current.value});
  return file.name === "down.png" ? {ok: false, status: 0, text: "TypeError: Failed to fetch", data: null} : {ok: true, status: 201, text: "", data: {path: `/host/uploads/abc/${decodeURIComponent(path.split("name=")[1])}`}};
};
vm.runInNewContext(code, sandbox);
const paste = (field, files, text) => {
  let prevented = false;
  field.fire({type: "paste", clipboardData: {files, getData: () => text}, preventDefault: () => { prevented = true; }});
  return prevented;
};
(async () => {
  const field = textarea("intro");
  sandbox.current = field;
  sandbox.attachWire(field);
  const row = sandbox.attachRow(field);
  const plain = paste(field, [], "just text");
  const mixed = paste(field, [{name: "image.png", type: "image/png", size: 3}], "cells as text");
  const before = sent.length;
  const image = paste(field, [{name: "image.png", type: "image/png", size: 3}], "");
  await settle();
  const pasted = {prevented: image, value: field.value, chips: row.children.length, hidden: row.hidden, thumb: row.children[0] && row.children[0].children[0].attrs.src};
  field.fire({type: "drop", dataTransfer: {types: ["Files"], files: [{name: "notes.txt", type: "text/plain", size: 4}]}, preventDefault: () => null});
  await settle();
  const dropped = {value: field.value, chips: row.children.length, icon: row.children[1] && row.children[1].children[0]};
  const big = {name: "big.bin", type: "", size: sandbox.UPLOAD_LIMIT + 1};
  const sentBefore = sent.length;
  sandbox.attachUpload(field, big, false);
  await settle();
  const over = {value: field.value, sent: sent.length - sentBefore};
  await sandbox.attachUpload(field, {name: "down.png", type: "image/png", size: 3}, false);
  const down = field.value;
  const path = sandbox.Attachments.paths(field.value)[0];
  const drop = row.children[0].children[2];
  drop.fire({type: "click"});
  console.log(JSON.stringify({
    plain, mixed, uploadsByText: before, pasted, dropped, over, down, sent,
    removed: {value: field.value, chips: row.children.length, revoked, path},
  }));
})().catch((error) => {
  console.error(error && error.stack || error);
  process.exit(1);
});
"""


def node(script: str, *args: str) -> dict:
    done = subprocess.run(["node", "-e", script, *map(str, args)], capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise AssertionError(done.stderr[-4000:])
    return json.loads(done.stdout)


class TestAttachmentLines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = node(PURE, ATTACHMENTS)

    def test_the_path_line_and_the_placeholder_name_the_file(self):
        self.assertEqual((self.data["line"], self.data["wait"]), ("📎 /host/uploads/abc/shot.png", "📎 uploading shot.png…"))

    def test_a_pasted_image_without_its_own_name_is_named_by_its_timestamp(self):
        self.assertEqual(self.data["names"], ["paste-20261127-090507.png", "paste-20261127-090507.jpeg", "paste-20261127-090507.png", "plan.md"])

    def test_a_line_lands_on_its_own_line_at_the_cursor(self):
        self.assertEqual(self.data["placed"], [
            {"value": "a\nL\nb", "caret": 3}, {"value": "a\nL\nb", "caret": 3}, {"value": "L", "caret": 1}, {"value": "a L b", "caret": 3},
        ])

    def test_the_placeholder_swaps_for_the_path_line_and_the_caret_moves_with_the_text(self):
        first, after, missing = self.data["swaps"]
        self.assertEqual((first["value"], first["caret"], first["found"]), ("a\n📎 /p/shot.png\nb", 0, True))
        self.assertEqual(after["caret"], 30 + len("📎 /p/shot.png") - len("📎 uploading shot.png…"))
        self.assertEqual((missing["value"], missing["found"]), ("a\nb", False))

    def test_a_failure_is_one_line_without_a_path(self):
        self.assertEqual(self.data["failed"], "⚠️ big.bin: 413 too large")

    def test_only_whole_path_lines_count_as_attachments(self):
        self.assertEqual(self.data["paths"], ["/h/a.png", "/h/a.png.bak"])

    def test_removing_a_chip_removes_exactly_its_line(self):
        self.assertEqual(self.data["removed"], "x\n📎 /h/a.png.bak\ny")
        self.assertEqual(self.data["kept"], "x\n📎 /h/a.png.bak")


class TestFieldAttachmentsWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = node(DOM, ATTACHMENTS, PAGE_ATTACH)

    def test_ctrl_v_of_text_uploads_nothing(self):
        self.assertEqual((self.data["plain"], self.data["mixed"], self.data["uploadsByText"]), (False, False, 0))

    def test_a_pasted_image_shows_its_placeholder_then_its_path_line_and_a_thumbnail_chip(self):
        pasted = self.data["pasted"]
        self.assertTrue(pasted["prevented"])
        self.assertRegex(pasted["value"], r"^intro\n📎 /host/uploads/abc/paste-\d{8}-\d{6}\.png$")
        self.assertRegex(self.data["sent"][0]["during"], r"^intro\n📎 uploading paste-\d{8}-\d{6}\.png…$")
        self.assertEqual((pasted["chips"], pasted["hidden"]), (1, False))
        self.assertRegex(pasted["thumb"], r"^blob:")

    def test_a_dropped_file_lands_as_its_line_with_a_file_icon_chip(self):
        dropped = self.data["dropped"]
        self.assertTrue(dropped["value"].endswith("\n📎 /host/uploads/abc/notes.txt"), dropped)
        self.assertEqual((dropped["chips"], dropped["icon"]), (2, "bi-file-earmark"))

    def test_an_upload_over_the_limit_or_to_an_unreachable_hub_leaves_the_error_and_no_path(self):
        self.assertEqual(self.data["over"]["sent"], 0)
        self.assertTrue(self.data["over"]["value"].endswith("\n⚠️ big.bin: too large, at most 50 MiB"), self.data["over"])
        self.assertTrue(self.data["down"].endswith("\n⚠️ down.png: upload failed, hub unreachable"), self.data["down"])
        self.assertNotRegex(self.data["down"], r"📎 /\S*down\.png")

    def test_the_chip_x_removes_the_chip_its_line_and_its_thumbnail(self):
        removed = self.data["removed"]
        self.assertNotIn(f"📎 {removed['path']}\n", f"{removed['value']}\n")
        self.assertEqual(removed["chips"], 1)
        self.assertEqual(len(removed["revoked"]), 1)
        self.assertRegex(removed["revoked"][0], r"^blob:")


class TestUploadsStorePastedImages(HubCase):
    def test_a_png_body_is_stored_and_its_host_path_is_the_line_the_field_names(self):
        headers = {**self.guard(self.host), "Content-Type": "application/octet-stream"}
        status, _, body = self.call("POST", "/api/uploads?name=paste-20261127-090507.png", PNG, headers)
        self.assertEqual(status, 201, body)
        upload = json.loads(body)
        self.assertEqual(upload["name"], "paste-20261127-090507.png")
        self.assertEqual(upload["path"], str(HOST_STATE / "uploads" / upload["id"] / "paste-20261127-090507.png"))
        self.assertEqual((self.state / "uploads" / upload["id"] / "paste-20261127-090507.png").read_bytes(), PNG)
        line = node("const A = require(process.argv[1]); console.log(JSON.stringify(A.paths(`note\n${A.pathLine(process.argv[2])}`)));", ATTACHMENTS, upload["path"])
        self.assertEqual(line, [upload["path"]])


if __name__ == "__main__":
    unittest.main()
