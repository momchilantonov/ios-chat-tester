---
name: chat-test-report
description: How to finish a chat test run - choosing the verdict, the end_run summary, severity of findings, writing report.md into the run folder, and suite summaries across runs. Use at the end of every run and whenever the user asks for a report.
---

# Finishing a run

1. `end_run(summary)` - writes `run.json`, `transcript.json`, `journal.jsonl` and log slices into the run
   folder. **With a plan** it also writes the filled table (`<plan>.result.md` next to the plan, and
   `results.md` in the run folder) and computes the verdict: any fail -> FAIL, else any blocked -> BLOCKED,
   else PASS. **Without a plan** pass a verdict; PASS is downgraded automatically (failed checks -> FAIL,
   no checks -> INCONCLUSIVE).
2. `write_file("<run_dir>/report.md", ...)` with the structure below.

## Verdicts
- **PASS** - every expectation was checked with evidence and held.
- **FAIL** - product behaviour was wrong: wrong/missing answer, wrong flow, expected button missing or not
  rendered, wrong payload, error reply.
- **BLOCKED** - could not execute: service down, driver/simulator problem, unknown session id, config.
  Not a product verdict - say what must be fixed.
- **INCONCLUSIVE** - ran, but nothing could be decided.

## report.md
```
# <scenario> - <VERDICT>
<date> · app <bundle id> · run folder <path>

## Summary
3-8 sentences: scenario (preconditions -> what was said -> expectation) -> what happened -> why this
verdict -> key finding with evidence -> what remains untested / next scenario.

## Conversation
| # | Who | Message / button | Evidence |   (quote verbatim, original language)

## Checks
| Check | Result | Evidence |

## Findings
- S? <title> - evidence, how to reproduce (exact phrases/taps)

## Artifacts
screenshots/, transcript.json, journal.jsonl, fetch-*.json, log-*.txt
```
Write the report in English; quote typed phrases and bot texts verbatim in their original language.

## Severity (start bug notes with it)
- **S1** wrong financial/irreversible action, data leak, asks for secrets, crash.
- **S2** flow cannot complete, wrong flow/branch, error reply, payload not transported, message not rendered.
- **S3** wrong or confusing wording, wrong button title, slow reply (> 10 s).
- **S4** cosmetic.

## Before calling it green
- [ ] Preconditions came from test data/app state, not from changing the system under test.
- [ ] `status` was ok.
- [ ] Every expectation has a `check` with concrete evidence.
- [ ] Buttons were read from the screen; payloads verified in the endpoint JSON where the profile says how.
- [ ] Every requested scenario step is marked done, blocked or not run - nothing silently skipped.

## Suite summary
On request, write `runs/SUITE-<yyyymmdd-hhmm>.md`: table | scenario | verdict | key finding | report |,
then bugs by severity, then flakiness (same scenario, different verdicts). Read each run's `run.json`.
