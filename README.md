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
tester/simchat_server.py ── send_message · wait_for_reply · tap · screen · fetch · read_log · runs/reports
        │ JSON over 127.0.0.1                      │ GET 127.0.0.1 / read log files
tester/driver (XCTest UI test, runs forever) ──▶  your app in the booted Simulator ──▶ your local bot/backend
```

## Install (on the Mac)
```bash
git clone <this repo> ~/tools/chat-tester && cd ~/tools/chat-tester
python3 install.py --name my-tester --bundle-id <your.app.bundle.id> \
    --app-repo ~/path/to/ios-app-repo --bot-repo ~/path/to/bot-repo
```
One command does all of this:
1. Checks Python, Xcode, `simctl` and Copilot CLI.
2. Creates `tester/config.json` and `tester/profile.md`. Both stay local and are git-ignored.
3. Installs the agent and its skills into `~/.copilot/agents` and `~/.copilot/skills`.
4. Registers the `simchat` MCP server in `~/.copilot/mcp-config.json` and VS Code's user `mcp.json`.
5. Writes the launcher `tester/bin/<name>`.
6. Builds the UI driver with `xcodebuild` (1–3 min the first time).

Use `--into <repo>` to install into `<repo>/.github` and `<repo>/.vscode` instead of your user folders.
Use `--dry-run` to preview. After `git pull`, run it again: files it wrote earlier are updated, and files
you edited are kept. Use `--uninstall` to remove everything it installed.

Then fill in **`tester/profile.md`**, the project-specific knowledge the agent reads first:
- the product and the customer's language,
- how you start the local stack,
- where the evidence is and what the error reply looks like,
- your rules.

Also check **`tester/config.json`**: the endpoints, the log files and, if needed, the Send button label.

## First run: watch it work
1. Run your app in the Simulator from Xcode and start your local backend.
2. Smoke test without any LLM. It builds and starts the driver if needed, brings Simulator.app to the front,
   types the message and waits for the reply:
   ```bash
   python3 tester/simchat_server.py demo "Hello"
   ```
   Single steps work too: `python3 tester/simchat_server.py screen`, `... send_message text="Hi"`,
   `... wait_for_reply`, `... tap element=12`.
3. Start the agent:
   - **Copilot CLI:** `tester/bin/<name>`. It starts `copilot --agent=<name>` and uses `--add-dir` to give
     the agent read access to the tester and your repos. Run it from your bot repo, for example.
   - **VS Code:** Copilot Chat → agent picker → `<name>`. In *Configure Tools*, allow `simchat`.

   Ask it something like: *"Run the example-greeting scenario"*, *"Explore the card-blocking flow as an
   impatient user"*, or *"Reproduce: after tapping X the bot answers with the fallback"*.

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
