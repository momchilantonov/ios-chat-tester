# Scenario: greeting and first answer

- Mode: scripted
- Preconditions: app open on the chat screen, local stack running
- Persona: polite first-time user

## Steps
1. `open_app(fresh=true)`, then `wait_for_reply` for the welcome message (if the app shows one).
2. Send: "Hello, what can you help me with?"
3. Expect: a reply within 15 s that describes what the assistant can do.
4. Expect: no error lines in `read_log(since="turn")`.
5. If quick-reply buttons are offered: tap the first one, `wait_for_reply`, expect a relevant answer.

## Pass when
- every Expect above holds, recorded with `check`.
