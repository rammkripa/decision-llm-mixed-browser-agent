# Hybrid browser agent: live results and refinement history

Updated October 22, 2026. This document preserves the local-fixture development runs,
Wikipedia regressions, and the seven-task live-suite comparison. Each section describes
the implementation tested at that time; historical results are not measurements of
today's code. The original Google Flights recording and timing remain historical evidence
for the original navigation agent.

## Current implementation and latest outcome

The latest full suite completed Flights, Wikipedia Webb, Wikipedia Gödel, and all three
Books tasks. Google/Python stopped at CAPTCHA in headless mode. That is six agent-checked
completions from seven tasks, with a limited independent source/outcome audit described
below. The visible baseline completed four tasks, including a human-assisted Python run.
This is one sample per task under different assistance/mode conditions, not a benchmark
score or a general success-rate estimate.

Changes accumulated since the original fixture runs:

- Direct OpenAI Chat Completions support alongside other compatible endpoints; TypeSafe
  remains the decision provider. OpenRouter is optional.
- Installed `jev-research` CLI, default headless mode, `--headfull`, isolated profiles,
  named Browser Harness connections, foreground task tabs and owned-process cleanup.
- Indexed `PRESS_ENTER` targets for input/search submission, with field clicks labeled
  as focus operations. Only the selected operation's compatible target can execute.
- Reachability filtering in the snapshot as well as the executor, so clipped calendar
  dates and covered controls are not offered as clickable targets.
- Visible human-verification handoff: pause before decisions, user solves the CAPTCHA,
  terminal Enter resumes from fresh state; headless runs stop. Detection is heuristic.
- Bounded text-model resolution of uncertain operations/targets. Invalid resolver output
  is rejected and logged without executing or crashing; uncertainty/replan limits remain.
- Observed field metadata, nearby editable controls and local context for text generation;
  calendar guidance distinguishes departure dates from cities. Invalid generated field
  values still stop safely; corrective field generation is not yet implemented.
- Semantic document passages, full observed link tooltips for truncated names, bounded
  reading windows, code-copied quotes, and separate captured offscreen evidence.
- Whole-window consumption after extraction, exact duplicate-fact rejection, compact
  decision evidence and compact last-check state, while preserving raw evidence.
- Source-witnessed reviews for uncertain verification, retained verified outcome snapshots,
  and separate original-goal and final-statement checks.
- At most one answer-generation revision, citation repair against uncited captured
  evidence, and suppression of statements still unsupported after the final draft.
  Remaining statements and the original goal must pass again before publication.
- Sequential `jev-live-suite`, task filters/repeats/date override, unique run directories,
  per-task logs/traces/results and incremental summary output, including failed runs.

There are no model-generated executable selectors, site-specific executor plans, automatic
browser-mutation retries, or relaxed verification thresholds in these changes. Model
verification is still fallible. Initialization/provider connection errors can still leave
no agent trace; the suite preserves their terminal logs. Startup can still show three
tabs, and generic keyboard widgets, frames and durable resume are not implemented.

## Historical local-fixture repeats

Live OpenAI and TypeSafe calls were run against the local two-page research fixture in
isolated headless Chrome. These three repeats used the final policy for that fixture
experiment, before the later research changes documented above.

Goal: “Use the calculator for five seats. Compare Basic and Pro annual costs, including taxes, cancellation deadlines and refund exceptions.”

Models: TypeSafe `jev-latest` (returned as `jev-1.14.0`) and direct OpenAI `gpt-6-luna`, with text reasoning set to `none`. Model names are captured in the final traces; no keys or authorization headers are recorded.

| Trace under ignored artifacts/ | Outcome | Total wall time | Loop time | Browser actions | Replans | Logical model calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| research-live-11.json | Passed independent oracle | 18.318 s | 16.154 s | 3 | 1 | 24 |
| research-live-12.json | Passed independent oracle | 12.531 s | 9.935 s | 3 | 1 | 22 |
| research-live-13.json | Blocked; no final answer | 15.509 s | 12.020 s | 3 | 2 | 28 |

Result: **2/3 completed and passed independent checks**. Each successful run actually entered five seats, submitted the calculator and followed the policy link. The sourced answers gave Basic $600 USD/year, Pro $1,200 USD/year, taxes excluded with no published rate, cancellation at least 30 days before renewal with access through the paid term, and the duplicate-charge refund exception reported within 14 days.

