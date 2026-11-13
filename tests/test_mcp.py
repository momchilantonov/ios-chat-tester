import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, FakeApp, FakeDriverServer

SERVER = ROOT / "tester" / "simchat_server.py"


class McpTest(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.drv = FakeDriverServer(self.app)
        self.tmp = tempfile.TemporaryDirectory()
        cfg = {"app": {"bundle_id": "com.example.ChatDemo"},
               "driver": {"port": self.drv.port, "manage": False, "token": self.drv.token},
               "pace_ms": 0, "waits": {"reply_timeout_s": 3, "quiet_ms": 300, "poll_ms": 80, "send_confirm_s": 2}}
        path = Path(self.tmp.name) / "config.json"
        path.write_text(json.dumps(cfg))
        env = dict(os.environ, SIMCHAT_CONFIG=str(path))
        self.proc = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
        self.n = 0

    def tearDown(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=5)
        self.proc.stdout.close()
        self.proc.stderr.close()
        self.drv.close()
        self.tmp.cleanup()

    def rpc(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.n += 1
            msg["id"] = self.n
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        return json.loads(self.proc.stdout.readline())

    def call(self, name, **args):
        res = self.rpc("tools/call", {"name": name, "arguments": args})["result"]
        return res["isError"], json.loads(res["content"][0]["text"])

    def test_handshake_tools_and_a_conversation(self):
        init = self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                       "clientInfo": {"name": "t", "version": "1"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(init["result"]["serverInfo"]["name"], "simchat")
        self.rpc("notifications/initialized", notify=True)
        tools = self.rpc("tools/list")["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertTrue({"status", "send_message", "wait_for_reply", "tap", "end_run", "scenarios"} <= names)
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
        err, res = self.call("send_message", text="Здравей")
        self.assertFalse(err, res)
        err, res = self.call("wait_for_reply")
        self.assertEqual(res["new_messages"], ["Hi! I can help with cards and payments."])
        err, res = self.call("tap", element=999)
        self.assertTrue(err)
        self.assertIn("error", res)
        err, res = self.call("send_message")
        self.assertTrue(err)
        self.assertIn("bad arguments", res["error"])
        self.assertEqual(self.rpc("nope")["error"]["code"], -32601)
        self.assertEqual(self.rpc("ping")["result"], {})

    def test_unknown_protocol_version_gets_latest(self):
        init = self.rpc("initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")


if __name__ == "__main__":
    unittest.main()
