from v7_scoring import aggregate, trade_health

def fr(tf,p,up=True):
    s=1 if up else -1
    return {"tf":tf,"o":p-10*s,"h":p+30,"l":p-30,"c":p,"ema20":p-40*s,"ema50":p-100*s,"ema200":p-250*s,"ema20_prev":p-70*s,"rsi":62 if up else 38,"atr":180,"atr_ma":160,"adx":31,"swing_hi":p-20 if up else p+300,"swing_lo":p-300 if up else p+20,"swing_hi50":p-10 if up else p+500,"swing_lo50":p-500 if up else p+10,"c3":p-120*s,"vol":150,"vma20":100,"bb_width":.02,"bb_width_ma":.035}

def test_bullish_trigger():
    p=45000
    payload={"symbol":"TEST:US30","frames":[fr("1m",p),fr("1h",p),fr("4h",p),fr("1D",p),fr("1W",p)],"intermarket":{"spx_ret":.6,"ndx_ret":.7,"vix_ret":-3,"dxy_ret":-.5,"us10y_chg":-.1}}
    r=aggregate(payload,{"score":1.2,"reasons":[]},{"score":.3,"reasons":[]})
    assert r["direction"]=="LONG"
    assert r["setup_state"] in ("ARMED","TRIGGERED")
    assert r["tp2_high"]>r["tp1_high"]>r["price"]>r["stop"]

def test_contradiction_blocks_trigger():
    p=45000
    payload={"symbol":"TEST:US30","frames":[fr("1h",p),fr("4h",p),fr("1D",p,False),fr("1W",p,False)],"intermarket":{"spx_ret":1.0,"vix_ret":-4}}
    r=aggregate(payload,{"score":2.0},{"score":1.0})
    assert r["contradiction"] or r["direction"]=="SHORT"
    if r["contradiction"]: assert r["setup_state"]!="TRIGGERED"


def test_bias_can_be_long_while_timing_waits():
    p=45000
    payload={"symbol":"TEST:US30","frames":[fr("1h",p,False),fr("4h",p,False),fr("1D",p,True),fr("1W",p,True)],
             "intermarket":{"spx_ret":.5,"vix_ret":-2}}
    r=aggregate(payload,{"score":.7},{"score":0})
    assert r["direction"]=="LONG"
    assert r["bias_label"]=="BULLISH"
    assert not r["timing_aligned"]
    assert r["setup_state"]!="TRIGGERED"
