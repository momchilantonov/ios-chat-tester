# Test plan: greeting and help menu (example)
Preconditions: local bot running; chat opened via app.after_launch
Source: example only - generate real plans with the planner agent

## Conversation 1: greeting
| Flow | User prompt | Expected | Result |
|---|---|---|---|
| greeting | Hello, what can you help me with? | a short answer listing what the assistant can do; buttons: "Cards", "Payments" | |
| greeting | tap Cards | "Which card?" with buttons "Debit", "Credit" | |
| greeting | tap Debit | "Your debit card is blocked." | |

## Conversation 2: unknown request
| Flow | User prompt | Expected | Result |
|---|---|---|---|
| fallback | asdf qwerty | a polite fallback that offers help; no error message | |
