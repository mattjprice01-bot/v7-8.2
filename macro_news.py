from __future__ import annotations
import csv, io, time, os, json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import httpx

CACHE = {"macro": (0, {}), "news": (0, {}), "market": (0, {})}

LAST_VALID_MACRO_FILE = Path(os.getenv("US30_LAST_MACRO_FILE", Path(__file__).resolve().parent / "data" / "last_macro.json"))
LAST_VALID_NEWS_FILE = Path(os.getenv("US30_LAST_NEWS_FILE", Path(__file__).resolve().parent / "data" / "last_news.json"))
LAST_VALID_MACRO_FILE.parent.mkdir(parents=True, exist_ok=True)
LAST_VALID_NEWS_FILE.parent.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 US30-Signal-Lab-V7/2.1"}

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_last_valid_macro(data: dict) -> None:
    try:
        LAST_VALID_MACRO_FILE.write_text(json.dumps(data))
    except Exception:
        pass

def _load_last_valid_macro() -> dict | None:
    try:
        if LAST_VALID_MACRO_FILE.exists():
            data = json.loads(LAST_VALID_MACRO_FILE.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return None

def _macro_age_minutes(data: dict | None) -> float | None:
    if not data or not data.get("fetched_at"):
        return None
    try:
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(data["fetched_at"])).total_seconds()/60.0)
    except Exception:
        return None

def _parse_gdelt_seen(value: str | None) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _fred_csv(series: str) -> list[tuple[str, float]]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={quote(series)}"
    r = httpx.get(url, timeout=10, headers=UA, follow_redirects=True)
    r.raise_for_status()
    rows: list[tuple[str, float]] = []
    for row in csv.DictReader(io.StringIO(r.text)):
        # FRED currently uses observation_date on fredgraph.csv; older exports used DATE.
        date = row.get("observation_date") or row.get("DATE") or row.get("date")
        raw = row.get(series)
        try:
            if date and raw not in (None, "", "."):
                rows.append((date, float(raw)))
        except (TypeError, ValueError):
            pass
    return rows


