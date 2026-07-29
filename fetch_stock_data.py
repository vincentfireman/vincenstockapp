"""
주식 브리핑 앱 - 1일 1회 데이터 수집 스크립트

이 스크립트가 하는 일:
1. 관심 종목(NVDA, INTC) 목록을 순회하면서
2. Finnhub API로 시세(quote), 지표(metric), 최근 뉴스, 애널리스트 의견을 가져오고
3. 필요한 값만 뽑아서 data.json 파일 하나로 저장한다

나중에 이 스크립트를 GitHub Actions에 걸어두면
사람이 손대지 않아도 매일 자동으로 data.json이 갱신된다.
"""

import os
import requests
import json
from datetime import datetime, timedelta

# API 키는 이제 코드에 직접 적지 않고, "환경변수"라는 곳에서 읽어옵니다.
# - 로컬(내 컴퓨터)에서 테스트할 땐 아래 FALLBACK_KEY에 본인 키를 잠깐 적어서 써도 되지만,
#   GitHub에 올리기 전에는 반드시 다시 빈 문자열로 지워야 합니다.
# - GitHub Actions에서 실행할 땐 GitHub Secrets에 등록한 값이 자동으로 여기에 들어옵니다.
FALLBACK_KEY = ""  # 로컬 테스트용. GitHub에 올리기 전 반드시 빈 문자열("")로 되돌릴 것!
API_KEY = os.environ.get("FINNHUB_API_KEY") or FALLBACK_KEY

# 뉴스 요약을 만들어줄 Claude API 키. 마찬가지로 환경변수(GitHub Secrets)에서 읽어온다.
ANTHROPIC_FALLBACK_KEY = ""  # 로컬 테스트용. GitHub에 올리기 전 반드시 빈 문자열("")로 되돌릴 것!
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or ANTHROPIC_FALLBACK_KEY
print(f"[진단] ANTHROPIC_API_KEY 길이: {len(ANTHROPIC_API_KEY)}자")  # 값은 안 찍고 길이만 확인용

if not API_KEY:
    raise SystemExit("Finnhub API 키가 없어요. FALLBACK_KEY에 임시로 적거나 FINNHUB_API_KEY 환경변수를 설정하세요.")

# 종목별 회사 이름(뉴스 헤드라인에 이 단어가 실제로 들어있는지 걸러낼 때 씀)
COMPANY_KEYWORDS = {
    "NVDA": ["nvidia", "nvda"],
    "INTC": ["intel", "intc"],
}
COMPANY_NAMES_KR = {"NVDA": "엔비디아", "INTC": "인텔"}

# 1차 버전 관심 종목 목록. 나중에 종목을 추가하고 싶으면 이 리스트에 티커만 추가하면 됨.
TICKERS = ["NVDA", "INTC"]

BASE_URL = "https://finnhub.io/api/v1"


def fetch_quote(symbol):
    """현재가, 전일 대비 변동률 등 시세 정보를 가져온다."""
    url = f"{BASE_URL}/quote"
    params = {"symbol": symbol, "token": API_KEY}
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def fetch_metrics(symbol):
    """PER, 52주 최고/최저가 같은 지표 정보를 가져온다."""
    url = f"{BASE_URL}/stock/metric"
    params = {"symbol": symbol, "metric": "all", "token": API_KEY}
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json().get("metric", {})


