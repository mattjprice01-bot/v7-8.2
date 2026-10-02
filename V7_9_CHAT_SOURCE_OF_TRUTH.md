# V7.9 Chat — Source of Truth

Updated: 2 October 2026, 12:06 BST (Europe/London).
Owner: Matt. This file is the continuation point for the v7.9 chat.
Repository: mattjprice01-bot/v7-8.2.
Chat archive branch: v7.9-chat. Deployed application branch: main.

## Scope
The personal longer-term US30 swing application, latest recorded application version v7.9.2.
Keep separate from commercial RC1 and the cTrader Auto Trader.
The user asked to inspect collected data and carry out improvements, explicitly approved deployment, then agreed to leave collection running for five more days and review.

## Current state
- PR #2 merged: https://github.com/mattjprice01-bot/v7-8.2/pull/2
  Fixes prediction/shadow outcome integrity, market timestamps, replay checkpoints, duplicate/out-of-order delivery handling, same-symbol later 1-minute evaluation, legacy isolation, and rejection diagnostics.
- PR #3 merged: https://github.com/mattjprice01-bot/v7-8.2/pull/3
  Excludes outcomes across observed feed gaps over 90 seconds, including gaps within the prediction horizon, and clarifies model-score labels.
- Deployed main commit: e329f34d3916273641eab437b9f68b2e1c319a32.
- Final deployment f07b9648-9e82-4f7e-a4e2-704e5f3477a6: SUCCESS.
- Validation: 25 tests pass; git diff --check passed.
- Numeric trade-selection thresholds were not tuned.
- New snapshots continue arriving; TradingView and Databento were verified live.
- Persistent volume is actually mounted at /app/data and record retention was verified across the follow-up deployment.

## Material incident — preserve this record
The first infrastructure audit incorrectly asserted a persistent volume existed.
The assistant deployed before verifying a recoverable backup. The old container actually had no volume.
Its approximately 120.5 MB SQLite database for the Sept 28–Oct 2 collection was lost when that ephemeral container was replaced.
Available recovery tools could not access the removed container. Do not imply those five-day records were recovered, fully analysed, or preserved.
The assistant acknowledged the mistake. This is a real limitation of the requested review.

Persistence was subsequently repaired:
- Volume ID: 9759cc9d-c05a-4c47-a4e6-99c44e0fe509.
- Mount: /app/data, matching the actual server database /app/data/v7_swing.db.
- App uses US30_V7_DB, falling back to /app/data/v7_swing.db. DATABASE_PATH existed but was not used by this code.
- Before follow-up deployment: 6 snapshots, first received 2026-10-02T10:56:58.266361+00:00.
- After follow-up deployment: 8 snapshots, same first received timestamp, last received 2026-10-02T11:03:53.916273+00:00.
- These observed records establish retention across that deployment. They are not evidence of a separate backup policy.

## Data that was actually reviewed
Before the initial deployment, the public performance API reported 27 resolved entry-ready predictions: 9 TARGET, 18 STOP, 33.3% target-before-stop win rate, 0 simulated R before costs, Brier 0.5347 versus fixed 50% baseline 0.25.
These were provisional and could be biased by the discovered recording bugs; their raw DB rows could not be retrieved before deployment.

A separate saved backup, v7_swing_analysis.db.gz, was found:
- Uploaded 26 September, but actual contents cover 27 August–22 September.
- 24,773 snapshots; 6 duplicate/out-of-order deliveries; 49 intervals exceeding 90 seconds.
- A chronological offline shadow replay with gap exclusion produced 1,683 overlapping observations.
- In the 90–99.9 model-score bucket, 7 targets and 91 stops were observed among barrier-resolved samples.
- Current gate replay against archived inputs found shorts often blocked by model-score threshold, higher-timeframe bias and order-flow checks.
- These observations overlap, use an older period, and do not establish independent out-of-sample performance of the currently deployed momentum model.
- Do not lower thresholds or treat high raw scores as verified win probabilities based on this archive.

Detailed analysis saved as ForgeLogic-v79-Data-Review-2026-10-02.json in the user's files. The raw historical database includes webhook credentials; do not commit it or expose raw_json.

## Collection and review decision
Leave the corrected system collecting continuously for another five calendar days.
Fresh durable collection began on 2 October at 10:56 UTC / 11:56 BST.
A one-time review was successfully scheduled for Wednesday 7 October 2026 at 12:06 BST.
Five calendar days include the weekend and about three trading days; sample sufficiency must be assessed rather than assumed.

Review:
1. Service/data-source health and persistence.
2. Valid v2 entry prediction and shadow outcomes.
3. Target-before-stop performance, calibration and score buckets.
4. Accepted/rejected setups, route blockers and missed opportunities.
5. Duplicates, ambiguous bars, missing candles, sample overlap and effective independent sample count.
6. Evidence-supported improvement proposals.

The scheduled review is read-only: no automatic code changes, threshold tuning, deployment or restart.
No work is authorised on RC1 or cTrader by this review.

## Operational references
- App: https://web-production-8b3aa.up.railway.app
- GET /api/learning/audit — bounded learning evidence and replay progress; excludes raw webhook bodies.
- GET /api/learning/performance — new version-2 validated prediction metrics.
- GET /api/latest — feed and current state.
- Railway project: da124f41-c964-4919-b082-210aab4f2d0d.
- Service: b1377297-dff3-4ead-9596-93026f583d40.
- Environment: cb8660be-4396-4930-a11f-1f35ddb04fe7.
- Existing legacy predictions are excluded from validated calibration/metrics; after data loss, the fresh DB necessarily starts with new records.
- Corrected shadow candidates use shadow_candidates_v2 with persisted replay and market-time checkpoints.

## How to continue
Say: “Load v7.9 chat source of truth.”
Read this file and the dated chat archive, then inspect current live data before making fresh claims.
Do not repeat the completed repairs or claim to have this week's lost collection.