def _yahoo_series(symbol: str) -> list[float]:
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?range=10d&interval=1d"
    r = httpx.get(u, timeout=8, headers=UA, follow_redirects=True)
    r.raise_for_status()
    result = (((r.json() or {}).get("chart") or {}).get("result") or [None])[0]
    if not result:
        return []
    closes = (((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
    return [float(x) for x in closes if x is not None]

def _yahoo_change(symbol: str, mode: str = "pct") -> float | None:
    vals = _yahoo_series(symbol)
    if len(vals) < 2:
        return None
    if mode == "chg":
        return vals[-1] - vals[-2]
    return 100.0 * (vals[-1] / vals[-2] - 1.0)

def _yahoo_last(symbol: str) -> tuple[float, float] | None:
    vals = _yahoo_series(symbol)
    if len(vals) < 2:
        return None
    return vals[-1], vals[-2]

def get_market(force: bool = False) -> dict:
    ts, old = CACHE["market"]
    if not force and time.time() - ts < 900 and old:
        return old
    mapping = {
        "spx_ret": ("^GSPC", "pct"),
        "ndx_ret": ("^NDX", "pct"),
        "vix_ret": ("^VIX", "pct"),
        "dxy_ret": ("DX-Y.NYB", "pct"),
        # Yahoo ^TNX is yield *10, so convert point change back to percentage points.
        "us10y_chg": ("^TNX", "chg"),
    }
    vals: dict[str, float] = {}
    errors: list[str] = []
    for key, (symbol, mode) in mapping.items():
        try:
            v = _yahoo_change(symbol, mode)
            if v is not None:
                if key == "us10y_chg":
                    v /= 10.0
                vals[key] = round(v, 4)
        except Exception as exc:
            errors.append(f"{key}:{type(exc).__name__}")
    out = {"values": vals, "source": "Yahoo Finance free backend (best effort)", "status": "LIVE" if vals else "UNAVAILABLE", "fetched_at": _iso_now(), "errors": errors}
    if vals:
        CACHE["market"] = (time.time(), out)
        return out
    return old or out


def get_macro(force: bool = False) -> dict:
    ts, old = CACHE["macro"]
    if not force and time.time() - ts < 900 and old:
        return old

    errors: list[str] = []
    series: dict = {}
    reasons: list[str] = []
    score = 0.0

    # PRIMARY: FRED CSV, using multiple series. One successful series is enough
    # to keep the source usable, but we report quality explicitly.
    fred_map = {"vix": "VIXCLS", "dgs2": "DGS2", "dgs10": "DGS10", "hy": "BAMLH0A0HYM2", "fed": "DFF"}
    for key, sid in fred_map.items():
        try:
            rows = _fred_csv(sid)[-3:]
            if rows:
                series[key] = {
                    "date": rows[-1][0],
                    "value": rows[-1][1],
                    "prev": rows[-2][1] if len(rows) > 1 else rows[-1][1],
                    "provider": "FRED",
                }
        except Exception as exc:
            errors.append(f"{sid}:{type(exc).__name__}")

    if series:
        if "vix" in series:
            d = series["vix"]["value"] - series["vix"]["prev"]
            if d <= -1: score += .65; reasons.append("VIX falling")
            elif d >= 1: score -= .65; reasons.append("VIX rising")
        if "dgs2" in series:
            d = series["dgs2"]["value"] - series["dgs2"]["prev"]
            if d >= .08: score -= .45; reasons.append("2Y yield rising sharply")
            elif d <= -.08: score += .35; reasons.append("2Y yield falling")
        if "dgs10" in series:
            d = series["dgs10"]["value"] - series["dgs10"]["prev"]
            if d >= .10: score -= .25; reasons.append("10Y yield rising sharply")
            elif d <= -.10: score += .20; reasons.append("10Y yield falling")
        if "hy" in series:
            d = series["hy"]["value"] - series["hy"]["prev"]
            if d >= .12: score -= .65; reasons.append("high-yield credit spread widening")
            elif d <= -.12: score += .35; reasons.append("high-yield credit spread tightening")

        quality = "PRIMARY_FULL" if len(series) >= 4 else "PRIMARY_PARTIAL"
        out = {
            "score": round(max(-2.5, min(2.5, score)), 3),
            "series": series,
            "reasons": reasons,
            "source": "FRED official data",
            "status": "LIVE",
            "quality": quality,
            "coverage": len(series),
            "fetched_at": _iso_now(),
            "errors": errors,
            "is_usable": True,
            "is_stale": False,
        }
        CACHE["macro"] = (time.time(), out)
        _save_last_valid_macro(out)
        return out

    # FALLBACK: market-derived macro context. This must not be reported as FRED.
    proxy: dict = {}
    proxy_reasons: list[str] = []
    proxy_score = 0.0
    mapping = {
        "vix": ("^VIX", 1.0),
        "us10y": ("^TNX", 0.1),
        "usd": ("DX-Y.NYB", 1.0),
        "credit": ("HYG", 1.0),
    }
    for key, (symbol, scale) in mapping.items():
        try:
            z = _yahoo_last(symbol)
            if z:
                last, prev = z
                last *= scale; prev *= scale
                proxy[key] = {
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "value": round(last, 4),
                    "prev": round(prev, 4),
                    "provider": "Yahoo proxy",
                }
        except Exception as exc:
            errors.append(f"fallback-{key}:{type(exc).__name__}")

    if "vix" in proxy:
        d = proxy["vix"]["value"] - proxy["vix"]["prev"]
        if d <= -1: proxy_score += .60; proxy_reasons.append("fallback VIX falling")
        elif d >= 1: proxy_score -= .60; proxy_reasons.append("fallback VIX rising")
    if "us10y" in proxy:
        d = proxy["us10y"]["value"] - proxy["us10y"]["prev"]
        if d >= .08: proxy_score -= .40; proxy_reasons.append("fallback 10Y yield rising")
        elif d <= -.08: proxy_score += .30; proxy_reasons.append("fallback 10Y yield falling")
    if "usd" in proxy:
        pct = 100.0 * (proxy["usd"]["value"] / max(proxy["usd"]["prev"], 1e-9) - 1.0)
        if pct >= .35: proxy_score -= .20; proxy_reasons.append("dollar strengthening")
        elif pct <= -.35: proxy_score += .20; proxy_reasons.append("dollar weakening")
    if "credit" in proxy:
        pct = 100.0 * (proxy["credit"]["value"] / max(proxy["credit"]["prev"], 1e-9) - 1.0)
        if pct >= .5: proxy_score += .35; proxy_reasons.append("high-yield risk proxy improving")
        elif pct <= -.5: proxy_score -= .45; proxy_reasons.append("high-yield risk proxy weakening")

    if proxy:
        out = {
            "score": round(max(-1.8, min(1.8, proxy_score)), 3),
            "series": proxy,
            "reasons": proxy_reasons,
            "source": "Yahoo market macro proxy",
            "status": "FALLBACK_LIVE",
            "quality": "FALLBACK",
            "coverage": len(proxy),
            "fetched_at": _iso_now(),
            "errors": errors,
            "is_usable": True,
            "is_stale": False,
        }
        CACHE["macro"] = (time.time(), out)
        _save_last_valid_macro(out)
        return out

    # LAST VALID: never convert missing evidence into a fake neutral zero.
    last = _load_last_valid_macro() or old
    if last:
        age = _macro_age_minutes(last)
        stale = dict(last)
        stale["status"] = "STALE_LAST_VALID"
        stale["quality"] = "STALE"
        stale["is_stale"] = True
        stale["is_usable"] = bool(age is not None and age <= 360)
        stale["stale_age_minutes"] = round(age, 1) if age is not None else None
        stale["errors"] = errors
        CACHE["macro"] = (time.time(), stale)
        return stale

    # Truly unavailable: score is None, not 0.0.
    out = {
        "score": None,
        "series": {},
        "reasons": [],
        "source": "Macro data unavailable",
        "status": "UNAVAILABLE",
        "quality": "NONE",
        "coverage": 0,
        "fetched_at": _iso_now(),
        "errors": errors,
        "is_usable": False,
        "is_stale": True,
    }
    CACHE["macro"] = (time.time(), out)
    return out

def _save_last_valid_news(data: dict) -> None:
    try:
        LAST_VALID_NEWS_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def _load_last_valid_news() -> dict | None:
    try:
        if LAST_VALID_NEWS_FILE.exists():
            data = json.loads(LAST_VALID_NEWS_FILE.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return None


def _news_age_minutes(data: dict | None) -> float | None:
    if not data or not data.get("fetched_at"):
        return None
    try:
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(data["fetched_at"])).total_seconds() / 60.0)
    except Exception:
        return None



def _parse_news_time(value: str | None) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    for fmt in (
        "%Y%m%dT%H%M%S",
        "%Y%m%dT%H%M",
        "%Y%m%dT%H%M%SZ",
        "%Y%m%d%H%M%S",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _headline_impact(title: str) -> float:
    low = title.lower()
    impact = 0.0

    # High-impact risk / risk-off language.
    if any(x in low for x in [
        "emergency", "crisis", "bank failure", "default", "war escalation",
        "attack", "credit crisis", "liquidity crisis"
    ]):
        impact -= .45

    # US equity / Dow-supportive macro language.
    if any(x in low for x in [
        "rate cut", "rate cuts", "disinflation", "soft landing",
        "cooling inflation", "inflation cools", "inflation eased",
        "inflation eases", "dovish"
    ]):
        impact += .25

    # US equity headwinds.
    if any(x in low for x in [
        "rate hike", "rate hikes", "hot inflation", "inflation surge",
        "tariff", "tariffs", "hawkish", "yields surge", "yield surge"
    ]):
        impact -= .25

    if any(x in low for x in [
        "payrolls miss", "unemployment rises sharply", "recession"
    ]):
        impact -= .20

    return impact


def _score_normalized_articles(articles: list[dict]) -> tuple[list[dict], list[str], float]:
    reasons: list[str] = []
    items: list[dict] = []
    score = 0.0
    now_dt = datetime.now(timezone.utc)
    seen_urls: set[str] = set()

    for a in articles[:80]:
        title = str(a.get("title", "")).strip()
        if not title:
            continue

        article_url = str(a.get("url") or "")
        if article_url and article_url in seen_urls:
            continue
        if article_url:
            seen_urls.add(article_url)

        published = _parse_news_time(a.get("published_at"))
        age_h = ((now_dt - published).total_seconds() / 3600.0) if published else None
        if age_h is not None and (age_h < -0.5 or age_h > 48):
            continue

        impact = _headline_impact(title)

        # Alpha Vantage supplies article sentiment. Use it only as a small
        # secondary adjustment; the explicit macro headline rules remain dominant.
        provider_sentiment = a.get("provider_sentiment")
        try:
            if provider_sentiment is not None:
                s = max(-1.0, min(1.0, float(provider_sentiment)))
                impact += 0.10 * s
        except (TypeError, ValueError):
            pass

        recency_weight = 1.0
        if age_h is not None:
            recency_weight = 1.0 if age_h <= 12 else 0.75 if age_h <= 24 else 0.5

        weighted = impact * recency_weight
        score += weighted

        if abs(weighted) >= .18 and len(reasons) < 5:
            reasons.append(title[:150])

        items.append({
            "title": title[:190],
            "url": a.get("url"),
            "domain": a.get("domain"),
            "seendate": a.get("published_at"),  # preserve UI-compatible field
            "age_hours": round(age_h, 1) if age_h is not None else None,
            "impact": round(weighted, 3),
        })

    return items[:15], reasons, round(max(-1.5, min(1.5, score)), 3)


def _alpha_vantage_news(api_key: str) -> tuple[list[dict], list[str]]:
    base = "https://www.alphavantage.co/query"
    params = {
        "function": "NEWS_SENTIMENT",
        # Financial-markets coverage is broad enough for US30 while the local
        # scoring rules decide which macro headlines actually move the score.
        "topics": "financial_markets",
        "sort": "LATEST",
        "limit": "50",
        "apikey": api_key,
    }
    errors: list[str] = []

    try:
        with httpx.Client(
            timeout=httpx.Timeout(15.0, connect=8.0),
            headers=UA,
            follow_redirects=True,
        ) as client:
            print("[ALPHAVANTAGE] GET NEWS_SENTIMENT", flush=True)
            r = client.get(base, params=params)
            body_preview = (r.text or "")[:500].replace("\n", " ").replace("\r", " ")
            print(
                f"[ALPHAVANTAGE] HTTP {r.status_code} "
                f"content-type={r.headers.get('content-type')} body={body_preview!r}",
                flush=True,
            )
            r.raise_for_status()
            data = r.json()

        # Alpha Vantage returns informational/rate-limit messages as JSON too.
        if data.get("Error Message"):
            raise RuntimeError(str(data.get("Error Message")))
        if data.get("Information"):
            raise RuntimeError(str(data.get("Information")))
        if data.get("Note"):
            raise RuntimeError(str(data.get("Note")))

        feed = data.get("feed") or []
        normalized: list[dict] = []
        for a in feed:
            source = str(a.get("source") or "")
            normalized.append({
                "title": a.get("title"),
                "url": a.get("url"),
                "domain": source,
                "published_at": a.get("time_published"),
                "provider_sentiment": a.get("overall_sentiment_score"),
            })

        print(f"[ALPHAVANTAGE] JSON OK articles={len(normalized)}", flush=True)
        return normalized, errors

    except Exception as exc:
        detail = str(exc).replace("\n", " ")[:800]
        errors.append(f"AlphaVantage:{type(exc).__name__}:{detail}")
        print(f"[ALPHAVANTAGE] ERROR {type(exc).__name__}: {detail}", flush=True)
        return [], errors


def _gdelt_news() -> tuple[list[dict], list[str]]:
    query = '(Federal Reserve OR FOMC OR inflation OR CPI OR payrolls OR recession OR tariffs OR banking OR Treasury OR yields)'
    base = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": "50",
        "format": "json",
        "sort": "HybridRel",
    }
    errors: list[str] = []

    for attempt in range(3):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(15.0, connect=8.0),
                headers=UA,
                follow_redirects=True,
            ) as client:
                print(f"[GDELT] fallback attempt {attempt+1}/3 GET {base}", flush=True)
                r = client.get(base, params=params)
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    wait = (
                        min(float(retry_after), 8.0)
                        if retry_after and retry_after.replace(".", "", 1).isdigit()
                        else (1.5 * (attempt + 1))
                    )
                    errors.append(f"GDELT:HTTP429:attempt{attempt+1}")
                    if attempt < 2:
                        time.sleep(wait)
                        continue

                r.raise_for_status()
                data = r.json()
                articles = data.get("articles") or []
                normalized = [{
                    "title": a.get("title"),
                    "url": a.get("url"),
                    "domain": a.get("domain"),
                    "published_at": a.get("seendate"),
                    "provider_sentiment": None,
                } for a in articles]
                print(f"[GDELT] fallback JSON OK articles={len(normalized)}", flush=True)
                return normalized, errors

        except Exception as exc:
            detail = str(exc).replace("\n", " ")[:800]
            errors.append(f"GDELT:{type(exc).__name__}:attempt{attempt+1}:{detail}")
            print(f"[GDELT] fallback attempt {attempt+1} ERROR {type(exc).__name__}: {detail}", flush=True)
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))

    return [], errors


