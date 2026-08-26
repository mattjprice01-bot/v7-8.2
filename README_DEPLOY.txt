US30 SIGNAL LAB V7.3.1 — CORRECTED FULL RAILWAY PACKAGE

WHY THIS PACKAGE EXISTS
The previous V7.3 server.py imports get_market from macro_news.py. If only server.py was replaced while an older macro_news.py remained in GitHub, Railway fails at startup with:
ImportError: cannot import name 'get_market' from 'macro_news'

THIS PACKAGE CONTAINS A MATCHED SET. UPLOAD/REPLACE THEM TOGETHER.

REPLACE IN THE V7 GITHUB REPOSITORY:
- server.py
- macro_news.py
- v7_scoring.py
- notifier.py
- requirements.txt
- Procfile

ADD OR REPLACE:
- assets/v7_mushroom_background.jpg

OPTIONAL / KEEP FOR REFERENCE:
- US30_V7_1_SWING_FEED_YM_ONLY.pine
- tests/test_scoring.py

IMPORTANT:
1. Do NOT touch the V6 repository, Railway service, Pine script, or V6 TradingView alert.
2. Do NOT recreate the V7 TradingView alert if your existing V7.1 YM-only alert is already sending data.
3. Do NOT upload this ZIP itself into GitHub. Extract it and upload the files/folders.
4. Make sure macro_news.py is replaced at the SAME TIME as server.py.
5. Keep secrets/API keys in Railway Variables, not GitHub.

EXPECTED GITHUB ROOT AFTER UPDATE:
server.py
macro_news.py
v7_scoring.py
notifier.py
requirements.txt
Procfile
US30_V7_1_SWING_FEED_YM_ONLY.pine
assets/
  v7_mushroom_background.jpg
tests/
  test_scoring.py

AFTER GITHUB COMMIT:
- Railway should redeploy automatically.
- In Railway Deploy Logs, confirm there is NO ImportError.
- Open /health. Expected JSON contains ok:true and service:US30 Signal Lab V7 Swing.
- Open the dashboard root /. It should load the mushroom background.
- LIVE = packet under 90 seconds old.
- STALE = 90–240 seconds old.
- OFFLINE = over 240 seconds/no packet.

BACKEND DATA:
- TradingView: US30 technical feed + YM confirmation.
- Free backend market context: SPX, Nasdaq 100, VIX, DXY, US10Y (best effort).
- Macro: FRED CSV.
- News: GDELT.
- External-source failures degrade gracefully and should not crash the server.
