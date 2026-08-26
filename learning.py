from __future__ import annotations
import json
import math
from datetime import datetime, timezone
from typing import Any

DEFAULT_SETTINGS = {
    'setup_notify_probability': 92.0,
    'perfect_notify_probability': 98.0,
    'prediction_target_points': 100.0,
    'prediction_stop_points': 50.0,
    'prediction_horizon_minutes': 480,
    'prediction_interval_minutes': 15,
    'min_calibration_samples': 20,
    'require_databento_for_perfect': True,
    'require_htf_zone_for_perfect': True,
}


def ensure_tables(c) -> None:
    c.executescript('''
    CREATE TABLE IF NOT EXISTS model_settings(
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS predictions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        created_ts_ms INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        entry_price REAL NOT NULL,
        target_points REAL NOT NULL,
        stop_points REAL NOT NULL,
        horizon_minutes INTEGER NOT NULL,
        raw_probability REAL NOT NULL,
        calibrated_probability REAL,
        calibration_samples INTEGER DEFAULT 0,
        challenger_probability REAL NOT NULL,
        bias_score REAL,
        timing_score REAL,
        databento_score REAL,
        intermarket_score REAL,
        macro_score REAL,
        session_name TEXT,
        session_risk TEXT,
        htf_zone_type TEXT,
        htf_zone_score REAL,
        htf_zone_confirmed INTEGER,
        htf_zone_distance REAL,
        htf_zone_confluence INTEGER,
        status TEXT NOT NULL DEFAULT 'OPEN',
        resolved_at TEXT,
        outcome TEXT,
        result_r REAL,
        direction_correct INTEGER,
        max_favourable_points REAL NOT NULL DEFAULT 0,
        max_adverse_points REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_predictions_open ON predictions(status, created_ts_ms);
    CREATE INDEX IF NOT EXISTS idx_predictions_resolved ON predictions(outcome, raw_probability);
    ''')
    cols={row["name"] for row in c.execute("PRAGMA table_info(predictions)").fetchall()}
    for name, sqltype in (
        ("htf_zone_type","TEXT"),("htf_zone_score","REAL"),("htf_zone_confirmed","INTEGER"),
        ("htf_zone_distance","REAL"),("htf_zone_confluence","INTEGER")
    ):
        if name not in cols:
            c.execute(f"ALTER TABLE predictions ADD COLUMN {name} {sqltype}")
    now = datetime.now(timezone.utc).isoformat()
    for k, v in DEFAULT_SETTINGS.items():
        c.execute('INSERT OR IGNORE INTO model_settings(key,value_json,updated_at) VALUES(?,?,?)', (k, json.dumps(v), now))


def get_settings(c) -> dict[str, Any]:
    ensure_tables(c)
    out = dict(DEFAULT_SETTINGS)
    for row in c.execute('SELECT key,value_json FROM model_settings').fetchall():
        try: out[row['key']] = json.loads(row['value_json'])
        except Exception: pass
    return out


