#!/usr/bin/env python3
"""Set up the live chat tester on this Mac - one command, no network, no packages.

    git clone <this repo> && cd <clone>
    python3 install.py              guided: asks a few questions, previews every step, waits for your OK
    python3 install.py --name my-tester --bundle-id <app bundle id> \\
        --app-repo ~/path/to/ios-app-repo --bot-repo ~/path/to/bot-repo      (no questions)

What it does:
  1. checks prerequisites (Python 3.9+, Xcode, simctl, Copilot CLI)
  2. creates tester/config.json and tester/profile.md from the examples (once; flags update config.json)
  3. installs the agent + skills for Copilot CLI (~/.copilot/agents, ~/.copilot/skills) and registers the
     "simchat" MCP server for Copilot CLI (~/.copilot/mcp-config.json) and VS Code (user mcp.json);
     writes the launcher tester/bin/<name>
     (or, with --into REPO, into REPO/.github/{agents,skills,mcp.json} and REPO/.vscode/mcp.json)
  4. builds the UI driver with xcodebuild

Re-run it after `git pull` - files it wrote before are updated, files you edited are kept (see --force).
    python3 install.py --dry-run      show what would happen
    python3 install.py --uninstall    stop the driver, remove it from the simulator and remove everything
                                      install.py put outside this folder (asks first). Then delete the folder.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTER = ROOT / "tester"
TEMPLATES = ROOT / "templates"
SERVER = TESTER / "simchat_server.py"
MANIFEST = TESTER / ".install.json"
MCP_NAME = "simchat"
SKILLS = ("chat-testing", "chat-test-report")
VSCODE_USER = Path("~/Library/Application Support/Code/User").expanduser()
RUNNER_ID = "dev.simchat.SimDriverUITests.xctrunner"  # the test-runner app Xcode installs on the simulator


class Quit(Exception):
    """The user answered q."""


class Installer:
    def __init__(self, args, out=print, inp=input, tty=None):
        self.a, self.out, self.inp = args, out, inp
        self.tty = sys.stdin.isatty() if tty is None else tty
        self.guided = False
        self.dry = args.dry_run
        self.problems = []
        self.old = self._load_manifest()
        self.manifest = {"files": {}, "json": []}

    # ------------------------------------------------------------------ helpers
    def say(self, text):
        self.out(text)

    def header(self, text):
        if not self.guided:
            self.say(text)

    def ask(self, question, default=""):
        answer = self.inp("%s%s: " % (question, " [%s]" % default if default else "")).strip()
        if answer.lower() == "q":
            raise Quit()
        return answer or default

    def confirm(self, question, default=True):
        if self.a.yes:
            return True
        while True:
            answer = self.inp("%s %s " % (question, "[Y/n/q]" if default else "[y/N/q]")).strip().lower()
            if not answer:
                return default
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            if answer in ("q", "quit"):
                raise Quit()

    @staticmethod
    def _sha(text):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _load_manifest(self):
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"files": {}, "json": []}

    def write(self, path, content, mode=None):
        """Write a generated file; keep it if the user edited it since we last wrote it."""
        path = Path(path)
        key = str(path)
        if path.exists():
            current = path.read_text(encoding="utf-8", errors="replace")
            if current == content:
                self.say("  same     %s" % path)
                self.manifest["files"][key] = self._sha(content)
                return
            ours = self.old["files"].get(key) == self._sha(current)
            if not ours and not self.a.force:
                self.say("  KEPT     %s (not written by install.py or edited since; --force overwrites)" % path)
                self.problems.append("kept %s" % path)
                return
            self.say("  update   %s" % path)
        else:
            self.say("  create   %s" % path)
        if not self.dry:
            self.manifest["files"][key] = self._sha(content)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            if mode:
                path.chmod(mode)

    def merge_json(self, path, key, entry):
        path = Path(path)
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except ValueError:
                self.say("  MANUAL   %s is not plain JSON (comments?). Add under \"%s\":\n%s"
                         % (path, key, json.dumps({MCP_NAME: entry}, indent=2)))
                self.problems.append("manual edit needed: %s" % path)
                return
        servers = data.setdefault(key, {})
        if servers.get(MCP_NAME) == entry:
            self.say("  same     %s (%s.%s)" % (path, key, MCP_NAME))
            self.manifest["json"].append({"path": str(path), "key": key})
            return
        if not self.dry:
            self.manifest["json"].append({"path": str(path), "key": key})
        self.say("  %s %s (%s.%s)" % ("merge   " if path.exists() else "create  ", path, key, MCP_NAME))
        servers[MCP_NAME] = entry
        if not self.dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def run(self, cmd, timeout=30):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return res.returncode, (res.stdout or res.stderr).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, str(exc)

    # ------------------------------------------------------------------ steps
    def prerequisites(self):
        self.header("[1/4] prerequisites")
        ok = sys.version_info >= (3, 9)
        self.say("  %s python %s (%s)" % ("ok  " if ok else "FAIL", platform.python_version(), sys.executable))
        if not ok:
            self.problems.append("Python 3.9+ required")
        self.mac = platform.system() == "Darwin"
        if not self.mac:
            self.say("  warn not macOS - files are generated, the driver build is skipped")
            return
        for label, cmd, required in (("xcode", ["xcodebuild", "-version"], True),
                                     ("simctl", ["xcrun", "simctl", "help"], True),
                                     ("copilot", ["copilot", "--version"], False)):
            code, text = self.run(cmd)
            first = text.splitlines()[0] if text else ""
            if code == 0:
                self.say("  ok   %s %s" % (label, first))
            else:
                self.say("  %s %s not found (%s)" % ("FAIL" if required else "warn", label, first[:120]))
                if required:
                    self.problems.append("%s missing - install Xcode and run: sudo xcode-select -s "
                                         "/Applications/Xcode.app" % label)

    def local_config(self):
        self.header("[2/4] local config (stays on this machine, git-ignored)")
        cfg_path, prof_path = TESTER / "config.json", TESTER / "profile.md"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except ValueError as exc:
                self.problems.append("%s is not valid JSON: %s" % (cfg_path, exc))
                self.say("  FAIL %s is not valid JSON" % cfg_path)
                self.cfg = {}
                return
            changed = False
        else:
            cfg = json.loads((TESTER / "config.example.json").read_text(encoding="utf-8"))
            changed = True
        if self.a.bundle_id:
            cfg.setdefault("app", {})["bundle_id"] = self.a.bundle_id
            changed = True
        repos = cfg.setdefault("repos", {})
        for role, path in self.repo_flags():
            repos[role] = str(Path(path).expanduser().resolve())
            changed = True
        cfg["agent_name"] = self.a.name
        self.cfg = cfg
        for role, path in repos.items():
            if not Path(path).is_dir():
                self.say("  warn repo %s: %s does not exist" % (role, path))
        if changed or not cfg_path.exists():
            self.say("  %s %s" % ("update  " if cfg_path.exists() else "create  ", cfg_path))
            if not self.dry:
                cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        else:
            self.say("  same     %s" % cfg_path)
        if not prof_path.exists():
            self.say("  create   %s - fill in the TODOs" % prof_path)
            if not self.dry:
                shutil.copy2(TESTER / "profile.example.md", prof_path)
        else:
            self.say("  same     %s" % prof_path)
        if not cfg.get("app", {}).get("bundle_id") or cfg["app"]["bundle_id"] == "com.example.ChatDemo":
            self.problems.append("set the app bundle id: --bundle-id or app.bundle_id in %s" % cfg_path)

    def repo_flags(self):
        out = []
        if self.a.app_repo:
            out.append(("app", self.a.app_repo))
        if self.a.bot_repo:
            out.append(("bot", self.a.bot_repo))
        for item in self.a.repo or []:
            role, _, path = item.partition("=")
            out.append((role, path))
        return out

    def render(self, text):
        repos = (getattr(self, "cfg", {}) or {}).get("repos") or {}
        lines = ["- %s: `%s`" % (role, path) for role, path in repos.items()]
        lines.append("- tester (scenarios, runs, profile): `%s`" % TESTER)
        return (text.replace("{{AGENT_NAME}}", self.a.name)
                    .replace("{{TESTER_DIR}}", str(TESTER))
                    .replace("{{REPOS}}", "\n".join(lines)))

    def agent_files(self):
        python = sys.executable or "python3"
        cli_entry = {"type": "local", "command": python, "args": [str(SERVER)], "env": {}, "tools": ["*"]}
        code_entry = {"type": "stdio", "command": python, "args": [str(SERVER)]}
        agent = self.render((TEMPLATES / "agent.md").read_text(encoding="utf-8"))
        if self.a.into:
            repo = Path(self.a.into).expanduser().resolve()
            self.header("[3/4] agent, skills and MCP registration into %s" % repo)
            base = repo / ".github"
            self.write(base / "agents" / ("%s.agent.md" % self.a.name), agent)
            for skill in SKILLS:
                self.write(base / "skills" / skill / "SKILL.md",
                           self.render((TEMPLATES / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")))
            self.merge_json(base / "mcp.json", "mcpServers", cli_entry)
            self.merge_json(repo / ".vscode" / "mcp.json", "servers", code_entry)
        else:
            home = Path(self.a.copilot_home).expanduser()
            self.header("[3/4] agent, skills and MCP registration (user level: %s)" % home)
            self.write(home / "agents" / ("%s.agent.md" % self.a.name), agent)
            for skill in SKILLS:
                self.write(home / "skills" / skill / "SKILL.md",
                           self.render((TEMPLATES / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")))
            self.merge_json(home / "mcp-config.json", "mcpServers", cli_entry)
            vscode = Path(self.a.vscode_dir).expanduser()
            if self.a.no_vscode:
                pass
            elif vscode.is_dir():
                self.merge_json(vscode / "mcp.json", "servers", code_entry)
            else:
                self.say("  skip     VS Code user folder %s not found (use --vscode-dir)" % vscode)
        dirs = [str(TESTER)] + [p for _, p in sorted((self.cfg.get("repos") or {}).items())]
        add = " ".join("--add-dir=%s" % _sh(d) for d in dirs)
        launcher = ("#!/bin/bash\n# Start the %s agent in Copilot CLI with read access to the tester and repos.\n"
                    "# Run it from the folder you want as the working directory (e.g. the bot repo).\n"
                    "exec copilot --agent=%s %s \"$@\"\n" % (self.a.name, self.a.name, add))
        self.write(TESTER / "bin" / self.a.name, launcher, mode=0o755)

    def build_driver(self):
        self.header("[4/4] UI driver build")
        if self.a.skip_build or not getattr(self, "mac", False):
            self.say("  skip     (%s)" % ("--skip-build" if self.a.skip_build else "not macOS"))
            return
        if self.dry:
            self.say("  would run tester/driver/run-driver.sh --build-only")
            return
        log = TESTER / "driver" / ".build" / "install-build.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.say("  building (1-3 min the first time) - log: %s" % log)
        with open(log, "w", encoding="utf-8") as fh:
            code = subprocess.call(["bash", str(TESTER / "driver" / "run-driver.sh"), "--build-only"],
                                   stdout=fh, stderr=subprocess.STDOUT)
        if code == 0:
            self.say("  ok       driver built")
        else:
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()
            errors = [ln for ln in tail if "error:" in ln][-8:] or tail[-8:]
            self.say("  FAIL     xcodebuild exited %d:\n    %s" % (code, "\n    ".join(errors)))
            self.problems.append("driver build failed - see %s" % log)

    def save_manifest(self):
        if not self.a.dry_run and (self.manifest["files"] or self.manifest["json"]):
            merged = dict(self.old.get("files", {}))
            merged.update(self.manifest["files"])
            jsons = {(j["path"], j["key"]) for j in self.old.get("json", []) + self.manifest["json"]}
            MANIFEST.write_text(json.dumps({"files": merged, "json": [{"path": p, "key": k} for p, k in sorted(jsons)]},
                                           indent=2) + "\n", encoding="utf-8")

    def install(self):
        self.prerequisites()
        self.local_config()
        self.agent_files()
        self.build_driver()
        self.save_manifest()
        return self.finish()

    # ------------------------------------------------------------------ guided
    def _existing_config(self):
        try:
            return json.loads((TESTER / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _ask_dir(self, question, default):
        while True:
            answer = self.ask(question + " (empty = skip)", default)
            if not answer:
                return None
            path = Path(answer).expanduser()
            if path.is_dir():
                return str(path.resolve())
            self.say("  %s is not a folder - try again" % path)

    def _step(self, number, title, explain, fn, ask=True):
        self.say("")
        self.say("== Step %d of 4: %s" % (number, title))
        for line in explain:
            self.say("   " + line)
        if not ask:
            fn()
            return
        self.say("   Preview:")
        self.dry = True
        fn()
        if self.confirm("   Do step %d?" % number):
            self.dry = False
            self.say("   Result:")
            fn()
        else:
            self.say("   skipped - you can run install.py again later")

    def guided_install(self):
        self.guided = True
        cfg = self._existing_config()
        self.say("Guided setup of the live chat tester. 4 steps; nothing changes before you confirm a step.")
        self.say("Answer with Enter to accept [the default], q to quit at any time.")
        self.say("")
        self.a.name = self.ask("Agent name (letters, digits, - and _)", cfg.get("agent_name") or self.a.name)
        while not all(c.isalnum() or c in "-_" for c in self.a.name):
            self.a.name = self.ask("Only letters, digits, - and _ please", "chat-tester")
        self.say("  The bundle id is in Xcode: app target > General > Bundle Identifier.")
        bundle = (cfg.get("app") or {}).get("bundle_id", "")
        self.a.bundle_id = self.ask("Bundle id of the app under test",
                                    "" if bundle == "com.example.ChatDemo" else bundle) or None
        repos = cfg.get("repos") or {}
        self.a.app_repo = self._ask_dir("Folder of the iOS app repo (the agent may read it)", repos.get("app", ""))
        self.a.bot_repo = self._ask_dir("Folder of the bot/backend repo (the agent may read it)", repos.get("bot", ""))
        where = self.ask("Install the agent for your user - works in every folder (1) - or into one repo's "
                         ".github/.vscode (2)?", "1")
        if where == "2":
            self.a.into = self._ask_dir("Repo to install into", self.a.bot_repo or "")
        self._step(1, "check prerequisites", ["Python 3.9+, Xcode, simctl, Copilot CLI. Changes nothing."],
                   self.prerequisites, ask=False)
        if self.problems and not self.confirm("   Some prerequisites are missing. Continue anyway?", default=False):
            return self.finish()
        self._step(2, "local settings", [
            "Creates/updates tester/config.json (bundle id, repos) and tester/profile.md.",
            "Both stay in this folder and are git-ignored - your project details never get pushed."],
            self.local_config)
        target = (Path(self.a.into) / ".github") if self.a.into else Path(self.a.copilot_home).expanduser()
        self._step(3, "agent, skills and tool registration", [
            "Writes the agent '%s' and 2 skills into %s," % (self.a.name, target),
            "registers the 'simchat' tool for Copilot CLI and VS Code (other entries are kept),",
            "and writes the launcher tester/bin/%s." % self.a.name], self.agent_files)
        self._step(4, "build the UI driver", [
            "Runs xcodebuild on tester/driver (1-3 minutes the first time). Offline, nothing installed globally."],
            self.build_driver)
        self.save_manifest()
        return self.finish()

    def finish(self):
        self.problems = list(dict.fromkeys(self.problems))
        self.say("")
        if self.problems:
            self.say("Finished with %d thing(s) to fix:" % len(self.problems))
            for p in self.problems:
                self.say("  - %s" % p)
        else:
            self.say("Done%s." % (" (dry run - nothing written)" if self.dry else ""))
        self.say("Next:\n"
                 "  1. fill in %s/profile.md and check %s/config.json\n"
                 "  2. run your app in the simulator (Xcode), start the local stack\n"
                 "  3. smoke test:  %s %s demo \"Hello\"\n"
                 "  4. Copilot CLI: %s/bin/%s     VS Code: Copilot Chat -> agent picker -> %s"
                 % (TESTER, TESTER, _sh(sys.executable or "python3"), SERVER, TESTER, self.a.name, self.a.name))
        return 1 if self.problems else 0

    def uninstall(self):
        if self.tty and not self.dry and not self.a.yes:
            self.say("This will:")
            self.dry = True
            self._uninstall()
            if not self.confirm("Remove all of the above?", default=False):
                self.say("nothing removed")
                return 0
            self.dry = False
        return self._uninstall()

    def _driver_cleanup(self):
        sys.path.insert(0, str(TESTER))
        try:
            from simchat.config import load_config
            from simchat.driver import STATE_FILE, DriverError, DriverManager, Simulator
        except ImportError as exc:
            self.say("  skip     driver cleanup (%s)" % exc)
            return
        cfg = load_config()
        sim = Simulator(cfg)
        if STATE_FILE.exists():
            self.say("  stop     the UI driver process")
            if not self.dry:
                DriverManager(cfg, sim).stop()
        if platform.system() != "Darwin":
            return
        try:
            booted = sim.booted()
        except DriverError:
            booted = []
        for dev in booted:
            self.say("  remove   driver runner app %s from simulator %s (if present)" % (RUNNER_ID, dev["name"]))
            if not self.dry:
                self.run(["xcrun", "simctl", "uninstall", dev["udid"], RUNNER_ID])

    def _uninstall(self):
        self._driver_cleanup()
        for path, sha in self.old.get("files", {}).items():
            p = Path(path)
            if not p.exists():
                continue
            if self._sha(p.read_text(encoding="utf-8", errors="replace")) != sha and not self.a.force:
                self.say("  KEPT     %s (edited since install; --force removes)" % p)
                continue
            self.say("  remove   %s" % p)
            if not self.dry:
                p.unlink()
                for parent in (p.parent, p.parent.parent):
                    try:
                        parent.rmdir()  # only if now empty
                    except OSError:
                        break
        for item in self.old.get("json", []):
            p = Path(item["path"])
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if MCP_NAME in data.get(item["key"], {}):
                self.say("  unmerge  %s (%s.%s)" % (p, item["key"], MCP_NAME))
                del data[item["key"]][MCP_NAME]
                if not self.dry:
                    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if not self.dry and MANIFEST.exists():
            MANIFEST.unlink()
        if not self.dry:
            self.say("done. Left in place: this folder with your config.json, profile.md, scenarios/, runs/ and")
            self.say("the driver build. To delete all of it:  rm -rf %s" % _sh(ROOT))
            self.say("(simulators that were not booted may still have the runner app: "
                     "xcrun simctl uninstall <udid> %s)" % RUNNER_ID)
        return 0


def _sh(text):
    text = str(text)
    if all(c.isalnum() or c in "/._-~=+:@" for c in text):
        return text
    return "'" + text.replace("'", "'\\''") + "'"


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="chat-tester", help="agent name (default: chat-tester)")
    ap.add_argument("--bundle-id", help="bundle id of the app under test")
    ap.add_argument("--app-repo", help="iOS app repository the agent may read")
    ap.add_argument("--bot-repo", help="bot/backend repository the agent may read")
    ap.add_argument("--repo", action="append", metavar="ROLE=PATH", help="another repository the agent may read")
    ap.add_argument("--into", metavar="REPO", help="install agent/skills/MCP into REPO/.github instead of ~/.copilot")
    ap.add_argument("--copilot-home", default=os.environ.get("COPILOT_HOME", "~/.copilot"))
    ap.add_argument("--vscode-dir", default=str(VSCODE_USER), help="VS Code user settings folder")
    ap.add_argument("--no-vscode", action="store_true", help="do not register the MCP server in VS Code")
    ap.add_argument("--skip-build", action="store_true", help="do not build the UI driver")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite/remove files even if edited by hand")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--guided", action="store_true", help="ask questions and confirm every step (default "
                    "when run without arguments in a terminal)")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    a = ap.parse_args(argv)
    if not all(c.isalnum() or c in "-_" for c in a.name):
        ap.error("--name may contain letters, digits, - and _ only")
    return a


def main(argv=None, out=print, inp=input, tty=None):
    raw = sys.argv[1:] if argv is None else argv
    a = parse(argv)
    inst = Installer(a, out, inp, tty)
    try:
        if a.uninstall:
            return inst.uninstall()
        if a.guided or (not raw and inst.tty):
            return inst.guided_install()
        return inst.install()
    except (Quit, KeyboardInterrupt, EOFError):
        inst.save_manifest()
        out("\nstopped - steps you confirmed are done, nothing else was changed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
