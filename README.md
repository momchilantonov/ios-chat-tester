# Live chat tester for iOS Simulator apps

An agent for **GitHub Copilot CLI** and **VS Code** that tests the chat assistant inside your iOS app *live*:
it behaves like a real user in the iOS Simulator. It types messages, taps quick-reply buttons and waits for
replies, then checks the bot's own evidence (local HTTP endpoint, logs) and writes a test report.
You can watch everything happen in the Simulator window.

- **No dependencies.** Python 3.9+ standard library and Xcode. No pip, npm, Homebrew or accounts.
- **Nothing leaves the machine.** The tools talk only to the Simulator and to `127.0.0.1`.
- **Unicode typing.** Uses Apple's XCTest, so any language works.

```
Copilot CLI / VS Code ── agents "<name>-planner" (writes plans) and "<name>" (runs them) + 3 skills
        │ MCP (stdio)
tester/simchat_server.py ── send_message · wait_for_reply · tap · swipe · long_press · scroll · screen · fetch · read_log · runs
        │ JSON over 127.0.0.1                      │ GET 127.0.0.1 / read log files
tester/driver (XCTest UI test, runs forever) ──▶  your app in the booted Simulator ──▶ your local bot/backend
```

> **Setting this up through an AI agent?** Point it at [GUIDE_FOR_AGENTS.md](GUIDE_FOR_AGENTS.md). For what
> changed and what to test again, see [CHANGELOG.md](CHANGELOG.md).

## Install, update, move, uninstall
Everything is done with one script, `install.py`, on the Mac where Xcode and the Simulator run.

**You need:** macOS with Xcode (your app builds and runs in the Simulator), Python 3.9+ (`python3 --version`),
and GitHub Copilot CLI and/or VS Code with Copilot.

### First: choose where the agents go
The tool itself always lives in the folder you clone. Only the agent files (2 agents, 3 skills and the
`simchat` tool registration) go to one of two places:

| | **A. For your user** (default) | **B. Into one repo** (`--into <repo>`) |
|---|---|---|
| Files go to | `~/.copilot/agents`, `~/.copilot/skills`, `~/.copilot/mcp-config.json`, VS Code's user `mcp.json` | `<repo>/.github/agents`, `<repo>/.github/skills`, `<repo>/.github/mcp.json`, `<repo>/.vscode/mcp.json` |
| The agents show up | in Copilot started from **any** folder | only in Copilot started **inside that repo** (or VS Code with that repo open) |
| Good when | you test from several repos | you keep your AI tools in one repo (e.g. the bot repo) |

Pick one. You can switch later (case 4).

### Case 1: install for your user (A)
1. Clone the tool anywhere, for example:
   ```bash
   git clone https://github.com/momchilantonov/ios-chat-tester.git ~/tools/ios-chat-tester
   cd ~/tools/ios-chat-tester
   ```
2. Run the installer and answer its questions (agent name, app bundle id, app repo folder, bot repo folder):
   ```bash
   python3 install.py
   ```
   Or give everything at once, without questions:
   ```bash
   python3 install.py --name my-tester --bundle-id <bundle id> --app-repo <ios app repo> --bot-repo <bot repo>
   ```
