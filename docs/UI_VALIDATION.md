# UI validation - 2026-10-06

> **Historical record.** Written before the full-dataset work of 2026-10-06. Commands, test counts and conclusions here may be out of date. Current status: [VALIDATION.md](VALIDATION.md); Synapt: [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md).

The professional light theme preserves the user's React layout. Warm neutrals, borders and clear
semantic states replace glow, gradients, glass, decorative orbit/pulsing branding and animated numbers.
Design references and alternatives are recorded in CHANGE_DECISIONS.md.

## Executed checks

| Check | Result |
| --- | --- |
| Production build (TypeScript + Vite) | Passed; final compiled application verified on existing port 8000 |
| Frontend rendering regressions | 6 passed; real initial values, missing/failed/passed validation, truthful loading, fluid empty state |
| Backend regression suite | 74 passed, credential/network-isolated |
| Oxlint | No errors; 14 remaining warnings for shared exports and existing fetch effects |
| Desktop 1526px | Light application loaded; no document or final workflow overflow |
| Tablet 1024px | Quality and connection pages fit viewport |
| Phone 390px | Submitted fixture investigation collapses intake; result focused at about 100px from top; no document overflow |
| Narrow phone 320px | Empty workspace, results, connection and navigation fit 310px content viewport without page overflow |
| Application-key recovery | Initial 401 displays actionable demo error/retry; applying test key refreshes health/integration and all four demos |
| Pending document submission | Typed without Enter; saved API run includes document (not only visible chip) |
| Same-run review draft | Accepting synthetic brief retains feedback note and selected rating |
| Rating keyboard | ArrowRight moved native radio from 3 to 4 |
| Invalid form | Empty submit focuses description with aria-invalid and linked message; fractional prior-claim count rejected |
| Hidden invalid filters | Invalid amount range expands section and focuses maximum amount field |
| Page navigation | Quality/navigation starts at top and focuses heading; ordinary return does not refocus old output |
| Evidence display | Structured submitted-claim details present; original source passages retained in disclosure |
| Browser diagnostics | Final QA tab returned no captured warning/error logs |

QA used AGENT_MODE=fixture and SYNAPT_MODE=fixture with a separate SQLite database and temporary
application key on port 8001. Test data is explicitly synthetic. The existing user server on port 8000
was preserved; its live-agent/fixture-Synapt status was verified read-only after the final build.
No new live NVIDIA or Synapt request was needed for this UI change.
The independent review identified stale refresh ordering, late review-result selection, repeat result
focus and source-key collisions. Guards were implemented and source-reviewed; adversarial delayed
response scheduling was not separately simulated in browser automation.

## Evidence

Screenshots and the separate QA database are outside the repository:
C:/Users/SAI/.codex/visualizations/2026/10/05/01a10cb2-6145-7301-8e57-1a2ca4a853b4/ui-polish-2026-10-06

- desktop.png: final light workspace on port 8000.
- desktop-result.png: final compact investigation summary in the fixture QA server.
- mobile-result.png: 390px result with wrapped workflow and two-column summary.
- qa.sqlite: isolated synthetic interaction runs (including saved document evidence).

Measured neutral token contrast is at least 5.18:1; primary white text is 7.62:1; semantic pill text
is at least 5.81:1 and strong control borders at least 3.44:1. This is targeted palette validation,
not full accessibility certification. Keyboard/focus checks cover the exercised paths, not every
assistive-technology combination. Actual likeability needs representative handler user testing.
Live Synapt tenant access and real claim accuracy remain unverified.

## Reproduce

From frontend: npm run test, npm run lint, npm run build.
From repository root: uv run pytest -q.
Review source decisions in CHANGE_DECISIONS.md and rebuild whenever the frontend source changes.
