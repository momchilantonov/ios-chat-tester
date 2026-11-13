import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from helpers import ROOT

import importlib.util

spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class InstallTest(unittest.TestCase):
    """Runs install.py against a copy of this repo so the real tester/ is untouched."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.clone = base / "clone"
        skip = shutil.ignore_patterns("__pycache__", "config.json", "profile.md", "bin", ".install.json", ".build")
        self.clone.mkdir()
        shutil.copy2(ROOT / "install.py", self.clone / "install.py")
        for part in ("templates", "tester"):
            shutil.copytree(ROOT / part, self.clone / part, ignore=skip)
        self.home = base / "copilot"
        self.vscode = base / "vscode"
        self.vscode.mkdir()
        (self.vscode / "mcp.json").write_text(json.dumps({"servers": {"other": {"type": "stdio", "command": "x"}}}))
        self.app_repo = base / "ios-app"
        self.app_repo.mkdir()
        spec = importlib.util.spec_from_file_location("install_copy", self.clone / "install.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, *extra):
        lines = []
        code = self.mod.main(["--copilot-home", str(self.home), "--vscode-dir", str(self.vscode),
                              "--skip-build"] + list(extra), out=lines.append)
        return code, "\n".join(lines)

    def test_fresh_install_rerun_and_uninstall(self):
        code, out = self.run_install("--name", "my-tester", "--bundle-id", "com.example.App",
                                     "--app-repo", str(self.app_repo))
        self.assertEqual(code, 0, out)
        agent = (self.home / "agents" / "my-tester.agent.md").read_text()
        self.assertIn("name: my-tester", agent)
        self.assertIn(str(self.app_repo), agent)
        self.assertNotIn("{{", agent)
        for skill in ("chat-testing", "chat-test-report"):
            text = (self.home / "skills" / skill / "SKILL.md").read_text()
            self.assertNotIn("{{", text)
        mcp = json.loads((self.home / "mcp-config.json").read_text())
        self.assertEqual(mcp["mcpServers"]["simchat"]["args"], [str(self.clone / "tester" / "simchat_server.py")])
        vs = json.loads((self.vscode / "mcp.json").read_text())
        self.assertIn("other", vs["servers"])
        self.assertIn("simchat", vs["servers"])
        cfg = json.loads((self.clone / "tester" / "config.json").read_text())
        self.assertEqual(cfg["app"]["bundle_id"], "com.example.App")
        self.assertEqual(cfg["repos"]["app"], str(self.app_repo.resolve()))
        self.assertTrue((self.clone / "tester" / "profile.md").exists())
        launcher = (self.clone / "tester" / "bin" / "my-tester").read_text()
        self.assertIn("--agent=my-tester", launcher)
        self.assertIn("--add-dir=%s" % self.app_repo.resolve(), launcher)

        code, out = self.run_install("--name", "my-tester")
        self.assertEqual(code, 0, out)
        step3 = out.split("[3/4]")[1].split("[4/4]")[0]
        self.assertNotIn("create", step3)
        self.assertNotIn("update", step3)
        self.assertNotIn("KEPT", out)

        # A hand-edited generated file is kept on re-install unless --force.
        skill = self.home / "skills" / "chat-testing" / "SKILL.md"
        skill.write_text(skill.read_text() + "\nmy local tweak\n")
        code, out = self.run_install("--name", "my-tester")
        self.assertEqual(code, 1)
        self.assertIn("KEPT", out)
        self.assertIn("my local tweak", skill.read_text())

        code, out = self.run_install("--name", "my-tester", "--uninstall", "--force")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.home / "agents" / "my-tester.agent.md").exists())
        self.assertFalse(skill.exists())
        self.assertNotIn("simchat", json.loads((self.home / "mcp-config.json").read_text())["mcpServers"])
        vs = json.loads((self.vscode / "mcp.json").read_text())
        self.assertEqual(list(vs["servers"]), ["other"])
        self.assertTrue((self.clone / "tester" / "config.json").exists())

    def test_into_repo_and_dry_run(self):
        repo = Path(self.tmp.name) / "botrepo"
        (repo / ".github").mkdir(parents=True)
        (repo / ".github" / "mcp.json").write_text(json.dumps({"mcpServers": {"x": {"command": "y"}}}))
        code, out = self.run_install("--into", str(repo), "--dry-run", "--bundle-id", "a.b")
        self.assertIn("dry run", out)
        self.assertFalse((repo / ".github" / "agents").exists())
        code, out = self.run_install("--into", str(repo), "--bundle-id", "a.b")
        self.assertEqual(code, 0, out)
        self.assertTrue((repo / ".github" / "agents" / "chat-tester.agent.md").exists())
        self.assertTrue((repo / ".github" / "skills" / "chat-testing" / "SKILL.md").exists())
        self.assertEqual(set(json.loads((repo / ".github" / "mcp.json").read_text())["mcpServers"]), {"x", "simchat"})
        self.assertIn("simchat", json.loads((repo / ".vscode" / "mcp.json").read_text())["servers"])

    def test_jsonc_file_is_not_rewritten(self):
        (self.vscode / "mcp.json").write_text('{ // comment\n "servers": {} }')
        code, out = self.run_install("--bundle-id", "a.b")
        self.assertEqual(code, 1)
        self.assertIn("MANUAL", out)
        self.assertIn("// comment", (self.vscode / "mcp.json").read_text())

    def test_missing_bundle_id_is_reported(self):
        code, out = self.run_install()
        self.assertEqual(code, 1)
        self.assertIn("bundle id", out)


if __name__ == "__main__":
    unittest.main()