3. Read the end of the output: `Done.`, or a short list of things to fix.
4. Continue with [Use it: step by step](#use-it-step-by-step).

### Case 2: install into one repo (B)
1. Clone the tool. It can live inside that repo, for example in its `.github` folder:
   ```bash
   cd <bot repo>/.github
   git clone https://github.com/momchilantonov/ios-chat-tester.git
   cd ios-chat-tester
   ```
2. Run the installer with `--into` and the repo's folder:
   ```bash
   python3 install.py --into <bot repo> --name my-tester --bundle-id <bundle id> \
       --app-repo <ios app repo> --bot-repo <bot repo>
   ```
3. Keep the new files out of that repo's git. They contain paths from your machine, so don't commit them.
   Add these lines to `<bot repo>/.git/info/exclude` (a local `.gitignore` that is never committed):
   ```text
   .github/ios-chat-tester/
   .github/agents/my-tester.agent.md
   .github/agents/my-tester-planner.agent.md
   .github/skills/chat-testing/
   .github/skills/chat-test-report/
   .github/skills/test-plan-format/
   ```
   `.github/mcp.json` and `.vscode/mcp.json` may already be tracked in the repo. The installer only adds a
   `simchat` entry to them, so `git status` will show them as changed: don't commit that change. Add
   `--no-vscode` if you don't want `.vscode/mcp.json` touched at all.
4. Always start the agents from **inside that repo**, e.g. `cd <bot repo> && <clone>/tester/bin/my-tester`.

### Case 2b: a main repo whose submodules link to its `.github`
For this layout: a main repo keeps all AI agents in its own `.github`, and the bot repo is a submodule of it whose
`.github/agents` and `.github/skills` are symlinks to the main repo's folders. The agents go into the **main**
repo, and the submodule sees them through its links, the same way it sees your other agents.
1. Clone the tool somewhere inside the main repo, for example next to your other AI tools:
   ```bash
   cd <main repo>/.github
   git clone https://github.com/momchilantonov/ios-chat-tester.git
   cd ios-chat-tester
   ```
2. Install into the **main** repo, and give the submodule as the bot repo:
   ```bash
   python3 install.py --into <main repo> --no-vscode --name my-tester --bundle-id <bundle id> \
       --app-repo <ios app repo> --bot-repo <main repo>/<bot submodule>
   ```
3. Check that the submodule sees the new files:
   ```bash
   ls -l <main repo>/<bot submodule>/.github/agents/my-tester.agent.md
   ```
   - **Whole folders are linked** (`agents -> ../../.github/agents`): nothing more to do.
   - **Single files are linked** (one link per agent): add links for `my-tester.agent.md`,
     `my-tester-planner.agent.md` and the skill folders `chat-testing`, `chat-test-report` and
     `test-plan-format`, the same way as for your other agents.
4. Keep the new files out of git:
   - **Main repo:** add the lines from case 2, step 3 to `<main repo>/.git/info/exclude`.
   - **Submodule:** linked folders are ignored there already, like your other agents. If you added file links
     in step 3, ignore them in the submodule's own exclude file. A submodule's `.git` is a file, not a folder,
     so ask git where the exclude file is: `git -C <bot submodule> rev-parse --git-path info/exclude`.
5. Start the agents from **inside the submodule**:
   `cd <main repo>/<bot submodule> && <main repo>/.github/ios-chat-tester/tester/bin/my-tester`.
   The launcher lets the agent read the folders the links point to (the installer prints them as
   `add-dir ... (symlink ...)`).

To update, move or uninstall, use cases 3, 4 and 7 with `--into <main repo>`.

### What the installer does (cases 1 and 2)
In guided mode it shows each step and waits for your OK (`Y`es, `n`o to skip, `q` to quit).

| Step | What it does |
|---|---|
| 1 Prerequisites | Checks Python 3.9+, Xcode, `simctl` and Copilot CLI. Changes nothing. |
| 2 Local settings | Creates `tester/config.json` and `tester/profile.md` in the clone. Both stay local and are git-ignored. |
| 3 Agents and tools | Writes the 2 agents and 3 skills to the place you chose (A or B), registers the `simchat` tool there, and writes the launchers `tester/bin/<name>` and `tester/bin/<name>-planner`. |
| 4 UI driver | Builds `tester/driver` with `xcodebuild`. Takes 1–3 min the first time and works offline. |

### Case 3: update to a new version
1. `cd` into the clone and run `git pull`.
2. Run **exactly the same install command as the first time**: the same `--name`, and `--into <repo>` if
   you used it. Without `--into`, the update goes to your user folders instead (place A) and you end up with
   two installs. Without `--name`, the name falls back to `chat-tester`.
3. Restart the agents: a running Copilot session keeps the old instructions.
4. Read the newest section of [CHANGELOG.md](CHANGELOG.md): it lists new settings and what to test again.

Files the installer wrote earlier are updated. Files you edited by hand are kept and reported as `KEPT`;
`--force` overwrites them.

### Case 4: move the agents (A → B, B → A, or to another repo)
A new install in another place does **not** remove the old one. Remove it first:
1. Stop any agent session that uses the tool.
2. Remove the current install. Your config, profile, plans and runs stay:
   ```bash
   python3 install.py --uninstall
   ```
3. Install in the new place, with the same `--name`:
   ```bash
   python3 install.py --name my-tester                      # → A, for your user
   python3 install.py --name my-tester --into <repo>        # → B, into that repo
   ```
   The bundle id and repo folders come from `tester/config.json`, so you don't need to repeat them.
4. If you moved away from a repo (B), remove the lines you added to its `.git/info/exclude`.

### Case 5: rename the agents
Same as case 4: `python3 install.py --uninstall`, then install again with the new `--name`.

### Case 6: move the tool folder itself
The launchers and the tool registration contain the folder's path. Uninstall in the old folder, move or
re-clone it, then install from the new folder (case 1 or 2). To keep your settings, copy `tester/config.json`,
`tester/profile.md`, `tester/plans/` and `tester/runs/` to the new folder before installing.

### Case 7: uninstall completely
1. Preview what will be removed:
   ```bash
   cd <clone>
   python3 install.py --uninstall --dry-run
   ```
2. Remove it. It shows the list again and asks before removing anything:
   ```bash
   python3 install.py --uninstall
   ```
   This:
   - stops the UI driver;
   - removes the driver's test-runner app from the booted simulators;
   - deletes the agents, the skills and the launchers from **every place you ever installed to** (A and B);
   - removes the `simchat` entry from each MCP config file. Other entries stay. A file the installer created
     itself is deleted when nothing else is left in it;
   - removes links in your repos that pointed at the removed agent or skill files (case 2b, one link per file).
     Links to other agents, and links to whole folders, stay.

   Files you edited by hand are kept; add `--force` to remove them too.
3. Delete the folder. This removes the rest: config, profile, plans, runs and the driver build.
   ```bash
   cd ~ && rm -rf <clone>
   ```
4. If you used B, remove the lines you added to that repo's `.git/info/exclude` (and the submodule's, case 2b).