def update_settings(c, values: dict[str, Any]) -> dict[str, Any]:
    allowed = set(DEFAULT_SETTINGS)
    now = datetime.now(timezone.utc).isoformat()
    for k, v in values.items():
        if k not in allowed:
            continue
        if k in ('setup_notify_probability','perfect_notify_probability'):
            v = max(50.0, min(99.9, float(v)))
        elif k in ('prediction_target_points','prediction_stop_points'):
            v = max(10.0, min(2000.0, float(v)))
        elif k in ('prediction_horizon_minutes','prediction_interval_minutes','min_calibration_samples'):
            v = int(max(1, min(10080, int(v))))
        elif k in ('require_databento_for_perfect','require_htf_zone_for_perfect'):
            v = bool(v)
        c.execute('''INSERT INTO model_settings(key,value_json,updated_at) VALUES(?,?,?)
                     ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
                  (k, json.dumps(v), now))
    return get_settings(c)


def _sign(direction: str) -> int:
    return 1 if direction == 'LONG' else -1 if direction == 'SHORT' else 0


def _bucket(prob: float) -> tuple[float,float]:
    lo = max(50.0, min(95.0, math.floor(prob/5.0)*5.0))
    return lo, lo+5.0


def calibrated_probability(c, raw_prob: float, direction: str, min_samples: int) -> dict[str, Any]:
    lo, hi = _bucket(raw_prob)
    rows = c.execute('''SELECT outcome FROM predictions
                        WHERE status='RESOLVED' AND outcome IN ('TARGET','STOP')
                        AND direction=? AND raw_probability>=? AND raw_probability<?''',
                     (direction, lo, hi)).fetchall()
    if len(rows) < min_samples:
        rows = c.execute('''SELECT outcome FROM predictions
                            WHERE status='RESOLVED' AND outcome IN ('TARGET','STOP')
                            AND raw_probability>=? AND raw_probability<?''', (lo, hi)).fetchall()
    n = len(rows); wins = sum(1 for r in rows if r['outcome']=='TARGET')
    if n < min_samples:
        return {'probability': None, 'samples': n, 'wins': wins, 'status': 'LEARNING', 'bucket': f'{int(lo)}–{int(hi)}'}
    # Beta(1,1) shrinkage prevents a small perfect sample from claiming 100%.
    p = 100.0 * (wins + 1.0) / (n + 2.0)
    return {'probability': round(p,1), 'samples': n, 'wins': wins, 'status': 'CALIBRATED', 'bucket': f'{int(lo)}–{int(hi)}'}


def challenger_probability(r: dict[str, Any], session: dict[str, Any], databento: dict[str, Any]) -> float:
    sign = _sign(str(r.get('direction','')))
    if not sign: return 50.0
    bias = sign * float(r.get('bias_score') or 0)
    timing = sign * float(r.get('timing_score') or 0)
    dbs = sign * float(databento.get('score') or 0)
    inter = sign * float(r.get('intermarket_score') or 0)
    macro = sign * float(r.get('macro_score') or 0)
    zone = float((r.get('htf_zones') or {}).get('zone_score') or 0)
    x = .29*bias + .23*timing + .19*dbs + .10*inter + .07*macro + .12*zone
    p = 50.0 + max(0.0, min(45.0, x * 9.0))
    p -= float(session.get('probability_penalty') or 0)
    return round(max(50.0, min(99.0, p)),1)


def apply_learning(c, r: dict[str, Any], session: dict[str, Any], databento: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings(c)
    raw = float(r.get('conviction') or 50.0)
    # Session volatility reduces entry probability, while live YM L2 can confirm/oppose it.
    sign = _sign(str(r.get('direction','')))
    db_score = float(databento.get('score') or 0)
    if databento.get('status') in ('LIVE','STALE') and sign:
        raw += max(-6.0, min(6.0, sign * db_score * 2.5))
    zone_ctx=r.get('htf_zones') or {}
    raw += max(-5.0,min(5.0,float(zone_ctx.get('probability_adjustment') or 0)))
    raw -= float(session.get('probability_penalty') or 0)
    raw = round(max(50.0, min(99.0, raw)),1)
    cal = calibrated_probability(c, raw, str(r.get('direction','')), int(settings['min_calibration_samples']))
    r['probability_raw'] = raw
    r['calibrated_probability'] = cal['probability']
    r['calibration_status'] = cal['status']
    r['calibration_samples'] = cal['samples']
    r['calibration_bucket'] = cal['bucket']
    r['challenger_probability'] = challenger_probability(r, session, databento)
    return r


def evaluate_predictions(c, ts_ms: int, high: float, low: float, close: float) -> int:
    settings = get_settings(c)
    rows = c.execute("SELECT * FROM predictions WHERE status='OPEN' ORDER BY id").fetchall()
    resolved = 0
    for row in rows:
        sign = _sign(row['direction']); entry=float(row['entry_price']); target=float(row['target_points']); stop=float(row['stop_points'])
        fav = (high-entry) if sign>0 else (entry-low)
        adv = (entry-low) if sign>0 else (high-entry)
        mfe=max(float(row['max_favourable_points']), max(0.0,fav)); mae=max(float(row['max_adverse_points']), max(0.0,adv))
        target_hit = high >= entry+target if sign>0 else low <= entry-target
        stop_hit = low <= entry-stop if sign>0 else high >= entry+stop
        outcome=None; result_r=None; correct=None
        # Conservative intrabar ordering.
        if target_hit and stop_hit:
            outcome='STOP'; result_r=-1.0; correct=0
        elif stop_hit:
            outcome='STOP'; result_r=-1.0; correct=0
        elif target_hit:
            outcome='TARGET'; result_r=target/stop; correct=1
        else:
            elapsed=(int(ts_ms)-int(row['created_ts_ms']))/60000.0
            if elapsed >= int(row['horizon_minutes']):
                move=sign*(close-entry); outcome='TIMEOUT'; result_r=max(-1.0,min(target/stop,move/stop)); correct=1 if move>0 else 0
        if outcome:
            c.execute('''UPDATE predictions SET status='RESOLVED',resolved_at=?,outcome=?,result_r=?,direction_correct=?,
                         max_favourable_points=?,max_adverse_points=? WHERE id=?''',
                      (datetime.now(timezone.utc).isoformat(),outcome,result_r,correct,mfe,mae,row['id']))
            resolved += 1
        else:
            c.execute('UPDATE predictions SET max_favourable_points=?,max_adverse_points=? WHERE id=?',(mfe,mae,row['id']))
    return resolved


def maybe_record_prediction(c, r: dict[str, Any], session: dict[str, Any], databento: dict[str, Any], ts_ms: int) -> bool:
    settings = get_settings(c)
    direction=str(r.get('direction','NONE'))
    if direction not in ('LONG','SHORT') or not r.get('price'):
        return False
    last=c.execute('SELECT created_ts_ms FROM predictions WHERE symbol=? ORDER BY id DESC LIMIT 1',(r.get('symbol','US30'),)).fetchone()
    if last and int(ts_ms)-int(last['created_ts_ms']) < int(settings['prediction_interval_minutes'])*60000:
        return False
    zone=r.get('htf_zones') or {}; best=zone.get('best_zone') or {}
    c.execute('''INSERT INTO predictions(created_at,created_ts_ms,symbol,direction,entry_price,target_points,stop_points,horizon_minutes,
                 raw_probability,calibrated_probability,calibration_samples,challenger_probability,bias_score,timing_score,databento_score,
                 intermarket_score,macro_score,session_name,session_risk,htf_zone_type,htf_zone_score,htf_zone_confirmed,htf_zone_distance,htf_zone_confluence)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (datetime.now(timezone.utc).isoformat(),int(ts_ms),r.get('symbol','US30'),direction,float(r['price']),
               float(settings['prediction_target_points']),float(settings['prediction_stop_points']),int(settings['prediction_horizon_minutes']),
               float(r.get('probability_raw') or 50),r.get('calibrated_probability'),int(r.get('calibration_samples') or 0),
               float(r.get('challenger_probability') or 50),float(r.get('bias_score') or 0),float(r.get('timing_score') or 0),
               float(databento.get('score') or 0),float(r.get('intermarket_score') or 0),float(r.get('macro_score') or 0),
               session.get('name'),session.get('risk'),best.get('kind'),float(zone.get('zone_score') or 0),
               1 if zone.get('zone_confirmed') else 0,float(best.get('distance_points') or 0) if best else None,
               int(zone.get('confluence_count') or 0)))
    return True