def get_news(force: bool = False) -> dict:
    ts, old = CACHE["news"]
    if not force and time.time() - ts < 300 and old:
        return old

    errors: list[str] = []
    api_key = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()

    # PRIMARY: Alpha Vantage Market News & Sentiment.
    if api_key:
        articles, alpha_errors = _alpha_vantage_news(api_key)
        errors.extend(alpha_errors)
        if articles:
            items, reasons, score = _score_normalized_articles(articles)
            out = {
                "score": score,
                "items": items,
                "reasons": reasons,
                "source": "Alpha Vantage News & Sentiment",
                "status": "LIVE" if items else "NO_FRESH_MATCHES",
                "quality": "PRIMARY",
                "fetched_at": _iso_now(),
                "errors": errors,
                "is_usable": True,
                "is_stale": False,
            }
            CACHE["news"] = (time.time(), out)
            _save_last_valid_news(out)
            return out
    else:
        errors.append("AlphaVantage:API_KEY_MISSING")
        print("[ALPHAVANTAGE] ALPHAVANTAGE_API_KEY missing; using GDELT fallback", flush=True)

    # FALLBACK: existing GDELT path.
    gdelt_articles, gdelt_errors = _gdelt_news()
    errors.extend(gdelt_errors)
    if gdelt_articles:
        items, reasons, score = _score_normalized_articles(gdelt_articles)
        out = {
            "score": score,
            "items": items,
            "reasons": reasons,
            "source": "GDELT DOC API · fallback",
            "status": "FALLBACK_LIVE" if items else "NO_FRESH_MATCHES",
            "quality": "FALLBACK",
            "fetched_at": _iso_now(),
            "errors": errors,
            "is_usable": True,
            "is_stale": False,
        }
        CACHE["news"] = (time.time(), out)
        _save_last_valid_news(out)
        return out

    # Provider outages must never become a fake neutral 0.0.
    last = _load_last_valid_news() or old
    if last:
        age = _news_age_minutes(last)
        stale = dict(last)
        stale["source"] = f"{last.get('source', 'News')} · last valid cache"
        stale["status"] = "STALE_LAST_VALID"
        stale["quality"] = "STALE"
        stale["is_stale"] = True
        stale["is_usable"] = bool(age is not None and age <= 180)
        stale["stale_age_minutes"] = round(age, 1) if age is not None else None
        stale["errors"] = errors
        CACHE["news"] = (time.time(), stale)
        return stale

    out = {
        "score": None,
        "items": [],
        "reasons": [],
        "source": "Alpha Vantage + GDELT",
        "status": "UNAVAILABLE",
        "quality": "NONE",
        "fetched_at": _iso_now(),
        "errors": errors,
        "is_usable": False,
        "is_stale": True,
    }
    CACHE["news"] = (time.time(), out)
    return out
