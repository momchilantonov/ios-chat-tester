# Guide for agents: set up, check and evaluate the chat tester

You are an AI agent asked to install, configure, check or evaluate this tool on a Mac for a human. Follow this
guide step by step. The human may not run any command themselves, so report clearly what you did, what you
found and what they must decide.

**Ground rules**
- This repository is **public**. Never commit or push anything to it. Never put project or company details
  (names, bundle ids, bot texts, URLs, flows) into tracked files. They belong only in the git-ignored local
  files `tester/config.json`, `tester/profile.md`, `tester/plans/*` and `tester/runs/*`.
- The app and the bot are the system under test. Read their code, but don't change it to make a test pass.
- Don't start, stop or restart the human's services (bot, mocks, Xcode). If one is missing, say which one and
  the command from the profile.
- Ask the human for values you cannot find: bundle id, ports, which menu entry opens the chat, and so on.

## 1. Install or update
```bash
cd <this clone> && git pull
python3 install.py --name <agent-name> --bundle-id <bundle id> --app-repo <ios app repo> --bot-repo <bot repo>
```
- Pass flags. Without arguments, in a terminal, the installer runs the guided mode, which asks questions.
  Re-running with only `--name <agent-name>` keeps the earlier values.
- It installs two agents, `<agent-name>` (runs tests) and `<agent-name>-planner` (writes plans), 3 skills, and
  the `simchat` MCP server for Copilot CLI and VS Code. It writes the launchers `tester/bin/<agent-name>` and
  `tester/bin/<agent-name>-planner` and builds the UI driver with `xcodebuild`.
- Exit code 1 means there are things to fix. They are listed at the end of the output.
- **After every update, restart the agents.** A running session keeps the old instructions.
- If the output has `WARN ... <name>.agent.md exists`: a same-named agent file in a repo can take precedence
  over the installed one. If it is empty or stale and not tracked by that repo's git, tell the human and
  suggest removing it. Don't delete tracked files yourself.
- If the clone lives inside another repo, add its folder to that repo's `.git/info/exclude`.
- Driver build failed: see `tester/driver/.build/install-build.log` and the README's "Troubleshooting the
  driver" section.

## 2. Configure `tester/config.json` (local, git-ignored)
| Key | What to put there | How to find it |
|---|---|---|
| `app.bundle_id` | the app under test | Xcode → app target → General → Bundle Identifier |
| `app.after_launch` | taps from a fresh launch to the chat, e.g. `["<menu entry>"]` | launch the app; the entry that opens the chat with the bot under test |
| `endpoints` | local bot endpoints for evidence, e.g. `{"extract": "http://127.0.0.1:<port>/extract/{session_id}"}` | bot repo / profile; only `127.0.0.1` is allowed |
| `reply_evidence` | `endpoint`, `list`, `match`, `text` that pick bot replies out of that endpoint's JSON | fetch one real response and look at its structure, e.g. `python3 tester/simchat_server.py fetch endpoint=extract` after `find_session_id` |
| `logs` | bot log file(s), e.g. `{"bot": "~/chat-logs/bot.log"}` | the human starts the bot with `... 2>&1 \| tee <file>`; without it, `app_log` still works |
| `chat.ignore_labels` | regexes for screen noise: scroll-bar labels, date separators, debug banners | `screen` output: labels that are never chat content |
| `chat.send_labels` / `send_ids` | only if the Send button isn't found | `screen` output |
| `session.regex` | only if `find_session_id` finds nothing | a log line that contains the id |
| `simulator.udid` | only if several simulators are booted | `xcrun simctl list devices booted` |

`reply_evidence` is strongly recommended. It detects bot replies that repeat an earlier message and gives the
full text of long messages, which the screen may show only partly.

