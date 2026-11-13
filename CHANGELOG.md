# Changelog

Newest first. After pulling: `python3 install.py` (with your usual flags), then restart both agents.

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
