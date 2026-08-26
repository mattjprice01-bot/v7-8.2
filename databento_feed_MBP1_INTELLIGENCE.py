from __future__ import annotations
import math
import os
import threading
import time
import traceback
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
    'schema': os.getenv('DATABENTO_SCHEMA', 'mbp-1'),
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
    'top_imbalance': 0.0,
    'liquidity_pressure': 0.0,
    'persistence': 0.0,
    'orderflow_score': 0.0,
    'score': 0.0,
}
_TRADE_BUY = 0.0
_TRADE_SELL = 0.0
_LAST_DECAY = time.time()
_PREV_BID_SZ = None
_PREV_ASK_SZ = None
_FLOW_EMA = 0.0
_PERSIST_EMA = 0.0
_LAST_FLOW_SIGN = 0

def _log(msg: str) -> None:
    # Flush immediately so Railway Deploy Logs show Databento stages/errors.
    print(f"[DATABENTO] {msg}", flush=True)



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
    global _PREV_BID_SZ, _PREV_ASK_SZ, _FLOW_EMA, _PERSIST_EMA, _LAST_FLOW_SIGN

    # Capture mapping messages without requiring exact class identity.
    if hasattr(record, 'stype_in_symbol') and hasattr(record, 'stype_out_symbol'):
        raw = str(getattr(record, 'stype_out_symbol', '') or '')
        with _LOCK:
            _STATE['raw_symbol'] = raw
        _log(f"symbol mapping received: {raw}")
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

    # MBP-1 provides one consolidated top-of-book level. This also remains
    # compatible with deeper MBP schemas if they are enabled later.
    bid_sizes, ask_sizes = [], []
    for lvl in lvls[:10]:
        try:
            bid_sizes.append(max(float(getattr(lvl, 'bid_sz', 0) or 0), 0.0))
            ask_sizes.append(max(float(getattr(lvl, 'ask_sz', 0) or 0), 0.0))
        except Exception:
            bid_sizes.append(0.0)
            ask_sizes.append(0.0)

    top = lvls[0]
    bid = _price(getattr(top, 'bid_px', None))
    ask = _price(getattr(top, 'ask_px', None))
    if bid is None or ask is None or ask < bid:
        return

    bsz = bid_sizes[0] if bid_sizes else 0.0
    asz = ask_sizes[0] if ask_sizes else 0.0
    top_denom = bsz + asz
    top_imbalance = (bsz - asz) / top_denom if top_denom else 0.0

    # If a deeper schema is ever used, these become true 5/10-level metrics.
    # On MBP-1 they intentionally equal the L1 imbalance rather than pretending
    # that unavailable depth exists.
    total5b = sum(bid_sizes[:5]); total5a = sum(ask_sizes[:5])
    total10b = sum(bid_sizes); total10a = sum(ask_sizes)
    imb5 = (total5b-total5a)/(total5b+total5a) if total5b+total5a else 0.0
    imb10 = (total10b-total10a)/(total10b+total10a) if total10b+total10a else 0.0

    mid = (bid + ask) / 2.0
    micro = ((bsz * ask) + (asz * bid)) / top_denom if top_denom else mid
    tick = max(float(os.getenv('DATABENTO_TICK_SIZE', '1.0')), 1e-9)
    micro_ticks = (micro - mid) / tick
    micro_signal = max(-1.0, min(1.0, micro_ticks))

    now_ts = time.time()
    with _LOCK:
        _decay_trade_pressure(now_ts)

        # MBP records can carry trade events. Side B/A is accumulated with
        # exponential time decay so old prints lose influence.
        if _char(getattr(record, 'action', None)) == 'T':
            try:
                qty = max(float(getattr(record, 'size', 0) or 0), 0.0)
            except Exception:
                qty = 0.0
            side = _char(getattr(record, 'side', None))
            if side == 'B':
                _TRADE_BUY += qty
            elif side == 'A':
                _TRADE_SELL += qty

        denom = _TRADE_BUY + _TRADE_SELL
        trade_pressure = (_TRADE_BUY - _TRADE_SELL) / denom if denom else 0.0

        # Detect changes in displayed top-of-book liquidity. More bid liquidity
        # and/or less ask liquidity is positive; the reverse is negative.
        liquidity_pressure = 0.0
        if _PREV_BID_SZ is not None and _PREV_ASK_SZ is not None:
            bid_delta = bsz - _PREV_BID_SZ
            ask_delta = asz - _PREV_ASK_SZ
            scale = max(bsz + asz + _PREV_BID_SZ + _PREV_ASK_SZ, 1.0)
            liquidity_pressure = max(-1.0, min(1.0, 2.0 * (bid_delta - ask_delta) / scale))
        _PREV_BID_SZ, _PREV_ASK_SZ = bsz, asz

        # Smooth the instantaneous L1 signal to stop the dashboard reacting to
        # every single book flicker.
        instant_flow = (
            0.38 * top_imbalance +
            0.22 * micro_signal +
            0.24 * trade_pressure +
            0.16 * liquidity_pressure
        )
        _FLOW_EMA = 0.82 * _FLOW_EMA + 0.18 * instant_flow

        sign = 1 if instant_flow > 0.05 else (-1 if instant_flow < -0.05 else 0)
        same_direction = 1.0 if sign != 0 and sign == _LAST_FLOW_SIGN else 0.0
        opposite = 1.0 if sign != 0 and _LAST_FLOW_SIGN != 0 and sign != _LAST_FLOW_SIGN else 0.0
        _PERSIST_EMA = max(0.0, min(1.0, 0.92 * _PERSIST_EMA + 0.08 * same_direction - 0.12 * opposite))
        if sign:
            _LAST_FLOW_SIGN = sign

        # Final normalized MBP-1 intelligence score: -2.5 .. +2.5.
        # Persistence increases confidence in the current smoothed direction
        # without manufacturing extra directional bias by itself.
        orderflow_score = max(-2.5, min(2.5, 2.5 * _FLOW_EMA * (0.75 + 0.25 * _PERSIST_EMA)))

        first_live = int(_STATE.get('records', 0)) == 0
        _STATE.update({
            'configured': True,
            'status': 'LIVE',
            'last_update': datetime.now(timezone.utc).isoformat(),
            'records': int(_STATE.get('records', 0)) + 1,
            'bid': round(bid, 2),
            'ask': round(ask, 2),
            'mid': round(mid, 2),
            'spread': round(ask-bid, 2),
            'book_imbalance_5': round(imb5, 4),
            'book_imbalance_10': round(imb10, 4),
            'top_imbalance': round(top_imbalance, 4),
            'microprice': round(micro, 3),
            'microprice_bias_ticks': round(micro_ticks, 4),
            'trade_pressure': round(trade_pressure, 4),
            'liquidity_pressure': round(liquidity_pressure, 4),
            'persistence': round(_PERSIST_EMA, 4),
            'orderflow_score': round(orderflow_score, 4),
            # Keep 'score' for compatibility with the existing V7 server/UI.
            'score': round(orderflow_score, 4),
            'last_error': None,
        })
        if first_live:
            _log(
                f"LIVE: first MBP-1 record | bid={bid:.2f} ask={ask:.2f} "
                f"L1imb={top_imbalance:.4f} flow={orderflow_score:.4f}"
            )


