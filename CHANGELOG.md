# Changelog

Newest first. After pulling: `python3 install.py` (with your usual flags), then restart both agents.

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
