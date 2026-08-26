from __future__ import annotations
import math
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any

try:
    import databento as db  # type: ignore
except Exception:  # optional at local test time
    db = None

_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_STOP = threading.Event()

_STATE: dict[str, Any] = {
    'configured': False,
    'status': 'NOT_CONFIGURED',
    'dataset': os.getenv('DATABENTO_DATASET', 'GLBX.MDP3'),
    'schema': os.getenv('DATABENTO_SCHEMA', 'mbp-10'),
    'symbol': os.getenv('DATABENTO_SYMBOL', 'YM.v.0'),
    'raw_symbol': None,
    'last_update': None,
    'last_error': None,
    'records': 0,
    'bid': None,
    'ask': None,
    'mid': None,
    'spread': None,
    'book_imbalance_5': 0.0,
    'book_imbalance_10': 0.0,
    'microprice': None,
    'microprice_bias_ticks': 0.0,
    'trade_pressure': 0.0,
    'score': 0.0,
}
_TRADE_BUY = 0.0
_TRADE_SELL = 0.0
_LAST_DECAY = time.time()


def _char(v: Any) -> str:
    if v is None:
        return ''
    if isinstance(v, bytes):
        try: return v.decode(errors='ignore')[:1]
        except Exception: return ''
    s = str(v)
    # enums sometimes stringify as Action.TRADE / Side.BID
    if s.endswith('TRADE'): return 'T'
    if s.endswith('BID'): return 'B'
    if s.endswith('ASK'): return 'A'
    return s[:1]


def _price(v: Any) -> float | None:
    try:
        x = float(v)
        if not math.isfinite(x) or x <= 0:
            return None
        return x / 1e9
    except Exception:
        return None


def _decay_trade_pressure(now_ts: float) -> None:
    global _TRADE_BUY, _TRADE_SELL, _LAST_DECAY
    dt = max(0.0, now_ts - _LAST_DECAY)
    if dt <= 0:
        return
    # ~60-second half-life.
    factor = 0.5 ** (dt / 60.0)
    _TRADE_BUY *= factor
    _TRADE_SELL *= factor
    _LAST_DECAY = now_ts


def _record_callback(record: Any) -> None:
    global _TRADE_BUY, _TRADE_SELL
    # Capture mapping messages without requiring exact class identity.
    if hasattr(record, 'stype_in_symbol') and hasattr(record, 'stype_out_symbol'):
        with _LOCK:
            _STATE['raw_symbol'] = str(getattr(record, 'stype_out_symbol', '') or '')
        return

    levels = getattr(record, 'levels', None)
    if levels is None:
        return
    try:
        lvls = list(levels)
    except Exception:
        return
    if not lvls:
        return

    bid_sizes, ask_sizes = [], []
    for lvl in lvls[:10]:
        try:
            bid_sizes.append(max(float(getattr(lvl, 'bid_sz', 0) or 0), 0.0))
            ask_sizes.append(max(float(getattr(lvl, 'ask_sz', 0) or 0), 0.0))
        except Exception:
            bid_sizes.append(0.0); ask_sizes.append(0.0)

    top = lvls[0]
    bid = _price(getattr(top, 'bid_px', None))
    ask = _price(getattr(top, 'ask_px', None))
    if bid is None or ask is None or ask < bid:
        return

    total5b = sum(bid_sizes[:5]); total5a = sum(ask_sizes[:5])
    total10b = sum(bid_sizes); total10a = sum(ask_sizes)
    imb5 = (total5b-total5a)/(total5b+total5a) if total5b+total5a else 0.0
    imb10 = (total10b-total10a)/(total10b+total10a) if total10b+total10a else 0.0

    bsz = bid_sizes[0] if bid_sizes else 0.0
    asz = ask_sizes[0] if ask_sizes else 0.0
    mid = (bid + ask) / 2.0
    micro = ((bsz * ask) + (asz * bid)) / (bsz + asz) if bsz + asz else mid
    tick = max(float(os.getenv('DATABENTO_TICK_SIZE', '1.0')), 1e-9)
    micro_ticks = (micro - mid) / tick

    now_ts = time.time()
    with _LOCK:
        _decay_trade_pressure(now_ts)
        if _char(getattr(record, 'action', None)) == 'T':
            try: qty = max(float(getattr(record, 'size', 0) or 0), 0.0)
            except Exception: qty = 0.0
            side = _char(getattr(record, 'side', None))
            if side == 'B': _TRADE_BUY += qty
            elif side == 'A': _TRADE_SELL += qty
        denom = _TRADE_BUY + _TRADE_SELL
        trade_pressure = (_TRADE_BUY - _TRADE_SELL) / denom if denom else 0.0

        score = 1.00 * imb5 + 0.55 * imb10 + 0.35 * max(-1.0, min(1.0, micro_ticks)) + 0.75 * trade_pressure
        score = max(-2.5, min(2.5, score))
        _STATE.update({
            'configured': True, 'status': 'LIVE', 'last_update': datetime.now(timezone.utc).isoformat(),
            'records': int(_STATE.get('records', 0)) + 1,
            'bid': round(bid, 2), 'ask': round(ask, 2), 'mid': round(mid, 2), 'spread': round(ask-bid, 2),
            'book_imbalance_5': round(imb5, 4), 'book_imbalance_10': round(imb10, 4),
            'microprice': round(micro, 3), 'microprice_bias_ticks': round(micro_ticks, 4),
            'trade_pressure': round(trade_pressure, 4), 'score': round(score, 4), 'last_error': None,
        })


