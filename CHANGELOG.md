# Changelog

Newest first. After pulling: `python3 install.py` (with your usual flags), then restart both agents.

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
