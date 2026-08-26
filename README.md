# US30 SIGNAL LAB V7.9 — IN-PLACE PATCH

This patch upgrades the current working V7.8.2 Railway deployment to V7.9 without rebuilding the project or re-entering variables.

## Replace these two files in the existing GitHub repo

1. `server.py`
2. `README.md`

Commit both files to the SAME branch Railway already deploys from.

## Railway variables

Do **not** delete, recreate, or change the working variables.

Keep the existing configuration, including:
- `ALPHAVANTAGE_API_KEY`
- `DATABASE_PATH` / existing database path variable
- `DATABENTO_API_KEY`
- `DATABENTO_DATASET`
- `DATABENTO_SCHEMA`
- `DATABENTO_SYMBOL`
- `FRED_API_KEY`
- `NTFY_TOPIC`
- Any existing Railway-provided variables

## V7.9 additions

- Persistent pre-trade state engine
- `WATCHING -> SETUP_FORMING -> ENTRY_READY -> ACTIVE_TRADE`
- Hysteresis to stop small probability fluctuations causing repeated state changes
- Setup invalidation back to `WATCHING`
- Meaningful state-change phone notifications
- Databento/YM order-flow rejection alerts when L2 materially flips against a developing setup
- Existing active-trade monitoring remains intact
- Existing Databento, Alpha Vantage, FRED, NTFY, learning, HTF zones and database configuration remain intact

## Deployment

1. Upload/replace `server.py`.
2. Upload/replace `README.md`.
3. Commit the two changes.
4. Allow Railway to redeploy automatically.
5. Wait for Railway to show **Active**.
6. Open the dashboard and confirm:
   - V7.9 branding
   - TradingView feed LIVE
   - Databento LIVE
   - Alpha Vantage LIVE
   - Phone alerts CONNECTED · NTFY
7. Check `/health`; it should identify:
   `US30 Signal Lab V7.9 Intelligent State Engine`

## Important behaviour

V7.9 does **not** assume that an entry-ready model signal means a trade has actually been taken.

`ACTIVE_TRADE` begins only after using the dashboard's **I'M IN THIS TRADE — START TRACKING** action.

## Rollback

If anything unexpected happens:
1. Restore the previous V7.8.2 `server.py`.
2. Commit and redeploy.

The V7.9 `signal_state` database table can remain in SQLite; it will not interfere with the previous version.

## Scope

This is decision-support software. It does not automatically execute trades.