## 3. Write `tester/profile.md` (local, git-ignored)
The agents read it first. Fill every TODO from `profile.example.md`:
- the product, and which chat or menu entry reaches the bot under test;
- the customer language, and that reports are in English;
- how the human starts the stack (commands, ports, log file);
- the evidence endpoint and what its JSON contains;
- how to find the session id;
- the bot's error reply, verbatim;
- where flows, response texts and functions live in the bot repo;
- project rules: scope, test data only, nothing that may be confirmed;
- **accepted Simulator behaviour.** Always include: *"Links and deeplinks cannot open in the Simulator; a tap
  that opens Safari or another app counts as success when the row expects a link."*

## 4. Smoke test without an LLM
Each command prints JSON. Watch the Simulator while they run.
```bash
T=tester/simchat_server.py
python3 $T status                      # config, simulator, driver, ports, profile, plans
python3 $T start_driver wait_s=110     # repeat while phase is "starting"
python3 $T open_app fresh=true         # should end on the chat screen (app.after_launch)
python3 $T wait_for_reply              # welcome message, if any
python3 $T send_message text="<a real customer sentence>"
python3 $T wait_for_reply              # new_messages, buttons, controls
python3 $T find_session_id             # then: python3 $T fetch endpoint=<name>
python3 $T screen                      # element listing with [index], types, SELECTED/(disabled)
```
Each CLI call is a separate process, so per-turn state (the anchor, seen texts) doesn't carry over between
calls. Use the CLI to check the plumbing, and judge reply detection with the agent.

## 5. Plan, then test
1. `tester/bin/<agent-name>-planner` → "Make a test plan for <flow>" or "Turn section <x> of @<guide.md> into a
   plan". It writes `tester/plans/<name>.md` (format: `tester/plans/README.md`). The prompts must be copied
   word for word from the source.
2. `tester/bin/<agent-name>` → "Run plan <name>". It fills the Result column: `success`, `fail: …`,
   `blocked: …`. Rows not run become `blocked: not run`, with verdict INCOMPLETE.
3. Results: `tester/plans/<name>.result.md`. Evidence: `tester/runs/<time>_<name>/`.

**Approvals:**
- The launchers pass `--allow-tool simchat`.
- If an organisation policy forces approval of MCP tools, answer "yes, for this session" once per tool, about
  10 times.
- Non-interactive runs (`copilot -p`) are not possible under such a policy.

**Model:** use the strongest available model (Opus-class) for both agents. Once things are stable, a
Sonnet-class model may do for the tester: compare the results of the same plan. Avoid small or fast models.

**Running in the background:** the driver doesn't use the real mouse or keyboard, so the human can keep
working. Don't touch the same Simulator, don't press Run in Xcode, and keep the Mac awake during long runs
(`caffeinate -dims`). The Simulator comes to the front once when the driver starts
(`simulator.open_simulator_app: false` turns that off).

## 6. Evaluate and report back
For each problem, report:
- what you asked the agent;
- what it did (the tool name and the JSON result it got);
- what you expected;
- the relevant `screen` listing lines (they show how iOS exposes the element);
- for driver problems, `tester/driver/.build/driver.log` (tail);
- for wrong results, the plan row and its `results.md` line.

Name the tool version (`git log --oneline -1`). See `CHANGELOG.md` for what changed and what to test again.

**Not a bug:**
- a link opening Safari with an error page;
- texts in `new_messages` that are quick-reply labels, if the app doesn't expose them as buttons (the agent
  must still tap them).

## Local changes and updates
- This clone is **read-only for you**: update it with `git pull`, never push, never open pull requests from
  this machine. Improvements reach the repository through the human's report (section 6); the maintainer
  makes them and pushes, and you pull.
- If you had to change a tracked file to get something working, keep it small and include it in your report
  (`git diff`). Before the next update: `git stash && git pull && git stash pop`. If the stash conflicts,
  prefer the pulled version and tell the human.
- `git status` should only show nothing or your own temporary edits. Local config, profile, plans and runs are
  git-ignored.

## Known limitations
- Without `reply_evidence`, a reply identical to an earlier message is not detected as new.
- The screen may show only the first part of a long message. Exact-text checks need the endpoint evidence.
- Elements are only what iOS accessibility exposes. Custom views without labels can't be read. Point at them
  by coordinates or ask the app team for accessibility labels.