The third run collected the correct source values but stalled on conservative semantic verification of tax qualifications. Its final tax-support probabilities were 0.84–0.87, below the 0.90 acceptance threshold. Replanning did not resolve that uncertainty, and no answer was published. Source-witnessed text review has since been implemented; these historical fixture repeats were not rerun to establish whether it resolves that specific failure. Thresholds have not been calibrated on a broader dataset.

The final three runs used the same agent policy. Runs 12 and 13 additionally recorded SHA-256 hashes of the policy, browser, reader and fixture sources; these hashes are identical. Run 11 predates the added hash metadata. Raw traces and rejected answer attempts remain local in ignored artifacts/. They are not bundled or committed. artifacts/research-live-summary.json contains the aggregate rows above.

Total wall time includes initial planning and browser setup, ending when the trace is saved before tab cleanup. Loop time starts at the first tick. Logical call counts include planning, decisions, extraction, verification, synthesis and typing; HTTP retries can increase actual provider request counts. No dollar-cost claim is made.

## Development failures retained

Two initial OpenAI requests were rejected before browser setup because JSON mode requires an explicit JSON instruction. An initial TypeSafe call was rejected before any agent action with HTTP 401; testing resumed after the user supplied a different key. Earlier full-agent traces research-live-04.json through research-live-10.json record seven non-completing development runs across changing implementations. These are not excluded from the development history or presented as successes. Their main failure modes were overstrict read-target gating, missing source context, normalized quotation whitespace, lost intermediate observations, and assessing overall completion before an answer existed.

Changes made during the live test:

- Direct OpenAI Chat Completions parameters, including max_completion_tokens and reasoning_effort, while preserving other providers' parameter conventions.
- Explicit JSON-mode instructions and sanitized provider diagnostics.
- Separate confidence handling for read-only passage choices; terminal DONE still requires a separate evidence check.
- Evidence checks after extraction, exact source resolution across whitespace differences, and neighboring source context.
- Captured source snapshots for completed subtasks so verified intermediate results survive navigation.
- Whole-goal assessment against the candidate answer and executed actions, followed by atomic answer-statement checks. Rejected drafts are retained for audit and withheld from the result.
- Wall-clock timing, model names and source hashes in CLI traces.

The OpenAI compatibility details follow the [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) and [GPT-6 Luna model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna).

## Recheck independently

```bash
uv run python scripts/verify_research_fixture.py artifacts/research-live-11.json
uv run python scripts/verify_research_fixture.py artifacts/research-live-12.json
uv run python scripts/verify_research_fixture.py artifacts/research-live-13.json
```

The third command deliberately exits 1. The independent oracle checks actual action history, expected fixture values, exact source quotations, answer coverage and source-reference integrity. A model's DONE or verification choice alone is insufficient. Inspect the generated answer and source text as well: the fixture oracle is intentionally narrow.

See research-testing.md for offline tests, the real-browser no-API integration test, and commands for additional live runs. Broader fixtures and real-site tasks remain necessary before making a general-purpose-agent reliability claim.

## Wikipedia CLI regression and follow-up

The reported main-page search stalled when the same autocomplete result appeared as both an option and a nested link. Jev chose CLICK confidently but split target probability between these equivalent representations. Replanning repeated the same ambiguity. Follow-up end-to-end testing exposed additional paragraph-fragmentation, context-size, extraction and semantic-verification failures beyond the initial navigation stall.

The research runner now has bounded text-model routes for uncertain operations and targets, restricted to the same code-owned observed vocabulary. Reading uses semantic paragraph chunks and windows bounded by both choice count and text size. Shared task state and verification sources are deduplicated. Extraction selects observed passage IDs, with quotes copied by code. Uncertain semantic checks can use a separate source-witnessed review. A rejected answer gets at most one generation revision before the same checks run again. Browser mutations are never retried by these routes.

Goal: “Find and summarize Gödel’s incompleteness theorems with sources.” Starting URL: https://en.wikipedia.org/wiki/Main_Page.

| Trace under ignored artifacts/ | Mode | Outcome | Total wall time | Loop time | Browser actions | Replans | Logical model calls |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| wikipedia-full-fix-10.json | headless | Completed and independently audited | 28.209 s | 25.147 s | 2 | 0 | 23 |
| wikipedia-headfull-verified.json | headfull | Completed and independently audited | 18.666 s | 15.307 s | 2 | 0 | 14 |

