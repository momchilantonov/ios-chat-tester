---
name: chat-testing
description: How to hold a test conversation with a chat assistant in the iOS Simulator using the simchat tools - the turn loop, waiting, tapping quick replies, gathering evidence from the endpoint and logs, and troubleshooting. Load before the first conversation of a session.
---

# Chat testing with simchat

## The turn loop
```
open_app(fresh=true)             # clean conversation; taps through app.after_launch (e.g. a demo menu) to the chat
wait_for_reply()                 # welcome message, if the app shows one
send_message("...")              # types, reads back, taps Send ONCE, confirms
wait_for_reply()                 # -> new_messages, buttons "[12] Label"
check(name, passed, evidence)    # one per expectation
tap(element=12)                  # a quick reply from the list you just got
wait_for_reply()
...
```
- `wait_for_reply` returns when new bot content appeared and the screen was quiet for `quiet_ms`.
  `replied: false` + `timed_out` means nothing new arrived - look (`screen`, `screenshot`) and read the log
  before deciding it is a bug. A slow bot is not a missing answer: one more `wait_for_reply(timeout_s=60)`
  is fine.
- **`tap_mismatch`** (`{"asked": ..., "sent": ...}`): your tap landed on another element - the app shows a
  different text as your message. That step is **invalid, not a bot result**: don't judge the reply against
  the row. `screen()`, tap the right `[index]` and continue; if it repeats, record the row `blocked` with the
  mismatch. A submit button whose echo lists the rows you selected ("Continue" -> the chosen cards) is not
  a mismatch. `skipped_hidden_copies` means invisible copies of the label were avoided - nothing to do;
  `screen()` marks such copies `HIDDEN-COPY` and they are never messages or tap targets.
- **Links / deeplinks**: when a tap opens another app (Safari, even a 404 page), `tap` returns
  `left_app: true` and brings the app back. That is the expected Simulator behaviour - if the row expects a
  link, record `success`; never report the opened page as a bug. Then `screen()`: the chat may have reset.
  An in-app web page instead returns `left_app: "in_app_browser"`: also success for a link row; close it with
  its Close/Done button (`screen()` lists it) before the next message.
- **`local_only: true`**: the app drew text but the bot's endpoint has no new reply - a local "please wait"
  text, not the bot's answer. `wait_for_reply()` again for the real reply; if none comes, that's the finding.
  `interim_messages` are such texts the config marks (`chat.interim_labels`); never judge the row by them.
- **Long messages**: the screen may show only the first part of a long bubble. For exact-text checks use the
  endpoint evidence (`evidence_texts` from `wait_for_reply` when configured, or `fetch`) and say so in the note.
  A reply longer than the screen is read from its start automatically (`scrolled_up`). `evidence_texts_missing`
  lists paragraphs the bot sent that were not found on screen: scrolled away or not rendered - `screenshot()`
  and decide; not rendered is an app bug (S2).
- **Action cards** (`actions: ["[n] New transfer ›"]`): full-width rows the user can tap, not chat text.
  Tap them like options.
- **Options are tapped, never typed.** Some apps don't expose quick replies as buttons; then their labels
  appear in `new_messages`/`screen()` as text. Tap them anyway: `tap(element=n)` or `tap(text="label")`.
  `send_message` refuses to type a label that is on screen and tells you which element to tap.
- Element indexes change with every screen. Use indexes from the **latest** `wait_for_reply`/`screen`.
- **Order**: `buttons`, `options`, `controls` and `new_messages` are in screen order (top to bottom, then left
  to right). Judge order from that, or from the `@(x,y)` coordinates.
- **Selectable rows without checkboxes**: rows between the bot's question and a disabled button come back
  as `options` (`[index] name · detail`). Tap a row by its index; when no SELECTED state is exposed, the
  disabled button (e.g. Continue) becoming enabled is the sign the selection worked.
- **`select <label> · <detail>`** (`select DEBIT MASTERCARD · 4321`): `tap(text="DEBIT MASTERCARD · 4321")` taps
  the row whose next line or neighbour contains the detail. When a label is on screen more than once with
  different details, `tap(text=...)` refuses with `ambiguous: [...]` - tap by `[index]` or label · detail.
- **Positional prompts** (`tap first option`, `select second row`): count top to bottom among the options
  of the bot's latest message (`buttons`, `options`, `controls`).
- **Rich components**: `wait_for_reply` lists `controls` (list rows, checkboxes, switches, pickers). `SELECTED`
  marks the selected state and `(disabled)` marks buttons that are not usable yet. Typical: tap a row ->
  `screen()` to confirm it is SELECTED and that "Continue" is enabled -> tap "Continue" -> `wait_for_reply`.
  Row taps usually don't make the bot answer; only call `wait_for_reply` after the action that sends.
- A reply identical to an earlier message: below your new message it is reported when something follows it
  (buttons) or the endpoint evidence confirms it; otherwise only the endpoint shows it (a `note` says so).
  `screen()` lists suspected `hidden_copies` of old bubbles separately.
