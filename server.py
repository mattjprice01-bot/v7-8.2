from __future__ import annotations
import json, os, secrets, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, FileResponse
from v7_scoring import aggregate, trade_health
from macro_news import get_macro, get_news, get_market
from notifier import send, status as notification_status
from databento_feed import start_background as start_databento, get_snapshot as get_databento_snapshot
from session_engine import session_context
from htf_zones import analyze_htf_zones
from learning import ensure_tables as ensure_learning_tables, get_settings, update_settings

BASE=Path(__file__).resolve().parent
DB=Path(os.getenv("US30_V7_DB", BASE/"data"/"v7_swing.db")); DB.parent.mkdir(parents=True,exist_ok=True)
SECRET=os.getenv("WEBHOOK_SECRET","").strip()
app=FastAPI(title="US30 Signal Lab V7.9.1 Learning Integrity + State Gate")

@app.on_event("startup")
def _startup():
    start_databento()

def now(): return datetime.now(timezone.utc).isoformat()

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.executescript('''
    CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY, received_at TEXT, symbol TEXT, raw_json TEXT, result_json TEXT);
    CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, opened_at TEXT, opened_ts INTEGER, symbol TEXT, side TEXT, entry REAL, stop REAL, structural_stop REAL, tp1_low REAL, tp1_high REAL, tp2_low REAL, tp2_high REAL, risk REAL, status TEXT DEFAULT 'OPEN', last_health INTEGER DEFAULT 70, max_mfe_r REAL DEFAULT 0, max_mae_r REAL DEFAULT 0, closed_at TEXT, close_reason TEXT, close_price REAL);
    CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, created_at TEXT, kind TEXT, title TEXT, body TEXT);
    CREATE TABLE IF NOT EXISTS notification_state(
        key TEXT PRIMARY KEY,
        state TEXT,
        last_sent_at TEXT,
        last_value REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS signal_state(
        symbol TEXT PRIMARY KEY,
        state TEXT NOT NULL DEFAULT 'WATCHING',
        direction TEXT NOT NULL DEFAULT 'NONE',
        entered_at TEXT,
        updated_at TEXT,
        last_probability REAL DEFAULT 0,
        last_orderflow REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS predictions_v791(
        id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL,
        created_ts INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        entry REAL NOT NULL,
        target_points REAL NOT NULL,
        stop_points REAL NOT NULL,
        horizon_minutes INTEGER NOT NULL,
        probability REAL NOT NULL,
        target_price REAL NOT NULL,
        stop_price REAL NOT NULL,
        state_at_entry TEXT NOT NULL DEFAULT 'ENTRY_READY',
        zone_type TEXT,
        session_name TEXT,
        databento_score REAL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'OPEN',
        resolved_at TEXT,
        resolved_ts INTEGER,
        outcome TEXT,
        favorable INTEGER,
        r_result REAL,
        close_price REAL,
        ambiguous INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_predictions_v791_status ON predictions_v791(status, created_ts);
    ''')
    cols={row["name"] for row in c.execute("PRAGMA table_info(trades)").fetchall()}
    if "structural_stop" not in cols:
        c.execute("ALTER TABLE trades ADD COLUMN structural_stop REAL")
    ensure_learning_tables(c)
    c.commit(); return c

def frame(payload, tf): return next((x for x in payload.get("frames",[]) if x.get("tf")==tf),None)

def _minutes_since(iso: str | None) -> float:
    if not iso:
        return 1e9
    try:
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60.0)
    except Exception:
        return 1e9

def _notify_once(c, key: str, state: str, title: str, body: str, priority: int = 3,
                 cooldown_minutes: int = 360, value: float = 0.0, reset: bool = False) -> bool:
    """Persistent state-change/cooldown gate so Railway restarts do not cause alert spam."""
    row = c.execute("SELECT * FROM notification_state WHERE key=?", (key,)).fetchone()
    if reset:
        c.execute("DELETE FROM notification_state WHERE key=?", (key,))
        return False
    if row:
        same_state = str(row["state"]) == state
        age = _minutes_since(row["last_sent_at"])
        if same_state and age < cooldown_minutes:
            return False

    c.execute("INSERT INTO alerts(created_at,kind,title,body) VALUES(?,?,?,?)", (now(), state, title, body))
    result = send(title, body, priority)
    c.execute(
        """INSERT INTO notification_state(key,state,last_sent_at,last_value)
           VALUES(?,?,?,?)
           ON CONFLICT(key) DO UPDATE SET state=excluded.state,last_sent_at=excluded.last_sent_at,last_value=excluded.last_value""",
        (key, state, now(), float(value)),
    )
    return bool(result.get("ok"))

def _direction_sign(direction: str) -> int:
    return 1 if direction == "LONG" else -1 if direction == "SHORT" else 0

def _context_not_opposing(r: dict) -> bool:
    sign = _direction_sign(str(r.get("direction", "")))
    if not sign:
        return False
    # A source may be neutral/unavailable, but a materially adverse macro or
    # intermarket reading blocks the phrase PERFECT ENTRY.
    if not bool(r.get("macro_available")):
        return False
    macro = float(r.get("macro_score", 0) or 0)
    inter = float(r.get("intermarket_score", 0) or 0)
    news = float(r.get("news_score", 0) or 0)
    return sign * macro > -0.65 and sign * inter > -0.75 and sign * news > -0.85

def _inside_entry(r: dict) -> bool:
    try:
        p = float(r["price"]); lo = float(r["entry_low"]); hi = float(r["entry_high"])
        return lo <= p <= hi
    except Exception:
        return False

def pretrade_alerts(c, r: dict) -> None:
    """Legacy probability alert layer disabled in V7.9.1; state engine is authoritative."""
    return


def _v791_evaluate_predictions(c, ts_ms: int, high: float, low: float, close: float) -> None:
    rows=c.execute("SELECT * FROM predictions_v791 WHERE status='OPEN' ORDER BY id").fetchall()
    for row in rows:
        p=dict(row); side=str(p["side"]); sign=1 if side=="LONG" else -1
        target=float(p["target_price"]); stop=float(p["stop_price"])
        target_hit=(high>=target) if sign>0 else (low<=target)
        stop_hit=(low<=stop) if sign>0 else (high>=stop)
        if target_hit and stop_hit:
            c.execute("""UPDATE predictions_v791 SET status='RESOLVED',resolved_at=?,resolved_ts=?,
                         outcome='AMBIGUOUS_SAME_BAR',ambiguous=1,close_price=? WHERE id=?""",
                      (now(),ts_ms,float(close),p["id"]))
        elif target_hit or stop_hit:
            favorable=1 if target_hit else 0
            outcome="TARGET" if target_hit else "STOP"
            rr=float(p["target_points"])/max(float(p["stop_points"]),1.0) if target_hit else -1.0
            c.execute("""UPDATE predictions_v791 SET status='RESOLVED',resolved_at=?,resolved_ts=?,
                         outcome=?,favorable=?,r_result=?,close_price=? WHERE id=?""",
                      (now(),ts_ms,outcome,favorable,rr,float(close),p["id"]))
        elif ts_ms >= int(p["created_ts"])+int(p["horizon_minutes"])*60000:
            move=sign*(float(close)-float(p["entry"]))
            favorable=1 if move>0 else 0
            outcome="TIMEOUT_FAVORABLE" if move>0 else "TIMEOUT_UNFAVORABLE" if move<0 else "TIMEOUT_FLAT"
            c.execute("""UPDATE predictions_v791 SET status='RESOLVED',resolved_at=?,resolved_ts=?,
                         outcome=?,favorable=?,r_result=0.0,close_price=? WHERE id=?""",
                      (now(),ts_ms,outcome,favorable,float(close),p["id"]))

