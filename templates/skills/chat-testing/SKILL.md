---
name: chat-testing
description: How to hold a test conversation with a chat assistant in the iOS Simulator using the simchat tools - the turn loop, waiting, tapping quick replies, gathering evidence from the endpoint and logs, and troubleshooting. Load before the first conversation of a session.
---

# Chat testing with simchat

## The turn loop
```
open_app(fresh=true)             # clean conversation (or fresh=false to continue the current one)
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
- Element indexes change with every screen. Use indexes from the **latest** `wait_for_reply`/`screen`.
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
| Log | `read_log(since="turn")` | errors and internal steps for this turn |

- **Button taps:** the screen shows the label; the payload is in the endpoint JSON. When the profile says
  where payloads appear, verify after a tap that the expected payload arrived (not just the label).
- **Rendered vs sent:** a bot message in the endpoint JSON that never appears on screen is a bug (S2).
- `check` evidence must be concrete: quote the bot text, name the button and payload, paste the log line.
- `screenshot` at the key moments (first answer, each decision point, the final state, any error).

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
| "typed text did not read back" | nothing was sent; `screen()`; retry once; then `note(kind="bug")` |
| "Send button not found" | tell the user to set `chat.send_labels`/`send_ids` in `{{TESTER_DIR}}/config.json` (show `screen()`) |
| send `confirmed: false` | do NOT resend; `screen(image=true)`, then decide |
| endpoint "cannot reach" | the service is down - tell the user the start command from the profile; BLOCKED |
| bot shows its generic error reply | `read_log(since="turn")`; quote the error; usually a local setup issue |
