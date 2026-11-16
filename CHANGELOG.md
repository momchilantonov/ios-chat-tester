# Changelog

Newest first. After pulling: `python3 install.py` (with your usual flags), then restart both agents.

## Round 10 – requirements R10-1, R10-2 from the ninth real run (verdict: ready for unattended runs)
**After pulling:** run `install.py`, restart both agents. Driver unchanged (version 3). No new config keys.

- **R10-1:** every command `install.py` runs goes through `Installer.run` (also the simulator listing and the
  runner-app uninstall), and the installer tests answer every `xcrun simctl` themselves - running the unit tests
  no longer removes the driver's runner app from the real simulator. `start_driver` retries once by itself when
  the first launch fails with "failed to launch" (result: `retried`).
- **R10-2:** picker rows are only the texts in the cell that holds the disabled Continue; the question is the
  last text above that cell. After a rejected typed text ("choose from the list" + the picker again) the caption
  stays in `new_messages` and `options` has only the rows - as for the first picker.

**Test again:** `python3 -m unittest discover -s tests` while the driver runs (it keeps running); a typed text
at the picker, then `options` and `screen()["options"]`.

## Round 9 – requirements R9-1 … R9-5 from the eighth real run
**After pulling:** run `install.py`, restart both agents. Driver unchanged (version 3). No new config keys.

**B – hides something that did happen**
- **R9-1 (high):** re-entering a finished flow. Cause: the scroll measurement paired the new picker caption with
  the old one (same text, same frame shape), so the user's old echo seemed still on screen and the new echo was
  taken for it. Now a text counts for the measurement only if it occurs once in the whole snapshot (off-screen
  copies included), possible ghost copies are left out, and the most common move wins. With the bot's evidence
  already showing the new reply, the newest echo is the echo whatever was counted; everything below it is new.

**A – reports something that did not happen**
- **R9-2:** widget markup without real text (`[CHECKBOX None | None …]`, also cut across evidence items) expects
  no text; a widget's items are split on `|`. Its rows are checked through `evidence_options`.
- **R9-3:** two copies with the same text at exactly the same frame that are not parent and child (two ghosts
  of an old echo) are now hidden-copy candidates, so the driver is asked about them.

**C – the rest**
- **R9-4:** `screen()["messages"]` prefixes the user's own bubbles with `you: `.
- **R9-5:** the unit tests used the real driver state file and stopped a running driver (the uninstall test,
  through `install.py` importing the already loaded `simchat`). The tests now use a temporary state file, and
  `install.py` stops only its own clone's driver, in a separate process.

**Not changed:** a bot text repeated after the new echo as the *last* bubble (e.g. the help-with-else line) is
still skipped without evidence when it may be a hidden copy (Round 5 rule); with `reply_evidence` it is reported.

**Test again:**
- R9-1 first: the full card-block flow, Cancel, then the start prompt again in the same conversation;
- the picker reply's `evidence_texts_missing` (R9-2); `screen()` after re-entry (R9-3, R9-4);
- `python3 -m unittest discover -s tests` while the driver runs: it keeps running (R9-5).

## Round 8 – requirements R8-1 … R8-7 from the seventh real run
**After pulling:** run `install.py` (it rewrites the launchers), restart both agents. The driver is unchanged
(version 3). No new config keys.

**A – reports something that did not happen**
- **R8-1 (blocker):** Round 7's "ends within 32pt of the right edge" rule is gone - in the real app picker rows end
  closer to the edge (358) than the user's bubble (350). "User side" is now decided by structure: a text in a
  cell that also holds the bot's avatar image or a button (a picker row next to Continue) is never the user's;
  then the right half of the screen. After the first sent message the tool learns where the user's bubbles end
  (±4pt) and requires that edge. The sent/tapped text stays the echo candidate at any y, also under the bars.
- **R8-3:** the evidence check reduces widget markup to the text it shows (`[SELECT Your points\n0.0 PTS]` →
  "Your points", "0.0 PTS", also across lines) and compares numbers loosely ("0.0" = "0," = "0").

