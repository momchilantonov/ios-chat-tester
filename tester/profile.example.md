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

## Evidence
- Conversation/event endpoint: TODO name from config.json `endpoints`, what the JSON contains,
  which fields hold user messages, bot messages, button payloads, function/tool calls.
- How to find the session/conversation id: TODO (e.g. `read_log(grep="sender")`, or ask the user)
- Error reply the user sees when the backend fails: TODO (quote it)

## Where flows live in this repo
- TODO paths to flows, functions, response templates, prompts

## Rules for this project
- TODO e.g. scope limits (which product line only), test data only, things never to confirm
