US30 SIGNAL LAB V7.6 — QUIET PHONE ALERT ENGINE

NOTIFICATION PHILOSOPHY
V7.6 is deliberately quiet.

WHEN NO TRADE IS ACTIVE
1. SETUP NEAR
   - Direction exists
   - Conviction >= 78%
   - Big Move >= 65%
   - Strong swing bias
   - No higher-timeframe contradiction
   - This is an early warning only. The message explicitly says no action yet.

2. PERFECT ENTRY READY
   - Conviction >= 85%
   - Big Move >= 70%
   - Strong swing bias
   - 4H + 1H entry timing aligned
   - No higher-timeframe contradiction
   - Macro/intermarket/news are not materially opposing
   - Price is actually inside the V7 entry zone

Routine WATCHING / ARMED / TRIGGERED minute-by-minute states do NOT send phone alerts.

WHEN A TRADE IS ACTIVE
Press I'M IN THIS TRADE — START TRACKING on the dashboard.
V7 then suppresses all new-entry alerts and monitors only the open position.

Meaningful active-trade notifications:
- POSITION DANGER: within 0.30R of the stop
- RISK INCREASED: Trade Health falls below 58 with a real deterioration
- DANGER / REVIEW EXIT: health < 38, model reverses direction, or HTF contradiction appears
- TP1 AREA REACHED
- TP2 AREA REACHED
- PROFIT PROTECTION: >= +1.5R with a healthy thesis
- STOP / INVALIDATION HIT
- Tracking started / closed acknowledgement

ANTI-SPAM
- Persistent SQLite notification-state table survives Railway restarts.
- Alerts fire on meaningful state transitions and have cooldowns.
- Risk states reset only after conditions materially recover.
- TP1/TP2/profit-protection milestones fire once per tracked trade.

PHONE DELIVERY
V7.6 supports either or both:

OPTION A — NTFY (simplest)
Install the ntfy app on the phone.
Choose a private topic name, then add this Railway variable:
NTFY_TOPIC=your-private-topic-name

Optional:
NTFY_BASE_URL=https://ntfy.sh

OPTION B — TELEGRAM
Railway variables:
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

The dashboard now shows PHONE ALERTS: CONNECTED / NOT CONFIGURED and has a manual TEST PHONE NOTIFICATION button.

IMPORTANT
The dashboard's trade button changes only V7 internal monitoring. It does not place, modify, or close broker orders.

DEPLOYMENT
Flat GitHub build: replace/upload all files from this package to the V7 repository root.
No Pine change is required if TradingView already points at the current V7 Railway webhook.
