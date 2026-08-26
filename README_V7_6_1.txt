US30 SIGNAL LAB V7.6.1 — MACRO RELIABILITY FIX

WHAT THIS FIXES
- Macro no longer silently becomes 0.000 when sources fail.
- A real neutral macro score may still be 0.000, but missing data is now shown as N/A / UNAVAILABLE.
- FRED remains primary.
- Yahoo market macro proxy remains fallback and is explicitly labelled FALLBACK_LIVE.
- Last valid macro snapshot is persisted to data/last_macro.json.
- If both live sources fail, V7 uses the last valid macro snapshot and labels it STALE_LAST_VALID.
- Last-valid macro is considered usable for up to 6 hours, then becomes unusable.
- PERFECT ENTRY READY is blocked whenever macro evidence is unavailable/unusable.
- Conviction is capped at 82% when macro is unavailable.
- Dashboard shows macro status/quality rather than misleading 0.000.

DEPLOYMENT
Replace/upload ALL files in this flat package to the V7 GitHub repository root.
No TradingView Pine or webhook change is required.
