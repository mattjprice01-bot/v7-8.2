import json
import sqlite3
import tempfile
from pathlib import Path

import shadow_learning as sl


def test_shadow_candidate_records_without_entry_ready():
    with tempfile.TemporaryDirectory() as td:
        sl.DB = Path(td) / 'test.db'
        c = sl._connect(); sl._ensure(c)
        result = {'symbol':'US30','direction':'LONG','price':52000,'conviction':72,'signal_state':'WATCHING','reason':'below live threshold'}
        sl._record_candidate(c, 1, 1_000_000, result); c.commit()
        row = c.execute('SELECT * FROM shadow_candidates_v2').fetchone()
        assert row is not None
        assert row['live_state'] == 'WATCHING'
        assert row['direction'] == 'LONG'
        c.close()


def test_shadow_outcome_does_not_touch_live_tables():
    with tempfile.TemporaryDirectory() as td:
        sl.DB = Path(td) / 'test.db'
        c = sl._connect(); sl._ensure(c)
        c.execute('CREATE TABLE trades(id INTEGER PRIMARY KEY, status TEXT)')
        c.execute("INSERT INTO trades(id,status) VALUES(1,'OPEN')")
        result = {'symbol':'US30','direction':'LONG','price':52000,'conviction':72,'signal_state':'WATCHING'}
        sl._record_candidate(c, 1, 1_000_000, result)
        sl._resolve_open(c, 1_060_000, 52110, 51990, 52090); c.commit()
        shadow = c.execute('SELECT outcome FROM shadow_candidates_v2').fetchone()['outcome']
        live = c.execute('SELECT status FROM trades WHERE id=1').fetchone()['status']
        assert shadow == 'TARGET'
        assert live == 'OPEN'
        c.close()
