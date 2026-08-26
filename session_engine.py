from __future__ import annotations
from datetime import datetime, timezone, time as dtime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

NY = ZoneInfo('America/New_York')


def _minutes(t: dtime) -> int:
    return t.hour * 60 + t.minute


def session_context(ts_ms: int | float | None = None) -> dict[str, Any]:
    if ts_ms:
        dt_utc = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
    else:
        dt_utc = datetime.now(timezone.utc)
    et = dt_utc.astimezone(NY)
    dow = et.weekday()  # Mon=0
    m = et.hour * 60 + et.minute

    name = 'OVERNIGHT'
    risk = 'NORMAL'
    penalty = 0
    block_perfect = False
    cash_open = False
    futures_open = True
    note = 'CME futures session / outside US cash hours'

    # CME equity index futures weekend / daily maintenance approximation.
    if dow == 5 or (dow == 6 and m < 18 * 60):
        name, risk, penalty, block_perfect, futures_open = 'WEEKEND_CLOSED', 'CLOSED', 20, True, False
        note = 'CME equity index futures weekend closure'
    elif 17 * 60 <= m < 18 * 60:
        name, risk, penalty, block_perfect, futures_open = 'CME_MAINTENANCE', 'CLOSED', 20, True, False
        note = 'Daily CME maintenance halt (approx. 17:00–18:00 ET)'
    elif 9 * 60 + 25 <= m < 9 * 60 + 40:
        name, risk, penalty, block_perfect = 'US_CASH_OPEN_VOLATILITY', 'EXTREME', 10, True
        cash_open = m >= 9 * 60 + 30
        note = 'US cash open discovery; false breaks/slippage risk elevated'
    elif 9 * 60 + 40 <= m < 10 * 60:
        name, risk, penalty = 'US_OPEN_DISCOVERY', 'HIGH', 5
        cash_open = True
        note = 'Opening range still forming; require stronger confirmation'
    elif 10 * 60 <= m < 15 * 60:
        name, risk, penalty, cash_open = 'US_CASH_SESSION', 'NORMAL', 0, True
        note = 'Normal US cash session'
    elif 15 * 60 <= m < 15 * 60 + 45:
        name, risk, penalty, cash_open = 'POWER_HOUR', 'ELEVATED', 2, True
        note = 'Late-session institutional flow can accelerate moves'
    elif 15 * 60 + 45 <= m < 16 * 60 + 10:
        name, risk, penalty, cash_open = 'US_CASH_CLOSE_VOLATILITY', 'HIGH', 5, m < 16 * 60
        note = 'Cash-close imbalance/rebalancing volatility elevated'
    elif 8 * 60 + 30 <= m < 9 * 60 + 25:
        name, risk, penalty = 'US_PREMARKET', 'ELEVATED', 3
        note = 'US premarket; data releases and positioning can increase volatility'
    elif 16 * 60 + 10 <= m < 17 * 60:
        name, risk, penalty = 'POST_CASH', 'ELEVATED', 2
        note = 'Post-cash session; liquidity profile differs from main session'
    elif m >= 18 * 60 or m < 8 * 60 + 30:
        name, risk, penalty = 'OVERNIGHT_FUTURES', 'ELEVATED', 3
        note = 'Overnight futures session; thinner liquidity than US cash hours'

    # Next regular cash open (Mon-Fri only; does not attempt a holiday calendar).
    candidate = et.replace(hour=9, minute=30, second=0, microsecond=0)
    if et >= candidate:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    mins_to_open = max(0, int((candidate - et).total_seconds() // 60))

    return {
        'name': name,
        'risk': risk,
        'probability_penalty': penalty,
        'block_perfect_entry': block_perfect,
        'cash_open': cash_open,
        'futures_open': futures_open,
        'note': note,
        'et_time': et.isoformat(),
        'minutes_to_next_cash_open': mins_to_open,
    }
