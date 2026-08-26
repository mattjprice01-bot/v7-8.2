US30 V7.3.2 — FLAT GITHUB BUILD

Upload every file in this folder directly to the ROOT of the V7 GitHub repository.

Required root files:
- server.py
- macro_news.py
- notifier.py
- v7_scoring.py
- requirements.txt
- Procfile
- US30_V7_1_SWING_FEED_YM_ONLY.pine
- v7_mushroom_background.jpg
- test_scoring.py
- README_DEPLOY.txt
- README_FLAT_GITHUB.txt

This build intentionally does NOT require assets/ or tests/ folders.
server.py serves v7_mushroom_background.jpg directly from the repository root.

No TradingView alert change is required if the existing V7.1 YM-only feed is already connected.
