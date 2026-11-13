# Live chat tester for iOS Simulator apps

An agent for **GitHub Copilot CLI** and **VS Code** that tests the chat assistant inside your iOS app *live*:
it behaves like a real user in the iOS Simulator. It types messages, taps quick-reply buttons and waits for
replies, then checks the bot's own evidence (local HTTP endpoint, logs) and writes a test report.
You can watch everything happen in the Simulator window.

- **No dependencies.** Python 3.9+ standard library and Xcode. No pip, npm, Homebrew or accounts.
- **Nothing leaves the machine.** The tools talk only to the Simulator and to `127.0.0.1`.
- **Unicode typing.** Uses Apple's XCTest, so any language works.

```
Copilot CLI / VS Code ── agent "<name>" + skills chat-testing, chat-test-report
        │ MCP (stdio)
tester/simchat_server.py ── send_message · wait_for_reply · tap · swipe · long_press · scroll · screen · fetch · read_log · runs
        │ JSON over 127.0.0.1                      │ GET 127.0.0.1 / read log files
tester/driver (XCTest UI test, runs forever) ──▶  your app in the booted Simulator ──▶ your local bot/backend
```

## Install (on the Mac)
```bash
git clone https://github.com/momchilantonov/ios-chat-tester.git ~/tools/ios-chat-tester
cd ~/tools/ios-chat-tester
python3 install.py
```
Without arguments, the installer is **guided**:
- It asks for the agent name, the app's bundle id, and the folders of your iOS app repo and bot repo.
- Then it goes through 4 steps. For each one it shows what will change and waits for your OK
  (`Y`es, `n`o to skip, `q` to quit).

| Step | What it does |
|---|---|
| 1 Prerequisites | Checks Python 3.9+, Xcode, `simctl` and Copilot CLI. Changes nothing. |
| 2 Local settings | Creates `tester/config.json` and `tester/profile.md`. Both stay local and are git-ignored. |
| 3 Agent and tools | Puts the agent and 2 skills into `~/.copilot/agents` and `~/.copilot/skills`, registers the `simchat` tool for Copilot CLI (`~/.copilot/mcp-config.json`) and VS Code (user `mcp.json`), and writes the launcher `tester/bin/<name>`. |
| 4 UI driver | Builds `tester/driver` with `xcodebuild`. Takes 1–3 min the first time and works offline. |

Other ways to run it:
- Without questions: `python3 install.py --name my-tester --bundle-id <id> --app-repo <dir> --bot-repo <dir>`.
- Preview only: add `--dry-run`.
- Into one repo's `.github`/`.vscode` instead of your user folders: add `--into <repo>`.
- **Update:** `git pull`, then `python3 install.py` again. Files it wrote earlier are updated; files you
  edited by hand are kept unless you add `--force`.

## Use it: step by step
Once, after installing:
1. **Fill in `tester/profile.md`.** This is what the agent reads first: your product, the customer's
   language, how you start the local stack, where the evidence is, the error reply text and your rules.
2. **Check `tester/config.json`:**
   - `endpoints`: the bot's local conversation/event URL.
   - `logs`: the file your bot logs to. Start the bot with `... 2>&1 | tee <that file>`.
   - `chat.send_labels`: only needed if your Send button isn't found.

Every test session:
1. **Start your local stack** (bot, mocks) the way your profile describes, logging to the file in `config.json`.
2. **Start the app:** in Xcode press **Run (⌘R)** on a simulator, then open the chat screen.
3. **Optional smoke test, without the agent:** `python3 tester/simchat_server.py demo "Hello"`.
   - The first time, this starts the UI driver, which takes about 30 s.
   - Watch the Simulator: the message is typed and sent, and the reply is printed.
4. **Start the agent:**
   - **Copilot CLI:** run `~/tools/ios-chat-tester/tester/bin/<name>` from your bot repo. The first time,
     trust the folder and allow the `simchat` tools.
   - **VS Code:** Copilot Chat → agent picker → `<name>`.
5. **Ask for a test.** For example:
   - `Run the example-greeting scenario`
   - `Test blocking a lost card, as an impatient customer`
   - `Reproduce: after tapping "X" the bot answers with the fallback`
6. **Watch the Simulator** and answer the agent if it asks something, for example the session id.
7. **Read the result:**
   - The agent replies with the verdict, its findings and the report path:
     `tester/runs/<time>_<name>/report.md`. That folder also holds the transcript, screenshots, the bot's
     evidence (`fetch-*.json`), log slices and `journal.jsonl`.
   - You don't need to stop anything afterwards. The driver keeps running for the next session; to stop it
     run `python3 tester/simchat_server.py stop_driver`.

Write your own scenarios as Markdown files in `tester/scenarios/`, using `example-greeting.md` as the
model, or ask the agent to save an exploratory run as a scenario.

## Uninstall
```bash
cd ~/tools/ios-chat-tester
python3 install.py --uninstall      # shows what it will remove and asks first
cd ~ && rm -rf ~/tools/ios-chat-tester
```
`--uninstall`:
- stops the UI driver,
- removes the driver's test-runner app from the booted simulators,
- deletes the agent, the skills and the launcher,
- removes the `simchat` entry from the Copilot CLI and VS Code MCP configs. Other entries stay.

Files you edited by hand are kept unless you add `--force`. Deleting the folder then removes everything
else: config, profile, runs and the driver build. Nothing was installed anywhere else.

## What the agent can and cannot do
- It **can** read the repos you configured, drive the app through the `simchat` tools, and write reports
  and scenarios to `tester/runs/` and `tester/scenarios/` only.
- It **cannot** run shell commands, edit your code, start or stop your services, or reach anything that
  isn't local.
- It works one action at a time and never resends blindly:
  - `send_message` reads the typed text back before it taps Send once.
  - It taps only buttons the bot offered.
- A run can only **PASS** with recorded checks and evidence. Otherwise it is FAIL, BLOCKED or
  INCONCLUSIVE.

## Troubleshooting the driver
- **Logs:** the build log is `tester/driver/.build/install-build.log`. The runtime log is
  `tester/driver/.build/driver.log`. `status` shows its tail.
- **Watch it directly:** run `tester/driver/run-driver.sh <udid> <bundle-id>` in a terminal to see
  everything xcodebuild prints.
- **Signing errors:** set `"driver": {"xcodebuild_args": "CODE_SIGNING_ALLOWED=NO"}` in `config.json` and
  re-run `install.py`.
- **The project won't open or build in your Xcode version:** create it in Xcode instead. Make a new iOS App
  project, add a *UI Testing Bundle* target named `SimDriverUITests` with Target Application *None*, and add
  `SimDriverUITests/SimDriverServer.swift` to it. The driver only needs that one Swift file.
- **"Several simulators are booted":** set `simulator.udid` in `config.json`.

## Layout
```
install.py                the one command
templates/                agent + skills (rendered with your paths and name)
tester/
  simchat_server.py       MCP server (no args) and CLI (with args)
  simchat/                Python, standard library only
  driver/                 SimDriver Xcode project: one Swift file, an XCTest UI test serving 127.0.0.1
  config.example.json     → config.json (local)
  profile.example.md      → profile.md (local)
  scenarios/              scenario files (Markdown)
  runs/                   one folder per run: journal, transcript, fetches, log slices, screenshots, report
tests/                    python3 -m unittest discover -s tests   (no simulator needed)
```

## Development
`python3 -m unittest discover -s tests` runs everything against a fake app and fake driver that speak the
same protocol as the Swift driver. Python must stay 3.9-compatible and standard-library only.
