import tempfile, json
import v7_scoring as vs

def frame(tf, score):
    return {"tf":tf,"o":100,"h":101,"l":99,"c":100,"ema20":100,"ema50":99,"ema200":98,
            "rsi":55,"atr":10,"vwap":100,"swing_hi":102,"swing_lo":98,"c3":99,"prev_o":99,"prev_c":99,
            "vol":1000,"vma20":900,"adx":30,"ema20_slope":score}

def test_macro_unavailable_not_fake_zero():
    payload={"symbol":"X","frames":[frame("1W",1),frame("1D",1),frame("4h",1),frame("1h",1)]}
    r=vs.aggregate(payload,{"score":None,"status":"UNAVAILABLE","quality":"NONE","is_usable":False},{"score":0})
    assert r["macro_score"] is None
    assert r["macro_available"] is False
    assert r["conviction"] <= 82