Simulators that were not running during the uninstall may still have the runner app:
`xcrun simctl uninstall <udid> dev.simchat.SimDriverUITests.xctrunner`.

### All installer options
| Option | Meaning |
|---|---|
| *(none, in a terminal)* | Guided: asks the questions, shows each step, waits for your OK. Same as `--guided`. |
| `--name NAME` | Agent name (default `chat-tester`). The planner is `NAME-planner`. Letters, digits, `-` and `_`. |
| `--bundle-id ID` | Bundle id of the app under test (Xcode → app target → General). |
| `--app-repo DIR` / `--bot-repo DIR` | Repos the agents may read. Saved in `tester/config.json`. |
| `--repo ROLE=DIR` | One more readable repo; repeat for more. |
| `--into REPO` | Install into that repo's `.github` and `.vscode` (place B) instead of your user folders. |
| `--copilot-home DIR` | Your Copilot folder for place A (default `~/.copilot` or `$COPILOT_HOME`). |
| `--vscode-dir DIR` | VS Code's user folder (default `~/Library/Application Support/Code/User`). |
| `--no-vscode` | Don't register the tool for VS Code. |
| `--python PATH` | The Python that runs the tool (default: the one you start `install.py` with; never a virtualenv). |
| `--ask-approval` | Copilot asks before every tap or message (by default the `simchat` tools are pre-approved). |
| `--skip-build` | Don't build the UI driver. |
| `--dry-run` | Show what would happen; change nothing. Works with `--uninstall` too. |
| `--yes` | Don't ask for confirmation. |
| `--force` | Also overwrite or remove files you edited by hand. |
| `--uninstall` | Remove what the installer put in place (case 7). |

### Good to know
- **Two installs at once** (A and B): the agents appear twice inside that repo, and an update to one place
  leaves the other on the old version. Use one place, or update both with their own commands.
- **The installer remembers what it wrote** (in `tester/.install.json`). That is how updates and uninstall find
  their files, and why it never overwrites or deletes a file you changed without `--force`.
- **An agent file with the same name already in a repo** (e.g. `.github/agents/my-tester.agent.md`) can hide
  the installed agent there. The installer warns about it (`WARN ... exists`); remove it or use another
  `--name`.

## Use it: step by step
Once, after installing:
1. **Fill in `tester/profile.md`.** This is what the agent reads first: your product, the customer's
   language, how you start the local stack, where the evidence is, the error reply text and your rules.
2. **Check `tester/config.json`:**
   - `endpoints`: the bot's local conversation/event URL, e.g. `.../extract/{session_id}`. The agent finds the
     session id with `find_session_id`.
   - `logs`: the file your bot logs to. Start the bot with `... 2>&1 | tee <that file>`; the terminal output
     stays the same. Without it the agent can still read the app's own Simulator log (`app_log`).
   - `app.after_launch`: the taps from a fresh launch to the chat, if the app opens on a menu, e.g.
     `["Open chat"]`.
   - `chat.ignore_labels`: regexes for screen noise such as debug banners.
   - `chat.send_labels`: only needed if your Send button isn't found.

