from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import math

HTF_WEIGHTS = {"1W": 0.30, "1D": 0.30, "4h": 0.25, "1h": 0.15}

@dataclass(frozen=True)
class SwingConfig:
    setup_near_score: int = 64
    armed_score: int = 74
    trigger_score: int = 80
    contradiction_limit: float = 2.2
    min_big_move: int = 62
    execution_stop_points: float = 50.0
    entry_half_width_points: float = 15.0


def fnum(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def score_frame(f: dict[str, Any]) -> dict[str, Any]:
    tf = str(f.get("tf", "?"))
    c = fnum(f.get("c")); o = fnum(f.get("o"), c); h = fnum(f.get("h"), c); l = fnum(f.get("l"), c)
    e20 = fnum(f.get("ema20"), c); e50 = fnum(f.get("ema50"), c); e200 = fnum(f.get("ema200"), c)
    rsi = fnum(f.get("rsi"), 50); atr = max(fnum(f.get("atr"), 1), 1e-9)
    atr_ma = max(fnum(f.get("atr_ma"), atr), 1e-9); adx = fnum(f.get("adx"), 20)
    sh20 = fnum(f.get("swing_hi"), h); sl20 = fnum(f.get("swing_lo"), l)
    sh50 = fnum(f.get("swing_hi50"), sh20); sl50 = fnum(f.get("swing_lo50"), sl20)
    c3 = fnum(f.get("c3"), c); e20_prev = fnum(f.get("ema20_prev"), e20)
    vol = max(fnum(f.get("vol"), 0), 0); vma20 = max(fnum(f.get("vma20"), vol or 1), 1e-9)
    bb_width = max(fnum(f.get("bb_width"), 0), 0); bb_width_ma = max(fnum(f.get("bb_width_ma"), bb_width or 1), 1e-9)

    score = 0.0; reasons: list[str] = []
    if c > e20 > e50 > e200:
        score += 3.0; reasons.append("full bullish EMA stack")
    elif c < e20 < e50 < e200:
        score -= 3.0; reasons.append("full bearish EMA stack")
    elif c > e20 > e50:
        score += 1.8; reasons.append("bullish trend stack")
    elif c < e20 < e50:
        score -= 1.8; reasons.append("bearish trend stack")

    slope = (e20 - e20_prev) / atr
    score += clamp(slope, -1.0, 1.0) * 1.2
    if abs(slope) > .15: reasons.append("EMA20 rising" if slope > 0 else "EMA20 falling")

    if adx >= 25:
        direction = 1 if c > e20 else -1 if c < e20 else 0
        score += direction * min((adx - 20) / 15, 1.2)
        reasons.append(f"trend strength ADX {adx:.0f}")

    mom = clamp((c - c3) / atr, -2, 2)
    score += mom * .7
    if abs(mom) > .55: reasons.append("persistent upside momentum" if mom > 0 else "persistent downside momentum")

    if c > sh20: score += 1.2; reasons.append("20-bar breakout")
    if c < sl20: score -= 1.2; reasons.append("20-bar breakdown")
    if c > sh50: score += 1.0; reasons.append("50-bar breakout")
    if c < sl50: score -= 1.0; reasons.append("50-bar breakdown")

    if 53 <= rsi <= 72: score += .55
    elif 28 <= rsi <= 47: score -= .55
    elif rsi > 78 and c < o: score -= .35; reasons.append("overbought rejection risk")
    elif rsi < 22 and c > o: score += .35; reasons.append("oversold rebound risk")

    atr_ratio = atr / atr_ma
    vol_ratio = vol / vma20 if vol > 0 else 1.0
    if atr_ratio >= 1.18:
        direction = 1 if c > o else -1
        score += direction * .45; reasons.append("volatility expansion")
    if vol_ratio >= 1.35:
        direction = 1 if c > o else -1
        score += direction * .45; reasons.append("relative-volume expansion")

    compression = bb_width > 0 and bb_width_ma > 0 and bb_width / bb_width_ma < .78
    return {
        "tf": tf, "score": round(clamp(score, -8, 8), 3), "price": c,
        "ema20": e20, "ema50": e50, "ema200": e200, "atr": atr, "adx": adx,
        "atr_ratio": round(atr_ratio, 3), "vol_ratio": round(vol_ratio, 3), "compression": compression,
        "swing_hi": sh20, "swing_lo": sl20, "swing_hi50": sh50, "swing_lo50": sl50, "reasons": reasons,
    }


def intermarket_score(x: dict[str, Any] | None) -> tuple[float, list[str]]:
    if not x: return 0.0, []
    s = 0.0; r: list[str] = []
    ym = fnum(x.get("ym_ret")); spx = fnum(x.get("spx_ret")); ndx = fnum(x.get("ndx_ret")); vix = fnum(x.get("vix_ret")); dxy = fnum(x.get("dxy_ret")); y10 = fnum(x.get("us10y_chg"))
    if ym > .12: s += .65; r.append("YM confirms upside")
    elif ym < -.12: s -= .65; r.append("YM confirms downside")
    if spx > .15: s += .7; r.append("SPX confirms risk-on")
    elif spx < -.15: s -= .7; r.append("SPX confirms risk-off")
    if ndx > .2: s += .5
    elif ndx < -.2: s -= .5
    if vix < -1.0: s += .8; r.append("VIX falling")
    elif vix > 1.0: s -= .8; r.append("VIX rising")
    if dxy > .35: s -= .25
    elif dxy < -.35: s += .25
    if y10 > .07: s -= .25
    elif y10 < -.07: s += .25
    return clamp(s, -2.5, 2.5), r


def aggregate(payload: dict[str, Any], macro: dict[str, Any] | None = None, news: dict[str, Any] | None = None, config: SwingConfig | None = None) -> dict[str, Any]:
    config = config or SwingConfig()
    scored = [score_frame(x) for x in payload.get("frames", []) if isinstance(x, dict)]
    by = {x["tf"]: x for x in scored}

    wk = fnum(by.get("1W", {}).get("score"))
    day = fnum(by.get("1D", {}).get("score"))
    h4 = fnum(by.get("4h", {}).get("score"))
    h1 = fnum(by.get("1h", {}).get("score"))

    # V7.5 separates the strategic swing thesis from actual entry timing.
    bias_active = [(wk, .44), (day, .36), (h4, .20)]
    bias_num = sum(v*w for v,w in bias_active if v or by)
    bias_den = sum(w for tf,w in [("1W",.44),("1D",.36),("4h",.20)] if tf in by)
    bias_score = bias_num / bias_den if bias_den else 0.0

    timing_active = [(h4, .58), (h1, .42)]
    timing_den = sum(w for tf,w in [("4h",.58),("1h",.42)] if tf in by)
    timing_score = sum(v*w for v,w in timing_active) / timing_den if timing_den else 0.0

    # Technical composite remains useful for continuity with V7.4.
    weighted = 0.0; aw = 0.0
    for tf, w in HTF_WEIGHTS.items():
        if tf in by:
            weighted += by[tf]["score"] * w; aw += w
    technical = weighted / aw if aw else 0.0

    im_score, im_reasons = intermarket_score(payload.get("intermarket"))
    db_ctx = payload.get("databento") or {}
    db_score = clamp(fnum(db_ctx.get("score")), -2.5, 2.5)
    db_live = str(db_ctx.get("status", "")).upper() in ("LIVE", "STALE")
    macro_raw = (macro or {}).get("score")
    macro_available = bool((macro or {}).get("is_usable")) and macro_raw is not None
    macro_score = clamp(fnum(macro_raw), -2.5, 2.5) if macro_available else 0.0
    news_score = clamp(fnum((news or {}).get("score")), -1.5, 1.5)

    # Strategic direction is led by Weekly/Daily/4H bias, with macro/intermarket
    # confirming rather than overpowering the chart.
    strategic = bias_score + .62*im_score + .62*macro_score + .32*news_score + .10*db_score
    direction = 1 if strategic > 0 else -1 if strategic < 0 else 0

    contradiction = False
    if direction > 0 and (wk < -config.contradiction_limit or day < -config.contradiction_limit): contradiction = True
    if direction < 0 and (wk > config.contradiction_limit or day > config.contradiction_limit): contradiction = True

    # Timing alignment is explicit. A bullish bias with bearish 4H/1H can remain
    # WATCHING but may not escalate to ARMED/TRIGGERED.
    timing_aligned = False
    timing_strong = False
    if direction > 0:
        timing_aligned = h4 > .35 and h1 > .15
        timing_strong = h4 > .85 and h1 > .55
    elif direction < 0:
        timing_aligned = h4 < -.35 and h1 < -.15
        timing_strong = h4 < -.85 and h1 < -.55

    combined = strategic + .30*timing_score + .55*db_score
    strength = clamp(abs(combined) / 6.0, 0, 1)
    conviction = round(50 + strength * 47)
    if contradiction:
        conviction = min(conviction, 59)
    elif not timing_aligned:
        conviction = min(conviction, 72)
    if not macro_available:
        conviction = min(conviction, 82)
    db_confirmed = bool(direction and db_live and direction * db_score >= .35)
    if direction and db_live and direction * db_score <= -.75:
        conviction = min(conviction, 76)

    same_dir = sum(1 for v in (wk, day, h4) if (v > .6 if direction > 0 else v < -.6)) if direction else 0
    compression = bool(by.get("1D", {}).get("compression") or by.get("4h", {}).get("compression"))
    expansion = max(fnum(by.get("1D", {}).get("atr_ratio"), 1), fnum(by.get("4h", {}).get("atr_ratio"), 1)) >= 1.15
    big_move = 30 + same_dir * 13 + (12 if compression else 0) + (9 if expansion else 0)
    big_move += int(min(abs(im_score), 1.5) * 4 + min(abs(macro_score), 1.5) * 4 + min(abs(db_score), 1.5) * 4)
    if timing_aligned: big_move += 5
    big_move = int(clamp(big_move, 5, 95))

    analysis_price = fnum((by.get("1h") or by.get("4h") or by.get("1D") or scored[0] if scored else {}).get("price"))
    live_price = fnum((by.get("1m") or by.get("1h") or by.get("4h") or scored[0] if scored else {}).get("price"), analysis_price)
    price = live_price
    atr4 = max(fnum(by.get("4h", {}).get("atr"), fnum(by.get("1D", {}).get("atr"), 100)), 1)
    h1_ema20 = fnum(by.get("1h", {}).get("ema20"), analysis_price)
    execution_risk = max(float(config.execution_stop_points), 1.0)
    entry_half_width = max(float(config.entry_half_width_points), 1.0)

    setup_state = "WATCHING"; signal = "WAIT"
    if big_move >= config.min_big_move and conviction >= config.setup_near_score:
        setup_state = "SETUP_NEAR"
    if big_move >= config.min_big_move and conviction >= config.armed_score and not contradiction and timing_aligned:
        setup_state = "ARMED"
    if conviction >= config.trigger_score and same_dir >= 2 and not contradiction and timing_strong:
        setup_state = "TRIGGERED"; signal = "LONG" if direction > 0 else "SHORT"

    # Precision execution model:
    # - Entry is anchored around the 1H EMA20 setup area, not around the moving live price.
    # - Execution stop is a tight configurable 50-point default.
    # - Structural invalidation remains the wider 4H thesis-failure level.
    # - Swing targets remain based on structural risk/ATR, then we report their R multiple
    #   against the tight execution risk.
    if direction > 0:
        entry_anchor = h1_ema20
        entry_low, entry_high = entry_anchor - entry_half_width, entry_anchor + entry_half_width
        structural_ref = fnum(by.get("4h", {}).get("swing_lo"), analysis_price - .9*atr4)
        structural_stop = min(analysis_price - .85*atr4, structural_ref - .08*atr4)
        execution_stop = entry_anchor - execution_risk
        structural_risk = max(entry_anchor - structural_stop, .5*atr4)
        tp1_low, tp1_high = entry_anchor + 1.7*structural_risk, entry_anchor + 2.0*structural_risk
        tp2_low, tp2_high = entry_anchor + 3.0*structural_risk, entry_anchor + 3.6*structural_risk
    elif direction < 0:
        entry_anchor = h1_ema20
        entry_low, entry_high = entry_anchor - entry_half_width, entry_anchor + entry_half_width
        structural_ref = fnum(by.get("4h", {}).get("swing_hi"), analysis_price + .9*atr4)
        structural_stop = max(analysis_price + .85*atr4, structural_ref + .08*atr4)
        execution_stop = entry_anchor + execution_risk
        structural_risk = max(structural_stop - entry_anchor, .5*atr4)
        tp1_low, tp1_high = entry_anchor - 2.0*structural_risk, entry_anchor - 1.7*structural_risk
        tp2_low, tp2_high = entry_anchor - 3.6*structural_risk, entry_anchor - 3.0*structural_risk
    else:
        entry_anchor = entry_low = entry_high = execution_stop = structural_stop = None
        tp1_low = tp1_high = tp2_low = tp2_high = None
        structural_risk = None

    if direction > 0 and entry_anchor is not None:
        rr_tp1_low = (tp1_low - entry_anchor) / execution_risk
        rr_tp1_high = (tp1_high - entry_anchor) / execution_risk
        rr_tp2_low = (tp2_low - entry_anchor) / execution_risk
        rr_tp2_high = (tp2_high - entry_anchor) / execution_risk
    elif direction < 0 and entry_anchor is not None:
        rr_tp1_low = (entry_anchor - tp1_high) / execution_risk
        rr_tp1_high = (entry_anchor - tp1_low) / execution_risk
        rr_tp2_low = (entry_anchor - tp2_high) / execution_risk
        rr_tp2_high = (entry_anchor - tp2_low) / execution_risk
    else:
        rr_tp1_low = rr_tp1_high = rr_tp2_low = rr_tp2_high = None

    regime = "NEUTRAL"
    if strategic >= 3.4: regime = "STRONG_BULL"
    elif strategic >= 1.2: regime = "BULL"
    elif strategic <= -3.4: regime = "STRONG_BEAR"
    elif strategic <= -1.2: regime = "BEAR"

    bias_label = "NEUTRAL"
    if bias_score >= 1.1: bias_label = "BULLISH"
    elif bias_score <= -1.1: bias_label = "BEARISH"
    timing_label = "ALIGNED" if timing_aligned else "COUNTERTREND" if direction else "NEUTRAL"

    reasons = []
    for tf in ("1W", "1D", "4h", "1h"):
        reasons.extend([f"{tf}: {x}" for x in by.get(tf, {}).get("reasons", [])[:2]])
    if direction and not timing_aligned:
        reasons.append("TIMING: higher-timeframe bias exists but 4H/1H entry timing is not aligned")
    if timing_aligned:
        reasons.append("TIMING: 4H and 1H are aligned with the swing direction")
    if db_live:
        if db_confirmed:
            reasons.append(f"DATABENTO: YM L2 confirms {'LONG' if direction > 0 else 'SHORT'} ({db_score:+.2f})")
        elif direction and direction * db_score <= -.35:
            reasons.append(f"DATABENTO: YM L2 opposes the swing direction ({db_score:+.2f})")
    if not macro_available:
        reasons.append("MACRO: unavailable/stale — perfect entry is blocked")
    reasons += im_reasons[:3] + list((macro or {}).get("reasons", []))[:3] + list((news or {}).get("reasons", []))[:2]

    return {
        "version": 7.81, "symbol": payload.get("symbol", "US30"), "exchange": payload.get("exchange", ""), "ts": payload.get("ts"),
        "signal": signal, "setup_state": setup_state, "regime": regime,
        "direction": "LONG" if direction > 0 else "SHORT" if direction < 0 else "NONE",
        "conviction": conviction, "big_move_probability": big_move,
        "technical_score": round(technical,3), "bias_score": round(bias_score,3), "bias_label": bias_label,
        "timing_score": round(timing_score,3), "timing_label": timing_label, "timing_aligned": timing_aligned,
        "intermarket_score": round(im_score,3),
        "databento_score": round(db_score,3), "databento_status": db_ctx.get("status","NOT_CONFIGURED"),
        "databento_confirmed": db_confirmed,
        "macro_score": round(macro_score,3) if macro_available else None,
        "macro_available": macro_available,
        "macro_status": (macro or {}).get("status","UNAVAILABLE"),
        "macro_quality": (macro or {}).get("quality","NONE"),
        "news_score": round(news_score,3),
        "combined_score": round(combined,3), "strategic_score": round(strategic,3), "contradiction": contradiction,
        "price": price, "analysis_price": round(analysis_price,1),
        "entry_anchor": round(entry_anchor,1) if entry_anchor is not None else None,
        "entry_low": round(entry_low,1) if entry_low is not None else None, "entry_high": round(entry_high,1) if entry_high is not None else None,
        "execution_stop_points": round(execution_risk,1),
        "execution_stop": round(execution_stop,1) if execution_stop is not None else None,
        "stop": round(execution_stop,1) if execution_stop is not None else None,
        "structural_stop": round(structural_stop,1) if structural_stop is not None else None,
        "structural_risk_points": round(structural_risk,1) if structural_risk is not None else None,
        "tp1_low": round(tp1_low,1) if tp1_low is not None else None, "tp1_high": round(tp1_high,1) if tp1_high is not None else None,
        "tp2_low": round(tp2_low,1) if tp2_low is not None else None, "tp2_high": round(tp2_high,1) if tp2_high is not None else None,
        "rr_tp1_low": round(rr_tp1_low,2) if rr_tp1_low is not None else None,
        "rr_tp1_high": round(rr_tp1_high,2) if rr_tp1_high is not None else None,
        "rr_tp2_low": round(rr_tp2_low,2) if rr_tp2_low is not None else None,
        "rr_tp2_high": round(rr_tp2_high,2) if rr_tp2_high is not None else None,
        "expected_hold": "3-10 trading days", "frames": scored, "reasons": reasons[:14], "macro": macro or {}, "news": news or {},
    }

def trade_health(trade: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    side = str(trade["side"]); sign = 1 if side == "LONG" else -1
    score = 70
    changes: list[str] = []
    for key, weight in (("combined_score", 5.0), ("technical_score", 3.0), ("intermarket_score", 2.0), ("macro_score", 2.0), ("news_score", 1.0)):
        v = fnum(result.get(key)); score += int(sign * v * weight)
    if result.get("contradiction"):
        score -= 20; changes.append("higher-timeframe contradiction")
    if result.get("direction") != side:
        score -= 18; changes.append("model direction reversed")
    if result.get("big_move_probability", 0) < 45:
        score -= 8; changes.append("big-move conditions faded")

    zone_ctx=result.get("htf_zones") or {}
    near_zones=zone_ctx.get("near_zones") or []
    if any(bool(z.get("opposing")) for z in near_zones):
        score -= 8; changes.append("nearby higher-timeframe zone opposes the position")
    if zone_ctx.get("high_quality_zone") and (zone_ctx.get("best_zone") or {}).get("aligned"):
        score += 4

    price = fnum(result.get("price")); entry = fnum(trade.get("entry")); stop = fnum(trade.get("stop")); risk = max(abs(entry-stop),1)
    pnl_r = sign * (price-entry) / risk
    if pnl_r > 1.5: score += 7
    if pnl_r < -.5: score -= 8
    score = int(clamp(score, 0, 100))
    action = "HOLD"
    if score < 38: action = "EXIT_OR_REDUCE"
    elif score < 55: action = "PROTECT_POSITION"
    elif pnl_r >= 1.5: action = "TRAIL_4H_STRUCTURE"
    return {"health": score, "action": action, "pnl_r": round(pnl_r,2), "issues": changes}
