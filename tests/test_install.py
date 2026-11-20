import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, load_module

install = load_module("install", ROOT / "install.py")


class InstallTest(unittest.TestCase):
    """Runs install.py against a copy of this repo so the real tester/ is untouched."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.clone = base / "clone"
        skip = shutil.ignore_patterns(
            "__pycache__", "config.json", "profile.md", "bin", ".install.json", ".build"
        )
        self.clone.mkdir()
        shutil.copy2(ROOT / "install.py", self.clone / "install.py")
        for part in ("templates", "tester"):
            shutil.copytree(ROOT / part, self.clone / part, ignore=skip)
        self.home = base / "copilot"
        self.vscode = base / "vscode"
        self.vscode.mkdir()
        (self.vscode / "mcp.json").write_text(
            json.dumps({"servers": {"other": {"type": "stdio", "command": "x"}}})
        )
        self.app_repo = base / "ios-app"
        self.app_repo.mkdir()
        self.mod = load_module("install_copy", self.clone / "install.py")
        self.stub_simctl(self.mod)

    def stub_simctl(self, mod):
        """No test may touch the real simulator (e.g. uninstall the driver's runner app while a driver runs):
        every `xcrun simctl` the installer runs is recorded and answered here."""
        self.simctl_calls, self.booted = [], []
        real = mod.Installer.run

        def run(inst, cmd, timeout=30):
            if list(cmd[:2]) == ["xcrun", "simctl"]:
                self.simctl_calls.append(list(cmd))
                if "list" in cmd:
                    return 0, json.dumps(
                        {
                            "devices": {
                                "iOS-18": [
                                    {"udid": u, "name": "iPhone", "state": "Booted"}
                                    for u in self.booted
                                ]
                            }
                        }
                    )
                return 0, ""
            return real(inst, cmd, timeout)

        mod.Installer.run = run

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, *extra, answers=None, tty=False):
        lines = []
        replies = list(answers or [])

        def inp(prompt):
            lines.append(prompt)
            if not replies:
                raise AssertionError(f"unexpected question: {prompt}")
            return replies.pop(0)

        code = self.mod.main(
            [
                "--copilot-home",
                str(self.home),
                "--vscode-dir",
                str(self.vscode),
                "--skip-build",
            ]
            + list(extra),
            out=lines.append,
            inp=inp,
            tty=tty,
        )
        self.assertEqual(replies, [], "not all answers were used")
        return code, "\n".join(lines)

    def test_guided_install_confirms_each_step(self):
        answers = [
            "my-tester",
            "com.example.App",
            str(self.app_repo),
            "",
            "1",
            "y",  # step 2 local settings
            "n",  # step 3 skipped
            "y",
        ]  # step 4 (build skipped by flag)
        code, out = self.run_install("--guided", answers=answers)
        self.assertIn("Step 3 of 4", out)
        self.assertIn("skipped", out)
        self.assertTrue((self.clone / "tester" / "config.json").exists())
        self.assertFalse((self.home / "agents" / "my-tester.agent.md").exists())
        # Defaults come from the existing config on the second run; q stops cleanly.
        code, out = self.run_install("--guided", answers=["", "", "", "", "", "y", "q"])
        self.assertEqual(code, 1)
        self.assertIn("[my-tester]", out)
        self.assertIn("stopped", out)
        self.assertFalse((self.home / "agents" / "my-tester.agent.md").exists())
        code, out = self.run_install(
            "--guided", answers=["", "", "", "", "", "y", "y", "y"]
        )
        self.assertTrue((self.home / "agents" / "my-tester.agent.md").exists())
        self.assertTrue(
            json.loads((self.clone / "tester" / ".install.json").read_text())["files"]
        )

    def test_uninstall_asks_in_a_terminal(self):
        self.run_install("--bundle-id", "a.b")
        agent = self.home / "agents" / "chat-tester.agent.md"
        _, out = self.run_install("--uninstall", answers=["n"], tty=True)
        self.assertIn("nothing removed", out)
        self.assertTrue(agent.exists())
        _code, out = self.run_install("--uninstall", answers=["y"], tty=True)
        self.assertFalse(agent.exists())
        self.assertFalse((self.clone / "tester" / "bin" / "chat-tester").exists())
        self.assertIn("rm -rf", out)

    def test_fresh_install_rerun_and_uninstall(self):
        code, out = self.run_install(
            "--name",
            "my-tester",
            "--bundle-id",
            "com.example.App",
            "--app-repo",
            str(self.app_repo),
        )
        self.assertEqual(code, 0, out)
        agent = (self.home / "agents" / "my-tester.agent.md").read_text()
        planner = (self.home / "agents" / "my-tester-planner.agent.md").read_text()
        self.assertIn("name: my-tester-planner", planner)
        self.assertIn("my-tester agent", planner)
        self.assertNotIn("{{", planner)
        self.assertIn("my-tester-planner", agent)
        self.assertTrue(
            (self.home / "skills" / "test-plan-format" / "SKILL.md").exists()
        )
        self.assertTrue((self.clone / "tester" / "bin" / "my-tester-planner").exists())
        self.assertIn("name: my-tester", agent)
        self.assertIn(str(self.app_repo), agent)
        self.assertNotIn("{{", agent)
        for skill in ("chat-testing", "chat-test-report", "test-plan-format"):
            text = (self.home / "skills" / skill / "SKILL.md").read_text()
            self.assertNotIn("{{", text)
        mcp = json.loads((self.home / "mcp-config.json").read_text())
        # macOS: /var -> /private/var
        self.assertEqual(
            [
                str(__import__("pathlib").Path(a).resolve())
                for a in mcp["mcpServers"]["simchat"]["args"]
            ],
            [str((self.clone / "tester" / "simchat_server.py").resolve())],
        )
        vs = json.loads((self.vscode / "mcp.json").read_text())
        self.assertIn("other", vs["servers"])
        self.assertIn("simchat", vs["servers"])
        cfg = json.loads((self.clone / "tester" / "config.json").read_text())
        self.assertEqual(cfg["app"]["bundle_id"], "com.example.App")
        self.assertEqual(cfg["repos"]["app"], str(self.app_repo.resolve()))
        self.assertTrue((self.clone / "tester" / "profile.md").exists())
        launcher = (self.clone / "tester" / "bin" / "my-tester").read_text()
        self.assertIn("--agent=my-tester --allow-tool simchat ", launcher)
        import subprocess

        res = subprocess.run(
            ["bash", "-n", str(self.clone / "tester" / "bin" / "my-tester")],
            capture_output=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("non-interactive run (-p)", launcher)
        planner_launcher = (
            self.clone / "tester" / "bin" / "my-tester-planner"
        ).read_text()
        self.assertIn(
            "--agent=my-tester-planner --allow-tool simchat ", planner_launcher
        )
        self.assertIn(f"--add-dir={self.app_repo.resolve()}", launcher)

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
        self.assertFalse((self.home / "agents" / "my-tester-planner.agent.md").exists())
        self.assertFalse(skill.exists())
        # the installer created it: now empty
        self.assertFalse((self.home / "mcp-config.json").exists(), out)
        # existed before: kept, entry gone
        vs = json.loads((self.vscode / "mcp.json").read_text())
        self.assertEqual(list(vs["servers"]), ["other"])
        self.assertTrue((self.clone / "tester" / "config.json").exists())

    def test_uninstall_keeps_a_created_mcp_file_the_user_added_servers_to(self):
        code, out = self.run_install("--bundle-id", "a.b")
        self.assertEqual(code, 0, out)
        cfg = self.home / "mcp-config.json"
        data = json.loads(cfg.read_text())
        data["mcpServers"]["mine"] = {"command": "x"}  # added by hand after the install
        cfg.write_text(json.dumps(data))
        code, out = self.run_install("--uninstall", "--force")
        self.assertEqual(
            json.loads(cfg.read_text()), {"mcpServers": {"mine": {"command": "x"}}}
        )

    def test_into_main_repo_seen_through_a_submodule_symlink(self):
        """A main repo holds the agents; the submodule's .github/agents is a symlink to them. The installed file,
        seen through that symlink, is not a 'same-named agent'. A real other file with that name still is."""
        main = Path(self.tmp.name) / "main"
        (main / ".github" / "agents").mkdir(parents=True)
        (main / ".github" / "skills").mkdir()
        bot = main / "bot"
        (bot / ".github").mkdir(parents=True)
        (bot / ".github" / "agents").symlink_to(
            main / ".github" / "agents", target_is_directory=True
        )
        (bot / ".github" / "skills").symlink_to(
            main / ".github" / "skills", target_is_directory=True
        )
        code, out = self.run_install(
            "--into",
            str(main),
            "--bot-repo",
            str(bot),
            "--bundle-id",
            "a.b",
            "--no-vscode",
        )
        self.assertEqual(code, 0, out)
        self.assertNotIn("WARN", out)
        # visible inside the submodule
        self.assertTrue((bot / ".github" / "agents" / "chat-tester.agent.md").exists())
        other = Path(self.tmp.name) / "other"
        (other / ".github" / "agents").mkdir(parents=True)
        (other / ".github" / "agents" / "chat-tester.agent.md").write_text("")
        code, out = self.run_install(
            "--into",
            str(main),
            "--bot-repo",
            str(bot),
            "--app-repo",
            str(other),
            "--bundle-id",
            "a.b",
            "--no-vscode",
        )
        self.assertEqual(code, 1, out)
        self.assertIn("WARN", out)
        self.assertIn(str(other.resolve()), out)

    def test_uninstall_removes_per_file_links_and_the_mcp_file_it_created(self):
        """Links one per file (bot repo -> main repo) to our files go with them; a link to another agent stays.
        An MCP file the installer created goes too once it is empty; one that existed before stays."""
        main = Path(self.tmp.name) / "main"
        agents, skills = main / ".github" / "agents", main / ".github" / "skills"
        agents.mkdir(parents=True)
        skills.mkdir()
        (agents / "other.agent.md").write_text("someone else's agent")
        bot = main / "bot"
        (bot / ".github" / "agents").mkdir(parents=True)
        (bot / ".github" / "skills" / "test-plan-format").mkdir(parents=True)
        code, out = self.run_install(
            "--into",
            str(main),
            "--bot-repo",
            str(bot),
            "--bundle-id",
            "a.b",
            "--no-vscode",
        )
        self.assertEqual(code, 0, out)
        # a link to the file
        links = [
            bot / ".github" / "agents" / "chat-tester.agent.md",
            bot / ".github" / "agents" / "chat-tester-planner.agent.md",
            bot / ".github" / "skills" / "chat-testing",  # a link to the folder
            bot / ".github" / "skills" / "test-plan-format" / "SKILL.md",
        ]
        targets = [
            agents / "chat-tester.agent.md",
            agents / "chat-tester-planner.agent.md",
            skills / "chat-testing",
            skills / "test-plan-format" / "SKILL.md",
        ]
        for link, target in zip(links, targets):
            link.symlink_to(target)
        other = bot / ".github" / "agents" / "other.agent.md"
        other.symlink_to(agents / "other.agent.md")
        self.assertTrue((main / ".github" / "mcp.json").exists())
        code, out = self.run_install("--uninstall", "--force")
        self.assertEqual(code, 0, out)
        for link in links:
            self.assertFalse(os.path.lexists(str(link)), out)
        # held only the link
        self.assertFalse((bot / ".github" / "skills" / "test-plan-format").exists())
        self.assertTrue(other.exists())
        # created, now empty
        self.assertFalse((main / ".github" / "mcp.json").exists(), out)
        self.assertTrue((main / ".github").is_dir())  # still has agents/

    def test_uninstall_keeps_an_mcp_file_that_existed_before(self):
        repo = Path(self.tmp.name) / "botrepo"
        (repo / ".github").mkdir(parents=True)
        (repo / ".github" / "mcp.json").write_text(json.dumps({"mcpServers": {}}))
        self.run_install("--into", str(repo), "--bundle-id", "a.b", "--no-vscode")
        # a re-install keeps the flag
        self.run_install("--into", str(repo), "--bundle-id", "a.b", "--no-vscode")
        _code, _out = self.run_install("--uninstall", "--force")
        self.assertEqual(
            json.loads((repo / ".github" / "mcp.json").read_text()), {"mcpServers": {}}
        )

    def test_into_repo_and_dry_run(self):
        repo = Path(self.tmp.name) / "botrepo"
        (repo / ".github").mkdir(parents=True)
        (repo / ".github" / "mcp.json").write_text(
            json.dumps({"mcpServers": {"x": {"command": "y"}}})
        )
        code, out = self.run_install(
            "--into", str(repo), "--dry-run", "--bundle-id", "a.b"
        )
        self.assertIn("dry run", out)
        self.assertFalse((repo / ".github" / "agents").exists())
        code, out = self.run_install(
            "--into", str(repo), "--bundle-id", "a.b", "--no-vscode"
        )
        self.assertEqual(code, 0, out)
        self.assertFalse((repo / ".vscode" / "mcp.json").exists())
        code, out = self.run_install("--into", str(repo), "--bundle-id", "a.b")
        self.assertEqual(code, 0, out)
        self.assertTrue((repo / ".github" / "agents" / "chat-tester.agent.md").exists())
        self.assertTrue(
            (repo / ".github" / "skills" / "chat-testing" / "SKILL.md").exists()
        )
        self.assertEqual(
            set(json.loads((repo / ".github" / "mcp.json").read_text())["mcpServers"]),
            {"x", "simchat"},
        )
        self.assertIn(
            "simchat",
            json.loads((repo / ".vscode" / "mcp.json").read_text())["servers"],
        )

    def test_python_choice(self):
        _code, _out = self.run_install(
            "--bundle-id", "a.b", "--python", "/opt/py/bin/python3.11"
        )
        entry = json.loads((self.home / "mcp-config.json").read_text())["mcpServers"][
            "simchat"
        ]
        self.assertEqual(entry["command"], "/opt/py/bin/python3.11")
        python, _note = self.mod.pick_python()
        self.assertTrue(python)

    def test_same_named_agent_in_a_repo_is_reported(self):
        agents = self.app_repo / ".github" / "agents"
        agents.mkdir(parents=True)
        (agents / "chat-tester.agent.md").write_text("")
        code, out = self.run_install(
            "--bundle-id", "a.b", "--app-repo", str(self.app_repo)
        )
        self.assertEqual(code, 1)
        self.assertIn("chat-tester.agent.md exists (empty)", out)

    def test_ask_approval_keeps_prompts(self):
        self.run_install("--bundle-id", "a.b", "--ask-approval")
        launcher = (self.clone / "tester" / "bin" / "chat-tester").read_text()
        self.assertNotIn("--allow-tool", launcher)

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
