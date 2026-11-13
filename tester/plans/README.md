# Test plans

One Markdown file per plan, written by the planner agent (or by hand), run by the tester agent.
Your plans and their results are git-ignored - they stay on your machine.

```markdown
# Test plan: <title>
Preconditions: <one line, optional>
Source: <flow files / ticket the plan was made from>

## Conversation 1: <name>            <- every ## section is one conversation, started with a fresh app launch
| Flow | User prompt | Expected | Result |
|---|---|---|---|
| <flow id> | <message to type> | "<exact bot text>" + what else must happen | |
| <flow id> | tap <button> | ... | |
```

**User prompt** - one action per row:
- plain text: typed and sent exactly as written
- `tap <label>` - tap a quick reply, row or button; `select <label>` - tick a checkbox/row
- `swipe left|right on <what>` - carousels; `wait` - only wait for the next bot message

**Expected**
- text in "double quotes" must appear exactly (letters, punctuation, emoji)
- `{...}` inside quotes is variable content (a name, an amount, a date)
- `buttons: "A", "B"` - these buttons must be offered
- anything else is a description the tester judges

**Result** - empty in a plan; the tester fills it:
`success` · `fail: <what happened instead>` · `blocked: <why it could not be run>`.
The filled plan is saved as `<plan>.result.md` next to the plan and as `results.md` in the run folder.