def _exception_callback(exc: Exception) -> None:
    msg = f'{type(exc).__name__}: {exc}'
    with _LOCK:
        _STATE['last_error'] = msg[:500]
        _STATE['status'] = 'ERROR'
    _log(f"ERROR: {msg}")


def _run() -> None:
    key = os.getenv('DATABENTO_API_KEY', '').strip()
    dataset = os.getenv('DATABENTO_DATASET', 'GLBX.MDP3').strip()
    schema = os.getenv('DATABENTO_SCHEMA', 'mbp-1').strip()
    symbol = os.getenv('DATABENTO_SYMBOL', 'YM.v.0').strip()

    _log(f"iterator worker starting | sdk={'yes' if db is not None else 'no'} | key_present={'yes' if bool(key) else 'no'}")
    _log(f"config dataset={dataset} schema={schema} symbol={symbol} stype_in=continuous")

    if not key:
        with _LOCK:
            _STATE.update({'configured': False, 'status': 'NOT_CONFIGURED', 'last_error': 'DATABENTO_API_KEY missing'})
        _log("NOT_CONFIGURED: DATABENTO_API_KEY is missing")
        return
    if db is None:
        with _LOCK:
            _STATE.update({'configured': True, 'status': 'SDK_MISSING', 'last_error': 'databento package is not installed'})
        _log("SDK_MISSING: databento package is not installed")
        return

    attempt = 0
    while not _STOP.is_set():
        attempt += 1
        try:
            with _LOCK:
                _STATE.update({'configured': True, 'status': 'CONNECTING', 'last_error': None,
                               'dataset': dataset, 'schema': schema, 'symbol': symbol})
            _log(f"attempt {attempt}: creating Live client")
            try:
                client = db.Live(key=key, reconnect_policy='reconnect', heartbeat_interval_s=10)
            except TypeError:
                client = db.Live(key=key, heartbeat_interval_s=10)

            start_time = datetime.now(timezone.utc) - timedelta(minutes=2)
            sub_id = client.subscribe(dataset=dataset, schema=schema, symbols=symbol,
                                      stype_in='continuous', start=start_time)
            _log(f"attempt {attempt}: subscription queued id={sub_id} start={start_time.isoformat()}")
            _log(f"attempt {attempt}: entering DIRECT ITERATOR (client.start() is intentionally NOT called)")

            record_count = 0
            for record in client:
                if _STOP.is_set():
                    try:
                        client.stop()
                    except Exception:
                        pass
                    break
                record_count += 1
                rtype = type(record).__name__
                if record_count <= 5:
                    _log(f"RX#{record_count} type={rtype} record={str(record)[:700]}")

                if isinstance(record, db.ErrorMsg):
                    err = str(getattr(record, 'err', record))
                    code = getattr(record, 'code', None)
                    with _LOCK:
                        _STATE['last_error'] = f"Databento ErrorMsg code={code}: {err}"[:500]
                        _STATE['status'] = 'ERROR'
                    _log(f"GATEWAY ERROR code={code}: {err}")
                    continue

                if isinstance(record, db.SymbolMappingMsg):
                    raw = str(getattr(record, 'stype_out_symbol', '') or '')
                    requested = str(getattr(record, 'stype_in_symbol', '') or '')
                    instrument_id = getattr(record, 'instrument_id', None)
                    with _LOCK:
                        _STATE['raw_symbol'] = raw
                    _log(f"SYMBOL MAPPING: {requested} -> {raw} instrument_id={instrument_id}")
                    continue

                if isinstance(record, db.SystemMsg):
                    msg = str(getattr(record, 'msg', '') or '')
                    code = getattr(record, 'code', None)
                    if record_count <= 5 or 'heartbeat' not in msg.lower():
                        _log(f"SYSTEM code={code}: {msg}")
                    continue

                _record_callback(record)

            _log(f"attempt {attempt}: iterator ended after {record_count} records")
        except Exception as exc:
            _exception_callback(exc)
            _log("traceback:\n" + traceback.format_exc())

        if not _STOP.wait(5):
            _log("retrying Databento iterator connection in 5s")
            continue

def start_background() -> None:
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_run, name='databento-ym-live', daemon=True)
    _THREAD.start()
    _log("background thread started")


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
