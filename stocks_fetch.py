import json
import math
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT = DATA_DIR / "stocks.json"

STOCKS = [
    ("NVDA", "NVIDIA", "AI"),
    ("AMD", "AMD", "반도체"),
    ("AVGO", "Broadcom", "반도체"),
    ("MU", "Micron", "반도체"),
    ("TSM", "TSMC", "반도체"),
    ("INTC", "Intel", "반도체"),
    ("QCOM", "Qualcomm", "반도체"),
    ("MRVL", "Marvell", "반도체"),
    ("AAPL", "Apple", "빅테크"),
    ("MSFT", "Microsoft", "빅테크"),
    ("GOOGL", "Alphabet", "빅테크"),
    ("AMZN", "Amazon", "빅테크"),
    ("META", "Meta", "빅테크"),
    ("TSLA", "Tesla", "AI"),
    ("PLTR", "Palantir", "AI"),
    ("IONQ", "IonQ", "양자"),
    ("RGTI", "Rigetti Computing", "양자"),
    ("QBTS", "D-Wave Quantum", "양자"),
    ("RKLB", "Rocket Lab", "우주항공"),
    ("ASTS", "AST SpaceMobile", "우주항공"),
    ("LUNR", "Intuitive Machines", "우주항공"),
    ("RCAT", "Red Cat", "로봇"),
    ("SERV", "Serve Robotics", "로봇"),
    ("OKLO", "Oklo", "에너지"),
    ("SMR", "NuScale Power", "에너지"),
]


def number(value):
    try:
        value = float(value)
        if not math.isfinite(value):
            return None
        return value
    except Exception:
        return None


def get_value(info, *keys):
    for key in keys:
        value = info.get(key)
        if value is not None:
            return number(value)
    return None


def get_latest_quarter_statement(ticker):
    try:
        q = ticker.quarterly_financials
        if q is None or q.empty:
            return None, None, None

        columns = list(q.columns)
        if not columns:
            return None, None, None

        col = columns[0]

        revenue = None
        operating_income = None

        for row in [
            "Total Revenue",
            "Operating Revenue",
        ]:
            if row in q.index:
                revenue = number(q.loc[row, col])
                if revenue is not None:
                    break

        for row in [
            "Operating Income",
            "Operating Income Loss",
        ]:
            if row in q.index:
                operating_income = number(q.loc[row, col])
                if operating_income is not None:
                    break

        quarter = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)

        return revenue, operating_income, quarter

    except Exception as e:
        print(f"[WARN] financials failed: {e}")
        return None, None, None


def fetch_stock(symbol, name, category):
    ticker = yf.Ticker(symbol)

    try:
        fast = ticker.fast_info
        price = number(fast.get("last_price"))
        previous_close = number(fast.get("previous_close"))
    except Exception:
        price = None
        previous_close = None

    change = None
    if price is not None and previous_close not in (None, 0):
        change = (price / previous_close - 1) * 100

    revenue, operating_income, quarter = get_latest_quarter_statement(ticker)

    return {
        "symbol": symbol,
        "name": name,
        "category": category,
        "price": price,
        "change": change,
        "currency": "USD",
        "revenue": revenue,
        "operatingIncome": operating_income,
        "quarter": quarter,
    }


def main():
    updated = datetime.now(timezone.utc).isoformat()
    stocks = []

    for symbol, name, category in STOCKS:
        try:
            item = fetch_stock(symbol, name, category)
            stocks.append(item)
            print(
                f"{symbol}: price={item['price']} "
                f"change={item['change']} "
                f"revenue={item['revenue']} "
                f"op={item['operatingIncome']}"
            )
        except Exception as e:
            print(f"[WARN] {symbol}: {e}")
            stocks.append({
                "symbol": symbol,
                "name": name,
                "category": category,
                "price": None,
                "change": None,
                "currency": "USD",
                "revenue": None,
                "operatingIncome": None,
                "quarter": None,
            })

    output = {
        "updated": updated,
        "market": "NASDAQ/US",
        "stocks": stocks,
    }

    OUTPUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Stocks updated: {OUTPUT}")


if __name__ == "__main__":
    main()
