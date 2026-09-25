"""
매크로 대시보드용 지표 사전 수집 스크립트.
GitHub Actions에서 매일 실행되어 data/indicators.json 을 갱신합니다.
"""
import csv
import io
import json
import sys
import time
from datetime import datetime, timezone

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MacroDashboardBot/1.0)"}
MONTHS = 36
OUTPUT_PATH = "data/indicators.json"


def fetch_yahoo_series(symbol, range_="5y", interval="1mo"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_, "interval": interval}
    r = requests.get(url, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    result = data["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    return [round(v, 2) for v in closes if v is not None]


def fetch_yahoo_yield(symbol):
    # CBOE 수익률 지수(^TNX 등)는 실제 수익률의 10배로 고시됨
    raw = fetch_yahoo_series(symbol)
    return [round(v / 10, 2) for v in raw]


def fetch_fred_series(series_id):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    reader = csv.reader(io.StringIO(r.text))
    next(reader, None)  # 헤더 스킵
    points = []
    for row in reader:
        if len(row) < 2:
            continue
        date, raw = row[0], row[1]
        if raw in (".", ""):
            continue
        try:
            points.append((date, float(raw)))
        except ValueError:
            continue
    return points


def to_yoy(points):
    out = []
    for i in range(12, len(points)):
        prev_v = points[i - 12][1]
        cur_v = points[i][1]
        if prev_v == 0:
            continue
        out.append(round((cur_v - prev_v) / prev_v * 100, 2))
    return out


def resample_monthly(points):
    seen = {}
    for date, v in points:
        seen[date[:7]] = v  # 각 월의 마지막 관측치로 덮어씀
    return [round(v, 2) for v in seen.values()]


def fetch_yoy_from_fred(series_id):
    return to_yoy(fetch_fred_series(series_id))


def fetch_monthly_from_fred_daily(series_id):
    return resample_monthly(fetch_fred_series(series_id))


def fetch_monthly_from_fred_direct(series_id):
    return [round(v, 2) for _, v in fetch_fred_series(series_id)]


def fetch_buffett_indicator():
    """윌셔5000 지수 / 명목 GDP * 100 (근사치). GDP는 분기 발표이므로 직전 발표치를 이후 일자에 그대로 적용(forward-fill)."""
    import bisect

    wilshire = fetch_fred_series("WILL5000PRFC")  # 일별, 지수 포인트 ≈ 시가총액(십억 달러) 근사
    gdp = sorted(fetch_fred_series("GDP"), key=lambda p: p[0])  # 분기, 십억 달러
    gdp_dates = [d for d, _ in gdp]
    gdp_vals = [v for _, v in gdp]

    ratio_points = []
    for date, w in wilshire:
        idx = bisect.bisect_right(gdp_dates, date) - 1
        if idx < 0:
            continue
        g = gdp_vals[idx]
        if not g:
            continue
        ratio_points.append((date, w / g * 100))
    return resample_monthly(ratio_points)


def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def rsi_from_avg(ag, al):
        if al == 0:
            return 100.0
        rs = ag / al
        return 100 - (100 / (1 + rs))

    rsis = [rsi_from_avg(avg_gain, avg_loss)]
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsis.append(rsi_from_avg(avg_gain, avg_loss))
    return [round(v, 2) for v in rsis]


def fetch_nasdaq_rsi():
    closes = fetch_yahoo_series("^IXIC", range_="1y", interval="1d")
    return compute_rsi(closes, period=14)


# 대시보드의 item.id 와 반드시 일치해야 함
# 값: (수집 함수, 저장할 최근 데이터 포인트 개수)
ITEMS = {
    "us_cpi": (lambda: fetch_yoy_from_fred("CPIAUCSL"), MONTHS),
    "core_cpi": (lambda: fetch_yoy_from_fred("CPILFESL"), MONTHS),
    "kr_cpi": (lambda: fetch_yoy_from_fred("KORCPIALLMINMEI"), MONTHS),
    "us10y": (lambda: fetch_yahoo_yield("^TNX"), MONTHS),
    "us2y": (lambda: fetch_monthly_from_fred_daily("DGS2"), MONTHS),
    "kr10y": (lambda: fetch_monthly_from_fred_direct("IRLTLT01KRM156N"), MONTHS),
    "wti": (lambda: fetch_yahoo_series("CL=F"), MONTHS),
    "gold": (lambda: fetch_yahoo_series("GC=F"), MONTHS),
    "copper": (lambda: fetch_yahoo_series("HG=F"), MONTHS),
    "buffett": (fetch_buffett_indicator, MONTHS),
    "nasdaq_rsi": (fetch_nasdaq_rsi, 60),   # RSI는 일별 지표이므로 최근 60거래일 보관
    "btc": (lambda: fetch_yahoo_series("BTC-USD", range_="3y", interval="1mo"), MONTHS),
}


def main():
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": {},
    }
    failures = []
    for item_id, (fetcher, keep) in ITEMS.items():
        try:
            series = fetcher()[-keep:]
            if len(series) < 4:
                raise ValueError("데이터 포인트 부족")
            result["items"][item_id] = {"series": series, "live": True}
            print(f"[OK] {item_id}: {len(series)}개 데이터 포인트")
        except Exception as e:
            print(f"[FAIL] {item_id}: {e}", file=sys.stderr)
            result["items"][item_id] = {"series": [], "live": False}
            failures.append(item_id)
        time.sleep(1)  # 과도한 연속 요청 방지

    import os
    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if failures:
        print(f"일부 지표 수집 실패: {failures}", file=sys.stderr)
        # 워크플로 자체는 실패시키지 않음 (대시보드가 실패 항목은 예시 데이터로 대체)


if __name__ == "__main__":
    main()
