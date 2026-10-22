# Live hybrid-agent fixture test — October 22, 2026

Live OpenAI and TypeSafe calls were run against the local two-page research fixture in isolated headless Chrome. This is a development smoke test on one task, not a general reliability benchmark. The existing Google Flights measurements describe the original Agent and are unaffected.

## Final-policy repeats

Goal: “Use the calculator for five seats. Compare Basic and Pro annual costs, including taxes, cancellation deadlines and refund exceptions.”

Models: TypeSafe `jev-latest` (returned as `jev-1.14.0`) and direct OpenAI `gpt-6-luna`, with text reasoning set to `none`. Model names are captured in the final traces; no keys or authorization headers are recorded.

| Trace under ignored artifacts/ | Outcome | Total wall time | Loop time | Browser actions | Replans | Logical model calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| research-live-11.json | Passed independent oracle | 18.318 s | 16.154 s | 3 | 1 | 24 |
| research-live-12.json | Passed independent oracle | 12.531 s | 9.935 s | 3 | 1 | 22 |
| research-live-13.json | Blocked; no final answer | 15.509 s | 12.020 s | 3 | 2 | 28 |

Result: **2/3 completed and passed independent checks**. Each successful run actually entered five seats, submitted the calculator and followed the policy link. The sourced answers gave Basic $600 USD/year, Pro $1,200 USD/year, taxes excluded with no published rate, cancellation at least 30 days before renewal with access through the paid term, and the duplicate-charge refund exception reported within 14 days.

The third run collected the correct source values but stalled on conservative semantic verification of tax qualifications. Its final tax-support probabilities were 0.84–0.87, below the 0.90 acceptance threshold. Replanning did not resolve that uncertainty, and no answer was published. This remains an unresolved reliability issue. A useful next experiment is independent text-model review of ambiguous source-backed requirements, with explicit witness quotes, rather than repeated checks against the same evidence. Thresholds have not been calibrated on a broader dataset.

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

Logical model-call counts now include target_resolution, decision_resolution, and verification_review in addition to the original categories. The headless run used two synthesis attempts; the visible run used one. The standard CLI command and mode flags are unchanged.
