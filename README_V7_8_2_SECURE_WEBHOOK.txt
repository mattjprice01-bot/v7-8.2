US30 SIGNAL LAB V7.8.2 — SECURE TRADINGVIEW WEBHOOK

WHAT CHANGED
- Pine now has a Webhook Secret input.
- Pine includes the secret inside every JSON webhook payload.
- Railway validates the JSON secret against the WEBHOOK_SECRET environment variable.
- The secret no longer needs to appear in the webhook URL.
- secrets.compare_digest is used for constant-time comparison.
- Legacy /webhook/tradingview/{secret} remains available for compatibility, but the recommended URL is the plain endpoint.

SETUP

1. Generate a long random private secret.
   Example format only:
   V782_<40+ random characters>

2. Railway Variables:
   WEBHOOK_SECRET=YOUR_PRIVATE_SECRET

3. In TradingView, add the new Pine:
   US30 V7.8.2 SWING FEED — SECURE HTF ZONES + YM

4. Open the indicator settings and paste THE SAME SECRET into:
   Webhook Secret

5. Create a NEW TradingView alert:
   Condition: US30 V7.8.2 SWING FEED — SECURE HTF ZONES + YM
   Trigger: Any alert() function call
   Chart: US30 1 minute
   Webhook URL:
   https://YOUR-RAILWAY-DOMAIN.up.railway.app/webhook/tradingview

6. Do not manually type an alert message.
   Pine builds and sends the JSON automatically.

SECURITY
- Never put the secret in GitHub.
- Never post it in screenshots/messages.
- If exposed, revoke/replace it in Railway and TradingView indicator settings.