def performance(c) -> dict[str, Any]:
    ensure_tables(c)
    rows=c.execute("SELECT * FROM predictions WHERE status='RESOLVED' ORDER BY id").fetchall()
    targetstop=[r for r in rows if r['outcome'] in ('TARGET','STOP')]
    wins=sum(1 for r in targetstop if r['outcome']=='TARGET')
    directional=sum(int(r['direction_correct'] or 0) for r in rows)
    curve=[]; cum=0.0
    for r in rows:
        cum += float(r['result_r'] or 0)
        curve.append({'t':r['resolved_at'],'r':round(cum,2),'outcome':r['outcome']})

    def brier(col: str) -> float | None:
        data=[r for r in targetstop if r[col] is not None]
        if not data:return None
        return round(sum(((float(r[col])/100.0)-(1.0 if r['outcome']=='TARGET' else 0.0))**2 for r in data)/len(data),4)

    buckets=[]
    for lo in range(50,100,5):
        b=[r for r in targetstop if lo <= float(r['raw_probability']) < lo+5]
        if b:
            bw=sum(1 for r in b if r['outcome']=='TARGET')
            buckets.append({'bucket':f'{lo}–{lo+5}','n':len(b),'win_rate':round(100*bw/len(b),1)})

    sessions=[]
    names=sorted(set(str(r['session_name']) for r in targetstop if r['session_name']))
    for name in names:
        b=[r for r in targetstop if r['session_name']==name]; bw=sum(1 for r in b if r['outcome']=='TARGET')
        sessions.append({'session':name,'n':len(b),'win_rate':round(100*bw/len(b),1)})

    zones=[]
    ztypes=sorted(set(str(r['htf_zone_type']) for r in targetstop if r['htf_zone_type']))
    for name in ztypes:
        b=[r for r in targetstop if r['htf_zone_type']==name]
        bw=sum(1 for r in b if r['outcome']=='TARGET')
        zones.append({'zone_type':name,'n':len(b),'win_rate':round(100*bw/len(b),1)})

    return {
        'total_predictions': c.execute('SELECT COUNT(*) n FROM predictions').fetchone()['n'],
        'resolved': len(rows), 'barrier_samples':len(targetstop), 'target_wins':wins,
        'barrier_win_rate': round(100*wins/len(targetstop),1) if targetstop else None,
        'directional_accuracy': round(100*directional/len(rows),1) if rows else None,
        'cumulative_r': round(cum,2), 'primary_brier':brier('raw_probability'), 'challenger_brier':brier('challenger_probability'),
        'curve':curve[-300:], 'buckets':buckets, 'sessions':sessions, 'zones':zones,
        'definition': f"Target {get_settings(c)['prediction_target_points']:.0f} pts before stop {get_settings(c)['prediction_stop_points']:.0f} pts within {int(get_settings(c)['prediction_horizon_minutes'])} minutes",
    }
