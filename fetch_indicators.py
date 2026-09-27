"""
매크로 대시보드용 지표 사전 수집 스크립트.
GitHub Actions에서 매일 실행되어 data/indicators.json 을 갱신합니다.

대시보드(index.html)의 DATA.items[].id 와 ITEMS 키가 반드시 일치해야 합니다.
"""
from __future__ import annotations

import bisect
import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MacroDashboardBot/1.0)"}
MONTHS = 36
OUTPUT_PATH = "data/indicators.json"

# BLS(미 노동통계국) 공식 API 키 — 없어도 동작하지만, 이 워크플로처럼 30분마다
# 호출하면 무키 한도(25회/일)에 금방 걸리므로 무료 키 발급을 권장합니다.
# 발급: https://data.bls.gov/registrationEngine/  →  GitHub 리포 Settings > Secrets
# 에 BLS_API_KEY 로 등록하면 자동으로 사용됩니다 (500회/일로 상향).
BLS_API_KEY = os.environ.get("BLS_API_KEY")


# ---------------------------------------------------------------------------
# Yahoo Finance
# ---------------------------------------------------------------------------
def fetch_yahoo_daily_points(symbol: str, range_: str = "5y") -> list[tuple[str, float]]:
    """일별 (날짜, 종가) 목록. Yahoo의 월봉(interval=1mo)과 달리 '진행 중인 이번 달'의
    최신 거래일도 그대로 들어온다."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_, "interval": "1d"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    result = r.json()["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    points: list[tuple[str, float]] = []
    for ts, c in zip(timestamps, closes):
        if c is None:
            continue
        date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        points.append((date, round(c, 2)))
    return points


def fetch_yahoo_monthly(symbol: str, range_: str = "5y") -> list[float]:
    """일별 종가를 월별 마지막 값으로 직접 집계.
    Yahoo의 1mo 캔들은 그 달이 끝나야 생기기 때문에, 이 방식 대신 이걸 써야
    '이번 달' 최신 데이터가 즉시 반영된다 (그동안 계속 지난달에 머물던 원인)."""
    return resample_monthly(fetch_yahoo_daily_points(symbol, range_))


def fetch_yahoo_yield_monthly(symbol: str, range_: str = "5y") -> list[float]:
    return [round(v / 10, 2) for v in fetch_yahoo_monthly(symbol, range_)]


def fetch_yahoo_series(symbol: str, range_: str = "5y", interval: str = "1mo") -> list[float]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_, "interval": interval}
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    result = data["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    return [round(v, 2) for v in closes if v is not None]


def fetch_yahoo_yield(symbol: str) -> list[float]:
    """CBOE 수익률 지수(^TNX 등)는 실제 수익률의 10배로 고시됨."""
    raw = fetch_yahoo_series(symbol)
    return [round(v / 10, 2) for v in raw]


# ---------------------------------------------------------------------------
# FRED (CSV 공개 다운로드)
# ---------------------------------------------------------------------------
def fetch_fred_series(series_id: str) -> list[tuple[str, float]]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    reader = csv.reader(io.StringIO(r.text))
    next(reader, None)  # 헤더 스킵
    points: list[tuple[str, float]] = []
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


def to_yoy(points: list[tuple[str, float]]) -> list[float]:
    out: list[float] = []
    for i in range(12, len(points)):
        prev_v = points[i - 12][1]
        cur_v = points[i][1]
        if prev_v == 0:
            continue
        out.append(round((cur_v - prev_v) / prev_v * 100, 2))
    return out


def resample_monthly(points: list[tuple[str, float]]) -> list[float]:
    """일·주 데이터를 월별 마지막 관측치로 집약."""
    seen: dict[str, float] = {}
    for date, v in points:
        seen[date[:7]] = v
    return [round(v, 2) for v in seen.values()]


def fetch_yoy_from_fred(series_id: str) -> list[float]:
    return to_yoy(fetch_fred_series(series_id))


def fetch_monthly_from_fred_daily(series_id: str) -> list[float]:
    return resample_monthly(fetch_fred_series(series_id))


def fetch_monthly_from_fred_direct(series_id: str) -> list[float]:
    return [round(v, 2) for _, v in fetch_fred_series(series_id)]


def fetch_mom_change(series_id: str) -> list[float]:
    """월별 수준 시계열의 전월 대비 변화량 (예: 비농업고용 천 명)."""
    levels = fetch_monthly_from_fred_direct(series_id)
    if len(levels) < 2:
        return []
    return [round(levels[i] - levels[i - 1], 2) for i in range(1, len(levels))]


# ---------------------------------------------------------------------------
# BLS (미 노동통계국) — CPI 공식 1차 소스, 직접 API 호출
# https://www.bls.gov/developers/api_signature_v2.htm
# ---------------------------------------------------------------------------
def fetch_bls_series(series_id: str) -> list[tuple[str, float]]:
    url = f"https://api.bls.gov/publicAPI/v2/timeseries/data/{series_id}"
    params = {"registrationkey": BLS_API_KEY} if BLS_API_KEY else {}
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API 실패: {series_id} -> {payload.get('message')}")
    points: list[tuple[str, float]] = []
    for e in payload["Results"]["series"][0]["data"]:
        if e["period"] == "M13":  # 연평균 행 제외
            continue
        date = f'{e["year"]}-{e["period"][1:]}'  # 예: 2026-08
        points.append((date, float(e["value"])))
    points.sort(key=lambda p: p[0])  # to_yoy는 오름차순 정렬을 전제로 함
    return points


def fetch_yoy_from_bls(series_id: str) -> list[float]:
    return to_yoy(fetch_bls_series(series_id))


# ---------------------------------------------------------------------------
# 복합 지표
# ---------------------------------------------------------------------------
def fetch_buffett_indicator() -> list[float]:
    """윌셔5000 / 명목 GDP * 100 (근사). GDP는 분기값이므로 forward-fill."""
    wilshire = fetch_fred_series("WILL5000PRFC")
    gdp = sorted(fetch_fred_series("GDP"), key=lambda p: p[0])
    gdp_dates = [d for d, _ in gdp]
    gdp_vals = [v for _, v in gdp]
    ratio_points: list[tuple[str, float]] = []
    for date, w in wilshire:
        idx = bisect.bisect_right(gdp_dates, date) - 1
        if idx < 0:
            continue
        g = gdp_vals[idx]
        if not g:
            continue
        ratio_points.append((date, w / g * 100))
    return resample_monthly(ratio_points)


def compute_rsi(closes: list[float], period: int = 14) -> list[float]:
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def rsi_from_avg(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - (100.0 / (1.0 + rs))

    rsis = [rsi_from_avg(avg_gain, avg_loss)]
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsis.append(rsi_from_avg(avg_gain, avg_loss))
    return [round(v, 2) for v in rsis]


def fetch_nasdaq_rsi() -> list[float]:
    closes = fetch_yahoo_series("^IXIC", range_="1y", interval="1d")
    return compute_rsi(closes, period=14)


# ---------------------------------------------------------------------------
# 대시보드 item.id → (수집 함수, 보관 포인트 수)
# ---------------------------------------------------------------------------
ITEMS: dict[str, tuple] = {
    # 기준금리 — 연준 목표 상단 (DFEDTARU), 없으면 실효금리(FEDFUNDS)
    "fedfunds": (lambda: fetch_monthly_from_fred_direct("DFEDTARU") or fetch_monthly_from_fred_direct("FEDFUNDS"), MONTHS),
    # 물가 — CPI는 발표기관인 BLS API에서 직접 수신 (CUUR0000SA0 / CUUR0000SA0L1E)
    "us_cpi": (lambda: fetch_yoy_from_bls("CUUR0000SA0"), MONTHS),
    "core_cpi": (lambda: fetch_yoy_from_bls("CUUR0000SA0L1E"), MONTHS),
    "pce_headline": (lambda: fetch_yoy_from_fred("PCEPI"), MONTHS),
    "pce_core": (lambda: fetch_yoy_from_fred("PCEPILFE"), MONTHS),
    "ppi_headline": (lambda: fetch_yoy_from_fred("PPIFIS"), MONTHS),
    "ppi_core": (lambda: fetch_yoy_from_fred("PPIFES"), MONTHS),
    # 고용
    "nfp": (lambda: fetch_mom_change("PAYEMS"), MONTHS),  # 전월 대비 천 명
    "urate": (lambda: fetch_monthly_from_fred_direct("UNRATE"), MONTHS),
    "earnings": (lambda: fetch_yoy_from_fred("CES0500000003"), MONTHS),  # 평균 시간당 임금 YoY
    "participation": (lambda: fetch_monthly_from_fred_direct("CIVPART"), MONTHS),
    # 국채
    "us2y": (lambda: fetch_monthly_from_fred_daily("DGS2"), MONTHS),
    "us5y": (lambda: fetch_monthly_from_fred_daily("DGS5"), MONTHS),
    "us10y": (lambda: fetch_yahoo_yield_monthly("^TNX"), MONTHS),
    "us30y": (lambda: fetch_monthly_from_fred_daily("DGS30"), MONTHS),
    # 원자재
    "wti": (lambda: fetch_yahoo_monthly("CL=F"), MONTHS),
    "gold": (lambda: fetch_yahoo_monthly("GC=F"), MONTHS),
    "copper": (lambda: fetch_yahoo_monthly("HG=F"), MONTHS),
    # 시장지표
    "buffett": (fetch_buffett_indicator, MONTHS),
    "nasdaq_rsi": (fetch_nasdaq_rsi, 60),  # 일별 RSI → 최근 60거래일
    "btc": (lambda: fetch_yahoo_monthly("BTC-USD", range_="3y"), MONTHS),
}


def main() -> None:
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": {},
    }
    failures: list[str] = []

    for item_id, (fetcher, keep) in ITEMS.items():
        try:
            series = fetcher()[-keep:]
            if len(series) < 4:
                raise ValueError(f"데이터 포인트 부족 ({len(series)}개)")
            result["items"][item_id] = {"series": series, "live": True}
            print(f"[OK] {item_id}: {len(series)}개 데이터 포인트 (최신={series[-1]})")
        except Exception as e:
            print(f"[FAIL] {item_id}: {e}", file=sys.stderr)
            result["items"][item_id] = {"series": [], "live": False}
            failures.append(item_id)
        time.sleep(0.8)  # 과도한 연속 요청 방지

    os.makedirs(os.path.dirname(OUTPUT_PATH) or ".", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n저장 완료 → {OUTPUT_PATH}")
    if failures:
        print(f"일부 지표 수집 실패: {failures}", file=sys.stderr)
        # 워크플로는 실패시키지 않음 — 대시보드가 live=false 항목을 예시 데이터로 대체


if __name__ == "__main__":
    main()
