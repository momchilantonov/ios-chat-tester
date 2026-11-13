# Test profile (local, project-specific)

The chat-tester agent reads this file at the start of every session. Keep project-specific knowledge
here - it stays in your repository, it is not part of the public chat-tester project.
Replace every TODO. Delete what does not apply.

## Product
- App under test: TODO (name, which screen holds the chat, how to open it)
- Bot / backend: TODO (what answers the chat, where its source lives in this repo)
- Customer language: TODO (e.g. "write as a native speaker of <language>; reports in English")

## How to start the local stack (the agent never starts services - it tells you this)
- TODO e.g. `make run-bot 2>&1 | tee ~/chat-logs/bot.log`
- TODO other services and their ports

## Getting to the chat
- TODO what a fresh app launch shows and which entries lead to the chat that talks to YOUR bot
  (also put them in config.json `app.after_launch`)
- TODO screen noise to ignore (debug banners ...) - also in config.json `chat.ignore_labels`

## Evidence
- Conversation/event endpoint: TODO name from config.json `endpoints`, what the JSON contains,
  which fields hold user messages, bot messages, button payloads, function/tool calls.
- How to find the session/conversation id: TODO (`find_session_id()` searches app + bot logs; say which
  log line shows it, or "ask the user")
- Error reply the user sees when the backend fails: TODO (quote it)

## Where flows live in this repo
- TODO paths to flows, functions, response templates, prompts

## Known Simulator behaviour (accepted)
- Links and deeplinks cannot open in the Simulator; a tap that opens Safari/another app counts as success
  when the row expects a link. TODO add other accepted differences

## Rules for this project
- TODO e.g. scope limits (which product line only), test data only, things never to confirm