def fetch_news(symbol, limit=4, pool=25):
    """
    최근 일주일 이내 뉴스를 넉넉히 가져온 뒤(pool개),
    헤드라인에 실제로 회사 이름이 들어간 것만 걸러서(limit개) 반환한다.
    Finnhub 무료 티어는 "관련" 뉴스에 업종 전체 뉴스를 섞어 줄 때가 있어서
    이 필터링이 없으면 엉뚱한 회사 뉴스가 섞여 들어온다.
    """
    today = datetime.now()
    week_ago = today - timedelta(days=7)
    url = f"{BASE_URL}/company-news"
    params = {
        "symbol": symbol,
        "from": week_ago.strftime("%Y-%m-%d"),
        "to": today.strftime("%Y-%m-%d"),
        "token": API_KEY,
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    articles = response.json()

    keywords = COMPANY_KEYWORDS.get(symbol, [symbol.lower()])
    relevant = [
        a for a in articles[:pool]
        if any(kw in (a.get("headline") or "").lower() for kw in keywords)
    ]

    news_list = []
    for article in relevant[:limit]:
        news_list.append({
            "headline": article.get("headline"),
            "summary": article.get("summary"),
            "source": article.get("source"),
            "url": article.get("url"),
        })
    return news_list


def summarize_news_with_claude(symbol, news_list):
    """
    걸러낸 뉴스 헤드라인·요약을 Claude API에 보내서
    초보 투자자도 이해하기 쉬운 3~4문장짜리 요약을 만든다.
    Claude API 키가 없거나 호출이 실패하면, 헤드라인만 이어붙인
    간단한 문장으로 대신한다(앱이 죽지 않도록).
    """
    company = COMPANY_NAMES_KR.get(symbol, symbol)

    if not news_list:
        return f"최근 일주일 사이 {company} 관련 뉴스가 눈에 띄게 없었어요."

    if not ANTHROPIC_API_KEY:
        print(f"  ⚠️ ANTHROPIC_API_KEY가 비어있어요 ({symbol}). GitHub Secrets 등록을 확인하세요.")
        headlines = " / ".join(n["headline"] for n in news_list if n.get("headline"))
        return f"최근 뉴스 헤드라인: {headlines}"

    articles_text = "\n".join(
        f"- {n.get('headline')}: {n.get('summary') or ''}" for n in news_list
    )

    prompt = f"""아래는 {company}({symbol}) 관련 최근 뉴스 목록이야.
이 뉴스들을 종합해서, 주식 투자를 처음 해보는 초보자도 이해할 수 있도록
쉬운 말로 4~5문장짜리 요약을 만들어줘.

규칙:
- 개별 기사를 나열하지 말고, 여러 뉴스를 종합해서 "요즘 이 회사에 이런 흐름이 있다"는 식으로 정리할 것
- 좋은 소식(호재)과 안 좋은 소식(악재)이 둘 다 있으면 각각 짚어줄 것. 어느 한쪽으로만 치우쳐 보이지 않게 균형있게 쓸 것
- 하나의 뉴스가 보는 시각에 따라 호재로도 악재로도 해석될 수 있으면, 그 양면성도 자연스럽게 설명할 것
- 전문 용어는 풀어서 설명할 것
- "사세요/파세요" 같은 투자 권유 표현은 절대 쓰지 말 것
- 사실 위주로, 과장 없이 담백하게 쓸 것
- 요약 문장만 출력하고 다른 말은 붙이지 말 것

뉴스 목록:
{articles_text}
"""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"].strip()
    except Exception as e:
        # 실패 원인을 GitHub Actions 로그에 남겨서 나중에 진단할 수 있게 한다.
        print(f"  ⚠️ Claude 뉴스 요약 실패 ({symbol}): {type(e).__name__}: {e}")
        headlines = " / ".join(n["headline"] for n in news_list if n.get("headline"))
        return f"최근 뉴스 헤드라인: {headlines}"


def fetch_recommendation(symbol):
    """가장 최근 애널리스트 의견 분포(강력매수/매수/중립/매도/강력매도 수)를 가져온다."""
    url = f"{BASE_URL}/stock/recommendation"
    params = {"symbol": symbol, "token": API_KEY}
    response = requests.get(url, params=params)
    response.raise_for_status()
    trends = response.json()
    if not trends:
        return None
    return trends[0]  # 가장 최근 기간이 0번째에 옴


def build_easy_explanation(quote, metrics):
    """
    숫자를 그대로 보여주지 않고 쉬운 문장으로 바꿔주는 부분.
    지금은 간단한 규칙 기반이고, 나중에 여기를 AI 호출로 바꾸면
    더 자연스러운 문장을 만들 수 있다.
    """
    change_pct = quote.get("dp", 0)
    pe = metrics.get("peTTM")
    high52 = metrics.get("52WeekHigh")
    low52 = metrics.get("52WeekLow")
    current = quote.get("c")

    lines = []

    if change_pct is not None:
        direction = "올랐어요" if change_pct >= 0 else "내렸어요"
        lines.append(f"오늘 전일 대비 {abs(change_pct):.2f}% {direction}.")

    if pe:
        lines.append(f"PER은 {pe:.1f}배로, 회사가 1년에 버는 돈의 {pe:.0f}배 가격에 거래되고 있어요.")

    if current and high52 and low52 and high52 != low52:
        position = (current - low52) / (high52 - low52) * 100
        lines.append(f"최근 1년 최저가~최고가 구간에서 {position:.0f}% 지점에 있어요.")

    return " ".join(lines)


def main():
    result = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stocks": {},
    }

    for symbol in TICKERS:
        print(f"{symbol} 데이터를 가져오는 중...")
        quote = fetch_quote(symbol)
        metrics = fetch_metrics(symbol)
        news = fetch_news(symbol)
        news_summary = summarize_news_with_claude(symbol, news)
        recommendation = fetch_recommendation(symbol)

        result["stocks"][symbol] = {
            "price": quote.get("c"),
            "change_pct": quote.get("dp"),
            "prev_close": quote.get("pc"),
            "pe_ttm": metrics.get("peTTM"),
            "week52_high": metrics.get("52WeekHigh"),
            "week52_low": metrics.get("52WeekLow"),
            "easy_explanation": build_easy_explanation(quote, metrics),
            "news": news,
            "news_summary": news_summary,
            "recommendation": recommendation,
        }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("완료! data.json 파일이 생성되었어요.")


if __name__ == "__main__":
    main()
