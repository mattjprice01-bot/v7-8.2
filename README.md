# US30 SIGNAL LAB V7.9.1 — LEARNING INTEGRITY + STATE GATE

This is an in-place patch for the existing V7.9 Railway deployment.

## Replace these files
1. `server.py`
2. `README.md`

Do not change the existing Railway variables.

## Direction display
V7.9.1 calculates direction internally but does not display LONG or SHORT while merely watching or while a setup is forming.

Public states:
- `WATCHING · NO TRADE`
- `SETUP FORMING · NO TRADE YET`
- `ENTRY READY · LONG` or `ENTRY READY · SHORT`
- `ACTIVE TRADE · LONG/SHORT`

The manual **I'M IN THIS TRADE** button is hidden until `ENTRY_READY`.

## Learning integrity
The old V7.9 evaluator is no longer used for live calibration or performance.

V7.9.1 starts a clean table and:
- creates a prediction only on a NEW `ENTRY_READY` transition;
- limits clean samples to one per direction per 60 minutes;
- resolves LONG/SHORT target and stop directionally;
- excludes a 1-minute bar when both target and stop are touched because OHLC cannot reveal which happened first;
- scores timeout outcomes directionally but gives them 0R in barrier equity;
- freezes adaptive weight changes while the clean evaluator is being validated;
- withholds statistical calibration until there are at least 30 clean resolved samples and 12 samples in the relevant 5-point qualification bucket;
- ignores old V7.9 learning rows in the V7.9.1 performance screen.

## Trade Map
Execution targets are separated from structural swing objectives:
- Execution TP1: 1.5R–2.0R
- Execution TP2: 2.5R–3.0R
- previous distant TP zones remain visible as structural swing objectives (context only).

Existing execution stop and structural invalidation remain separate.

## Existing integrations preserved
TradingView, Databento YM L2, FRED/macro, Alpha Vantage News & Sentiment, NTFY, SQLite path, Railway service/domain.

## Deploy
Replace `server.py` and `README.md` in the same repo and commit. Railway should redeploy automatically.

After deployment verify:
1. V7.9.1 branding.
2. WATCHING shows NO TRADE, not LONG/SHORT.
3. Databento stays LIVE.
4. NTFY stays connected.
5. Learning Stats restart from the clean V7.9.1 table.
6. Execution TP ranges show about 1.5–3R and old distant targets are labelled context only.

Decision support only; no automatic order execution.


## V7.9.1 hotfix
Fixed missing V7.9.1 learning helper definitions that caused Railway NameError on webhook ingestion.


## V7.9.1 full helper audit hotfix
Audited every direct function call in server.py. Restored qualification probability, clean-sample calibration, and execution-target helpers. Static unresolved-call audit: PASS. Python compile: PASS.
