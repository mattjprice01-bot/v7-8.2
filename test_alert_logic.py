import sqlite3
import server

def fake_result(**kw):
    x = {
        "symbol":"TEST:US30","direction":"LONG","conviction":86,"big_move_probability":74,
        "bias_score":1.8,"bias_label":"BULLISH","timing_aligned":True,"timing_label":"ALIGNED",
        "contradiction":False,"macro_score":0.2,"macro_available":True,"intermarket_score":0.8,"news_score":0.0,
        "price":53000.0,"entry_low":52950.0,"entry_high":53020.0,"stop":52400.0,
        "tp1_low":54000.0,"tp1_high":54200.0,"tp2_low":54800.0,"tp2_high":55200.0,
    }
    x.update(kw); return x

def test_context_gate():
    assert server._context_not_opposing(fake_result())
    assert not server._context_not_opposing(fake_result(intermarket_score=-1.5))

def test_entry_zone_gate():
    assert server._inside_entry(fake_result())
    assert not server._inside_entry(fake_result(price=53100.0))
