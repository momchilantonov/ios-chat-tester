---
name: test-plan-format
description: The test plan format shared by the planner and the tester - a Markdown table Flow | User prompt | Expected | Result, one ## section per conversation, results success / fail / blocked. Load when writing, reading, running or reporting a test plan.
---

# Test plan format

Plans live in `{{TESTER_DIR}}/plans/<name>.md`. The planner writes them with an empty Result column; the
tester fills it. Example: `{{TESTER_DIR}}/plans/example-plan.md`.

```markdown
# Test plan: <title>
Preconditions: <one line - test data, mock toggles, app state; optional>
Source: <flow files / ticket / guide section the plan was made from>

## Conversation 1: <short name>
| Flow | User prompt | Expected | Result |
|---|---|---|---|
| <flow id> | <message the customer types> | "<exact bot text>" + what else must happen | |
| <flow id> | tap <button label> | ... | |
```

## Rules
- **Every `##` section is one conversation.** The tester starts it with a fresh app launch, so a section
  must contain everything needed from the start (including any prelude steps as normal rows).
- **One action per row** in *User prompt*:
  - plain text -> typed and sent exactly as written (write it as a real customer would, in the profile's language)
  - `tap <label>` -> tap a quick reply / row / button with that label - always a real tap, never typed
  - `select <label>` -> tick a checkbox or list row (usually followed by a `tap <continue label>` row)
  - `swipe left|right on <what>` -> carousels
  - `wait` -> send nothing, only wait for the next bot message
- **Expected**
  - text in "double quotes" must appear exactly - letters, punctuation, emoji. Copy it from the bot's
    response files; never paraphrase inside quotes.
  - `{...}` inside quotes is variable content, e.g. "Здравей, {name}!".
  - `buttons: "A", "B"` - these quick replies must be offered (others may exist unless you write "only").
  - anything outside quotes describes behaviour the tester judges ("asks for the card", "no error").
- **Links and deeplinks**: the Simulator cannot really open them. If a row expects a link/deeplink to open,
  a tap that leaves the app (Safari, another app - even with an error page) is `success`; the opened page is
  not judged. The tester brings the app back automatically.
- **Result** (filled by the tester only): `success` · `fail: <what happened instead>` ·
  `blocked: <why it could not be executed>`. Rows not run end up as `blocked: not run`.
- Keep cells on one line; use `\|` for a literal pipe.
