US30 SIGNAL LAB V7.5 — DATA INTELLIGENCE UPGRADE

MAIN CHANGES
1. Macro source resilience
   - FRED remains the PRIMARY official macro source.
   - If FRED is unavailable, V7.5 automatically uses a transparent Yahoo-derived macro proxy:
     VIX, 10Y Treasury yield, US Dollar and HYG credit-risk proxy.
   - The dashboard explicitly labels this FALLBACK_LIVE. It never pretends fallback data is FRED.

2. Source freshness
   - Information Sources shows provider status, quality and latest fetch time.
   - LIVE / FALLBACK_LIVE / UNAVAILABLE states are visible.

3. Strategic swing bias vs entry timing
   - SWING BIAS uses Weekly + Daily + 4H.
   - ENTRY TIMING uses 4H + 1H.
   - A strong bullish/bearish thesis may remain WATCHING when entry timing is countertrend.

4. Stricter escalation
   - SETUP_NEAR can warn early.
   - ARMED requires 4H + 1H alignment with the swing direction.
   - TRIGGERED requires stronger 4H + 1H confirmation.
   - Short-term disagreement can no longer be hidden inside one blended score.

5. Existing features retained
   - Vibrant mushroom dashboard.
   - LIVE/STALE/OFFLINE feed indicator.
   - Active-trade tracking button.
   - Trade Health / MFE / MAE / warnings.
   - Free Yahoo market context and GDELT news.
   - Same V7.1 YM-only TradingView Pine feed.

DEPLOYMENT
Flat GitHub build: upload/replace ALL files in the repository root.
No TradingView Pine change is required if its webhook already points at the V7 Railway service.
