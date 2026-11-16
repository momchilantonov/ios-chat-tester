# iOS chat tester

Test the chat assistant inside your iOS app **live**, the way a customer uses it. An AI agent types messages
in the iOS Simulator, taps the buttons the bot offers, reads the replies and checks them against a test
plan. It writes the result into the plan and a report into a run folder. You can watch every step in the
Simulator window.

It works with **GitHub Copilot CLI** (terminal) and **VS Code with Copilot**. You get two agents:

| Agent | What it does | Needs the Simulator? |
|---|---|---|
| `<name>-planner` | Reads the bot's code or your test guide and writes a **test plan** (a Markdown table). | no |
| `<name>` | **Runs** a plan (or a free request) in the Simulator and writes the **results and report**. | yes |

`<name>` is the name you choose when you install, e.g. `my-tester`.

- **No dependencies:** Python 3.9+ (standard library) and Xcode. No pip, npm, Homebrew or accounts.
- **Nothing leaves your Mac:** the tools talk only to the Simulator and to `127.0.0.1`.
- **Any language:** typing goes through Apple's XCTest, so Unicode and emoji work.

> Setting this up through an AI agent? Point it at [GUIDE_FOR_AGENTS.md](GUIDE_FOR_AGENTS.md).
> What changed in each version: [CHANGELOG.md](CHANGELOG.md).

