from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = Path(os.getenv("US30_V7_DB", BASE / "data" / "v7_swing.db"))
POLL_SECONDS = 5
SAMPLE_INTERVAL_MS = 15 * 60 * 1000
TARGET_POINTS = 100.0
STOP_POINTS = 50.0
HORIZON_MS = 8 * 60 * 60 * 1000
_started = False
_lock = threading.Lock()


def _connect():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _ensure(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS shadow_candidates(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_snapshot_id INTEGER NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        created_ts_ms INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        entry_price REAL NOT NULL,
        probability REAL,
        live_state TEXT,
        rejection_reason TEXT,
        target_points REAL NOT NULL DEFAULT 100,
        stop_points REAL NOT NULL DEFAULT 50,
        horizon_minutes INTEGER NOT NULL DEFAULT 480,
        target_price REAL NOT NULL,
        stop_price REAL NOT NULL,
        context_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        resolved_at TEXT,
        outcome TEXT,
        result_r REAL,
        direction_correct INTEGER,
        max_favourable_points REAL NOT NULL DEFAULT 0,
        max_adverse_points REAL NOT NULL DEFAULT 0,
        close_price REAL
    );
    CREATE INDEX IF NOT EXISTS idx_shadow_open ON shadow_candidates(status, created_ts_ms);
    CREATE INDEX IF NOT EXISTS idx_shadow_direction ON shadow_candidates(direction, created_ts_ms);
    ''')
    c.commit()


def _frame(payload, tf):
    return next((x for x in payload.get("frames", []) if str(x.get("tf")) == str(tf)), None)


def _num(d, *keys):
    for k in keys:
        try:
            v = d.get(k)
            if v is not None:
                return float(v)
        except Exception:
            pass
    return None


def _resolve_open(c, ts_ms, high, low, close):
    rows = c.execute("SELECT * FROM shadow_candidates WHERE status='OPEN' ORDER BY id").fetchall()
    for row in rows:
        sign = 1 if row['direction'] == 'LONG' else -1
        entry = float(row['entry_price'])
        fav = (high - entry) if sign > 0 else (entry - low)
        adv = (entry - low) if sign > 0 else (high - entry)
        mfe = max(float(row['max_favourable_points']), max(0.0, fav))
        mae = max(float(row['max_adverse_points']), max(0.0, adv))
        target_hit = high >= float(row['target_price']) if sign > 0 else low <= float(row['target_price'])
        stop_hit = low <= float(row['stop_price']) if sign > 0 else high >= float(row['stop_price'])
        outcome = None
        rr = None
        correct = None
        if target_hit and stop_hit:
            outcome, rr, correct = 'AMBIGUOUS_SAME_BAR', None, None
        elif stop_hit:
            outcome, rr, correct = 'STOP', -1.0, 0
        elif target_hit:
            outcome, rr, correct = 'TARGET', TARGET_POINTS / STOP_POINTS, 1
        elif ts_ms - int(row['created_ts_ms']) >= HORIZON_MS:
            move = sign * (close - entry)
            outcome = 'TIMEOUT_FAVORABLE' if move > 0 else 'TIMEOUT_UNFAVORABLE' if move < 0 else 'TIMEOUT_FLAT'
            rr = max(-1.0, min(TARGET_POINTS / STOP_POINTS, move / STOP_POINTS))
            correct = 1 if move > 0 else 0
        if outcome:
            c.execute('''UPDATE shadow_candidates SET status='RESOLVED',resolved_at=?,outcome=?,result_r=?,
                         direction_correct=?,max_favourable_points=?,max_adverse_points=?,close_price=? WHERE id=?''',
                      (datetime.now(timezone.utc).isoformat(), outcome, rr, correct, mfe, mae, close, row['id']))
        else:
            c.execute('UPDATE shadow_candidates SET max_favourable_points=?,max_adverse_points=? WHERE id=?',
                      (mfe, mae, row['id']))


def _record_candidate(c, snapshot_id, ts_ms, result):
    direction = str(result.get('direction') or 'NONE').upper()
    if direction not in ('LONG', 'SHORT'):
        return
    price = _num(result, 'price', 'last', 'close')
    if not price:
        return
    symbol = str(result.get('symbol') or 'US30')
    last = c.execute('SELECT created_ts_ms FROM shadow_candidates WHERE symbol=? AND direction=? ORDER BY id DESC LIMIT 1',
                     (symbol, direction)).fetchone()
    if last and ts_ms - int(last['created_ts_ms']) < SAMPLE_INTERVAL_MS:
        return
    state = str(result.get('signal_state') or result.get('state') or result.get('trade_state') or 'OBSERVED')
    probability = _num(result, 'probability_raw', 'probability', 'conviction')
    reasons = result.get('rejection_reasons') or result.get('blockers') or result.get('reason') or ''
    if isinstance(reasons, (list, dict)):
        reasons = json.dumps(reasons, separators=(',', ':'))
    sign = 1 if direction == 'LONG' else -1
    c.execute('''INSERT OR IGNORE INTO shadow_candidates(
        source_snapshot_id,created_at,created_ts_ms,symbol,direction,entry_price,probability,live_state,rejection_reason,
        target_points,stop_points,horizon_minutes,target_price,stop_price,context_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (snapshot_id, datetime.now(timezone.utc).isoformat(), ts_ms, symbol, direction, price, probability, state,
         str(reasons), TARGET_POINTS, STOP_POINTS, 480, price + sign * TARGET_POINTS, price - sign * STOP_POINTS,
         json.dumps(result, separators=(',', ':'), default=str)))


def _worker():
    last_id = 0
    while True:
        try:
            c = _connect()
            _ensure(c)
            rows = c.execute('SELECT id,received_at,raw_json,result_json FROM snapshots WHERE id>? ORDER BY id', (last_id,)).fetchall()
            for row in rows:
                last_id = int(row['id'])
                try:
                    raw = json.loads(row['raw_json'] or '{}')
                    result = json.loads(row['result_json'] or '{}')
                    f1 = _frame(raw, '1') or _frame(raw, '1m') or {}
                    high = _num(f1, 'high', 'h')
                    low = _num(f1, 'low', 'l')
                    close = _num(f1, 'close', 'c') or _num(result, 'price', 'last', 'close')
                    ts_ms = int(_num(f1, 'ts', 'time', 'timestamp') or time.time() * 1000)
                    if high is not None and low is not None and close is not None:
                        _resolve_open(c, ts_ms, high, low, close)
                    _record_candidate(c, int(row['id']), ts_ms, result)
                    c.commit()
                except Exception as exc:
                    print(f'[SHADOW] snapshot {row["id"]} skipped: {exc}', flush=True)
            c.close()
        except Exception as exc:
            print(f'[SHADOW] worker error: {exc}', flush=True)
        time.sleep(POLL_SECONDS)


def start_background():
    global _started
    with _lock:
        if _started:
            return
        _started = True
        t = threading.Thread(target=_worker, name='v79-shadow-learning', daemon=True)
        t.start()
        print('[SHADOW] observational learner started; live decision logic unchanged', flush=True)
