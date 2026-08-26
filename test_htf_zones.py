from htf_zones import analyze_htf_zones

def test_old_ath_retest_band_long():
    p={
      "frames":[
        {"tf":"1m","c":53350},
        {"tf":"1D","atr":500,"swing_hi":54000,"swing_lo":52000,"swing_hi50":54500,"swing_lo50":51000},
        {"tf":"1W","swing_hi":54500,"swing_lo":50000,"swing_hi50":55000,"swing_lo50":49000},
        {"tf":"1M","swing_hi":55000,"swing_lo":47000}
      ],
      "reference_levels":{"old_ath":53300,"prev_day_close":53400,"prev_day_high":53500,"prev_day_low":52800}
    }
    z=analyze_htf_zones(p,"LONG")
    ath=next(x for x in z["zones"] if x["kind"]=="OLD_ATH_RETEST_BAND")
    assert ath["side"]=="SUPPORT"
    assert z["zone_confirmed"]
    assert z["probability_adjustment"] > 0

def test_weekly_low_is_long_support():
    p={"frames":[{"tf":"1m","c":52040},{"tf":"1D","atr":400},
                 {"tf":"1W","swing_lo":52000,"swing_hi":54000,"swing_lo50":51000,"swing_hi50":55000}]}
    z=analyze_htf_zones(p,"LONG")
    assert any(x["aligned"] and "Weekly 20-bar swing low" in x["label"] for x in z["near_zones"])

def test_weekly_high_is_short_resistance():
    p={"frames":[{"tf":"1m","c":53970},{"tf":"1D","atr":400},
                 {"tf":"1W","swing_lo":52000,"swing_hi":54000,"swing_lo50":51000,"swing_hi50":55000}]}
    z=analyze_htf_zones(p,"SHORT")
    assert any(x["aligned"] and "Weekly 20-bar swing high" in x["label"] for x in z["near_zones"])
