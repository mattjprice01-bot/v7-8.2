US30 SIGNAL LAB V7.8.1 — HIGHER-TIMEFRAME SWING ZONE INTELLIGENCE

WHAT WAS ADDED
V7 now has a dedicated HTF Swing Zone Engine designed around the tactic of finding major reactions from historically important higher-timeframe areas.

ZONE REFERENCES
• Previous day high, low and close
• Previous week high, low and close
• Previous month high, low and close
• Daily 20-bar and 50-bar swing highs/lows
• Weekly 20-bar and 50-bar swing highs/lows
• Monthly swing highs/lows
• Historical old-ATH reference
• Dedicated Old ATH → confirmed daily close breakout/retest band

OLD ATH RETEST LOGIC
If the previous confirmed daily close is above the old ATH, V7 builds a support/retest band between the old ATH and that confirmed daily close.

This is explicitly classified as:
OLD_ATH_RETEST_BAND

For a bullish swing thesis, a return into/near that band is treated as a potentially important reaction area.
If price is below the old ATH rather than confirmed above it, the ATH remains a resistance reference instead.

BOTH DIRECTIONS
LONG setups favour nearby support/retest zones:
• Weekly/monthly lows
• Previous lows/closes
• Bullish old-ATH breakout/retest band

SHORT setups favour nearby resistance/retest zones:
• Weekly/monthly highs
• Previous highs/closes
• Failed/overhead ATH reference

CONFLUENCE
V7 clusters overlapping HTF references.
For example:
Previous week low + Daily 50-bar swing low + Monthly close
may be identified as a 3-level confluence area.

LEARNING / SELF-TEST
Every prediction now stores:
• HTF zone type
• HTF zone score
• Whether the zone confirmed the model direction
• Distance from the zone
• Number of overlapping HTF levels

The performance engine reports actual target-before-stop win rate and sample count by zone type.

This allows V7 to discover whether categories such as:
OLD_ATH_RETEST_BAND
WEEKLY_SWING_LOW_20
PREV_MONTH_HIGH
DAILY_SWING_LOW_50
actually outperform in live forward data.

PROBABILITY SAFETY
HTF zone evidence may adjust the RAW model probability by a maximum of +/-5 percentage points.

It does not manufacture a "90%" or "98%" claim.

The CALIBRATED probability remains based on resolved prediction history, so the zone tactic has to prove itself.

PERFECT ENTRY
By default V7.8.1 now requires an aligned HTF swing zone for PERFECT ENTRY.

The personal dashboard includes:
Require HTF zone for Perfect Entry

This can be switched off for comparison/testing.

ACTIVE TRADES
Once a trade is active, V7 also watches nearby HTF zones:
• strong aligned zone can support Trade Health
• a nearby opposing HTF zone reduces Trade Health and is shown as a risk factor

IMPORTANT — TRADINGVIEW PINE UPDATE
This version DOES require the updated Pine file because the backend now needs:
• Monthly confirmed timeframe data
• Previous D/W/M high, low and close
• Historical old-ATH reference

The included file is still named:
US30_V7_1_SWING_FEED_YM_ONLY.pine

but its indicator title is:
US30 V7.8.1 SWING FEED — HTF ZONES + YM

After replacing the Pine code, CREATE A NEW V7 TRADINGVIEW ALERT:
• Chart: US30 1 minute
• Condition: new V7.8.1 indicator
• Any alert() function call
• Existing V7 Railway webhook /webhook/tradingview

TradingView alert snapshots keep the old script logic, so simply editing Pine without recreating the alert is not sufficient.

OLD ATH REFERENCE NOTE
Pine uses the highest high from the previous 5000 confirmed Daily bars (roughly 20 trading years) as the historical old-ATH reference.

This is a practical model reference, not an exchange-certified lifetime all-time-high database.

DEPLOYMENT
Upload/replace ALL files from this flat package to the V7 GitHub repository.

Keep your Railway persistent volume mounted so:
• prediction history
• calibration
• zone performance
• model settings
survive future deployments.
