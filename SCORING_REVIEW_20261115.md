# AI finish and scoring review — 2026-11-15

Changes for the isolated test service:

- A human pass in an AI game now requests score review immediately, for either color and for both the resident engine and tactical fallback. It does not declare the position settled or approve a score.
- Scoring uses two smaller readings (32/128 visits) with the existing confidence gates; only inconclusive positions request a 256-visit refinement. Broadly unsettled boards (at least 85 locally uncertain intersections) return review without refinement. All stages share the existing 60-second deadline.
- Single-query refinements work with both the resident engine and separate-process protocol.
- The preview model prepares a real 16-visit empty-board opening at startup, outside player clocks. That engine-selected opening is cached per binary/model, revalidated against server legality, and reused for fresh Black AI games even after score cancellation restarts the engine. Nonempty positions always search normally. Shutdown cancels unfinished preparation.
- Uncertain ownership remains `review` and is explained separately from engine/time failures. Board, SGF, retry and resume remain available; unverified winners remain hidden.
- HTML loads explicitly as UTF-8 on Windows.

Evidence:

- Hosted log at 2026-11-15 02:26:13 UTC confirms a 60-second timeout while waiting for the resident scoring engine response.
- 172 server regressions pass, including twelve new finish/progressive-search/warmup checks.
- All browser logic suites pass; additional Master/same-color Play again and scoring-control suites pass.
- Real killed-process restart test passes after a 31-second single-seat recovery wait.
- Official KataGo 1.16.3 Windows Eigen and the same checksum-pinned g170 b10c128 model were exercised locally. A natural 137-move self-play game reached two passes, but score verification remained `review` after 13.45 seconds. Two artificial enclosed-death/seki stress fixtures also remained review. These failures are retained, not reclassified as passing results.
- The final self-play readings predict Black ahead about 52.2 points, while the strict classifier does not confidently mark one 13-stone group dead. The resulting provisional count differs substantially, so automatic confirmation is correctly blocked. No confidence thresholds were loosened.
- The first hosted improvement (3eee355) entered scoring after a human pass in 0.78/0.80 seconds for Black/White, retained the board through resume and supported fresh same-color AI games. The deliberately unfinished White case still hit the 60-second deadline in refinement; the follow-up removes that unnecessary refinement for broadly unsettled boards. Engine timing now has its own stream handler, so queue/search measurements are actually emitted without enabling unrelated debug logs.

Limits:

- Full Japanese adjudication is NOT fixed. Existing small-model ownership plus agreement thresholds cannot yet reliably finish even every ordinary game. A representative reviewed game set and better adjudication/engine validation remain required.
- The previous room LF2XEY8 is no longer on the disposable test server. The user's exact latest game is not identified, so the self-play game must not be represented as their game.
- Local Windows timing does not establish Render latency or iPhone physical-device behavior.
- Test storage is disposable SQLite, so sleep/restart/redeploy may lose room links. Production and paid service plans are unchanged.