def _v791_maybe_record_prediction(c, r: dict, state_result: dict, sess: dict, dbento: dict, ts_ms: int) -> None:
    if state_result.get("state")!="ENTRY_READY" or not state_result.get("changed"):
        return
    side=str(state_result.get("direction","NONE"))
    if side not in ("LONG","SHORT"):
        return
    last=c.execute("SELECT created_ts FROM predictions_v791 WHERE symbol=? AND side=? ORDER BY id DESC LIMIT 1",
                   (str(r.get("symbol","US30")),side)).fetchone()
    if last and ts_ms-int(last["created_ts"]) < 3600000:
        return
    st=get_settings(c)
    target_points=float(st.get("prediction_target_points",100.0))
    stop_points=float(st.get("prediction_stop_points",50.0))
    horizon=int(st.get("prediction_horizon_minutes",480))
    entry=float(r["price"]); sign=1 if side=="LONG" else -1
    probability=float(r.get("probability_raw",r.get("conviction",0)) or 0)
    zone=((r.get("htf_zones") or {}).get("best_zone") or {})
    zone_name=zone.get("type") or zone.get("label") or ""
    flow=float((dbento or {}).get("score",r.get("databento_score",0)) or 0)
    c.execute("""INSERT INTO predictions_v791(created_at,created_ts,symbol,side,entry,target_points,stop_points,
                 horizon_minutes,probability,target_price,stop_price,state_at_entry,zone_type,session_name,databento_score)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (now(),ts_ms,str(r.get("symbol","US30")),side,entry,target_points,stop_points,horizon,probability,
               entry+sign*target_points,entry-sign*stop_points,"ENTRY_READY",str(zone_name),
               str((sess or {}).get("name") or ""),flow))

def _v791_performance(c) -> dict:
    rows=[dict(x) for x in c.execute("SELECT * FROM predictions_v791 ORDER BY id").fetchall()]
    resolved=[x for x in rows if x["status"]=="RESOLVED" and not int(x.get("ambiguous") or 0)]
    barriers=[x for x in resolved if x.get("outcome") in ("TARGET","STOP")]
    directional=[x for x in resolved if x.get("favorable") is not None]
    barrier_win=round(100*sum(x["outcome"]=="TARGET" for x in barriers)/len(barriers),1) if barriers else None
    accuracy=round(100*sum(int(x["favorable"]) for x in directional)/len(directional),1) if directional else None
    cumulative=0.0; curve=[]
    for x in resolved:
        if x.get("outcome") in ("TARGET","STOP"):
            cumulative+=float(x.get("r_result") or 0)
        curve.append({"id":x["id"],"r":round(cumulative,3)})
    brier=round(sum((float(x["probability"])/100-int(x["favorable"]))**2 for x in directional)/len(directional),4) if directional else None
    return {"definition":"V7.9.1 clean ENTRY_READY samples; same-bar target+stop excluded.",
            "total_predictions":len(rows),"resolved":len(resolved),"barrier_samples":len(barriers),
            "barrier_win_rate":barrier_win,"directional_accuracy":accuracy,"cumulative_r":round(cumulative,2),
            "primary_brier":brier,"challenger_brier":0.25 if directional else None,
            "ambiguous_excluded":sum(int(x.get("ambiguous") or 0) for x in rows),"zones":[],"curve":curve[-200:]}


def _qualification_probability(r: dict) -> float:
    """Raw pre-trade qualification score. This is deliberately separate from learned calibration."""
    base = float(r.get("conviction", 0) or 0)
    zone = r.get("htf_zones") or {}
    zone_adj = float(zone.get("probability_adjustment", 0) or 0)

    # Small confirmation/rejection adjustment from live YM order flow.
    direction = str(r.get("direction", "NONE"))
    sign = _direction_sign(direction)
    flow = float(r.get("databento_score", 0) or (r.get("databento") or {}).get("score", 0) or 0)
    flow_adj = max(-2.0, min(2.0, sign * flow * 2.0)) if sign else 0.0

    # Contradiction must materially reduce qualification rather than merely decorate the UI.
    contradiction_penalty = 8.0 if bool(r.get("contradiction")) else 0.0

    score = base + zone_adj + flow_adj - contradiction_penalty
    return max(0.0, min(99.9, score))


def _v791_calibration(c, raw_probability: float):
    """Return empirical V7.9.1 calibration only after the clean-sample gates are met."""
    p = max(0.0, min(99.9, float(raw_probability)))
    bucket_low = int(p // 5) * 5
    bucket_high = min(100, bucket_low + 5)
    bucket_label = f"{bucket_low}-{bucket_high}"

    clean = [dict(x) for x in c.execute(
        """SELECT probability,favorable,ambiguous,status
           FROM predictions_v791
           WHERE status='RESOLVED' AND ambiguous=0 AND favorable IS NOT NULL"""
    ).fetchall()]

    total_n = len(clean)
    bucket = [x for x in clean if bucket_low <= float(x["probability"]) < bucket_high]
    bucket_n = len(bucket)

    # README contract: >=30 clean resolved overall AND >=12 in this 5-point bucket.
    if total_n < 30 or bucket_n < 12:
        return None, bucket_n, bucket_label

    calibrated = 100.0 * sum(int(x["favorable"]) for x in bucket) / bucket_n
    return round(calibrated, 1), bucket_n, bucket_label


def _apply_execution_targets(r: dict) -> None:
    """Keep structural swing objectives for context; publish executable targets at 1.5–3.0R."""
    direction = str(r.get("direction", "NONE"))
    sign = _direction_sign(direction)
    if not sign:
        return

    entry_low = float(r.get("entry_low", r.get("price", 0)) or 0)
    entry_high = float(r.get("entry_high", r.get("price", 0)) or 0)
    entry_mid = (entry_low + entry_high) / 2.0

    # Preserve the original model's distant swing targets before replacing the public TP fields.
    for key in ("tp1_low", "tp1_high", "tp2_low", "tp2_high"):
        if r.get(key) is not None:
            r["swing_" + key] = r[key]

    risk = 50.0
    r["execution_stop_points"] = risk
    r["execution_stop"] = entry_mid - sign * risk

    # Preserve the model's structural invalidation if supplied; otherwise use its original stop.
    structural = r.get("structural_stop")
    if structural is None:
        structural = r.get("stop")
    if structural is None:
        structural = r.get("stop_price")
    if structural is None:
        structural = r["execution_stop"]
    r["structural_stop"] = float(structural)

    if sign > 0:
        r["tp1_low"], r["tp1_high"] = entry_mid + 1.5*risk, entry_mid + 2.0*risk
        r["tp2_low"], r["tp2_high"] = entry_mid + 2.5*risk, entry_mid + 3.0*risk
    else:
        r["tp1_low"], r["tp1_high"] = entry_mid - 2.0*risk, entry_mid - 1.5*risk
        r["tp2_low"], r["tp2_high"] = entry_mid - 3.0*risk, entry_mid - 2.5*risk

    r["rr_tp1_low"], r["rr_tp1_high"] = 1.5, 2.0
    r["rr_tp2_low"], r["rr_tp2_high"] = 2.5, 3.0

def update_signal_state(c, r: dict) -> dict:
    """V7.9 pre-trade state machine with hysteresis and meaningful-change alerts."""
    symbol=str(r.get("symbol","US30")); direction=str(r.get("direction","NONE"))
    prob=_qualification_probability(r)
    settings=get_settings(c); setup=float(settings.get("setup_notify_probability",92.0)); perfect=float(settings.get("perfect_notify_probability",98.0))
    big=int(r.get("big_move_probability",0) or 0); bias=abs(float(r.get("bias_score",0) or 0)); timing=bool(r.get("timing_aligned")); contradiction=bool(r.get("contradiction"))
    dbx=r.get("databento") or {}; flow=float(r.get("databento_score",0) or 0); sign=_direction_sign(direction)
    row=c.execute("SELECT * FROM signal_state WHERE symbol=?",(symbol,)).fetchone(); old=dict(row) if row else {"state":"WATCHING","direction":"NONE","last_probability":0,"last_orderflow":0}
    old_state=str(old.get("state") or "WATCHING"); old_dir=str(old.get("direction") or "NONE")
    if c.execute("SELECT 1 FROM trades WHERE status='OPEN' LIMIT 1").fetchone(): new="ACTIVE_TRADE"
    elif direction not in ("LONG","SHORT") or contradiction or prob < setup-7: new="WATCHING"
    elif prob >= perfect and big>=65 and bias>=1.20 and timing and _inside_entry(r) and _context_not_opposing(r) and bool(r.get("databento_confirmed")): new="ENTRY_READY"
    elif prob >= setup and big>=60 and bias>=1.0: new="SETUP_FORMING"
    else: new="WATCHING"
    # Hysteresis: once forming/ready, don't collapse on a tiny probability wobble.
    if old_dir==direction and old_state=="ENTRY_READY" and new=="SETUP_FORMING" and prob >= perfect-3: new="ENTRY_READY"
    if old_dir==direction and old_state=="SETUP_FORMING" and new=="WATCHING" and prob >= setup-4 and not contradiction: new="SETUP_FORMING"
    changed=(new!=old_state or direction!=old_dir)
    entered=now() if changed else old.get("entered_at")
    c.execute("""INSERT INTO signal_state(symbol,state,direction,entered_at,updated_at,last_probability,last_orderflow)
                 VALUES(?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET state=excluded.state,direction=excluded.direction,
                 entered_at=excluded.entered_at,updated_at=excluded.updated_at,last_probability=excluded.last_probability,last_orderflow=excluded.last_orderflow""",
              (symbol,new,direction,entered,now(),prob,flow))
    # State transition alerts. Existing _notify_once provides cooldown/deduplication.
    if changed and new=="SETUP_FORMING":
        _notify_once(c,f"v79:{symbol}:{direction}:forming","V79_SETUP_FORMING",f"US30 V7.9.1 SETUP FORMING",f"Qualification {prob:.1f}% · Big move {big}% · YM L2 {flow:+.2f}. Direction remains hidden until ENTRY READY.",3,30,prob)
    elif changed and new=="ENTRY_READY":
        _notify_once(c,f"v79:{symbol}:{direction}:ready","V79_ENTRY_READY",f"US30 V7.9.1 {direction} ENTRY READY",f"Probability {prob:.1f}% · Price {r.get('price')} · Entry {r.get('entry_low')}–{r.get('entry_high')} · YM L2 {flow:+.2f}. Timing and context confirmed.",5,60,prob)
    elif changed and old_state in ("SETUP_FORMING","ENTRY_READY") and new=="WATCHING":
        _notify_once(c,f"v79:{symbol}:{old_dir}:invalid","V79_INVALIDATED",f"US30 V7.9.1 SETUP INVALIDATED",f"State returned to WATCHING · probability {prob:.1f}% · YM L2 {flow:+.2f}.",4,20,prob)
    # Material L2 reversal while a setup is live.
    prev_flow=float(old.get("last_orderflow") or 0); flow_reversal=old_dir==direction and new in ("SETUP_FORMING","ENTRY_READY") and sign and sign*prev_flow>0.15 and sign*flow<-0.15
    if flow_reversal:
        _notify_once(c,f"v79:{symbol}:{direction}:flow-reject","V79_ORDERFLOW_REJECT",f"US30 V7.9.1 ORDER FLOW REJECTING",f"YM L2 flipped from {prev_flow:+.2f} to {flow:+.2f}. Re-check entry thesis.",4,20,flow)
    public_direction = direction if new in ("ENTRY_READY","ACTIVE_TRADE") else "NONE"
    out={"state":new,"direction":direction,"public_direction":public_direction,"changed":changed,"probability":prob,"previous_state":old_state,"orderflow":flow}
    r["trade_state"]=new; r["state_engine"]=out; r["public_direction"]=public_direction
    return out

def maybe_open(c, r):
    # V7.9 does not assume that a model signal means the user actually entered.
    # The dashboard's I'M IN THIS TRADE button is the authoritative transition.
    return

def update_trades(c, payload, r):
    bar = frame(payload, "1m") or frame(payload, "1h")
    if not bar:
        return
    high = float(bar.get("h", r["price"])); low = float(bar.get("l", r["price"])); price = float(r["price"])

    for t in c.execute("SELECT * FROM trades WHERE status='OPEN'").fetchall():
        td = dict(t); tid = int(td["id"]); sign = 1 if td["side"] == "LONG" else -1
        risk = max(float(td["risk"]), 1.0); entry = float(td["entry"]); stop = float(td["stop"])
        prev_health = int(td["last_health"])
        mfe = max(0.0, (high-entry)/risk) if sign > 0 else max(0.0, (entry-low)/risk)
        mae = max(0.0, (entry-low)/risk) if sign > 0 else max(0.0, (high-entry)/risk)
        pnl_r = sign * (price-entry) / risk
        distance_to_stop_r = sign * (price-stop) / risk

        stop_hit = low <= stop if sign > 0 else high >= stop
        tp1_touched = high >= float(td["tp1_low"]) if sign > 0 else low <= float(td["tp1_high"])
        tp2_touched = high >= float(td["tp2_low"]) if sign > 0 else low <= float(td["tp2_high"])

        health = trade_health(td, r)
        h = int(health["health"])
        status = "OPEN"; reason = None; cp = None

        # 1) Hard invalidation / stop — always meaningful.
        if stop_hit:
            status = "CLOSED"; reason = "STOP"; cp = stop
            _notify_once(
                c, f"trade:{tid}:stop", "STOP_HIT",
                f"US30 {td['side']} EXECUTION STOP HIT",
                f"Price reached the 50-point execution stop at {stop:.1f}. Tracking is closed.",
                5, 100000, h
            )
        else:
            # 2) Imminent stop danger, only once unless it later recovers and re-enters.
            if distance_to_stop_r <= 0.30:
                _notify_once(
                    c, f"trade:{tid}:stop-danger", "STOP_DANGER",
                    f"US30 {td['side']} POSITION DANGER",
                    f"Price is only {distance_to_stop_r:.2f}R from the stop.\n"
                    f"Current {price:.1f} · Stop {stop:.1f}\n"
                    f"Trade health {h}/100 · {health['action']}",
                    5, 180, distance_to_stop_r
                )
            elif distance_to_stop_r >= 0.55:
                _notify_once(c, f"trade:{tid}:stop-danger", "RESET", "", "", reset=True)

            # 3) Thesis danger: only on a meaningful health collapse or explicit reversal.
            direction_reversed = str(r.get("direction")) != str(td["side"])
            contradiction = bool(r.get("contradiction"))
            health_drop = prev_health - h

            if h < 38 or direction_reversed or contradiction:
                issues = ", ".join(health.get("issues") or []) or "model thesis materially deteriorated"
                _notify_once(
                    c, f"trade:{tid}:thesis", "DANGER_EXIT",
                    f"US30 {td['side']} DANGER / REVIEW EXIT",
                    f"Trade health {prev_health} → {h}/100\n"
                    f"P/L {pnl_r:+.2f}R\n"
                    f"{issues}\n"
                    f"Action: {health['action']}",
                    5, 180, h
                )
            elif h < 58 and (prev_health >= 58 or health_drop >= 15):
                issues = ", ".join(health.get("issues") or []) or "multiple supporting factors weakened"
                _notify_once(
                    c, f"trade:{tid}:health", "RISK_INCREASED",
                    f"US30 {td['side']} RISK INCREASED",
                    f"Trade health {prev_health} → {h}/100\n"
                    f"P/L {pnl_r:+.2f}R\n"
                    f"{issues}\n"
                    f"Action: {health['action']}",
                    4, 180, h
                )
            elif h >= 68:
                _notify_once(c, f"trade:{tid}:health", "RESET", "", "", reset=True)
                _notify_once(c, f"trade:{tid}:thesis", "RESET", "", "", reset=True)

            # 4) Target management — one meaningful alert per milestone.
            if tp2_touched:
                _notify_once(
                    c, f"trade:{tid}:tp2", "TP2_REACHED",
                    f"US30 {td['side']} TP2 AREA REACHED",
                    f"Price {price:.1f} has reached the TP2 area {td['tp2_low']:.1f}–{td['tp2_high']:.1f}.\n"
                    f"Trade health {h}/100 · P/L {pnl_r:+.2f}R\n"
                    f"Review the runner / exit plan.",
                    4, 100000, pnl_r
                )
            elif tp1_touched:
                _notify_once(
                    c, f"trade:{tid}:tp1", "TP1_REACHED",
                    f"US30 {td['side']} TP1 AREA REACHED",
                    f"Price {price:.1f} has reached TP1 {td['tp1_low']:.1f}–{td['tp1_high']:.1f}.\n"
                    f"Trade health {h}/100 · P/L {pnl_r:+.2f}R\n"
                    f"Consider partial profit; keep the runner only while the swing thesis remains healthy.",
                    4, 100000, pnl_r
                )

            # 5) Profit protection, only after a real move.
            if pnl_r >= 1.50 and h >= 62:
                _notify_once(
                    c, f"trade:{tid}:protect", "PROTECT_PROFIT",
                    f"US30 {td['side']} PROFIT PROTECTION",
                    f"Trade is {pnl_r:+.2f}R with health {h}/100.\n"
                    f"Use 4H structure for the trailing stop; avoid choking the swing with 1m/5m noise.",
                    3, 100000, pnl_r
                )

        c.execute(
            """UPDATE trades SET status=?,last_health=?,max_mfe_r=max(max_mfe_r,?),max_mae_r=max(max_mae_r,?),
               closed_at=?,close_reason=?,close_price=? WHERE id=?""",
            (status, h, mfe, mae, now() if status == "CLOSED" else None, reason, cp, tid)
        )

def authorised(secret):
    if not SECRET:return True
    return bool(secret and secrets.compare_digest(secret,SECRET))

async def ingest(request, secret=None):
    p=await request.json()
    if not isinstance(p,dict) or not isinstance(p.get("frames"),list): raise HTTPException(422,"expected frames[]")
    supplied = str(p.get("secret") or secret or "")
    if SECRET and not secrets.compare_digest(supplied, SECRET):
        raise HTTPException(403,"bad webhook secret")
    ts_ms=int(p.get("ts") or int(datetime.now(timezone.utc).timestamp()*1000))
    macro=get_macro(); news=get_news(); market=get_market(); dbento=get_databento_snapshot(); sess=session_context(ts_ms)
    inter=dict(p.get("intermarket") or {}); inter.update((market or {}).get("values") or {}); p["intermarket"]=inter; p["databento"]=dbento
    r=aggregate(p,macro,news)
    zone_ctx=analyze_htf_zones(p,str(r.get("direction","NONE")))
    r["htf_zones"]=zone_ctx
    r["reasons"]=(list(r.get("reasons") or []) + list(zone_ctx.get("reasons") or []))[:18]
    r["market_context"]=market; r["databento"]=dbento; r["session"]=sess
    r["context_status"]={"macro":macro.get("status","UNKNOWN"),"news":news.get("status","UNKNOWN"),"market":market.get("status","UNKNOWN"),"databento":dbento.get("status","UNKNOWN")}
    bar=frame(p,"1m") or frame(p,"1h") or {}
    with db() as c:
        if bar:
            _v791_evaluate_predictions(c,ts_ms,float(bar.get("h",r["price"])),float(bar.get("l",r["price"])),float(bar.get("c",r["price"])))
        raw_prob=_qualification_probability(r)
        cal_prob,cal_n,cal_bucket=_v791_calibration(c,raw_prob)
        r["probability_raw"]=round(raw_prob,1)
        r["calibrated_probability"]=cal_prob
        r["calibration_samples"]=cal_n
        r["calibration_bucket"]=cal_bucket
        r["learning_integrity"]="V7.9.1_CLEAN_ONLY"
        settings=get_settings(c)
        r["prediction_definition"]=f"{float(settings['prediction_target_points']):.0f}pt target before {float(settings['prediction_stop_points']):.0f}pt stop within {int(settings['prediction_horizon_minutes'])} min"
        _apply_execution_targets(r)
        update_trades(c,p,r)
        state_result=update_signal_state(c,r)
        _v791_maybe_record_prediction(c,r,state_result,sess,dbento,ts_ms)
        c.execute("INSERT INTO snapshots(received_at,symbol,raw_json,result_json) VALUES(?,?,?,?)",(now(),r["symbol"],json.dumps(p),json.dumps(r)))
        c.commit()
    return {"ok":True,"result":r}

@app.post("/webhook/tradingview")
async def webhook(request:Request): return await ingest(request,None)
@app.post("/webhook/tradingview/{secret}")
async def webhook_secret(secret:str,request:Request): return await ingest(request,secret)

@app.get("/health")
def health(): return {"ok":True,"service":"US30 Signal Lab V7.9.1 Learning Integrity + State Gate","databento":get_databento_snapshot().get("status")}

def latest_rows(c):
    return (c.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1").fetchone(),
            c.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY id DESC LIMIT 1").fetchone())

@app.get("/api/latest")
def latest():
    with db() as c: row,trade=latest_rows(c)
    received=row["received_at"] if row else None; age=None
    if received:
        try: age=max(0,int((datetime.now(timezone.utc)-datetime.fromisoformat(received)).total_seconds()))
        except Exception: age=None
    feed_status="OFFLINE" if age is None or age>240 else "STALE" if age>90 else "LIVE"
    data=json.loads(row["result_json"]) if row else None; td=dict(trade) if trade else None
    th=trade_health(td,data) if td and data else None
    current_db=get_databento_snapshot(); current_session=session_context()
    if data:
        data["databento_live"]=current_db; data["session_live"]=current_session
    with db() as c2:
        settings=get_settings(c2)
    return {"ok":True,"data":data,"received_at":received,"feed_status":feed_status,"feed_age_seconds":age,"open_trade":td,"trade_health":th,"settings":settings,"databento":current_db,"session":current_session}

@app.get("/api/history")
def history(limit:int=80):
    limit=max(10,min(limit,240))
    with db() as c: rows=c.execute("SELECT received_at,result_json FROM snapshots ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    pts=[]
    for row in reversed(rows):
        try:
            r=json.loads(row["result_json"]); pts.append({"t":row["received_at"],"price":float(r.get("price",0)),"conviction":int(r.get("conviction",0))})
        except Exception: pass
    return {"ok":True,"items":pts}

@app.post("/api/trade/start-current")
def start_current_trade():
    with db() as c:
        row,existing=latest_rows(c)
        if existing: raise HTTPException(409,"an active trade is already being tracked")
        if not row: raise HTTPException(409,"no live market snapshot yet")
        r=json.loads(row["result_json"]); side=str(r.get("public_direction","NONE"))
        if str(r.get("trade_state","WATCHING")) != "ENTRY_READY" or side not in ("LONG","SHORT"):
            raise HTTPException(409,"trade tracking can only start when V7.9.1 is ENTRY READY")
        entry=float(r["price"])
        risk=max(float(r.get("execution_stop_points",50.0)),1.0)
        stop=entry-risk if side=="LONG" else entry+risk
        structural_stop=float(r.get("structural_stop") or stop)
        c.execute("""INSERT INTO trades(opened_at,opened_ts,symbol,side,entry,stop,structural_stop,tp1_low,tp1_high,tp2_low,tp2_high,risk,last_health)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (now(),r.get("ts"),r.get("symbol","US30"),side,entry,stop,structural_stop,
                   r["tp1_low"],r["tp1_high"],r["tp2_low"],r["tp2_high"],risk,70))
        trade_id=c.execute("SELECT last_insert_rowid()").fetchone()[0]
        _notify_once(c, f"trade:{trade_id}:started", "TRACKING_STARTED",
                       f"US30 {side} TRADE MONITORING ACTIVE",
                       f"Entry {entry:.1f} · Execution stop {stop:.1f} ({risk:.0f} pts)\\n"
                       f"Structural invalidation {structural_stop:.1f}\\n"
                       f"TP1 {r['tp1_low']}–{r['tp1_high']} · TP2 {r['tp2_low']}–{r['tp2_high']}\\n"
                       f"All R and danger calculations now use the {risk:.0f}-point execution stop.",
                       3, 100000, entry)
        c.commit()
    return {"ok":True,"side":side,"entry":entry,"execution_stop":stop,"risk_points":risk,"structural_stop":structural_stop}

@app.post("/api/trade/close-current")
def close_current_trade():
    with db() as c:
        row,trade=latest_rows(c)
        if not trade: raise HTTPException(409,"no active trade")
        r=json.loads(row["result_json"]) if row else {}; price=float(r.get("price",trade["entry"]))
        c.execute("UPDATE trades SET status='CLOSED',closed_at=?,close_reason='MANUAL',close_price=? WHERE id=?",(now(),price,trade["id"]))
        _notify_once(c, f"trade:{trade['id']}:manual-close", "TRACKING_CLOSED",
                       f"US30 {trade['side']} TRADE TRACKING CLOSED",
                       f"V7 tracking closed at {price:.1f}.", 3, 100000, price); c.commit()
    return {"ok":True,"close_price":price}

@app.get("/api/notifications/status")
def notifications_status():
    return {"ok": True, **notification_status()}

@app.post("/api/notifications/test")
def notifications_test():
    st = notification_status()
    if not st.get("configured"):
        raise HTTPException(409, "No phone notification channel configured. Set NTFY_TOPIC or Telegram variables in Railway.")
    result = send("US30 V7.9.1 PHONE TEST", "Phone notifications are connected. Automatic V7 alerts remain quiet until a meaningful setup or active-trade risk event.", 3)
    return {"ok": bool(result.get("ok")), **result}

@app.get("/api/databento/status")
def databento_status():
    return {"ok":True, **get_databento_snapshot()}

@app.get("/api/learning/performance")
def learning_perf():
    with db() as c:
        return {"ok":True, **_v791_performance(c)}

@app.get("/api/settings")
def settings_get():
    with db() as c:
        return {"ok":True,"settings":get_settings(c)}

@app.post("/api/settings")
async def settings_set(request:Request):
    body=await request.json()
    if not isinstance(body,dict): raise HTTPException(422,"expected settings object")
    with db() as c:
        settings=update_settings(c,body); c.commit()
    return {"ok":True,"settings":settings}

@app.post("/api/refresh-context")
def refresh_context(): return {"ok":True,"macro":get_macro(True),"news":get_news(True),"market":get_market(True)}

HTML=r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#050711"><title>US30 V7.9 Adaptive</title>
<style>
:root{--panel:rgba(5,13,28,.90);--panel2:rgba(8,20,39,.93);--line:rgba(142,73,255,.36);--text:#f2f5ff;--muted:#9aa9c4;--purple:#ae62ff;--pink:#ff3c79;--cyan:#27d7ff;--green:#34ec83;--red:#ff465d;--orange:#ff963b;--yellow:#f6d65c}
*{box-sizing:border-box}body{margin:0;background:#02040a;color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif}body:before{content:"";position:fixed;inset:0;z-index:-2;background:url('/assets/v7_mushroom_background.jpg') center/cover fixed no-repeat;filter:saturate(2.1) contrast(1.18) brightness(1.12)}body:after{content:"";position:fixed;inset:0;z-index:-1;background:linear-gradient(90deg,rgba(1,3,9,.08),rgba(1,4,13,.70) 27%,rgba(1,4,13,.80) 50%,rgba(1,4,13,.70) 73%,rgba(1,3,9,.08))}
.wrap{max-width:1500px;margin:auto;padding:12px 14px 70px}.top{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;padding:9px 12px;background:rgba(2,6,15,.76);border:1px solid rgba(133,73,255,.28);border-radius:16px}.brand{font-size:26px;font-weight:950}.sub{font-size:11px;color:#a9b3c9;letter-spacing:1px}.pill{display:flex;align-items:center;gap:7px;padding:8px 12px;border:1px solid rgba(122,137,255,.24);background:rgba(3,12,25,.84);border-radius:999px;font-size:12px;font-weight:850}.dot{width:9px;height:9px;border-radius:50%;background:var(--red);box-shadow:0 0 14px var(--red)}.live .dot{background:var(--green);box-shadow:0 0 14px var(--green)}.stale .dot{background:var(--yellow);box-shadow:0 0 14px var(--yellow)}
.card{border:1px solid var(--line);background:linear-gradient(145deg,var(--panel2),var(--panel));backdrop-filter:blur(10px);border-radius:15px;padding:14px;box-shadow:0 12px 38px rgba(0,0,0,.28)}.hero{margin-top:10px;text-align:center;padding:16px;border:1px solid var(--line);border-radius:18px;background:rgba(4,10,23,.79)}.hero h1{font-size:39px;margin:0 0 9px;font-weight:950}.long{color:var(--green)}.short{color:var(--pink)}.factors{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;max-width:980px;margin:auto}.factor{padding:10px;border:1px solid rgba(130,100,255,.28);border-radius:10px;background:rgba(5,13,28,.78)}.factor .n{font-size:22px;font-weight:950}.healthbar{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;max-width:940px;margin:10px auto 0}.healthitem{padding:8px;border:1px solid rgba(79,117,150,.30);border-radius:10px;background:rgba(4,14,26,.75);font-size:12px}
.grid5{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:10px}.grid3{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:10px}.settingsGrid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.field label{display:block;color:#aab6cd;font-size:11px;margin-bottom:5px}.field input{width:100%;background:#081528;border:1px solid rgba(130,100,255,.35);color:#fff;border-radius:9px;padding:10px;font-size:16px}.label{font-size:12px;color:#aab6cd;text-transform:uppercase;letter-spacing:.5px}.value{font-size:29px;font-weight:950;margin-top:7px}.green{color:var(--green)}.red{color:var(--red)}.cyan{color:var(--cyan)}.purple{color:var(--purple)}.orange{color:var(--orange)}.muted{color:var(--muted)}
.main{display:grid;grid-template-columns:1.2fr .92fr .95fr;gap:10px;margin-top:10px}.sectionTitle{font-size:15px;font-weight:900;margin-bottom:12px}.tradezone{border:1px solid rgba(42,232,132,.32);background:rgba(4,39,32,.55);border-radius:11px;padding:12px;margin-bottom:10px}.stopzone{border-color:rgba(255,70,93,.35);background:rgba(45,8,18,.52)}.targets{display:grid;grid-template-columns:1fr 1fr;gap:8px}.bigval{font-size:22px;font-weight:900}.row{display:flex;justify-content:space-between;gap:12px;padding:6px 0;border-bottom:1px solid rgba(122,140,180,.12);font-size:13px}.reason{display:grid;grid-template-columns:45px 1fr;gap:8px;padding:4px 0;font-size:12px}.tag{border:1px solid rgba(126,82,255,.45);border-radius:6px;padding:2px 6px;text-align:center;color:#cfb6ff;font-weight:850}.btn{width:100%;border:1px solid rgba(53,237,132,.48);background:rgba(7,55,35,.65);color:#63f4a6;font-weight:950;padding:12px;border-radius:10px;cursor:pointer}.btn.close{border-color:rgba(255,70,93,.5);background:rgba(55,7,17,.64);color:#ff6275}.lower{display:grid;grid-template-columns:1.15fr .7fr 1.1fr;gap:10px;margin-top:10px}.chart{height:190px;width:100%}.srcrow{display:grid;grid-template-columns:1fr auto auto;gap:8px;padding:7px 0;border-bottom:1px solid rgba(132,142,180,.10);font-size:12px}.fresh{color:var(--green)}.unavailable{color:var(--red)}.staletxt{color:var(--yellow)}.progress{height:12px;border-radius:10px;background:linear-gradient(90deg,#8d1320 0 23%,#f04928 23% 32%,#bdd13c 45%,#24e56e 75%);margin:16px 3px}.nav{margin-top:10px;display:grid;grid-template-columns:repeat(6,1fr);gap:6px;padding:7px;background:rgba(3,7,17,.90);border:1px solid rgba(121,76,255,.28);border-radius:14px}.nav div{border:1px solid rgba(120,92,255,.26);border-radius:10px;padding:10px;text-align:center;font-size:11px}.foot{text-align:center;color:#8796b0;font-size:11px;margin-top:12px}
@media(max-width:980px){.top{grid-template-columns:1fr}.grid5,.grid3{grid-template-columns:repeat(2,1fr)}.main,.lower{grid-template-columns:1fr}.factors{grid-template-columns:repeat(2,1fr)}.nav{grid-template-columns:repeat(3,1fr)}}@media(max-width:520px){.wrap{padding:8px}.grid3{grid-template-columns:1fr}.brand{font-size:20px}.hero h1{font-size:30px}.value{font-size:24px}.healthbar{grid-template-columns:1fr}.targets{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<div class="top"><div><div class="brand">⚗ US30 SIGNAL LAB <span class="purple">V7.9</span> · SWING</div><div class="sub">PREMIUM MULTI-FRAME INTELLIGENCE</div></div><div id="conn" class="pill"><span class="dot"></span><span id="connText">OFFLINE</span><span id="age" class="muted"></span></div><div id="clock" class="muted"></div></div>
<div class="hero"><h1 id="headline">WATCHING</h1><div class="factors"><div class="factor"><small>SWING BIAS</small><div id="bias" class="n">—</div></div><div class="factor"><small>ENTRY TIMING</small><div id="timing" class="n">—</div></div><div class="factor"><small>TECHNICAL</small><div id="tech" class="n">—</div></div><div class="factor"><small>MACRO</small><div id="macro" class="n">—</div></div><div class="factor"><small>INTERMARKET</small><div id="inter" class="n">—</div></div><div class="factor"><small>NEWS</small><div id="news" class="n">—</div></div></div><div class="healthbar"><div class="healthitem">SOURCE STATUS <b id="sourceHealth">Waiting</b></div><div class="healthitem">DATA QUALITY <b id="dataQuality">Waiting</b></div><div class="healthitem">MODEL HEALTH <b>Nominal</b></div><div class="healthitem">PHONE ALERTS <b id="phoneStatus">Checking</b></div></div></div>
<div class="grid5"><div class="card"><div class="label">Regime</div><div id="regime" class="value">—</div></div><div class="card"><div class="label">Conviction</div><div id="conv" class="value cyan">—</div></div><div class="card"><div class="label">Big move probability</div><div id="big" class="value purple">—</div></div><div class="card"><div class="label">Price</div><div id="price" class="value">—</div></div><div class="card"><div class="label">State</div><div id="tradeState" class="value">WATCHING</div><div id="tradeSide" class="muted">—</div></div></div>
<div class="grid3"><div class="card"><div class="label">Calibrated probability</div><div id="calProb" class="value cyan">LEARNING</div><div id="calMeta" class="muted">Building prediction history</div></div><div class="card"><div class="label">HTF swing zone</div><div id="zoneName" class="value" style="font-size:18px">SCANNING</div><div id="zoneMeta" class="muted">D/W/M + old ATH references</div></div><div class="card"><div class="label">Databento YM L2</div><div id="dbScore" class="value">—</div><div id="dbMeta" class="muted">Waiting for live book</div></div><div class="card"><div class="label">Market session</div><div id="sessionName" class="value" style="font-size:20px">—</div><div id="sessionMeta" class="muted">Session-aware volatility control</div></div></div>
<div class="main">
<div class="card"><div class="sectionTitle">⌖ TRADE MAP</div><div class="tradezone"><div class="label">Entry zone</div><div id="entry" class="bigval green">—</div><div id="enteredAt" class="muted"></div></div><div class="targets"><div class="tradezone stopzone"><div class="label">Execution stop</div><div id="stop" class="bigval red">—</div><div id="riskText" class="muted"></div><div class="label" style="margin-top:8px">Structural invalidation</div><div id="structStop" class="bigval" style="font-size:17px">—</div></div><div><div class="tradezone"><div class="label">TP1</div><div id="tp1" class="bigval">—</div></div><div class="tradezone"><div class="label">TP2</div><div id="tp2" class="bigval">—</div></div></div></div><div id="swingObjectives" class="muted" style="margin:8px 0 12px">Structural swing objectives: —</div><div class="label">Position progress</div><div class="progress"></div></div>
<div class="card"><div class="sectionTitle">ACTIVE TRADE</div><div id="tradeDetails" class="muted">No active trade is being tracked.</div><button id="tradeBtn" class="btn" style="margin-top:12px">I'M IN THIS TRADE — START TRACKING</button></div>
<div class="card"><div class="sectionTitle">WHAT CHANGED / REASONS</div><div id="reasons" class="muted">Waiting…</div></div>
</div>
<div class="lower"><div class="card"><div class="sectionTitle">PRICE ACTION · STORED LIVE SNAPSHOTS</div><canvas id="chart" class="chart"></canvas></div><div class="card"><div class="sectionTitle">TECHNICAL HEALTH</div><div id="healthGauge" class="value green" style="text-align:center;font-size:44px">—</div><div id="frameGrid"></div></div><div class="card"><div class="sectionTitle">INFORMATION SOURCES</div><div id="sources"></div><button id="refreshBtn" class="btn" style="margin-top:12px">REFRESH FREE CONTEXT SOURCES</button><button id="phoneTestBtn" class="btn" style="margin-top:8px">TEST PHONE NOTIFICATION</button></div></div>
<div class="card" style="margin-top:10px"><div class="sectionTitle">HTF SWING ZONE MAP · DAILY / WEEKLY / MONTHLY / OLD ATH</div><div id="zoneDetails" class="muted">Waiting for higher-timeframe references…</div></div>
<div class="card" style="margin-top:10px"><div class="sectionTitle">INTERMARKET / MACRO / NEWS DETAIL</div><div id="contextDetails" class="muted">Waiting…</div></div>
<div class="lower"><div class="card"><div class="sectionTitle">SELF-TEST PERFORMANCE · PREDICTION EQUITY</div><canvas id="perfChart" class="chart"></canvas><div id="perfDefinition" class="muted" style="font-size:11px"></div></div><div class="card"><div class="sectionTitle">LEARNING STATS</div><div id="perfStats" class="muted">No resolved predictions yet.</div></div><div class="card"><div class="sectionTitle">PERSONAL ALERT SETTINGS</div><div class="settingsGrid"><div class="field"><label>Setup warning probability %</label><input id="setupPct" type="number" min="50" max="99.9" step="0.1"></div><div class="field"><label>Perfect entry probability %</label><input id="perfectPct" type="number" min="50" max="99.9" step="0.1"></div><div class="field"><label>Self-test target points</label><input id="predTarget" type="number" min="10" max="2000" step="10"></div><div class="field"><label>Prediction horizon minutes</label><input id="predHorizon" type="number" min="30" max="10080" step="30"></div><div class="field"><label>Require HTF zone for Perfect Entry</label><input id="requireZone" type="checkbox" style="width:auto"></div></div><button id="saveSettingsBtn" class="btn" style="margin-top:10px">SAVE ALERT / LEARNING SETTINGS</button><div id="settingsNote" class="muted" style="margin-top:8px;font-size:11px">Perfect Entry uses calibrated probability only after enough resolved predictions exist.</div></div></div>
<div class="nav"><div>DASHBOARD<br><span class="muted">Overview</span></div><div>TRADE<br><span class="muted">Management</span></div><div>TECHNICAL<br><span class="muted">Breakdown</span></div><div>MACRO<br><span class="muted">Overview</span></div><div>NEWS<br><span class="muted">Headlines</span></div><div>PERFORMANCE<br><span class="muted">Self-test</span></div></div><div class="foot">US30 Signal Lab V7.9.1 Swing · Learning-integrity gate · Decision support only</div></div>
<script>
const $=x=>document.getElementById(x);let latest=null;const fmt=(x,d=1)=>Number.isFinite(Number(x))?Number(x).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d}):'—';const signed=v=>v==null?'N/A':((Number(v)>0?'+':'')+Number(v).toFixed(3));const col=v=>Number(v)>0?'green':Number(v)<0?'red':'muted';
function setConn(s,a){$('conn').className='pill '+String(s||'offline').toLowerCase();$('connText').textContent=s||'OFFLINE';$('age').textContent=a==null?'':'· '+(a<60?a+'s ago':Math.floor(a/60)+'m ago')}
function reasons(d){$('reasons').innerHTML=(d.reasons||[]).map(x=>{let p=String(x).split(':');let t=p.length>1?p.shift():'•';return `<div class="reason"><span class="tag">${t}</span><span>${p.join(':').trim()||x}</span></div>`}).join('')}
function frames(d){$('frameGrid').innerHTML=(d.frames||[]).filter(x=>['1M','1W','1D','4h','1h','1m'].includes(x.tf)).map(x=>`<div class="row"><span>${x.tf}</span><span class="${col(x.score)}">${signed(x.score)} · ADX ${fmt(x.adx,0)}</span></div>`).join('')}
function ftime(x){if(!x)return'';try{return new Date(x).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})}catch(e){return''}}function sources(d,j){let ma=d.macro||{},mk=d.market_context||{},nw=d.news||{},db=j.databento||{};let a=[['TradingView US30',j.feed_status,j.feed_age_seconds==null?'':j.feed_age_seconds+'s'],['Databento YM L2',db.status||'NOT_CONFIGURED',db.age_seconds==null?'':db.age_seconds+'s'],[ma.source||'FRED',ma.status||'UNAVAILABLE',(ma.quality||'')+' '+ftime(ma.fetched_at)],[mk.source||'Yahoo Finance',mk.status||'UNAVAILABLE',ftime(mk.fetched_at)],[nw.source||'GDELT',nw.status||'UNAVAILABLE',ftime(nw.fetched_at)],['Railway V7 engine','ONLINE','now']];$('sources').innerHTML=a.map(x=>`<div class="srcrow"><span>${x[0]}</span><b class="${['LIVE','ONLINE','NO_FRESH_MATCHES','FALLBACK_LIVE'].includes(String(x[1]).toUpperCase())?'fresh':String(x[1]).toUpperCase().includes('STALE')?'staletxt':'unavailable'}">${x[1]}</b><span class="muted">${x[2]}</span></div>`).join('');$('sourceHealth').textContent=a.filter(x=>['LIVE','ONLINE','NO_FRESH_MATCHES','FALLBACK_LIVE'].includes(String(x[1]).toUpperCase())).length>=5?'Operational':'Partial';$('dataQuality').textContent=j.feed_status==='LIVE'?'Fresh':'Check feed'}
function context(d){let im=d.market_context?.values||{},mac=d.macro?.series||{},nw=d.news?.items||[];$('contextDetails').innerHTML=`<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px"><div><b>Intermarket</b>${Object.entries(im).map(([k,v])=>`<div class="row"><span>${k}</span><span class="${col(v)}">${signed(v)}</span></div>`).join('')||'<p>Unavailable</p>'}</div><div><b>Macro · ${(d.macro||{}).status||'UNAVAILABLE'} · ${(d.macro||{}).quality||'NONE'}</b>${Object.entries(mac).map(([k,v])=>`<div class="row"><span>${k.toUpperCase()}</span><span>${fmt(v.value,3)} · ${v.date}</span></div>`).join('')||'<p>Unavailable</p>'}</div><div><b>Fresh news</b>${nw.slice(0,6).map(n=>`<div class="row"><span>${n.title}</span><span>${n.age_hours==null?'':n.age_hours+'h'}</span></div>`).join('')||'<p>No fresh matches</p>'}</div></div>`}
function trade(j,d){let t=j.open_trade,h=j.trade_health,st=d.trade_state||'WATCHING',pub=d.public_direction||'NONE';if(!t){$('tradeState').textContent=st;$('tradeSide').textContent=st==='ENTRY_READY'?pub:'NO TRADE';if(st==='ENTRY_READY'){$('tradeDetails').innerHTML='A qualified trade setup is ready.<br><span class="muted">Only start tracking after you have actually entered the trade.</span>';$('tradeBtn').style.display='block';$('tradeBtn').disabled=false;$('tradeBtn').textContent="I'M IN THIS TRADE — START TRACKING";$('tradeBtn').className='btn'}else{$('tradeDetails').innerHTML='No trade is ready.<br><span class="muted">V7 is analysing direction internally. LONG/SHORT remains hidden until all ENTRY READY conditions are satisfied.</span>';$('tradeBtn').style.display='none'}$('enteredAt').textContent='';$('healthGauge').textContent=d.conviction+'%';return}let s=t.side==='LONG'?1:-1,p=s*(Number(d.price)-Number(t.entry)),pr=p/Math.max(Number(t.risk),1);$('tradeState').textContent='IN TRADE';$('tradeSide').textContent=t.side;$('enteredAt').textContent='Entered '+fmt(t.entry)+' · '+new Date(t.opened_at).toLocaleString();$('healthGauge').textContent=(h?h.health:t.last_health)+'/100';$('tradeDetails').innerHTML=[['Status','IN TRADE'],['Direction',t.side],['Entry',fmt(t.entry)],['Current',fmt(d.price)],['Unrealized P/L',(p>=0?'+':'')+fmt(p)+' pts · '+pr.toFixed(2)+'R'],['Execution stop',fmt(t.stop)+' · '+fmt(t.risk,0)+' pts'],['Structural invalidation',fmt(t.structural_stop)],['Trade health',(h?h.health:t.last_health)+'/100'],['Action',h?h.action:'HOLD'],['MFE',Number(t.max_mfe_r).toFixed(2)+'R'],['MAE',Number(t.max_mae_r).toFixed(2)+'R']].map(x=>`<div class="row"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('');$('tradeBtn').style.display='block';$('tradeBtn').disabled=false;$('tradeBtn').textContent='CLOSE ACTIVE TRADE';$('tradeBtn').className='btn close'}
function chart(points){let c=$('chart'),q=c.getContext('2d'),r=c.getBoundingClientRect(),d=window.devicePixelRatio||1;c.width=r.width*d;c.height=r.height*d;q.scale(d,d);q.clearRect(0,0,r.width,r.height);if(points.length<2){q.fillStyle='#9aa9c4';q.fillText('Waiting for history…',10,20);return}let v=points.map(x=>Number(x.price)),mn=Math.min(...v),mx=Math.max(...v),sp=Math.max(mx-mn,1);q.strokeStyle='rgba(74,210,255,.16)';for(let i=1;i<5;i++){q.beginPath();q.moveTo(0,r.height*i/5);q.lineTo(r.width,r.height*i/5);q.stroke()}q.strokeStyle='#34ec83';q.lineWidth=2;q.beginPath();points.forEach((p,i)=>{let x=i/(points.length-1)*(r.width-8)+4,y=r.height-10-(Number(p.price)-mn)/sp*(r.height-24);i?q.lineTo(x,y):q.moveTo(x,y)});q.stroke()}
function perfChart(points){let c=$('perfChart'),q=c.getContext('2d'),r=c.getBoundingClientRect(),d=window.devicePixelRatio||1;c.width=r.width*d;c.height=r.height*d;q.scale(d,d);q.clearRect(0,0,r.width,r.height);if(!points.length){q.fillStyle='#9aa9c4';q.fillText('Learning — no resolved predictions yet',10,20);return}let v=points.map(x=>Number(x.r)),mn=Math.min(0,...v),mx=Math.max(0,...v),sp=Math.max(mx-mn,1);q.strokeStyle='rgba(174,98,255,.18)';for(let i=1;i<5;i++){q.beginPath();q.moveTo(0,r.height*i/5);q.lineTo(r.width,r.height*i/5);q.stroke()}q.strokeStyle='#ae62ff';q.lineWidth=2;q.beginPath();points.forEach((p,i)=>{let x=i/Math.max(points.length-1,1)*(r.width-8)+4,y=r.height-10-(Number(p.r)-mn)/sp*(r.height-24);i?q.lineTo(x,y):q.moveTo(x,y)});q.stroke();q.fillStyle='#f2f5ff';q.fillText('Cumulative '+Number(points[points.length-1].r).toFixed(2)+'R',8,16)}
function perfRender(p){$('perfDefinition').textContent=p.definition||'';let z=(p.zones||[]).slice(0,6).map(x=>'<div class="row"><span>Zone '+x.zone_type+'</span><b>'+x.win_rate+'% · n='+x.n+'</b></div>').join('');$('perfStats').innerHTML=[['Predictions',p.total_predictions],['Resolved',p.resolved],['Barrier samples',p.barrier_samples],['Target-before-stop win rate',p.barrier_win_rate==null?'LEARNING':p.barrier_win_rate+'%'],['Directional accuracy',p.directional_accuracy==null?'LEARNING':p.directional_accuracy+'%'],['Cumulative simulated R',fmt(p.cumulative_r,2)+'R'],['Primary Brier',p.primary_brier==null?'—':p.primary_brier],['Challenger Brier',p.challenger_brier==null?'—':p.challenger_brier],['Ambiguous bars excluded',p.ambiguous_excluded||0]].map(x=>`<div class="row"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('')+z;perfChart(p.curve||[])}
function renderAdaptive(d,j){let db=j.databento||d.databento_live||{},ss=j.session||d.session_live||d.session||{},z=d.htf_zones||{},bz=z.best_zone||{};$('zoneName').textContent=bz.label||'NO ACTIVE ZONE';$('zoneName').className='value '+(z.high_quality_zone?'green':z.zone_confirmed?'cyan':'orange');$('zoneMeta').textContent=(bz.location||'')+(bz.distance_points!=null?' · '+fmt(bz.distance_points,0)+' pts':'')+' · confluence '+(z.confluence_count||0)+' · raw adj '+fmt(z.probability_adjustment,1)+'%';$('zoneDetails').innerHTML=(z.near_zones||[]).slice(0,10).map(q=>`<div class="row"><span>${q.label}<br><span class="muted">${q.side} · ${q.source}</span></span><b class="${q.aligned?'green':q.opposing?'red':'muted'}">${fmt(q.low)}–${fmt(q.high)} · ${fmt(q.distance_points,0)} pts</b></div>`).join('')||'<span class="muted">No major HTF zone currently nearby.</span>';if(d.calibrated_probability==null){$('calProb').textContent='LEARNING';$('calMeta').textContent=(d.calibration_samples||0)+' samples in '+(d.calibration_bucket||'current')+' bucket'}else{$('calProb').textContent=fmt(d.calibrated_probability,1)+'%';$('calMeta').textContent='Clean calibration: '+(d.calibration_samples||0)+' samples · qualification '+fmt(d.probability_raw,1)+'%'}$('dbScore').textContent=signed(db.score);$('dbScore').className='value '+col(db.score);$('dbMeta').textContent=(db.status||'NOT_CONFIGURED')+' · imbalance5 '+fmt(db.book_imbalance_5,2)+' · trade pressure '+fmt(db.trade_pressure,2);$('sessionName').textContent=ss.name||'—';$('sessionName').className='value '+((ss.risk==='EXTREME'||ss.risk==='CLOSED')?'red':ss.risk==='HIGH'?'orange':'green');$('sessionMeta').textContent=(ss.risk||'')+' · '+(ss.note||'')}
let settingsLoaded=false;function renderSettings(st){if(settingsLoaded)return;$('setupPct').value=st.setup_notify_probability;$('perfectPct').value=st.perfect_notify_probability;$('predTarget').value=st.prediction_target_points;$('predHorizon').value=st.prediction_horizon_minutes;$('requireZone').checked=st.require_htf_zone_for_perfect!==false;settingsLoaded=true}
async function load(){try{let [a,b,nf,pf,sf]=await Promise.all([fetch('/api/latest',{cache:'no-store'}),fetch('/api/history?limit=90',{cache:'no-store'}),fetch('/api/notifications/status',{cache:'no-store'}),fetch('/api/learning/performance',{cache:'no-store'}),fetch('/api/settings',{cache:'no-store'})]);let j=await a.json(),d=j.data;let ns=await nf.json(),perf=await pf.json(),st=(await sf.json()).settings||{};$('phoneStatus').textContent=ns.configured?('CONNECTED · '+ns.channels.join('+').toUpperCase()):'NOT CONFIGURED';$('phoneStatus').className=ns.configured?'green':'orange';latest=j;setConn(j.feed_status,j.feed_age_seconds);renderSettings(st);perfRender(perf);if(!d)return;let active=!!j.open_trade,st=d.trade_state||'WATCHING',side=active?j.open_trade.side:(d.public_direction||'NONE');if(active){$('headline').innerHTML='ACTIVE TRADE · <span class="'+(side==='LONG'?'long':'short')+'">'+side+'</span>'}else if(st==='ENTRY_READY'&&(side==='LONG'||side==='SHORT')){$('headline').innerHTML='ENTRY READY · <span class="'+(side==='LONG'?'long':'short')+'">'+side+'</span>'}else if(st==='SETUP_FORMING'){$('headline').innerHTML='SETUP FORMING · <span class="muted">NO TRADE YET</span>'}else{$('headline').innerHTML='WATCHING · <span class="muted">NO TRADE</span>'};$('bias').textContent=d.bias_label+' '+signed(d.bias_score);$('bias').className='n '+col(d.bias_score);$('timing').textContent=d.timing_label+' '+signed(d.timing_score);$('timing').className='n '+(d.timing_aligned?'green':'orange');[['tech',d.technical_score],['macro',d.macro_score],['inter',d.intermarket_score],['news',d.news_score]].forEach(([i,v])=>{$(i).textContent=signed(v);$(i).className='n '+(v==null?'orange':col(v))});if(d.macro_score==null){$('macro').textContent='N/A · '+(d.macro_status||'UNAVAILABLE')}$('regime').textContent=d.regime.replace('_',' ');$('regime').className='value '+(d.regime.includes('BULL')?'green':d.regime.includes('BEAR')?'red':'purple');$('conv').textContent=d.conviction+'%';$('big').textContent=d.big_move_probability+'%';$('price').textContent=fmt(d.price);$('entry').textContent=fmt(d.entry_low)+' – '+fmt(d.entry_high);$('stop').textContent=fmt(d.execution_stop);$('structStop').textContent=fmt(d.structural_stop);$('tp1').textContent=fmt(d.tp1_low)+' – '+fmt(d.tp1_high);$('tp2').textContent=fmt(d.tp2_low)+' – '+fmt(d.tp2_high);$('swingObjectives').textContent=(d.swing_tp1_low!=null?'Structural swing objectives (context only): '+fmt(d.swing_tp1_low)+'–'+fmt(d.swing_tp1_high)+' / '+fmt(d.swing_tp2_low)+'–'+fmt(d.swing_tp2_high):'Structural swing objectives: —');$('riskText').textContent='Execution risk '+fmt(d.execution_stop_points,0)+' pts · TP1 '+fmt(d.rr_tp1_low,1)+'–'+fmt(d.rr_tp1_high,1)+'R · TP2 '+fmt(d.rr_tp2_low,1)+'–'+fmt(d.rr_tp2_high,1)+'R';reasons(d);frames(d);sources(d,j);context(d);trade(j,d);renderAdaptive(d,j);chart((await b.json()).items||[])}catch(e){setConn('OFFLINE',null)}}
$('tradeBtn').onclick=async()=>{let u=latest&&latest.open_trade?'/api/trade/close-current':'/api/trade/start-current';let r=await fetch(u,{method:'POST'}),j=await r.json();if(!r.ok){alert(j.detail||'Unable to change tracking');return}load()};$('refreshBtn').onclick=async()=>{await fetch('/api/refresh-context',{method:'POST'});load()};$('phoneTestBtn').onclick=async()=>{let r=await fetch('/api/notifications/test',{method:'POST'}),j=await r.json();if(!r.ok){alert(j.detail||'Phone notification test failed');return}alert('Test notification sent');load()};$('saveSettingsBtn').onclick=async()=>{let body={setup_notify_probability:Number($('setupPct').value),perfect_notify_probability:Number($('perfectPct').value),prediction_target_points:Number($('predTarget').value),prediction_horizon_minutes:Number($('predHorizon').value),require_htf_zone_for_perfect:$('requireZone').checked};let r=await fetch('/api/settings',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)}),j=await r.json();if(!r.ok){alert(j.detail||'Unable to save settings');return}$('settingsNote').textContent='Saved · setup '+j.settings.setup_notify_probability+'% · perfect '+j.settings.perfect_notify_probability+'%';settingsLoaded=false;load()};setInterval(()=>{$('clock').textContent=new Date().toLocaleString('en-GB',{timeZone:'Europe/London'})+' UK'},1000);load();setInterval(load,5000);addEventListener('resize',load);
</script></body></html>'''

@app.get("/",response_class=HTMLResponse)
def index(): return HTML
@app.get("/assets/v7_mushroom_background.jpg")
def bg(): return FileResponse(BASE/"v7_mushroom_background.jpg",media_type="image/jpeg")
@app.get("/manifest.webmanifest")
def manifest(): return {"name":"US30 V7.9 Adaptive","short_name":"US30 V7.9","start_url":"/","display":"standalone","background_color":"#050711","theme_color":"#050711"}
@app.get("/sw.js")
def sw(): return Response("self.addEventListener('install',e=>self.skipWaiting());",media_type="application/javascript")