Every test session:
1. **Start your local stack** (bot, mocks) the way your profile describes, logging to the file in `config.json`.
2. **Start the app:** in Xcode press **Run (⌘R)** on a simulator, then open the chat screen.
3. **Optional smoke test, without the agent:** `python3 tester/simchat_server.py demo "Hello"`.
   - The first time, this starts the UI driver, which takes about 30 s.
   - Watch the Simulator: the message is typed and sent, and the reply is printed.
4. **Generate a test plan** with the planner agent. It only reads code and writes the plan; it doesn't
   need the Simulator.
   - **Copilot CLI:** run `~/tools/ios-chat-tester/tester/bin/<name>-planner` from your bot repo.
   - **VS Code:** Copilot Chat → agent picker → `<name>-planner`.
   - Ask, for example: `Make a test plan for the rating flow` or
     `Turn section 3 of @docs/.../test-guide.md into a plan`.
   - It writes `tester/plans/<flow>-<topic>.md`. Review it, and edit it if you like: it's plain Markdown.
5. **Run the plan** with the tester agent:
   - **Copilot CLI:** `~/tools/ios-chat-tester/tester/bin/<name>`, then `Run plan rating-thumbs`.
     The first time, trust the folder. The launchers start Copilot with `--allow-tool simchat`, so it doesn't
     ask for approval before every tap or message. Those tools only drive the Simulator, read local
     endpoints and logs, and write under `tester/runs/` and `tester/plans/`. Other actions, such as reading
     files outside the allowed folders, still ask. If you want to be asked every time, install with
     `--ask-approval`. If your organisation's Copilot policy requires approval for MCP tools, the flag has no
     effect. Then answer "yes, for this session" the first time each tool asks; there are about 10.
     Non-interactive runs (`copilot -p`) are not possible under such a policy.
   - **VS Code:** agent picker → `<name>`. The first time it asks, choose "always allow" for the `simchat` tools.
   - Free-form requests work too, e.g. `Test blocking a lost card, as an impatient customer`.
6. **Watch the Simulator** and answer the agent if it asks something, for example the session id.
7. **Read the result:**
   - **`tester/plans/<plan>.result.md`** is your plan with the Result column filled in: `success`,
     `fail: <what happened instead>` or `blocked: <why>`.
   - The agent also replies with the verdict, its findings and the run folder `tester/runs/<time>_<plan>/`.
     That folder holds `report.md`, `results.md`, the transcript, screenshots, the bot's evidence
     (`fetch-*.json`), log slices and `journal.jsonl`.
   - You don't need to stop anything afterwards. The driver keeps running for the next session; to stop it
     run `python3 tester/simchat_server.py stop_driver`.

### Test plan format
```markdown
# Test plan: Rate the conversation
Preconditions: test customer
Source: <flow file>

## Conversation 1: thumbs up          ← each ## section is one conversation, started with a fresh app launch
| Flow | User prompt | Expected | Result |
|---|---|---|---|
| rating | I'd like to rate this chat | "Was I helpful?" buttons: "👍", "👎", "Skip" | |
| rating | tap 👍 | "Great 🤩" | |
```
- **User prompt:** text to type; `tap <label>`, `select <label>`, `swipe left|right on <what>` or `wait`.
- **Expected:** "quoted" text must appear exactly (`{...}` marks variable content); `buttons:` lists the
  quick replies that must be offered; anything else is judged.
- **Result:** left empty in the plan; the tester fills it.

Full rules: [tester/plans/README.md](tester/plans/README.md). Your plans and results are git-ignored.

## What the agent can and cannot do
- It **can** read the repos you configured, drive the app through the `simchat` tools, and write reports
  and plans to `tester/runs/` and `tester/plans/` only. The planner can only write plans.
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
templates/                2 agents + 3 skills (rendered with your paths and name)
tester/
  simchat_server.py       MCP server (no args) and CLI (with args)
  simchat/                Python, standard library only
  driver/                 SimDriver Xcode project: one Swift file, an XCTest UI test serving 127.0.0.1
  config.example.json     → config.json (local)
  profile.example.md      → profile.md (local)
  plans/                  test plans and their .result.md (yours are git-ignored)
  runs/                   one folder per run: journal, transcript, fetches, log slices, screenshots, report
tests/                    python3 -m unittest discover -s tests   (no simulator needed)
```

## Development
`python3 -m unittest discover -s tests` runs everything against a fake app and fake driver that speak the
same protocol as the Swift driver. Python must stay 3.9-compatible and standard-library only.