**B – hides something that did happen**
- **R8-2:** with R8-1 the echo under the nav bar is found again, so the reply behind the banner is read by
  scrolling (or returned in `under_bar`). Picker rows that share one cell with Continue are separate options.
- **R8-5:** "hittable" answers are kept only until the next action, and `screen()` always asks again: a real
  bubble above the composer can become a hidden copy at the same frame. Hidden copies stay hidden.

**C – the rest**
- **R8-4:** when typing fails with "no keyboard focus" (right after a fresh launch), the composer is tapped again
  and typing is retried for up to 5 s - nothing is typed by the failed attempt.
- **R8-6:** the launcher test compares resolved paths (macOS `/var` → `/private/var`).
- **R8-7:** the planner launcher's `-p` line says the planner prints the plan but can't save it under `-p`.

**Changed tests:** the two Round 5 fixtures changed in Round 7 are back at their original 40pt from the edge (as
the real app). The fake app's tap no longer stops at an unlabelled container cell (the real app taps the
button inside it).

**Test again:**
- R8-1 first: one FAQ question (no own prompt in `new_messages`), a chip Cancel, re-entry with the same prompt;
- type a card name while the picker is shown (R8-2); an FAQ reply with a rich card (R8-3);
- the first `send_message` right after `open_app(fresh=true)` (R8-4); `screen()` after a few flows (R8-5).

## Round 7 – requirements R7-1 … R7-7 from the sixth real run
**After pulling:** run `install.py` (it rebuilds the driver - version 3 - and rewrites the launchers), restart
both agents. If `status` shows `driver.outdated`: `stop_driver`, then `start_driver`. No new config keys.

**A – reports something that did not happen**
- **R7-1:** the user's echo is found also under the navigation bar or a top banner (lists scroll it there after
  a send/tap); those elements are still never reported as messages. "User side" = the bubble (or a tight
  wrapper) ends within 32pt of the right screen edge - a picker row right of the middle is no anchor. The
  user's old bubbles are counted only if they are still on screen (the scroll since the action is measured), so
  re-entering a flow with the same prompt anchors on the new echo. New reply texts under the bar/banner are read
  by scrolling up (as for long replies); what still can't be read comes back as `under_bar` and is missing in
  the evidence check.
- **R7-2:** a text inside any button frame - also a hidden copy or one under a bar - is a caption, never a
  message. A new bubble on the user's side that shows the selected rows (the submit echo) counts as the echo
  even when the anchor isn't found: everything above it is old.
- **R7-3:** cause found: the driver's `hittable` looked only at the first 12 copies of a label, and a closing
  line like "Anything else I can do for you?" has more. Now the tool sends the frames it needs and the driver
  (version 3) looks through all copies, binding only the wanted ones. Unresolved frames are cached.

**B – hides something that did happen**
- **R7-4:** an open dialog stays a dialog after `wait_for_reply` reported it: `screen()` lists it in
  `app_alerts` (texts not in `messages`), and `send_message` refuses with its text and buttons and says to tap.

**C – planner**
- **R7-5:** picker rows always by visible text (no `select first row`); a disabled control is never a step
  (an empty selection is typed, e.g. "none of them"); every picker/chip step gets a re-entry row and a typed-option
  row. New plan form `type: <text>` = typed even if it is an option label (`allow_button_text=true`).
  `plans(name)` returns `warnings` for positional rows, disabled steps and missing branches; the planner fixes
  them before it replies.

**D – the rest**
- **R7-6:** disabled buttons above the user's latest bubble (an answered Continue) move from `buttons` to
  `stale_buttons` (in `wait_for_reply` and `screen()`). `screen()` lists picker rows under `options`, not
  `messages`. An ignored banner (`chat.ignore_labels`) is no `app_alert`.
- **R7-7:** the launchers pass the MCP config themselves (`--additional-mcp-config=@tester/bin/mcp-config.json`),
  and `-p` prints one line: it fails if MCP tools need interactive approval - run without `-p`.

