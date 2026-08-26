import sqlite3
from types import SimpleNamespace
from datetime import datetime, timezone
import learning
import session_engine
import databento_feed


def con():
    c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row; learning.ensure_tables(c); return c


def test_default_perfect_threshold_is_98():
    c=con(); s=learning.get_settings(c); assert s['perfect_notify_probability']==98.0


def test_calibration_requires_samples():
    c=con(); z=learning.calibrated_probability(c,92,'LONG',20); assert z['probability'] is None and z['status']=='LEARNING'


def test_session_open_is_extreme():
    # 2026-08-25 13:32 UTC = 09:32 ET (EDT)
    ts=int(datetime(2026,8,25,13,32,tzinfo=timezone.utc).timestamp()*1000)
    s=session_engine.session_context(ts); assert s['name']=='US_CASH_OPEN_VOLATILITY'; assert s['block_perfect_entry']


def test_databento_book_scoring_fake_record():
    levels=[SimpleNamespace(bid_px=int((53000-i)*1e9), ask_px=int((53001+i)*1e9), bid_sz=200-i*5, ask_sz=50+i*2) for i in range(10)]
    rec=SimpleNamespace(levels=levels, action='T', side='B', size=20)
    databento_feed._record_callback(rec)
    snap=databento_feed.get_snapshot()
    assert snap['book_imbalance_5']>0
    assert snap['score']>0
