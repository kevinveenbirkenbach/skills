from __future__ import annotations

import json
import unittest

from hub_case import HubCase
from hub_support import PAGE, SCORE, TREE
from kvb_hub import mcp

TOOLS = {"review_request", "review_status", "review_wait", "review_list", "decision_request", "decision_wait", "operator_message"}


class TestHubMcp(HubCase):
    def test_mcp_round_trip(self):
        init = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", init["result"]["capabilities"])
        self.assertEqual(init["result"]["serverInfo"]["name"], "kvb-hub")
        self.assertEqual(self.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"], mcp.PROTOCOLS[0])
        status, _, body = self.post_mcp({"jsonrpc": "2.0", "method": "notifications/initialized"}, {})
        self.assertEqual((status, body), (202, b""))
        self.assertEqual(self.rpc("ping", {})["result"], {})
        tools = self.rpc("tools/list", {})["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, TOOLS)
        for entry in tools:
            with self.subTest(tool=entry["name"]):
                schema = entry["inputSchema"]
                self.assertEqual((schema["type"], schema["additionalProperties"]), ("object", False))
                self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]))
        review_id = self.request("feat: hub", "table")
        self.assertRegex(review_id, r"^[0-9a-f]{16}$")
        state = self.tool("review_status", {"id": review_id})
        self.assertEqual(json.loads(state["content"][0]["text"]), state["structuredContent"])
        self.assertEqual(state["structuredContent"], {"id": review_id, "status": "pending", "tree": TREE, "decided": None})
        listed = self.tool("review_list", {})["structuredContent"]["reviews"]
        self.assertEqual([(r["id"], r["title"], r["tree"]) for r in listed], [(review_id, "feat: hub", TREE)])
        self.assertEqual(self.rpc("resources/list", {})["error"]["code"], -32601)
        self.assertEqual(self.rpc("tools/call", {"name": "review_approve", "arguments": {"id": review_id}})["error"]["code"], -32602)
        status, _, body = self.call("POST", "/mcp", b"{not json", {"Host": self.host, "Content-Type": "application/json"})
        self.assertEqual((status, json.loads(body)["error"]["code"]), (400, -32700))

    def test_tool_arguments_are_validated(self):
        good = self.arguments("feat: x", "", self.page("bundle.html", PAGE))
        for name, arguments in (
            ("review_request", {k: v for k, v in good.items() if k != "notes"}),
            ("review_request", {k: v for k, v in good.items() if k != "repo"}),
            ("review_request", {**good, "repo": "relative/.git"}),
            ("review_request", {**good, "extra": "1"}),
            ("review_request", {**good, "tree": "HEAD"}),
            ("review_request", {**good, "title": "   "}),
            ("review_request", {**good, "title": "two\nlines"}),
            ("review_request", {**good, "worktree": "relative/path"}),
            ("review_request", {**good, "branch": "has space"}),
            ("review_request", {**good, "notes": 5}),
            ("review_request", {k: v for k, v in good.items() if k != "gate"}),
            ("review_request", {k: v for k, v in good.items() if k != "score"}),
            ("review_request", {**good, "gate": "maybe"}),
            ("review_request", {**good, "score": 5}),
            ("review_request", {**good, "score": "x" * 501}),
            ("review_status", {"id": "../../etc"}),
            ("review_status", {"id": "0123456789abcdef"}),
            ("review_wait", {"id": "0123456789abcdef", "timeout_seconds": 1}),
            ("review_list", {"extra": 1}),
        ):
            with self.subTest(name=name, arguments=arguments):
                self.assertTrue(self.tool(name, arguments)["isError"])
        review_id = self.request("feat: x", "")
        for timeout in (-1, True, "5", None, float("nan"), float("inf")):
            with self.subTest(timeout=timeout):
                self.assertTrue(self.tool("review_wait", {"id": review_id, "timeout_seconds": timeout})["isError"])
        bad = self.rpc("tools/call", {"name": "review_status", "arguments": ["x"]})
        self.assertEqual(bad["error"]["code"], -32602)

    def test_mcp_rejects_foreign_origins_hosts_and_simple_requests(self):
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        self.assertEqual(self.post_mcp(ping, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.post_mcp(ping, {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.post_mcp(ping, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.post_mcp(ping, {"Origin": f"http://{self.host}"})[0], 200)
        self.assertEqual(self.get("/mcp")[0], 405)

    def test_mcp_requires_gate_score_and_recommended(self):
        tools = {entry["name"]: entry["inputSchema"] for entry in self.rpc("tools/list", {})["result"]["tools"]}
        self.assertEqual(tools["review_request"]["properties"]["gate"]["enum"], ["pass", "fail"])
        self.assertTrue({"gate", "score"} <= set(tools["review_request"]["required"]))
        self.assertIn("recommended", tools["decision_request"]["required"])
        review_id = self.request("feat: gated", "")
        decision_id = self.decision("Wait")
        inbox = {item["id"]: item for item in self.snapshot()["inbox"]}
        self.assertEqual((inbox[review_id]["gate"], inbox[review_id]["score"], inbox[review_id]["green"]), ("pass", SCORE, True))
        self.assertEqual((inbox[decision_id]["recommended"], inbox[decision_id]["green"]), ("Wait", True))
        plain = self.decision("")
        self.assertFalse(next(item for item in self.snapshot()["inbox"] if item["id"] == plain)["green"])


if __name__ == "__main__":
    unittest.main()