**Changed tests:** two Round 5 fixtures (`test_echo_matches_label_with_ios_dot`,
`test_trailing_copy_of_an_old_bubble_is_not_new`) had a "user bubble" ending 40pt before the right edge. Under
R7-1 that is not a user bubble, so the fixtures now end 20pt from the edge; the assertions are unchanged.

**Test again:**
- R7-1 first: re-enter the card-block flow after Cancel; type a card name while the picker is shown;
- select 2 cards → Continue (R7-2): only the confirm question, no caption, no history;
- `screen()` after a few flows: the ghost of the closing line is `HIDDEN-COPY` (R7-3);
- Close → `wait_for_reply` → `screen()` → `send_message` (R7-4); the planner on the same section (R7-5);
- `bin/<name> -p "..."` from the bot repo (R7-7).

## Round 6 – requirements R6-1 … R6-9 from the fifth real run
**After pulling:** run `install.py` (it rewrites the launchers: symlinked folders in the repos are now
readable), restart both agents. No new config keys.

**A – reports something that did not happen**
- **R6-1:** every screen read marks hidden copies: texts/buttons whose frames overlap another one's (real
  bubbles never overlap) and that the driver reports as not hittable (cached per conversation). They are never
  messages, anchors or tap targets; `screen()` lists them with `HIDDEN-COPY`.
- **R6-2:** the anchor is only a bubble on the user's side - never a picker row, button or hidden copy with the
  same text. A multi-line echo is matched as a whole.
- **R6-3:** after a tap the whole echo bubble is read; the reply is anchored below it. `tap_mismatch` only when
  an echo line is a *different* tappable label on screen and not a row selected since the latest reply - the
  submit echo listing the selected cards is fine.

**B – hides something that did happen**
- **R6-4:** with evidence, the wait ends only when every paragraph of the new reply is on screen (or, for a
  reply longer than the screen, its last part), or `render_grace_s` after the evidence arrived – then
  `evidence_texts_missing`.
- **R6-5:** option rows without a cell: short text lines at the same x, stacked closer than the rows are
  spaced, form one option (`name · number`).
- **R6-6:** a label shown several times in the latest reply with different details is refused:
  `ambiguous: ["[i] DEBIT MASTERCARD · 4000…", ...]`. `tap(text="DEBIT MASTERCARD · 4321")` taps the row whose
  next line or neighbour has the detail.