## Contents
1. [How it works](#1-how-it-works)
2. [What you need](#2-what-you-need)
3. [Quick start](#3-quick-start)
4. [Install: pick your case](#4-install-pick-your-case)
5. [Set it up once: config and profile](#5-set-it-up-once-config-and-profile)
6. [Before every test session](#6-before-every-test-session)
7. [Start the agents](#7-start-the-agents)
8. [Prompts you can use](#8-prompts-you-can-use)
9. [Test plans](#9-test-plans)
10. [What the tool writes: results and reports](#10-what-the-tool-writes-results-and-reports)
11. [Use it without an agent (command line)](#11-use-it-without-an-agent-command-line)
12. [Update, move, rename, uninstall](#12-update-move-rename-uninstall)
13. [All installer options](#13-all-installer-options)
14. [What the agent can and cannot do](#14-what-the-agent-can-and-cannot-do)
15. [Troubleshooting](#15-troubleshooting)
16. [Folder layout and development](#16-folder-layout-and-development)

**Placeholders used below.** Replace them with your own values:

| Placeholder | Meaning | Example |
|---|---|---|
| `<clone>` | the folder where you cloned this tool | `~/tools/ios-chat-tester` |
| `<name>` | the agent name you chose | `my-tester` |
| `<bundle id>` | your app's bundle id | `com.example.ChatApp` |
| `<ios app repo>` | the folder of the iOS app's code | `~/repos/ios-app` |
| `<bot repo>` | the folder of the bot/backend code | `~/repos/chat-bot` |
| `<main repo>` / `<bot submodule>` | only for case 2b (a main repo with the bot as a submodule) | `~/repos/workspace` / `chat-bot` |
| `<flow>` | a flow (conversation topic) of your bot | `card_block` |
| `<plan>` | a plan's file name without `.md` | `card_block-lost-card` |
| `<guide.md>` | a test guide or ticket in a repo | `docs/tests/cards-guide.md` |

---

## 1. How it works
```
 you ──"Make a test plan for <flow>"──▶ <name>-planner ──reads──▶ bot code / your guide
                                              │
                                              ▼ writes
                                  <clone>/tester/plans/<plan>.md          (you review it)
                                              │
 you ──"Run plan <plan>"──────────────▶ <name> ──types, taps, reads──▶ your app in the iOS Simulator
                                              │                              │
                                              │◀── evidence: local bot endpoint (127.0.0.1), log files
                                              ▼ writes
                    <clone>/tester/plans/<plan>.result.md                (the plan with results filled in)
                    <clone>/tester/runs/<date>-<time>_<plan>/            (report.md, transcript, screenshots …)
```
Under the hood: the agents use a small local tool called **`simchat`** (an MCP server, started by Copilot).
It drives the app through a **UI driver**, an XCTest runner that the installer builds with Xcode. The driver
runs in the background in the Simulator, and you don't need to touch it.

## 2. What you need
- A **Mac** with **Xcode**. Your app builds and runs in the iOS Simulator from Xcode.
- **Python 3.9 or newer**: `python3 --version` (macOS ships one with Xcode's command line tools).
- **GitHub Copilot CLI** (`copilot --version`) and/or **VS Code with GitHub Copilot**.
- Your **bot running locally** (for example on `127.0.0.1:<port>`), the way your team normally runs it.
- Optional but recommended: the bot writing its log to a file, e.g. `<start command> 2>&1 | tee ~/chat-logs/bot.log`.

## 3. Quick start
This is the shortest path: install for your user (case 1), then plan and run one test.
```bash
# 1. get the tool
git clone https://github.com/momchilantonov/ios-chat-tester.git ~/tools/ios-chat-tester
cd ~/tools/ios-chat-tester

# 2. install (answers the questions for you; takes 1-3 min the first time because it builds the UI driver)
python3 install.py --name my-tester --bundle-id <bundle id> --app-repo <ios app repo> --bot-repo <bot repo>

# 3. describe your project once (see section 5)
open tester/profile.md          # fill in the TODOs
open tester/config.json         # check endpoints, logs, app.after_launch

# 4. start your bot, then in Xcode press Run (⌘R) on a simulator

# 5. check that the tool can chat (no AI involved): types "Hello" and prints the reply
python3 tester/simchat_server.py demo "Hello"

# 6. write a plan, from the bot repo
cd <bot repo>
~/tools/ios-chat-tester/tester/bin/my-tester-planner
#    > Make a test plan for the <flow> flow

# 7. run it
~/tools/ios-chat-tester/tester/bin/my-tester
#    > Run plan <plan>
```
Then open `~/tools/ios-chat-tester/tester/plans/<plan>.result.md` and the run folder the agent names.

---

## 4. Install: pick your case
The tool itself always stays in the folder you cloned (`<clone>`). Only the **agent files** go somewhere
else. These are 2 agents, 3 skills (instructions the agents load) and the registration of the `simchat` tool.
Pick **one** place:

| Case | Agent files go to | The agents appear | Choose it when |
|---|---|---|---|
| **1. For your user** (default) | `~/.copilot/…` and VS Code's user settings | in Copilot started from **any** folder | you're not sure, or you test from several repos |
| **2. Into one repo** (`--into <repo>`) | `<repo>/.github/…` (and `<repo>/.vscode/mcp.json`) | only in Copilot started **inside that repo** | you keep your AI tools in one repo |
| **2b. Main repo + submodule** | `<main repo>/.github/…`; the bot submodule sees them through links | inside the main repo and the submodule | your main repo's `.github` is linked into the bot submodule |

You can switch later ([section 12](#12-update-move-rename-uninstall)). Installing into two places at once
works, but each update must then be done twice. Avoid it.

### Case 1: install for your user
1. Clone the tool anywhere:
   ```bash
   git clone https://github.com/momchilantonov/ios-chat-tester.git <clone>
   cd <clone>
   ```
2. Install. Either let it ask you the questions (agent name, bundle id, app repo, bot repo):
   ```bash
   python3 install.py
   ```
   or give everything at once:
   ```bash
   python3 install.py --name <name> --bundle-id <bundle id> --app-repo <ios app repo> --bot-repo <bot repo>
   ```
   Only Copilot CLI, no VS Code? Add `--no-vscode`.
3. The last lines say `Done.` or list what to fix (exit code 1). Fix those and run the same command again.

### Case 2: install into one repo
1. Clone the tool. It may live inside that repo:
   ```bash
   cd <bot repo>/.github
   git clone https://github.com/momchilantonov/ios-chat-tester.git
   cd ios-chat-tester
   ```
2. Install with `--into`:
   ```bash
   python3 install.py --into <bot repo> --name <name> --bundle-id <bundle id> \
       --app-repo <ios app repo> --bot-repo <bot repo>
   ```
   Add `--no-vscode` if you only use Copilot CLI (then `<bot repo>/.vscode/mcp.json` is not touched).
3. **Keep the new files out of git.** They contain paths from your Mac, so never commit them. Add these lines
   to `<bot repo>/.git/info/exclude`, a personal ignore list that is never committed:
   ```text
   .github/ios-chat-tester/
   .github/agents/<name>.agent.md
   .github/agents/<name>-planner.agent.md
   .github/skills/chat-testing/
   .github/skills/chat-test-report/
   .github/skills/test-plan-format/
   ```
   If `.github/mcp.json` or `.vscode/mcp.json` is already tracked, the installer only adds a `simchat` entry.
   `git status` will show the file as changed. Don't commit that change.
4. Start the agents from **inside that repo** ([section 7](#7-start-the-agents)).

### Case 2b: a main repo whose bot submodule links to its `.github`
For this layout: a main repo keeps all AI agents in its own `.github`, and the bot repo is a git submodule
whose `.github/agents` and `.github/skills` link (symlink) to the main repo's folders, as a whole folder or
one link per file.
1. Clone the tool inside the main repo, next to your other AI tools:
   ```bash
   cd <main repo>/.github
   git clone https://github.com/momchilantonov/ios-chat-tester.git
   cd ios-chat-tester
   ```
2. Install into the **main** repo, with the submodule as the bot repo:
   ```bash
   python3 install.py --into <main repo> --no-vscode --name <name> --bundle-id <bundle id> \
       --app-repo <ios app repo> --bot-repo <main repo>/<bot submodule>
   ```
3. Check that the submodule sees the agent:
   ```bash
   ls -l <main repo>/<bot submodule>/.github/agents/<name>.agent.md
   ```
   - **Whole folders are linked** (`agents -> ../../.github/agents`): nothing more to do.
   - **One link per file**: add links the same way as for your other agents:
     ```bash
     cd <main repo>/<bot submodule>/.github/agents
     ln -s ../../../.github/agents/<name>.agent.md .
     ln -s ../../../.github/agents/<name>-planner.agent.md .
     cd ../skills
     ln -s ../../../.github/skills/chat-testing .
     ln -s ../../../.github/skills/chat-test-report .
     ln -s ../../../.github/skills/test-plan-format .
     ```
     (Adjust the `../` count to how your other links are written: `ls -l` shows them.)
4. Keep the new files out of git:
   - **Main repo:** the lines from case 2, step 3, in `<main repo>/.git/info/exclude`.
   - **Submodule:** only if you added file links. A submodule's `.git` is a file, so ask git where its
     exclude file is, then add the link paths there:
     ```bash
     git -C <main repo>/<bot submodule> rev-parse --git-path info/exclude
     ```
5. Start the agents from **inside the submodule** ([section 7](#7-start-the-agents)).

### What the installer does
Without arguments (in a terminal) it is **guided**: it shows each step and waits for `Y`es, `n`o (skip) or
`q` (quit).

| Step | What happens |
|---|---|
| 1 Prerequisites | Checks Python, Xcode, `simctl` and Copilot CLI. Changes nothing. |
| 2 Local settings | Creates `<clone>/tester/config.json` and `<clone>/tester/profile.md` (yours, never committed). |
| 3 Agents and tools | Writes the 2 agents and 3 skills to the place you chose, registers `simchat`, and writes the launchers `<clone>/tester/bin/<name>` and `<clone>/tester/bin/<name>-planner`. |
| 4 UI driver | Builds the driver with `xcodebuild` (1–3 min the first time, offline). |

Every file it writes is listed in `<clone>/tester/.install.json`. Updates and uninstall use that list, so
they never touch files the installer didn't write.

---

## 5. Set it up once: config and profile
Both files are in `<clone>/tester/`, stay on your Mac and are never committed.

### `tester/profile.md`: what the agents should know about your project
The agents read it at the start of every session. Fill every `TODO`. A short example:
```markdown
## Product
- App under test: <app name>; the chat is behind the "<menu entry>" button on the home screen
- Bot / backend: <bot name>, source in <bot repo>/<folder>
- Customer language: write as a native <language> speaker; reports in English

## How to start the local stack (the agent never starts services - it tells you this)
- `<start command> 2>&1 | tee ~/chat-logs/bot.log`  (port <port>)
- the mock backend: `<mock start command>`  (port <mock port>)

## Getting to the chat
- A fresh launch shows the home screen; tap "<menu entry>" to open the chat with our bot

## Evidence
- Endpoint `conversation` (config.json): JSON with `events`; bot messages have `event: "bot"`
- Session id: printed in the bot log as `sender_id=<id>`
- Error reply when the backend fails: "<the bot's error text>"

## Where flows live in this repo
- flows: <bot repo>/<flows folder>; response texts: <bot repo>/<responses folder>

## Known Simulator behaviour (accepted)
- Links and deeplinks cannot open in the Simulator; a tap that opens Safari or another app counts as
  success when the row expects a link.

## Rules for this project
- Test data only. Never confirm a payment, a signature or any other commitment.
```

### `tester/config.json`: how to reach the app, the bot and its logs
The installer fills `app.bundle_id` and `repos`. Check these keys:

| Key | What to put there | Example |
|---|---|---|
| `app.after_launch` | taps from a fresh app launch to the chat | `["<menu entry>"]` or `[{"tap": "<menu entry>", "wait_s": 20}]` |
| `endpoints` | local URLs the agent may GET for evidence | `{"conversation": "http://127.0.0.1:<port>/conversations/{session_id}"}` |
| `logs` | log files the agent may read | `{"bot": "~/chat-logs/bot.log"}` |
| `reply_evidence` | which events in the endpoint's JSON are bot replies (recommended) | `{"endpoint": "conversation", "list": "events", "match": {"event": "bot"}, "text": "text"}` |
| `chat.ignore_labels` | screen texts that are never chat content (regexes) | `["^DEBUG build .*$"]` |
| `chat.interim_labels` | texts the app shows while the bot works (regexes) | `["^Typing…$"]` |
| `chat.send_labels` | only if the Send button isn't found | `["Send", "<Send in your language>"]` |
| `simulator.udid` | only if several simulators are booted | `xcrun simctl list devices booted` shows the udid |

The full list with comments is in `tester/config.example.json`.

**Check your settings:**
```bash
cd <clone>
python3 tester/simchat_server.py status       # config, simulator, driver, ports, profile TODOs, plans
```

---

## 6. Before every test session
1. **Start your bot** (and mocks), logging to the file in `config.json`:
   `<start command> 2>&1 | tee ~/chat-logs/bot.log`
2. **Start the app:** in Xcode press **Run (⌘R)** on a simulator. Leave it on any screen. The agent opens the
   chat itself with a fresh launch (`app.after_launch`).
3. **Optional quick check** without the AI:
   ```bash
   python3 <clone>/tester/simchat_server.py demo "Hello"
   ```
   The first time, this starts the UI driver (about 30 s). You should see "Hello" typed in the Simulator and
   the bot's reply printed.

While the agent works, don't use the same Simulator and don't press Run in Xcode. The rest of your Mac is free:
the driver doesn't move your mouse or use your keyboard. For long runs keep the Mac awake: `caffeinate -dims`.

## 7. Start the agents

### Copilot CLI: with the launchers (recommended)
The launchers start Copilot with the right agent, the `simchat` tool, and read access to your repos.
**Start them from the repo you work in** (case 1: any repo; case 2: that repo; case 2b: the bot submodule):
```bash
cd <bot repo>
<clone>/tester/bin/<name>-planner     # the planner: writes plans
<clone>/tester/bin/<name>             # the tester: runs plans
```
Then type your request at the prompt ([section 8](#8-prompts-you-can-use)). Anything after the launcher is
passed to Copilot, for example a model:
```bash
<clone>/tester/bin/<name> --model <model name>
```
Tip: make short commands for yourself (in `~/.zshrc`):
```bash
alias plan-chat='<clone>/tester/bin/<name>-planner'
alias test-chat='<clone>/tester/bin/<name>'
```

### Copilot CLI: without the launchers
Case 1 only. The tool is then registered in `~/.copilot/mcp-config.json`:
```bash
cd <bot repo>
copilot --agent=<name>
```
Copilot then asks before each `simchat` tool, and the agent can only read the folder you started in.
Prefer the launchers.

### VS Code
Open the repo (case 2/2b: that repo), then **Copilot Chat → agent picker → `<name>-planner`** or **`<name>`**.
The first time a `simchat` tool runs, choose "Always allow".

### Approvals and models
- The launchers pre-approve the `simchat` tools (`--allow-tool simchat`), so you aren't asked before every tap.
  To be asked every time, install with `--ask-approval`.
- If your organisation's policy forces approval of tool calls, answer **"yes, for this session"** once per
  tool (about 10 times). In that case non-interactive runs (`copilot -p "…"`) don't work: the tools are denied
  and the planner can't save its plan. Always run the agents interactively.
- Use the **strongest model** you have for both agents. A policy may silently pick "auto". Check the model
  shown in the session and choose it with `/model`.
- **After every update** of the tool, restart the agents: a running session keeps the old instructions.

---

## 8. Prompts you can use
Write in plain language. These are examples; replace the placeholders.

### Planner (`<name>-planner`): making plans
| You want | Prompt |
|---|---|
| a plan for one flow, from the bot's code | `Make a test plan for the <flow> flow` |
| a plan from a test guide | `Turn section 3 of @<guide.md> into a plan` |
| a plan from a ticket or spec file | `Make a test plan from @<ticket file>; check the texts against the response files` |
| only some branches | `Make a test plan for <flow>: only the cancel and invalid-input branches` |
| several smaller plans | `Split the <flow> flow into plans of at most 5 conversations` |
| fix or extend a plan | `Add a conversation to plans/<plan>.md where the customer types "<text>" at the picker` |
| list existing plans | `Which plans do we have?` |

It writes `<clone>/tester/plans/<flow>-<topic>.md` and replies with the conversations, **"N rows runnable,
M blocked"** with a reason per blocked row, the preconditions and open questions.
It copies prompts **word for word** from your guide. A rephrased prompt could send the bot down another
flow. Rows that would change something real (block a card, pay, sign) come pre-filled as
`blocked: state-changing - needs operator OK`.

**Review the plan before running it.** It is plain Markdown, so edit it in any editor
([section 9](#9-test-plans)).

### Tester (`<name>`): running tests
| You want | Prompt |
|---|---|
| run a plan | `Run plan <plan>` |
| run it again (a new run folder, the result file is replaced) | `Run plan <plan> again` |
| a free test, no plan | `Test blocking a lost card, as an impatient customer` |
| reproduce a bug | `Reproduce: after "<message>" the bot answers "<wrong text>" instead of the card list` |
| check a change you just made | `I changed the <flow> confirmation text; check that the new text is shown` |
| try one message | `Send "<message>" and tell me exactly what the bot shows, with buttons` |
| see the screen | `What is on the screen right now?` / `Take a screenshot` |
| a summary of several runs | `Write a suite summary of today's runs` |
| turn a free test into a plan | `Make this a plan` (then ask the planner) |

During a run the agent may ask you something, e.g. which session id is the right one. Answer it in the chat.

**Allowing a state-changing row** (only with test data): rows pre-filled with `blocked: …` are always skipped.
To run one, delete the `blocked: …` text from its Result cell in `plans/<plan>.md`, then `Run plan <plan>`.

### After a run
| You want | Prompt |
|---|---|
| explain a failure | `Why did row 4 fail? Show the evidence` |
| the bot's raw evidence | `Show the bot events for the last message` |
| the bot log for a step | `What did the bot log when I tapped Continue?` |
| a short report for the team | `Summarize the findings of the last run in 5 lines, with severity` |

---

## 9. Test plans
A plan is a Markdown file in `<clone>/tester/plans/`. Each `##` section is **one conversation**, started with a
fresh app launch. Each row is **one customer action**.
```markdown
# Test plan: Block a card
Preconditions: default test user with two cards
Source: <guide.md> section 4.1, <bot repo>/flows/card_block.yml

## Conversation 1: select and confirm
| Flow | User prompt | Expected | Result |
|---|---|---|---|
| card_block | I want to block a card | the card list; buttons: "Continue" (disabled) | |
| card_block | select <card label> | the row is selected; "Continue" enabled | |
| card_block | tap Continue | "Do you want to block the selected cards?" buttons: "Confirm", "Cancel" | |
| card_block | tap Confirm | the card is blocked | blocked: state-changing - needs operator OK |

## Conversation 2: typed answers
| Flow | User prompt | Expected | Result |
|---|---|---|---|
| card_block | I want to block a card | the card list | |
| card_block | none of them | the empty-selection reply; nothing is blocked | |
| card_block | type: <card label> | the flow's answer to a typed card name | |
```

**User prompt**: what the customer does:

| Write | Means |
|---|---|
| `I want to block a card` | type this text and send it, exactly as written |
| `tap <label>` | tap a quick reply, list row or button |
| `select <label>` | tick a checkbox or list row |
| `swipe left on <what>` / `swipe right on <what>` | swipe a carousel |
| `type: <label>` | **type** the text of an option instead of tapping it |
| `wait` | send nothing, only wait for the next bot message |

**Expected**: what must happen:

| Write | Means |
|---|---|
| `"Exact text"` | this text must appear exactly (letters, punctuation, emoji) |
| `"Hello {name}"` | `{…}` is variable content |
| `buttons: "Yes", "No"` | these buttons must be offered |
| `precondition: <what>` | a note; the row still runs |
| anything else | a description the agent judges |

**Result** stays empty. The tester fills it with `success`, `fail: <what happened instead>` or `blocked: <why>`.
Put `blocked: <why>` there yourself to skip a row. More rules: [tester/plans/README.md](tester/plans/README.md);
an example: [tester/plans/example-plan.md](tester/plans/example-plan.md).

---

## 10. What the tool writes: results and reports
Everything goes into the tool's folder, `<clone>/tester/`, and is never committed:
```
<clone>/tester/
├── config.json, profile.md                    your settings (section 5)
├── plans/
│   ├── <plan>.md                              the plan (planner or you)
│   └── <plan>.result.md                       the plan with the Result column filled - replaced on every run
└── runs/
    ├── 20250101-093000_<plan>/                one folder per run: <date>-<time>_<plan or name>
    │   ├── report.md                          the readable report (verdict, conversation, checks, findings)
    │   ├── results.md                         the filled plan of THIS run (kept, unlike <plan>.result.md)
    │   ├── run.json                           verdict, counts, checks and notes as data
    │   ├── transcript.json                    every message and tap, in order
    │   ├── journal.jsonl                      every tool call the agent made, with its result
    │   ├── screenshots/<name>.png             screenshots the agent took
    │   ├── fetch-01-<endpoint>.json           the bot's evidence fetched from your local endpoint
    │   └── log-<name>.txt                     the bot/app log lines from this run
    ├── SUITE-<date>-<time>.md                 a summary of several runs (only when you ask)
    └── _scratch/                              screenshots taken outside a run
```

### Read the results in this order
1. **The agent's reply** in the chat: the verdict, 2–5 findings with evidence, the run folder and what is
   still untested.
2. **`plans/<plan>.result.md`**: your plan with each row's result:
   ```markdown
   | card_block | I want to block a card | the card list; buttons: "Continue" (disabled) | success |
   | card_block | none of them | the empty-selection reply | fail: the bot answered "<other text>" (a general answer) instead |
   | card_block | tap Confirm | the card is blocked | blocked: state-changing - needs operator OK |
   ```
3. **`runs/<run>/report.md`**: the full report:
   ```markdown
   # Block a card - FAIL
   <date> · app <bundle id> · run folder <path>
   ## Summary        what was tested, what happened, why this verdict, what is still untested
   ## Conversation   | # | Who | Message / button | Evidence |
   ## Checks         | Check | Result | Evidence |
   ## Findings       - S2 <title> - evidence, how to reproduce
   ## Artifacts      screenshots/, transcript.json, …
   ```

### Verdicts
| Verdict | Means | What you do |
|---|---|---|
| **PASS** | every row/expectation was checked with evidence and held | nothing |
| **FAIL** | the bot or app did something wrong | read the `fail:` rows and the findings |
| **BLOCKED** | some rows could not run: a service was down, a precondition was missing, a state-changing step | fix the cause, run again |
| **INCOMPLETE** | the run stopped before every row was tried (`blocked: not run`) | run the plan again |
| **INCONCLUSIVE** | a free test ran, but nothing could be decided | give a clearer request or a plan |

A PASS always needs recorded evidence. The agent never reports a pass it didn't see.

**Severity of findings:** S1 (wrong irreversible action, data leak, crash), S2 (flow can't complete, wrong
branch, error reply), S3 (wrong wording, wrong button title, slow reply), S4 (cosmetic).

---

## 11. Use it without an agent (command line)
Every `simchat` tool can be called by hand. This is useful for checking the setup or a single message. Each
command prints JSON:
```bash
cd <clone>
T=tester/simchat_server.py
python3 $T status                          # is everything ready?
python3 $T start_driver wait_s=110         # start the UI driver (repeat while "starting")
python3 $T open_app fresh=true             # fresh launch, then the taps in app.after_launch
python3 $T wait_for_reply                  # the welcome message, if any
python3 $T send_message text="<message>"   # type and send
python3 $T wait_for_reply                  # new messages, buttons, options
python3 $T screen                          # what is on screen, with [index] numbers
python3 $T tap element=7                   # tap by index from screen …
python3 $T tap text="<button label>"       # … or by its text
python3 $T screenshot name=<name>          # saved under tester/runs/_scratch/
python3 $T find_session_id                 # the bot's session id from the logs
python3 $T fetch endpoint=conversation     # GET a configured endpoint
python3 $T read_log name=bot grep=<text>   # bot log lines that contain <text>
python3 $T stop_driver                     # stop the UI driver
python3 $T demo "<message>"                # all of the above in one: start, send, wait, print
```
Each call is a separate process, so it doesn't remember the previous one. To judge whole conversations,
use the agent.

---

## 12. Update, move, rename, uninstall
All commands run in `<clone>`. Use the **same `--name`** (and `--into`, if you used it) as when you installed.

### Update to a new version
```bash
cd <clone>
git pull
python3 install.py --name <name>                                  # case 1
python3 install.py --name <name> --into <repo>                    # case 2
python3 install.py --name <name> --into <main repo> --no-vscode   # case 2b
```
Your bundle id and repos come from `config.json`, so you don't need to repeat them. Then **restart the
agents** and read the newest section of [CHANGELOG.md](CHANGELOG.md) (new settings, what to test again).
Files you edited by hand are kept and shown as `KEPT`. Add `--force` to overwrite them.

### Move the agents to another place (case 1 ↔ case 2, or another repo)
A new install does **not** remove the old one. First uninstall, then install in the new place:
```bash
cd <clone>
python3 install.py --uninstall                     # config, profile, plans and runs stay
python3 install.py --name <name>                   # → case 1, for your user
python3 install.py --name <name> --into <repo>     # → case 2, into that repo
```
If you leave a repo, also remove your lines from its `.git/info/exclude`.

### Rename the agents
```bash
python3 install.py --uninstall
python3 install.py --name <new name>               # add --into <repo> for case 2
```

### Move the tool folder itself
The launchers contain the folder's path, so uninstall first:
```bash
cd <old clone> && python3 install.py --uninstall
mv <old clone> <new clone>                         # or clone again and copy tester/config.json,
cd <new clone> && python3 install.py --name <name> #    tester/profile.md, tester/plans/, tester/runs/
```

### Uninstall completely
```bash
cd <clone>
python3 install.py --uninstall --dry-run           # 1. preview: lists everything it would remove
python3 install.py --uninstall                     # 2. remove (asks before removing anything)
cd ~ && rm -rf <clone>                             # 3. delete the tool with your config, plans and runs
```
The uninstall:
- stops the UI driver and removes its runner app from the booted simulators;
- deletes the agents, skills and launchers from **every place you installed to**;
- removes the `simchat` entry from MCP config files. A file the installer created is deleted once it's empty;
- removes links in your repos that pointed at the removed files (case 2b). Links to other agents stay.

Files you edited by hand are kept; add `--force` to remove them too. Afterwards remove your lines from
`.git/info/exclude`. Simulators that weren't running may still have the runner app:
`xcrun simctl uninstall <udid> dev.simchat.SimDriverUITests.xctrunner`.

## 13. All installer options
| Option | Meaning |
|---|---|
| *(none, in a terminal)* | Guided mode: asks the questions and waits for your OK at each step. Same as `--guided`. |
| `--name NAME` | Agent name (default `chat-tester`); the planner is `NAME-planner`. Letters, digits, `-`, `_`. |
| `--bundle-id ID` | Bundle id of the app under test (Xcode → app target → General). |
| `--app-repo DIR` / `--bot-repo DIR` | Repos the agents may read. Saved in `config.json`. |
| `--repo ROLE=DIR` | One more readable repo; repeat for more (e.g. `--repo docs=<docs repo>`). |
| `--into REPO` | Install into that repo's `.github` (cases 2 and 2b) instead of your user folders. |
| `--copilot-home DIR` | Copilot's user folder for case 1 (default `~/.copilot` or `$COPILOT_HOME`). |
| `--vscode-dir DIR` | VS Code's user folder (default `~/Library/Application Support/Code/User`). |
| `--no-vscode` | Don't register the tool for VS Code. |
| `--python PATH` | The Python that runs the tool (default: the one running `install.py`). |
| `--ask-approval` | Copilot asks before every tap or message. |
| `--skip-build` | Don't build the UI driver. |
| `--dry-run` | Only show what would happen. Also with `--uninstall`. |
| `--yes` | Don't ask for confirmation. |
| `--force` | Also overwrite or remove files you edited by hand. |
| `--uninstall` | Remove what the installer put in place. |

## 14. What the agent can and cannot do
- It **can** read the repos you configured, drive the app through `simchat`, read local endpoints
  (`127.0.0.1` only) and the log files in `config.json`, and write only to `tester/runs/` and `tester/plans/`.
  The planner can only write plans.
- It **cannot** run shell commands, change your code, start or stop your services, or reach anything that
  isn't local.
- It taps only what the bot offered, types only what the plan says, waits after each action and never
  resends blindly.
- It never confirms payments, signatures or other commitments and never uses real personal data. Rows that
  change something stay `blocked` unless you clear them in the plan (section 8).

## 15. Troubleshooting
| Problem | What to do |
|---|---|
| The agent doesn't appear in Copilot | Case 2/2b: start Copilot **inside** that repo. Restart Copilot after installing. |
| An older agent with the same name shows up | The installer warns `WARN … <name>.agent.md exists`. Remove that file or install with another `--name`. |
| `simchat` tools are missing or denied | Start with the launcher (`<clone>/tester/bin/<name>`), not plain `copilot`. Under an approval policy, answer "yes, for this session". Don't use `-p`. |
| The planner can't read a guide behind a symlink | Run `install.py` again (it adds the link targets to the launchers), or start with `--add-dir <real folder>`. |
| "UI driver is not running" | `python3 <clone>/tester/simchat_server.py start_driver wait_s=110`. The first start builds for 1–3 min. |
| `status` shows `driver.outdated` | `stop_driver`, then `start_driver` (it rebuilds). |
| The driver build failed | See `<clone>/tester/driver/.build/install-build.log`. Signing errors: set `"driver": {"xcodebuild_args": "CODE_SIGNING_ALLOWED=NO"}` in `config.json` and run `install.py` again. |
| "Several simulators are booted" | Set `simulator.udid` in `config.json` (`xcrun simctl list devices booted`). |
| The agent doesn't reach the chat after launch | Set `app.after_launch` to the taps that open it, e.g. `["<menu entry>"]`. |
| Send isn't found | Add your Send button's label to `chat.send_labels`. |
| Debug banners are read as messages | Add a regex to `chat.ignore_labels`. |
| The same reply twice isn't detected | Configure `reply_evidence` (section 5). |
| No session id found | Check `logs` in `config.json` and that the bot logs to that file; or tell the agent the id. |
| A link opens Safari with an error | Expected in the Simulator: it counts as success when the row expects a link. |
| Watch the driver directly | `<clone>/tester/driver/run-driver.sh <udid> <bundle id>`; runtime log: `<clone>/tester/driver/.build/driver.log`. |
| Xcode can't open the driver project | In Xcode: new iOS App project, add a *UI Testing Bundle* target `SimDriverUITests` (Target Application: None), add `tester/driver/SimDriverUITests/SimDriverServer.swift`. |

## 16. Folder layout and development
```
install.py                the one command (install, update, uninstall)
templates/                the 2 agents + 3 skills (filled in with your name and paths on install)
tester/
  simchat_server.py       the simchat tool: MCP server (no arguments) and command line (with arguments)
  simchat/                Python, standard library only
  driver/                 the UI driver: an Xcode project with one Swift file (XCTest, serves 127.0.0.1)
  bin/                    the launchers (written by install.py)
  config.example.json     → config.json (yours)
  profile.example.md      → profile.md (yours)
  plans/                  test plans and results (yours are git-ignored)
  runs/                   one folder per run (git-ignored)
tests/                    unit tests: python3 -m unittest discover -s tests   (no simulator needed)
GUIDE_FOR_AGENTS.md       for an AI agent that sets up or evaluates the tool
CHANGELOG.md              what changed, what to test again
```
The unit tests run everything against a fake app and a fake driver that speak the same protocol as the Swift
driver. Code must stay Python 3.9-compatible and standard-library only.
