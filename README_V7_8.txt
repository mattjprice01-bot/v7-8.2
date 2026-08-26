US30 SIGNAL LAB V7.8 — ADAPTIVE + DATABENTO YM L2

WHAT V7.8 ADDS

1) DATABENTO YM LIVE L2
- Direct Databento Live subscription using dataset GLBX.MDP3.
- Default symbol: YM.v.0 (volume-ranked front YM contract via continuous symbology).
- Default schema: mbp-10 (10 levels of market-by-price / L2 depth).
- Calculates top-5 and top-10 book imbalance, microprice bias, spread and recent aggressive trade pressure.
- Converts those into a bounded YM L2 confirmation score used primarily for entry timing.
- Databento has its own LIVE / STALE / OFFLINE / ERROR / NOT_CONFIGURED indicator.

2) MARKET SESSION ENGINE
All session logic is DST-aware using America/New_York.
V7.8 distinguishes:
- US premarket
- US cash-open volatility window
- opening discovery
- normal cash session
- power hour
- cash-close volatility
- post-cash
- overnight futures
- CME daily maintenance
- weekend closure

The cash-open window applies a probability penalty and blocks PERFECT ENTRY during the most volatile opening-discovery period. Later opening minutes remain higher-risk and require stronger confirmation.

Note: the session engine handles normal weekday/session times. It does not yet contain a full NYSE holiday / special early-close calendar.

3) CONSTANT SELF-TESTING / LEARNING
V7.8 creates a prediction ledger automatically every 15 minutes by default while a directional thesis exists.
Each prediction records:
- direction
- entry price
- raw model probability
- calibrated probability if available
- challenger-model probability
- swing bias
- entry timing
- Databento L2 score
- intermarket score
- macro score
- market session / session risk

Default measurable prediction outcome:
TARGET: +100 US30 points before
STOP: -50 US30 points
HORIZON: 480 minutes (8 hours)

These are adjustable in the dashboard.

V7.8 later resolves every prediction as TARGET, STOP or TIMEOUT and records MFE, MAE, directional correctness and simulated R.

4) CALIBRATED PROBABILITY
The existing model Conviction is NOT presented as a guaranteed probability.
V7.8 learns from its own resolved predictions in 5-point raw-confidence buckets.
Only after the minimum sample requirement is met (default 20) does it display a CALIBRATED PROBABILITY.

A Beta prior prevents tiny perfect samples from immediately claiming 100% probability.
Until sufficient evidence exists, the dashboard shows LEARNING and Perfect Entry probability alerts remain suppressed.

This means a 98% alert is intended to mean:
"Historically, this calibrated model bucket has achieved the defined target-before-stop outcome at approximately this empirical rate, after shrinkage."
It is never a guarantee of the next trade.

5) ADJUSTABLE PHONE NOTIFICATION THRESHOLDS
Dashboard defaults:
- SETUP WARNING: 92%
- PERFECT ENTRY: 98%

Both can be changed directly on the dashboard.

Perfect Entry also requires:
- strong swing bias
- 4H + 1H timing alignment
- no major higher-timeframe contradiction
- usable macro context
- no materially opposing macro/intermarket/news condition
- price inside the precision entry zone
- Databento YM L2 confirmation (default required)
- session engine not blocking the entry

When an active trade is being tracked, new-entry notifications remain suppressed and V7 continues the V7.7 risk/danger/profit-management alert logic.

6) PERFORMANCE DASHBOARD
Adds a Self-Test Performance section showing:
- total predictions
- resolved predictions
- target-before-stop win rate
- directional accuracy
- cumulative simulated R
- raw primary-model Brier score
- shadow challenger-model Brier score
- prediction performance curve

The challenger model receives the same predictions but weights timing, Databento and intermarket information differently. It is evaluation-only and never takes over the live model automatically.

IMPORTANT: The prediction performance curve is a MODEL SELF-TEST, not an account equity curve. Predictions can overlap and are not proof that all signals could have been executed simultaneously.

DATABENTO RAILWAY SETUP
Add these Railway variables:

DATABENTO_API_KEY=YOUR_PRIVATE_DATABENTO_KEY
DATABENTO_DATASET=GLBX.MDP3
DATABENTO_SYMBOL=YM.v.0
DATABENTO_SCHEMA=mbp-10
DATABENTO_TICK_SIZE=1

Never put the API key in GitHub.

PHONE ALERTS
Existing V7 notification variables still apply:

NTFY_TOPIC=your-private-topic

or Telegram:
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

PERSISTENT LEARNING — IMPORTANT
Railway deployment storage can be replaced on redeploy. If the prediction history is to keep learning across deployments, attach a Railway persistent Volume and set:

US30_V7_DB=/data/v7_swing.db
US30_LAST_MACRO_FILE=/data/last_macro.json

Mount the Railway volume at /data.
Without persistent storage the learning database can be lost when the service is rebuilt/redeployed.

TRADINGVIEW
No Pine change is required.
Keep the existing V7.1 YM-only TradingView feed if it is already working.
TradingView continues to supply US30 multi-timeframe chart structure; Databento now independently supplies direct live YM L2/order-flow confirmation.

DEPLOYMENT
This is a flat GitHub package.
Upload/replace all files in the repository root, then let Railway redeploy.

NEW FILES
- databento_feed.py
- session_engine.py
- learning.py
- test_v78_adaptive.py

SECURITY
- Keep DATABENTO_API_KEY private in Railway Variables.
- Do not commit private notification tokens to GitHub.
- WEBHOOK_SECRET can still be used if you want to secure the TradingView endpoint later.

MODEL SAFETY
The adaptive layer recalibrates probabilities and tests a shadow challenger. It does NOT rewrite its own production strategy or promote challenger weights automatically. That prevents uncontrolled overfitting while still allowing the system to learn from every prediction.

Trading remains risky. Calibrated probabilities are historical empirical estimates for a precisely defined outcome, not guarantees of future results.