**C – planner**
- **R6-7:** an unreadable source stops the planner (real path + `--add-dir` hint), and the launchers now add the
  real folders that symlinks in the repos point to. A row confirming a state change is
  `blocked: state-changing - needs operator OK` unless the guide allows it. One row per branch and rejection
  (invalid input, empty selection, typed yes/no, hand-off, linked flows' first responses). Picker rows by
  visible text (`select DEBIT MASTERCARD · 4321`). Second worked example: picker + confirmation.

**D – the rest**
- **R6-8:** a dialog drawn over the chat (no composer, new texts and buttons) → `app_alerts` with
  `kind: "dialog"`, `texts`, `buttons`; `send_message` refuses and names it; `wait_for_reply` returns on it.
- **R6-9:** elements under the navigation bar or a top banner that don't belong to it are not listed.

**Test again:**
- R6-1 first: re-enter the card-block flow in one conversation, an invalid answer, "none of them";
- typing a card name while the picker is shown (R6-2); select 2 cards → Continue (R6-3);
- a 2-bubble reply (R6-4); the 8-card picker (R6-5); two "DEBIT MASTERCARD" rows (R6-6);
- the planner on the same guide section through the symlink (R6-7); the close-chat dialog (R6-8).

## Round 5 – requirements R5-1 … R5-11 from the fourth real run
**After pulling:** run `install.py` (it rebuilds the driver and stops the old one; `status` shows
`driver.outdated` if an old one still runs, then `stop_driver` + `start_driver`). In `tester/config.json` set
`waits.app_switch_s` to `6` (or delete the key) and, if the app shows local "please wait" texts,
`chat.interim_labels`.

**A – reports something that did not happen**
- **R5-1:** a tap by text skips copies the driver reports as not hittable (new driver command `hittable`;
  `skipped_hidden_copies: n`). A tap by `[index]` on a hidden copy is refused. After every tap on a
  button/option, the user's echo bubble is compared with the label: a different one returns
  `tap_mismatch: {"asked", "sent"}` (journaled) and the next `wait_for_reply` anchors on what was really sent.
- **R5-2:** the anchor and texts are compared without iOS's trailing "." ("Keep consent." = "Keep consent").
- **R5-3:** with `reply_evidence` working, on-screen text alone no longer ends the wait: it ends when the
  endpoint has the new reply and the screen shows it. At the timeout, texts without a bot event come back with
  `local_only: true`. New optional `chat.interim_labels` (regexes): such texts go to `interim_messages`.
- **R5-4:** the anchor matches exactly; a 30-character prefix only for a bubble on the user's side.

**B – hides something that did happen**
- **R5-5:** below the user's new message every bubble counts, also a text seen before (a sub-menu with the
  main menu's title). A repeated text sitting below everything else counts only if the endpoint confirms
  it or something tappable follows it; otherwise it is a hidden copy of an old bubble. *Changed test:*
  `test_round2.test_identical_reply_detected_via_endpoint` now expects the repeat in `new_messages` (it used
  to get only a `note`) – stricter, not looser.
- **R5-6:** a reply longer than the screen: when the user's message is not visible and the reply starts at
  the top, it scrolls up (max 3 swipes), collects the bubbles, scrolls back (`scrolled_up`). Evidence
  paragraphs (markers like `[QUICK-REPLY …]` dropped) not found on screen → `evidence_texts_missing`.
- **R5-7:** full-width single-line rows that are not sentences, below the last bubble → `actions` (tappable,
  not in `new_messages`). If a short final bot message shows up there instead, report it.

**C – planner**
- **R5-8:** copy one of the guide's example prompts verbatim; block a row only if the guide explicitly needs
  other data/setup or a forbidden action, else keep it runnable with `precondition: <what>` in Expected;
  reply "N rows runnable, M blocked" from the new `plans(name).summary`. Worked example in the planner.

**D – the rest**
- **R5-9:** `waits.app_switch_s` default 6. The watch ends early as soon as the chat changes, so normal taps
  are not slower. An in-app web page over the chat → `left_app: "in_app_browser"` with a hint to tap
  Close/Done; `send_message` refuses to type into it.
- **R5-10:** texts inside the same cell (name above a masked number) form one option.
- **R5-11:** `find_session_id` no longer says "several candidates" for one; `screen()` lists trailing hidden
  copies of old bubbles under `hidden_copies` instead of `messages`; in-app alerts, sheets and banners
  (id containing banner/toast/snackbar/notification) → `app_alerts`. The typing indicator is never a message.

**Test again:**
- R5-1 and R5-3 first: the old-menu taps near the composer, and a flow with a local "please wait" text (set
  `chat.interim_labels`);
- the sub-menu with the main menu's title (R5-5), the long FAQ answer (R5-6), the action card (R5-7);
- the planner on the same guide section (R5-8): compare runnable/blocked counts;
- links that open slowly or in-app (R5-9), the card picker (R5-10).

## Round 4 – requirements R1–R11 from the third real run
- **R1:** if the endpoint already has the reply but the screen doesn't, `wait_for_reply` waits up to
  `waits.render_grace_s` (default 6 s) for it to appear.
- **R2:** `tap(text=…)` matches part of a label only on buttons and controls, only for labels longer than 4
  characters or with several words, and prefers whole words. It never taps a chat bubble that merely contains
  the text.
- **R3:** after each tap the app state is watched for `waits.app_switch_s` (default 2 s), and every screen read
  checks it first. A backgrounded app is brought back and reported (`left_app`, `reactivated`). A crashed app
  (`notRunning`) is reported as a finding and not relaunched silently.
- **R4:** the session id is searched since the last fresh launch, and the newest id is taken. `send_message`
  looks for it right after the first message, so the first turn has evidence too. `"evidence": "off - …"`
  says when evidence isn't used.
- **R5:** a text covered by a button with the same label is not a carousel card. The trailing "." iOS adds to
  button labels is ignored when matching.
- **R6:** `buttons`, `controls` and `carousel` are in screen order.
- **R7:** positional prompts (`tap first option`, `select second row`). The planner pre-fills
  `blocked: needs <precondition>` for rows the tester cannot set up, and the tester skips them. No
  placeholders in prompts.
- **R8:** rows between the bot's question and a disabled button come back as `options`; a disabled button
  becoming enabled signals the selection.
- **R9:** `reply_evidence.options` / `option_regex` give `evidence_options`; options sent but not drawn are
  reported in `evidence_options_missing`.
- **R10:** `--into` honours `--no-vscode`.
- **R11:** the launchers warn about `-p` (non-interactive) runs. If saving a plan is denied, the planner
  prints it instead.
- **Extra:** `reply_evidence.flow` reports `evidence_flows`, showing which flow answered each turn without an
  extra `fetch`.

**Test again:**
- R1–R3 first: a fast bot with a slow screen, short-label taps, and links with slow app switches;
- several conversations in one plan (session id);
- the card picker (`options`);
- the Confirm/Cancel chips;
- the 5-option menu order;
- a plan with precondition rows.

## Round 3 – fixes from the second real run
- **Links and deeplinks:** a tap that opens Safari or another app returns `left_app: true` and brings the app
  back. If the row expects a link, it counts as success; the Simulator cannot open real links.
- **`tap(text=…)`:** prefers the copy of a label below the user's latest message. If nothing changes on
  screen, it reports `no_visible_effect` and the other copies.
- **Carousels:** cards are reported in `carousel` / `new_carousel_cards`, no longer as new messages.
- **`reply_evidence` (config):** counts bot replies in an endpoint. Detects replies that repeat an earlier
  one and returns `evidence_texts` with the full text of long messages.
- **Planner:** copies given prompts word for word; marks invented ones; no counts in prose.
- **Plans:** rows not run give the verdict INCOMPLETE and are counted as `not_run`.
- **`fetch`:** slices such as `events[-6:].text`.
- **Installer:** warns about a same-named `.github/agents/<name>.agent.md` in a repo.
- **Docs:** `GUIDE_FOR_AGENTS.md`; approvals under an organisation policy.

**Test again:**
- a plan with links;
- a plan with a repeated menu;
- carousels;
- long messages with `reply_evidence` configured;
- planner output against the guide's prompts.

## Round 2 – plans, planner, options
- **Plan format** `Flow | User prompt | Expected | Result`; Result is `success` / `fail: …` / `blocked: …`.
- **Planner agent** `<name>-planner`; tester tools `plans`, `start_run(plan=…)`, `record_result`; filled
  `<plan>.result.md`.
- **`send_message`** refuses to type a label that is shown as an option; the agent must tap options.
- **Launchers** pre-approve the `simchat` tools (`--ask-approval` to opt out).
- **`swipe` and `long_press`** tools; carousels and sliders are listed.

## Round 1 – fixes from the first real run
- **Reply detection** ignores scroll bars, placeholder labels and hidden copies of old bubbles;
  `chat.ignore_labels`.
- **New tools** `app_log`, `find_session_id`, `set_session_id`; `fetch` fills in `{session_id}`.
- **Rich controls** (rows, checkboxes) with SELECTED / disabled state; `app.after_launch` navigation.
- **Text fields:** robust clearing of a pre-filled composer.

## Initial version
- Own XCTest driver and a stdlib-only MCP server (Python 3.9+), with one-command install and uninstall.
