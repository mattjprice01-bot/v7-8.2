from v7_scoring import aggregate

def f(tf,c,e20,score_up=True):
    return {
        "tf":tf,"o":c-2,"h":c+10,"l":c-10,"c":c,
        "ema20":e20,"ema50":e20-20 if score_up else e20+20,
        "ema200":e20-50 if score_up else e20+50,
        "rsi":60 if score_up else 40,"atr":100,"atr_ma":100,"adx":30,
        "vwap":c,"swing_hi":c+200,"swing_lo":c-200,"swing_hi50":c+300,"swing_lo50":c-300,
        "c3":c-20 if score_up else c+20,"ema20_prev":e20-5 if score_up else e20+5,
        "vol":1000,"vma20":900,"bb_width":10,"bb_width_ma":12,
    }

def test_long_execution_stop_is_50_points():
    p={"symbol":"US30","frames":[
        f("1m",53000,52990,True),f("1h",52995,52990,True),
        f("4h",52900,52800,True),f("1D",52500,52000,True),f("1W",51000,50000,True)
    ],"intermarket":{"spx_ret":.5,"vix_ret":-2}}
    macro={"score":.5,"is_usable":True,"status":"LIVE","quality":"PRIMARY"}
    r=aggregate(p,macro,{"score":0})
    assert r["direction"]=="LONG"
    assert r["execution_stop_points"]==50.0
    assert r["execution_stop"]==r["entry_anchor"]-50.0
    assert r["structural_stop"] < r["execution_stop"]
    assert r["rr_tp1_low"] > 1.0
