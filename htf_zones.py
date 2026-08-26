from __future__ import annotations
from typing import Any
import math

def fnum(v: Any, default: float | None = None) -> float | None:
    try:
        x=float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default

def _frame(payload: dict, tf: str) -> dict:
    return next((x for x in payload.get("frames",[]) if isinstance(x,dict) and x.get("tf")==tf), {}) or {}

def _level_zone(kind: str, label: str, price: float, width: float, side: str, weight: float, source: str) -> dict:
    return {"kind":kind,"label":label,"low":round(price-width,1),"high":round(price+width,1),
            "mid":round(price,1),"side":side,"weight":float(weight),"source":source}

def analyze_htf_zones(payload: dict, model_direction: str = "NONE") -> dict[str, Any]:
    d=_frame(payload,"1D"); w=_frame(payload,"1W"); m=_frame(payload,"1M")
    refs=payload.get("reference_levels") or {}
    live=_frame(payload,"1m") or _frame(payload,"1h") or d or w
    price=fnum(live.get("c"), fnum(live.get("price"),0.0)) or 0.0
    datr=max(fnum(d.get("atr"),100.0) or 100.0,1.0)
    base_width=max(18.0,min(90.0,datr*0.10))
    near_distance=max(50.0,min(180.0,datr*0.22))
    zones=[]

    def add(kind,label,value,side,weight,source,width=None):
        v=fnum(value)
        if v is None or v<=0:return
        zones.append(_level_zone(kind,label,v,width or base_width,side,weight,source))

    add("PREV_DAY_HIGH","Previous day high",refs.get("prev_day_high"),"RESISTANCE",1.25,"D")
    add("PREV_DAY_LOW","Previous day low",refs.get("prev_day_low"),"SUPPORT",1.25,"D")
    add("PREV_DAY_CLOSE","Previous day close",refs.get("prev_day_close"),"PIVOT",1.15,"D")
    add("PREV_WEEK_HIGH","Previous week high",refs.get("prev_week_high"),"RESISTANCE",1.75,"W")
    add("PREV_WEEK_LOW","Previous week low",refs.get("prev_week_low"),"SUPPORT",1.75,"W")
    add("PREV_WEEK_CLOSE","Previous week close",refs.get("prev_week_close"),"PIVOT",1.45,"W")
    add("PREV_MONTH_HIGH","Previous month high",refs.get("prev_month_high"),"RESISTANCE",2.10,"M")
    add("PREV_MONTH_LOW","Previous month low",refs.get("prev_month_low"),"SUPPORT",2.10,"M")
    add("PREV_MONTH_CLOSE","Previous month close",refs.get("prev_month_close"),"PIVOT",1.75,"M")

    add("DAILY_SWING_HIGH_20","Daily 20-bar swing high",d.get("swing_hi"),"RESISTANCE",1.65,"D")
    add("DAILY_SWING_LOW_20","Daily 20-bar swing low",d.get("swing_lo"),"SUPPORT",1.65,"D")
    add("DAILY_SWING_HIGH_50","Daily 50-bar swing high",d.get("swing_hi50"),"RESISTANCE",2.00,"D")
    add("DAILY_SWING_LOW_50","Daily 50-bar swing low",d.get("swing_lo50"),"SUPPORT",2.00,"D")
    add("WEEKLY_SWING_HIGH_20","Weekly 20-bar swing high",w.get("swing_hi"),"RESISTANCE",2.45,"W",base_width*1.20)
    add("WEEKLY_SWING_LOW_20","Weekly 20-bar swing low",w.get("swing_lo"),"SUPPORT",2.45,"W",base_width*1.20)
    add("WEEKLY_SWING_HIGH_50","Weekly 50-bar swing high",w.get("swing_hi50"),"RESISTANCE",2.80,"W",base_width*1.35)
    add("WEEKLY_SWING_LOW_50","Weekly 50-bar swing low",w.get("swing_lo50"),"SUPPORT",2.80,"W",base_width*1.35)
    if m:
        add("MONTHLY_SWING_HIGH_20","Monthly 20-bar swing high",m.get("swing_hi"),"RESISTANCE",3.10,"M",base_width*1.45)
        add("MONTHLY_SWING_LOW_20","Monthly 20-bar swing low",m.get("swing_lo"),"SUPPORT",3.10,"M",base_width*1.45)

    old_ath=fnum(refs.get("old_ath")); prev_d_close=fnum(refs.get("prev_day_close"))
    if old_ath and prev_d_close:
        if prev_d_close >= old_ath:
            lo=min(old_ath,prev_d_close); hi=max(old_ath,prev_d_close)
            if hi-lo <= max(2.0*datr,1200.0):
                zones.append({"kind":"OLD_ATH_RETEST_BAND","label":"Old ATH → confirmed daily close retest band",
                              "low":round(lo,1),"high":round(hi,1),"mid":round((lo+hi)/2,1),
                              "side":"SUPPORT","weight":3.60,"source":"ATH+D","width":round(hi-lo,1)})
        else:
            add("OLD_ATH","Old all-time high",old_ath,"RESISTANCE",3.20,"ATH",base_width*1.35)

    sign=1 if model_direction=="LONG" else -1 if model_direction=="SHORT" else 0
    evaluated=[]
    for z in zones:
        lo=float(z["low"]); hi=float(z["high"])
        if lo <= price <= hi: dist=0.0; location="IN_ZONE"
        elif price < lo: dist=lo-price; location="BELOW"
        else: dist=price-hi; location="ABOVE"
        aligned=(sign==1 and z["side"] in ("SUPPORT","PIVOT")) or (sign==-1 and z["side"] in ("RESISTANCE","PIVOT"))
        opposing=(sign==1 and z["side"]=="RESISTANCE") or (sign==-1 and z["side"]=="SUPPORT")
        proximity=max(0.0,1.0-dist/max(near_distance,1.0))
        score=float(z["weight"])*proximity
        directional_score=score if aligned else (-0.65*score if opposing else 0.20*score)
        zz=dict(z); zz.update({"distance_points":round(dist,1),"location":location,"near":dist<=near_distance,
                               "aligned":bool(aligned),"opposing":bool(opposing),
                               "directional_score":round(directional_score,3)})
        evaluated.append(zz)

    evaluated.sort(key=lambda x:(x["distance_points"],-x["weight"]))
    near=[z for z in evaluated if z["near"]]
    aligned_near=[z for z in near if z["aligned"]]
    opposing_near=[z for z in near if z["opposing"]]

    clusters=[]
    for z in near:
        match=None
        for c in clusters:
            if abs(float(z["mid"])-c["mid"]) <= base_width*1.3:
                match=c; break
        if match:
            match["items"].append(z)
            match["mid"]=sum(float(i["mid"]) for i in match["items"])/len(match["items"])
        else:
            clusters.append({"mid":float(z["mid"]),"items":[z]})
    confluence=max((len(c["items"]) for c in clusters),default=0)

    best=max(aligned_near,key=lambda z:(z["directional_score"],z["weight"]),default=None)
    total=max(-5.0,min(5.0,sum(float(z["directional_score"]) for z in near)))
    probability_adjustment=max(-5.0,min(5.0,total*1.15 + max(0,confluence-1)*0.8))
    confirmed=bool(best and best["weight"] >= 1.65)
    high_quality=bool(best and best["weight"] >= 2.45 and (best["location"]=="IN_ZONE" or best["distance_points"]<=near_distance*0.45))
    reasons=[]
    if best: reasons.append(f"HTF ZONE: {best['label']} {best['location'].lower()} · {best['distance_points']:.0f} pts away")
    if confluence>=2: reasons.append(f"HTF ZONE: {confluence}-level confluence around current price")
    if opposing_near:
        z=opposing_near[0]; reasons.append(f"HTF ZONE RISK: nearby {z['label']} may oppose the {model_direction} thesis")

    return {"status":"ACTIVE" if evaluated else "NO_LEVELS","price":round(price,1),"daily_atr":round(datr,1),
            "zone_width":round(base_width,1),"near_distance":round(near_distance,1),"best_zone":best,
            "zone_confirmed":confirmed,"high_quality_zone":high_quality,"zone_score":round(total,3),
            "probability_adjustment":round(probability_adjustment,2),"confluence_count":int(confluence),
            "near_zones":near[:10],"zones":evaluated[:24],"reasons":reasons}
