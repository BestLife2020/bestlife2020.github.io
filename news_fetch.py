import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
import requests

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT = DATA_DIR / "news.json"

CATEGORIES = {
    "ai": {
        "title": "AI",
        "query": '"artificial intelligence" OR AI OR "AI agent"'
    },
    "semiconductor": {
        "title": "반도체",
        "query": 'semiconductor OR NVIDIA OR AMD OR Broadcom OR TSMC'
    },
    "quantum": {
        "title": "양자",
        "query": 'quantum computing OR quantum computer OR quantum chip'
    },
    "space": {
        "title": "우주항공",
        "query": 'space OR NASA OR SpaceX OR satellite OR aerospace'
    },
    "robotics": {
        "title": "로봇",
        "query": 'robotics OR humanoid robot OR industrial robot'
    },
    "energy": {
        "title": "에너지",
        "query": 'nuclear energy OR SMR OR uranium OR energy storage'
    },
    "bigtech": {
        "title": "빅테크",
        "query": 'Apple OR Microsoft OR Amazon OR Alphabet OR Meta OR Tesla'
    }
}

TIMEOUT = 30
MAX_ARTICLES = 8


def now_utc():
    return datetime.now(timezone.utc)


def choose_provider(now):
    # 00-09 GNews, 10-19 NewsAPI, 20-29 GNews, 30-39 NewsAPI...
    slot = (now.minute // 10) % 2
    return "gnews" if slot == 0 else "newsapi"


def clean_text(value):
    if not value:
        return ""
    return " ".join(str(value).split())


def dedupe(articles):
    seen = set()
    result = []
    for article in articles:
        key = article.get("url") or article.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(article)
    return result


def fetch_gnews(query, api_key, from_dt):
    if not api_key:
        return []

    params = {
        "q": query,
        "lang": "en",
        "country": "us",
        "max": MAX_ARTICLES,
        "sortby": "publishedAt",
        "from": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "apikey": api_key,
    }

    r = requests.get(
        "https://gnews.io/api/v4/search",
        params=params,
        timeout=TIMEOUT,
    )
    r.raise_for_status()

    data = r.json()
    result = []

    for a in data.get("articles", []):
        result.append({
            "title": clean_text(a.get("title")),
            "summary": clean_text(a.get("description")),
            "url": a.get("url", ""),
            "press": clean_text((a.get("source") or {}).get("name")),
            "time": a.get("publishedAt", ""),
        })

    return dedupe(result)


def fetch_newsapi(query, api_key, from_dt):
    if not api_key:
        return []

    params = {
        "q": query,
        "from": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": MAX_ARTICLES,
    }

    r = requests.get(
        "https://newsapi.org/v2/everything",
        params=params,
        headers={"X-Api-Key": api_key},
        timeout=TIMEOUT,
    )
    r.raise_for_status()

    data = r.json()
    if data.get("status") != "ok":
        raise RuntimeError(data.get("message", "NewsAPI error"))

    result = []

    for a in data.get("articles", []):
        result.append({
            "title": clean_text(a.get("title")),
            "summary": clean_text(a.get("description")),
            "url": a.get("url", ""),
            "press": clean_text((a.get("source") or {}).get("name")),
            "time": a.get("publishedAt", ""),
        })

    return dedupe(result)


def fetch_category(category, provider, from_dt):
    query = category["query"]

    try:
        if provider == "gnews":
            articles = fetch_gnews(
                query,
                os.getenv("GNEWS_API_KEY", ""),
                from_dt,
            )
        else:
            articles = fetch_newsapi(
                query,
                os.getenv("NEWSAPI_API_KEY", ""),
                from_dt,
            )

        # API 1개가 실패하거나 키가 없으면 다른 API를 fallback으로 사용
        if not articles:
            if provider == "gnews":
                articles = fetch_newsapi(
                    query,
                    os.getenv("NEWSAPI_API_KEY", ""),
                    from_dt,
                )
                fallback = "newsapi"
            else:
                articles = fetch_gnews(
                    query,
                    os.getenv("GNEWS_API_KEY", ""),
                    from_dt,
                )
                fallback = "gnews"
            return articles, fallback

        return articles, provider

    except Exception as e:
        print(f"[WARN] {category['title']} / {provider}: {e}")

        try:
            if provider == "gnews":
                articles = fetch_newsapi(
                    query,
                    os.getenv("NEWSAPI_API_KEY", ""),
                    from_dt,
                )
                return articles, "newsapi-fallback"

            articles = fetch_gnews(
                query,
                os.getenv("GNEWS_API_KEY", ""),
                from_dt,
            )
            return articles, "gnews-fallback"

        except Exception as e2:
            print(f"[WARN] fallback failed: {e2}")
            return [], provider


def main():
    now = now_utc()
    provider = choose_provider(now)

    # 최근 24시간 뉴스만 검색
    from_dt = now - timedelta(hours=24)

    result = {
        "updated": now.isoformat(),
        "provider": provider,
        "categories": {},
    }

    for key, category in CATEGORIES.items():
        articles, actual_provider = fetch_category(
            category,
            provider,
            from_dt,
        )

        result["categories"][key] = {
            "title": category["title"],
            "source": actual_provider,
            "count": len(articles),
            "news": articles,
        }

    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"News updated: {OUTPUT}")
    print(f"Provider slot: {provider}")


if __name__ == "__main__":
    main()
