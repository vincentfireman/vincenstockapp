"""
주식 브리핑 앱 - 1일 1회 데이터 수집 스크립트

이 스크립트가 하는 일:
1. 관심 종목(NVDA, INTC) 목록을 순회하면서
2. Finnhub API로 시세(quote)와 지표(metric)를 가져오고
3. 필요한 값만 뽑아서 data.json 파일 하나로 저장한다

나중에 이 스크립트를 GitHub Actions에 걸어두면
사람이 손대지 않아도 매일 자동으로 data.json이 갱신된다.
"""

import os
import requests
import json
from datetime import datetime

# API 키는 이제 코드에 직접 적지 않고, "환경변수"라는 곳에서 읽어옵니다.
# - 로컬(내 컴퓨터)에서 테스트할 땐 아래 FALLBACK_KEY에 본인 키를 잠깐 적어서 써도 되지만,
#   GitHub에 올리기 전에는 반드시 다시 빈 문자열로 지워야 합니다.
# - GitHub Actions에서 실행할 땐 GitHub Secrets에 등록한 값이 자동으로 여기에 들어옵니다.
FALLBACK_KEY = ""  # 로컬 테스트용. GitHub에 올리기 전 반드시 빈 문자열("")로 되돌릴 것!
API_KEY = os.environ.get("FINNHUB_API_KEY") or FALLBACK_KEY

if not API_KEY:
    raise SystemExit("API 키가 없어요. FALLBACK_KEY에 임시로 적거나 FINNHUB_API_KEY 환경변수를 설정하세요.")

# 1차 버전 관심 종목 목록. 나중에 종목을 추가하고 싶으면 이 리스트에 티커만 추가하면 됨.
TICKERS = ["NVDA", "INTC"]

BASE_URL = "https://finnhub.io/api/v1"


def fetch_quote(symbol):
    """현재가, 전일 대비 변동률 등 시세 정보를 가져온다."""
    url = f"{BASE_URL}/quote"
    params = {"symbol": symbol, "token": API_KEY}
    response = requests.get(url, params=params)
    response.raise_for_status()  # 요청이 실패하면 여기서 에러를 발생시켜 바로 알 수 있게 함
    return response.json()


def fetch_metrics(symbol):
    """PER, 52주 최고/최저가 같은 지표 정보를 가져온다."""
    url = f"{BASE_URL}/stock/metric"
    params = {"symbol": symbol, "metric": "all", "token": API_KEY}
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json().get("metric", {})


def build_easy_explanation(quote, metrics):
    """
    숫자를 그대로 보여주지 않고 쉬운 문장으로 바꿔주는 부분.
    지금은 간단한 규칙 기반이고, 나중에 여기를 AI 호출로 바꾸면
    더 자연스러운 문장을 만들 수 있다.
    """
    change_pct = quote.get("dp", 0)  # 전일 대비 변동률(%)
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

        result["stocks"][symbol] = {
            "price": quote.get("c"),
            "change_pct": quote.get("dp"),
            "prev_close": quote.get("pc"),
            "pe_ttm": metrics.get("peTTM"),
            "week52_high": metrics.get("52WeekHigh"),
            "week52_low": metrics.get("52WeekLow"),
            "easy_explanation": build_easy_explanation(quote, metrics),
        }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("완료! data.json 파일이 생성되었어요.")


if __name__ == "__main__":
    main()