Both runs actually entered the search, opened the requested article, summarized both theorems with their consistency/effective-axiomatization/arithmetic scope, and returned source links whose quotes match captured passages. The saved summaries were also read against those passages. Source-reference and action-history checks are recorded in artifacts/wikipedia-final-audit.json. This checks the requested browser outcome and source grounding; it is not a formal mathematical proof audit.

The policy/reader/CLI/fixture hashes in the two successful traces are identical. These are one successful run in each mode, not a general reliability benchmark. Nine preceding non-completing development attempts, wikipedia-full-fix-01.json through wikipedia-full-fix-09.json, are retained with their failures across changing implementations. The user's original failure trace was not overwritten. No success-rate claim is made by excluding those attempts.

At this stage logical model-call counts included target_resolution, decision_resolution,
and verification_review in addition to the original categories. Citation repair is counted
as citation_repair when used by the current code. The historical headless run used two
synthesis attempts; the visible run used one. The standard CLI command and mode flags
are unchanged.

## Sequential live suite: first refinement pass (2026-10-22)

Baseline: `artifacts/live-suite/20261022T220720.792389Z/summary.json`.
Follow-up: `artifacts/live-suite/20261022T222755.138686Z/summary.json`.
Machine-readable comparison and limited independent audit are saved as `comparison.json`
and `independent-audit.json` beside the follow-up summary. Every task retains its raw
trace, terminal log, task definition and result record. Neither run was overwritten.

Changes in this pass: expose observed input metadata and local context to the decision
and typing models; read full link title attributes when displayed text is truncated;
consume an entire extraction window once rather than repeatedly using different starting
passages; deduplicate facts; bound the evidence portion of decision context to 12,000
characters and remove full source copies from the decision's last-check summary; explicitly
distinguish captured offscreen information from currently reachable controls in policy.
No site-specific selectors, task plans, or executor field values were added.

| Task | Baseline outcome / loop seconds | Follow-up outcome / loop seconds | Logical calls, baseline → follow-up |
| --- | --- | --- | --- |
| Flights | Invalid date-field output / 8.297 | Completed / 30.148 | 16 → 39 |
| Python search | Completed with human CAPTCHA help / 52.702 | CAPTCHA blocked / 1.997 | 12 → 5 |
| Wikipedia Webb | Completed / 19.499 | Completed / 17.840 | 20 → 20 |
| Wikipedia Gödel | Completed / 15.712 | Completed / 31.740 | 14 → 39 |
| Books identifiers | Completed / 6.057 | Completed / 12.540 | 9 → 17 |
| Books first five | HTTP 400 after repeated extraction / 196.072 | Completed / 9.259 | 178 → 11 |
| Books cheapest Travel | Uncertainty budget exhausted / 20.380 | Completed / 37.179 | 29 → 55 |

The baseline was visible Chrome; follow-up used headless Chrome without CAPTCHA assistance.
The task goals and flight date (2026-12-21) were preserved. This is one sample per task,
not a controlled reliability or speed benchmark. Six follow-up tasks completed under the
agent's checks; Python's environmental block cannot be compared to the assisted baseline
as a model regression. Gödel and identifiers took more calls/time, and Travel still
revisited the product/category pages, so there is remaining efficiency work.

Independent checks outside model verification confirmed exact returned quote/source
references for all six completions; the actual Flights controls and action history matched
one-way/economy, route, date and one-adult results; the first-five Books titles/prices and
product identifiers matched captured source; Travel's captured 11 category prices have
minimum £23.21 and the correct product page was actually opened. The audit does not
formally grade every mathematical/scientific qualification or establish broad reliability.
The Webb and Gödel answers were also read against their captured supporting passages.

The first-five task dropped from 44 extractions and 233 evidence entries to one extraction
and 11 entries including the verified outcome. Flights typed the requested ISO date rather
than a city. Travel scrolled to reveal its target and returned its full title and URL.

Offline validation for this pass: 110 pytest tests; Ruff; JavaScript syntax checks; package
build; 24 real-browser guard checks; and the local research/reader integration fixture.
All passed without paid model calls. The seven-task suite itself used live paid models.
