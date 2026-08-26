US30 SIGNAL LAB V7.7 — PRECISION EXECUTION RISK

CORE CHANGE
V7 now separates TWO stop concepts:

1) EXECUTION STOP
- Default: 50 US30 points.
- This is the actual trading risk used by V7's R calculations.
- When you press I'M IN THIS TRADE, the stop is fixed exactly 50 points from the live entry price:
  LONG: entry - 50
  SHORT: entry + 50
- Trade Health P/L in R, MFE, MAE, stop-danger alerts and profit-protection calculations all use this execution risk.

2) STRUCTURAL INVALIDATION
- The wider 4H level remains visible.
- It represents where the overall swing thesis is structurally wrong.
- It is NOT used as 1R and does not inflate position risk.

PRECISION ENTRY
- The live 1-minute price is now used for execution price.
- The preferred entry zone is a narrow area around the 1H EMA20 setup level.
- Default entry-zone half-width is 15 points.
- PERFECT ENTRY still requires price to actually enter this narrow zone plus all V7.6 quality filters.

TARGETS
- TP1/TP2 remain swing targets based on 4H structural range/ATR.
- Dashboard reports their R multiple against the 50-point execution stop.
- This preserves the objective of catching large multi-day moves with small execution risk.

IMPORTANT
A 50-point US30 stop can be hit by ordinary intraday noise. V7.7 therefore does NOT call an entry PERFECT merely because bias is bullish/bearish. Timing and the precision entry zone must also align.

DEPLOYMENT
Upload/replace ALL files in this flat package to the V7 GitHub repository root.
No TradingView Pine or webhook change is required.
