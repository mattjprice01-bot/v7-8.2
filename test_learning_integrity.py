import json
import sqlite3
from pathlib import Path
import tempfile
import server
import shadow_learning as sl


def connection():
    c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row; sl._ensure(c)
    return c


def snapshot(i, ts, high=101, low=99, close=100):
    return {'id':i,'received_at':'2026-10-02T10:00:00+00:00',
            'raw_json':json.dumps({'ts':ts,'frames':[{'tf':'1m','h':high,'l':low,'c':close}]}),
            'result_json':json.dumps({'symbol':'US30','direction':'LONG','price':100,'trade_state':'WATCHING'})}


def test_shadow_replay_uses_market_time_and_never_entry_bar():
    c=connection()
    sl._process_snapshot(c,snapshot(1,1_000_000,250,20))
    row=c.execute('SELECT * FROM shadow_candidates_v2').fetchone()
    assert row['created_ts_ms']==1_000_000 and row['status']=='OPEN'
    sl._process_snapshot(c,snapshot(2,1_000_000,250,20))
    assert c.execute('SELECT status FROM shadow_candidates_v2').fetchone()[0]=='OPEN'
    sl._process_snapshot(c,snapshot(3,1_060_000,210,95,200))
    assert c.execute('SELECT outcome FROM shadow_candidates_v2').fetchone()[0]=='TARGET'


def test_shadow_symbol_and_gap_exclusion():
    c=connection(); sl._process_snapshot(c,snapshot(1,1_000_000))
    sl._resolve_open(c,1_060_000,210,95,200,'OTHER')
    assert c.execute('SELECT status FROM shadow_candidates_v2').fetchone()[0]=='OPEN'
    sl._resolve_open(c,1_000_000+sl.HORIZON_MS+120000,210,95,200,'US30')
    row=c.execute('SELECT * FROM shadow_candidates_v2').fetchone()
    assert row['outcome']=='DATA_GAP' and row['result_r'] is None


def test_shadow_restart_keeps_progress_and_legacy():
    c=connection(); c.execute('CREATE TABLE shadow_candidates(id INTEGER)'); c.execute('INSERT INTO shadow_candidates VALUES(7)')
    sl._process_snapshot(c,snapshot(1,1_000_000)); c.execute('UPDATE shadow_progress_v2 SET last_snapshot_id=1')
    sl._ensure(c)
    assert c.execute('SELECT last_snapshot_id FROM shadow_progress_v2').fetchone()[0]==1
    assert c.execute('SELECT id FROM shadow_candidates').fetchone()[0]==7


def test_prediction_duplicate_symbol_and_gap():
    old=server.DB
    with tempfile.TemporaryDirectory() as td:
        server.DB=Path(td)/'test.db'
        try:
            c=server.db()
            c.execute("INSERT INTO predictions_v791(created_at,created_ts,symbol,side,entry,target_points,stop_points,horizon_minutes,probability,target_price,stop_price,integrity_version) VALUES('x',1000000,'US30','LONG',100,100,50,480,98,200,50,2)")
            server._v791_evaluate_predictions(c,1_000_000,210,20,100,'US30')
            server._v791_evaluate_predictions(c,1_060_000,210,95,200,'OTHER')
            assert c.execute('SELECT status FROM predictions_v791').fetchone()[0]=='OPEN'
            server._v791_evaluate_predictions(c,1_000_000+sl.HORIZON_MS+120000,210,95,200,'US30')
            row=c.execute('SELECT outcome,ambiguous FROM predictions_v791').fetchone()
            assert tuple(row)==('DATA_GAP',1)
        finally:
            server.DB=old


def test_legacy_predictions_excluded_from_validated_metrics():
    old=server.DB
    with tempfile.TemporaryDirectory() as td:
        server.DB=Path(td)/'test.db'
        try:
            c=server.db()
            c.execute("INSERT INTO predictions_v791(created_at,created_ts,symbol,side,entry,target_points,stop_points,horizon_minutes,probability,target_price,stop_price,status,outcome,favorable,r_result) VALUES('x',1000000,'US30','LONG',100,100,50,480,98,200,50,'RESOLVED','TARGET',1,2)")
            perf=server._v791_performance(c)
            assert perf['total_predictions']==0 and perf['legacy_predictions_preserved']==1
            assert server._v791_calibration(c,98)[0] is None
        finally:
            server.DB=old


def test_ingest_duplicate_does_not_call_sources_or_advance_state(monkeypatch):
    import asyncio
    old=server.DB
    with tempfile.TemporaryDirectory() as td:
        server.DB=Path(td)/'test.db'
        try:
            c=server.db()
            payload={'symbol':'US30','ts':1000000,'frames':[],'secret':'never-export-this'}
            c.execute('INSERT INTO snapshots(received_at,symbol,raw_json,result_json) VALUES(?,?,?,?)',('2026-10-02T10:00:00+00:00','US30',json.dumps(payload),json.dumps({'direction_streak':8})))
            c.commit()
            def forbidden():
                raise AssertionError('Duplicate requested context')
            monkeypatch.setattr(server,'get_macro',forbidden)
            class Request:
                async def json(self): return payload
            assert asyncio.run(server.ingest(Request()))['ignored']=='duplicate_or_out_of_order'
            assert 'never-export-this' not in json.dumps(server.learning_audit())
        finally:
            server.DB=old


def test_record_new_prediction_has_integrity_version():
    old=server.DB
    with tempfile.TemporaryDirectory() as td:
        server.DB=Path(td)/'test.db'
        try:
            c=server.db()
            server._v791_maybe_record_prediction(c,{'symbol':'US30','price':100,'probability_raw':98},{'state':'ENTRY_READY','changed':True,'direction':'LONG'},{},{},1000000)
            assert c.execute('SELECT integrity_version FROM predictions_v791').fetchone()[0]==2
        finally:
            server.DB=old


def test_shadow_excludes_gap_inside_horizon():
    c=connection(); sl._process_snapshot(c,snapshot(1,1_000_000))
    sl._process_snapshot(c,snapshot(2,1_180_000,210,95,200))
    row=c.execute('SELECT outcome,result_r FROM shadow_candidates_v2 WHERE id=1').fetchone()
    assert tuple(row)==('DATA_GAP',None)


def test_prediction_excludes_gap_inside_horizon():
    old=server.DB
    with tempfile.TemporaryDirectory() as td:
        server.DB=Path(td)/'test.db'
        try:
            c=server.db()
            server._v791_maybe_record_prediction(c,{'symbol':'US30','price':100,'probability_raw':98},{'state':'ENTRY_READY','changed':True,'direction':'LONG'},{},{},1000000)
            server._v791_evaluate_predictions(c,1_180_000,210,95,200,'US30',1_000_000)
            assert tuple(c.execute('SELECT outcome,ambiguous FROM predictions_v791').fetchone())==('DATA_GAP',1)
        finally:
            server.DB=old