- `app_alerts`: in-app alerts, sheets, banners and dialogs drawn over the chat (`kind: "dialog"` with `texts`
  and `buttons`, e.g. "end the conversation?"). Read them; tap their buttons only if harmless or the row asks
  for it. `send_message` refuses while a dialog covers the chat.
- Long replies may scroll. If the reply looks cut off, `screen()`; `scroll("up")` to read earlier parts.

## Swiping, carousels, long press
- **Carousels** (cards, accounts, offers shown side by side): `screen()` lists the container as
  `[n] collectionView ... 390x120`. `swipe("left", element=n)` shows the next item, `swipe("right", element=n)`
  the previous one - direction is where the finger moves. The result lists `now_visible` texts; check each
  item you need. Stop when `changed` is false (end of the carousel).
- You can also swipe on visible text (`swipe("left", text="Debit card")`), a point, or the screen centre.
  `speed="fast"` flicks (paging), `speed="slow"` drags precisely (sliders). `distance` 0.1-0.95.
- **Long press** (`long_press(element=n)`) opens context menus, e.g. copy a message; then `screen()`.
- After any swipe or long press the `[index]` numbers change: call `screen()` before tapping.
- Only swipe things a real user would; never swipe to confirm a payment or any commitment.

## Writing as the user
- Natural sentences in the customer language from the profile, like a real person, not keywords.
- Vary wording across runs; one realistic detour (a follow-up question, a typo, changing your mind) per
  exploratory run unless told otherwise.
- Never real personal data. Use the test data the profile names.

## Evidence, strongest first
| Evidence | How | Proves |
|---|---|---|
| Endpoint JSON | `fetch(endpoint, vars={...}, path=...)` | what the bot really received/sent: payloads, function calls |
| Screen | `wait_for_reply`, `screen`, `screenshot` | what the user actually saw (rendered) |
| Bot log | `read_log(since="turn")` | errors and internal steps for this turn (only if the bot logs to a file) |
| App log | `app_log(since="turn", grep=...)` | the app/SDK side: requests, errors, often the session id |

- **Button taps:** the screen shows the label; the payload is in the endpoint JSON. When the profile says
  where payloads appear, verify after a tap that the expected payload arrived (not just the label).
- **Rendered vs sent:** a bot message in the endpoint JSON that never appears on screen is a bug (S2).
- `check` evidence must be concrete: quote the bot text, name the button and payload, paste the log line.
- `screenshot` at the key moments (first answer, each decision point, the final state, any error).

## Evidence and session id
- With `reply_evidence` configured, `wait_for_reply` reports `evidence_new_replies`, the full `evidence_texts`,
  `evidence_flows` (which flow answered) and `evidence_options` (options the bot sent);
  `evidence_options_missing` = sent but not drawn - check `screen()`, it may be an app/bot bug.
- `"evidence": "off - ..."` means the endpoint isn't used for this turn - say so when a check depends on it.
- The app leaving the foreground (a link) is reported as `left_app` by `tap` or by the next screen read.

## Session id
`send_message` looks for it automatically after the first message of a conversation (when `reply_evidence`
needs it). `find_session_id()` searches the app log and the bot log since the last fresh launch (patterns:
`session.regex`) and takes the newest id. None -> follow the profile or ask the user, then `set_session_id`.
`open_app(fresh=true)` starts a new conversation and clears it.

## Checks to consider each turn
- The reply is relevant and in the right language; no error/fallback reply (profile lists the error text).
- Expected buttons are offered (and only sensible ones).
- `read_log(since="turn")` has `error_count: 0` - or explain the errors.
- Reply time is acceptable (`waited_s`; above ~10 s is worth a note).

## Troubleshooting
| Symptom | Do |
|---|---|
| `status` driver stopped | `start_driver`; repeat while "starting". If it fails, show the user `log_tail`. |
| "no booted simulator" / "several simulators" | ask the user to run the app from Xcode / set `simulator.udid` |
| app not foreground | `open_app()` |
| system alert (permissions) | `tap(alert_button="Allow")` or the label shown in `alerts` - only if harmless |
| "typed text did not read back" / "could not clear" | nothing was sent; `screen()`; retry once; then `note(kind="bug")` |
| `open_app` lands on a menu, not the chat | the user should set `app.after_launch` in config.json (e.g. `["<menu entry>"]`) |
| noise in `new_messages` (banners, debug labels) | the user can add regexes to `chat.ignore_labels` in config.json |
| `read_log` has nothing / no log configured | use `app_log`; ask the user to start the bot with `... 2>&1 | tee <log file>` |
| "Send button not found" | tell the user to set `chat.send_labels`/`send_ids` in `{{TESTER_DIR}}/config.json` (show `screen()`) |
| send `confirmed: false` | do NOT resend; `screen(image=true)`, then decide |
| endpoint "cannot reach" | the service is down - tell the user the start command from the profile; BLOCKED |
| bot shows its generic error reply | `read_log(since="turn")`; quote the error; usually a local setup issue |