def _exception_callback(exc: Exception) -> None:
    with _LOCK:
        _STATE['last_error'] = f'{type(exc).__name__}: {exc}'[:300]
        _STATE['status'] = 'ERROR'


def _run() -> None:
    key = os.getenv('DATABENTO_API_KEY', '').strip()
    if not key:
        with _LOCK:
            _STATE.update({'configured': False, 'status': 'NOT_CONFIGURED', 'last_error': None})
        return
    if db is None:
        with _LOCK:
            _STATE.update({'configured': True, 'status': 'SDK_MISSING', 'last_error': 'databento package is not installed'})
        return

    while not _STOP.is_set():
        try:
            with _LOCK:
                _STATE.update({'configured': True, 'status': 'CONNECTING', 'last_error': None})
            try:
                client = db.Live(key=key, reconnect_policy='reconnect', heartbeat_interval_s=10)
            except TypeError:
                client = db.Live(key=key)
            start = datetime.now(timezone.utc) - timedelta(minutes=2)
            client.subscribe(
                dataset=os.getenv('DATABENTO_DATASET', 'GLBX.MDP3'),
                schema=os.getenv('DATABENTO_SCHEMA', 'mbp-10'),
                symbols=os.getenv('DATABENTO_SYMBOL', 'YM.v.0'),
                stype_in='continuous',
                start=start,
            )
            client.add_callback(record_callback=_record_callback, exception_callback=_exception_callback)
            client.start()
            client.block_for_close()
        except Exception as exc:
            _exception_callback(exc)
        if not _STOP.wait(5):
            continue


def start_background() -> None:
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_run, name='databento-ym-live', daemon=True)
    _THREAD.start()


def stop_background() -> None:
    _STOP.set()


def get_snapshot() -> dict[str, Any]:
    with _LOCK:
        snap = dict(_STATE)
    last = snap.get('last_update')
    age = None
    if last:
        try:
            age = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds())
        except Exception:
            age = None
    snap['age_seconds'] = round(age, 1) if age is not None else None
    if snap.get('configured') and age is not None:
        if age > 300:
            snap['status'] = 'OFFLINE'
        elif age > 30:
            snap['status'] = 'STALE'
        else:
            snap['status'] = 'LIVE'
    return snap
