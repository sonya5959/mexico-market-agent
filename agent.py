"""
============================================================
 멕시코 가전 마켓 인텔리전스 자동화 에이전트
 Mexico Home Appliance Market Intelligence Agent
============================================================

[전체 워크플로우]
  ┌─────────────────────────────────────────────────────────┐
  │  1. 데이터 수집 (Collectors)                             │
  │     ├─ Google News RSS  → 뉴스/이슈 수집                │
  │     ├─ Reddit API(PRAW) → 커뮤니티 반응 수집            │
  │     └─ Apify API        → 이커머스 가격/리뷰 수집       │
  │               ↓                                         │
  │  2. 데이터 전처리 (Preprocessor)                        │
  │     └─ 수집 데이터를 AI 분석용 텍스트로 통합            │
  │               ↓                                         │
  │  3. AI 분석 (Analyzer)                                  │
  │     └─ Claude / OpenAI → 스페인어 분석 + 한국어 리포트 │
  │               ↓                                         │
  │  4. 알림 발송 (Notifier)                                │
  │     └─ Gmail SMTP → HTML 이메일 자동 발송              │
  └─────────────────────────────────────────────────────────┘

[실행 방법]
  1. pip install -r requirements.txt
  2. cp .env.example .env  →  .env 파일에 API 키 입력
  3. python agent.py
"""

import os
import time
import logging
import json
import smtplib
import textwrap
import requests
import feedparser
import praw
import anthropic
import schedule
import pytz
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from openai import OpenAI

# ─── 환경 변수 로드 ────────────────────────────────────────
load_dotenv()

# ─── 로깅 설정 ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# ① 설정값 (Config)
# ══════════════════════════════════════════════════════════
class Config:
    """모든 설정값과 API 키를 중앙에서 관리하는 클래스"""

    # Reddit
    REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
    REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
    REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "MarketIntelligenceBot/1.0")

    # Apify
    APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")

    # AI
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic")  # "anthropic" or "openai"

    # 알림 — Gmail
    GMAIL_SENDER = os.getenv("GMAIL_SENDER")          # 발신 Gmail 주소
    GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")  # Gmail 앱 비밀번호 (16자리)
    GMAIL_RECIPIENT = os.getenv("GMAIL_RECIPIENT")    # 수신 Gmail 주소 (본인 주소로 입력)

    # 에이전트 동작
    LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "1"))

    # 검색 타겟
    NEWS_KEYWORDS = [
        "lavadora México",
        "electrodomésticos México",
        "lavasecadora México",
    ]
    REDDIT_SUBREDDITS = ["mexico", "Monterrey", "cdmx", "guadalajara", "tijuana"]
    REDDIT_SEARCH_QUERY = "lavadora"

    # Apify Actor IDs
    # Mercado Libre 스크래퍼: apify/mercado-libre-scraper (공식) 또는 커뮤니티 Actor
    APIFY_MERCADOLIBRE_ACTOR = "apify/mercado-libre-scraper"
    # Amazon Mexico 스크래퍼
    APIFY_AMAZON_ACTOR = "apify/amazon-product-scraper"


# ══════════════════════════════════════════════════════════
# ② 데이터 수집 모듈 (Collectors)
# ══════════════════════════════════════════════════════════

def collect_google_news(keywords: list[str], lookback_days: int = 1) -> list[dict]:
    """
    구글 뉴스 RSS 피드를 파싱하여 최신 뉴스 기사를 수집합니다.

    Args:
        keywords: 검색할 키워드 리스트 (예: ["lavadora México"])
        lookback_days: 최근 며칠치 뉴스를 가져올지 (기본: 1일)

    Returns:
        뉴스 기사 딕셔너리 리스트
        [{"title": ..., "summary": ..., "published": ..., "link": ...}]
    """
    articles = []
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    for keyword in keywords:
        # 구글 뉴스 RSS URL 생성 (스페인어/멕시코 타겟)
        encoded_keyword = requests.utils.quote(keyword)
        rss_url = (
            f"https://news.google.com/rss/search"
            f"?q={encoded_keyword}"
            f"&hl=es-419"   # 라틴 아메리카 스페인어
            f"&gl=MX"       # 멕시코 지역
            f"&ceid=MX:es-419"
        )

        logger.info(f"[뉴스 수집] 키워드: '{keyword}' RSS 파싱 중...")
        try:
            feed = feedparser.parse(rss_url)

            for entry in feed.entries:
                # 발행 시간 파싱
                try:
                    pub_time = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    pub_time = datetime.now(timezone.utc)

                # 기간 필터링
                if pub_time < cutoff_time:
                    continue

                articles.append({
                    "source": "Google News",
                    "keyword": keyword,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:500],  # 요약 최대 500자
                    "published": pub_time.strftime("%Y-%m-%d %H:%M UTC"),
                    "link": entry.get("link", ""),
                })

            logger.info(f"  └─ '{keyword}': {len([a for a in articles if a['keyword'] == keyword])}개 수집")
            time.sleep(1)  # 레이트 리밋 방지

        except Exception as e:
            logger.error(f"  └─ 뉴스 수집 실패 ({keyword}): {e}")

    logger.info(f"[뉴스 수집 완료] 총 {len(articles)}개 기사")
    return articles


def collect_reddit_posts(
    subreddits: list[str],
    search_query: str,
    lookback_days: int = 1,
) -> list[dict]:
    """
    Reddit API(PRAW)를 사용하여 관련 게시물과 댓글을 수집합니다.

    Args:
        subreddits: 검색할 서브레딧 리스트
        search_query: 검색 키워드 (예: "lavadora")
        lookback_days: 최근 며칠치 포스트를 가져올지

    Returns:
        게시물 딕셔너리 리스트
    """
    # Reddit API 인증 (읽기 전용 - 계정 불필요)
    reddit = praw.Reddit(
        client_id=Config.REDDIT_CLIENT_ID,
        client_secret=Config.REDDIT_CLIENT_SECRET,
        user_agent=Config.REDDIT_USER_AGENT,
    )

    posts = []
    cutoff_timestamp = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp()

    for subreddit_name in subreddits:
        logger.info(f"[Reddit 수집] r/{subreddit_name} 검색 중... 키워드: '{search_query}'")
        try:
            subreddit = reddit.subreddit(subreddit_name)

            # 최근 게시물 검색 (시간 순 정렬)
            for post in subreddit.search(
                query=search_query,
                sort="new",
                time_filter="week",  # 최근 1주일 검색 후 아래에서 필터링
                limit=50,
            ):
                # 기간 필터링
                if post.created_utc < cutoff_timestamp:
                    continue

                # 상위 댓글 최대 5개 수집
                top_comments = []
                try:
                    post.comments.replace_more(limit=0)  # "더 보기" 댓글 제외
                    for comment in list(post.comments)[:5]:
                        if hasattr(comment, "body") and len(comment.body) > 20:
                            top_comments.append(comment.body[:300])
                except Exception:
                    pass

                posts.append({
                    "source": "Reddit",
                    "subreddit": subreddit_name,
                    "title": post.title,
                    "body": post.selftext[:500] if post.selftext else "",
                    "score": post.score,
                    "num_comments": post.num_comments,
                    "created": datetime.fromtimestamp(post.created_utc, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                    "url": f"https://reddit.com{post.permalink}",
                    "top_comments": top_comments,
                })

            found = len([p for p in posts if p["subreddit"] == subreddit_name])
            logger.info(f"  └─ r/{subreddit_name}: {found}개 포스트 수집")
            time.sleep(1)  # Reddit API 레이트 리밋 방지

        except Exception as e:
            logger.error(f"  └─ r/{subreddit_name} 수집 실패: {e}")

    logger.info(f"[Reddit 수집 완료] 총 {len(posts)}개 포스트")
    return posts


def collect_ecommerce_via_apify(search_keyword: str = "lavadora") -> dict:
    """
    Apify API를 통해 Mercado Libre Mexico와 Amazon Mexico의
    세탁기 검색 결과(가격, 할인율)와 상위 제품 리뷰를 수집합니다.

    [Apify 사용 방법]
    1. https://apify.com 에서 회원가입 (월 $5 무료 크레딧 제공)
    2. https://console.apify.com/account/integrations 에서 API 토큰 발급
    3. Actor를 직접 실행하거나 아래 코드처럼 API로 호출

    Args:
        search_keyword: 검색 키워드 (스페인어, 예: "lavadora")

    Returns:
        {"mercadolibre": [...], "amazon": [...]}
    """
    results = {"mercadolibre": [], "amazon": []}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {Config.APIFY_API_TOKEN}",
    }

    # ── Mercado Libre Mexico 스크래핑 ──────────────────────
    logger.info("[Apify] Mercado Libre Mexico 데이터 수집 중...")
    try:
        ml_input = {
            "search": search_keyword,
            "country": "MX",           # 멕시코
            "maxItems": 20,            # 상위 20개 제품
            "includeReviews": True,    # 리뷰 포함
        }

        # Actor 실행 요청 (동기 실행 - 최대 60초 대기)
        # Actor ID: apify/mercado-libre-scraper (공식) 또는 실제 사용 가능한 Actor로 교체
        ml_response = requests.post(
            f"https://api.apify.com/v2/acts/{Config.APIFY_MERCADOLIBRE_ACTOR}/run-sync-get-dataset-items",
            json=ml_input,
            headers=headers,
            params={"timeout": 60, "memory": 256},
            timeout=120,
        )

        if ml_response.status_code == 200:
            ml_data = ml_response.json()
            # 필요한 필드만 추출하여 정리
            for item in ml_data[:20]:
                results["mercadolibre"].append({
                    "platform": "Mercado Libre MX",
                    "title": item.get("title", ""),
                    "price": item.get("price", ""),
                    "original_price": item.get("originalPrice", ""),
                    "discount_percent": item.get("discountPercentage", ""),
                    "rating": item.get("rating", ""),
                    "review_count": item.get("reviewsCount", ""),
                    "seller": item.get("seller", {}).get("name", ""),
                    "url": item.get("url", ""),
                    # 리뷰 텍스트 (있을 경우)
                    "reviews": [
                        r.get("text", "")[:200]
                        for r in item.get("reviews", [])[:3]
                    ],
                })
            logger.info(f"  └─ Mercado Libre: {len(results['mercadolibre'])}개 제품 수집")
        else:
            logger.warning(f"  └─ Mercado Libre 수집 실패: HTTP {ml_response.status_code}")
            logger.warning(f"     응답: {ml_response.text[:200]}")

    except Exception as e:
        logger.error(f"  └─ Mercado Libre Apify 호출 오류: {e}")

    time.sleep(2)

    # ── Amazon Mexico 스크래핑 ────────────────────────────
    logger.info("[Apify] Amazon Mexico 데이터 수집 중...")
    try:
        amz_input = {
            "searchQueries": [search_keyword],
            "country": "MX",           # amazon.com.mx
            "maxItems": 20,
            "includeReviews": True,
        }

        amz_response = requests.post(
            f"https://api.apify.com/v2/acts/{Config.APIFY_AMAZON_ACTOR}/run-sync-get-dataset-items",
            json=amz_input,
            headers=headers,
            params={"timeout": 90, "memory": 512},
            timeout=180,
        )

        if amz_response.status_code == 200:
            amz_data = amz_response.json()
            for item in amz_data[:20]:
                results["amazon"].append({
                    "platform": "Amazon MX",
                    "title": item.get("productName", item.get("name", "")),
                    "price": item.get("price", {}).get("value", ""),
                    "original_price": item.get("originalPrice", {}).get("value", ""),
                    "discount_percent": item.get("saving", {}).get("percentage", ""),
                    "rating": item.get("stars", ""),
                    "review_count": item.get("reviewsCount", ""),
                    "asin": item.get("asin", ""),
                    "url": item.get("url", ""),
                    "reviews": [
                        r.get("text", "")[:200]
                        for r in item.get("reviews", [])[:3]
                    ],
                })
            logger.info(f"  └─ Amazon MX: {len(results['amazon'])}개 제품 수집")
        else:
            logger.warning(f"  └─ Amazon MX 수집 실패: HTTP {amz_response.status_code}")

    except Exception as e:
        logger.error(f"  └─ Amazon MX Apify 호출 오류: {e}")

    logger.info("[Apify 수집 완료]")
    return results


# ══════════════════════════════════════════════════════════
# ③ 데이터 전처리 (Preprocessor)
# ══════════════════════════════════════════════════════════

def preprocess_data_for_ai(
    news: list[dict],
    reddit: list[dict],
    ecommerce: dict,
) -> str:
    """
    수집된 원본 데이터를 AI 분석을 위한 구조화된 텍스트로 변환합니다.
    토큰 절약을 위해 각 섹션에 최대 글자 수를 제한합니다.

    Returns:
        AI에 전달할 통합 텍스트 (스페인어 원문 포함)
    """
    today = datetime.now(pytz.timezone("America/Mexico_City")).strftime("%Y년 %m월 %d일")
    sections = [f"# 멕시코 세탁기 시장 원본 데이터 ({today})\n"]

    # ── 섹션 1: 뉴스 ──────────────────────────────────────
    sections.append("## [섹션 A] 구글 뉴스 (최신 기사)")
    if news:
        for i, article in enumerate(news[:15], 1):  # 최대 15개
            sections.append(
                f"[뉴스{i}] {article['published']}\n"
                f"제목: {article['title']}\n"
                f"내용: {article['summary']}\n"
            )
    else:
        sections.append("수집된 뉴스 없음\n")

    # ── 섹션 2: Reddit ────────────────────────────────────
    sections.append("## [섹션 B] Reddit 커뮤니티 게시물")
    if reddit:
        for i, post in enumerate(reddit[:10], 1):  # 최대 10개
            comments_text = " | ".join(post["top_comments"][:3]) if post["top_comments"] else "댓글 없음"
            sections.append(
                f"[Reddit{i}] r/{post['subreddit']} | 추천수: {post['score']}\n"
                f"제목: {post['title']}\n"
                f"본문: {post['body'][:300] if post['body'] else '(본문 없음)'}\n"
                f"주요 댓글: {comments_text[:400]}\n"
            )
    else:
        sections.append("수집된 Reddit 포스트 없음\n")

    # ── 섹션 3: 이커머스 ──────────────────────────────────
    sections.append("## [섹션 C] 이커머스 가격 및 프로모션 데이터")

    ml_items = ecommerce.get("mercadolibre", [])
    amz_items = ecommerce.get("amazon", [])

    if ml_items:
        sections.append("### Mercado Libre MX 상위 제품:")
        for item in ml_items[:10]:
            discount_info = f" (할인: {item['discount_percent']}%)" if item.get("discount_percent") else ""
            review_text = " / ".join(item["reviews"][:2]) if item.get("reviews") else ""
            sections.append(
                f"- {item['title'][:60]}\n"
                f"  가격: {item['price']} MXN{discount_info} | "
                f"평점: {item['rating']} ({item['review_count']}개 리뷰)\n"
                f"  리뷰: {review_text[:300]}\n"
            )
    else:
        sections.append("Mercado Libre 데이터 수집 없음\n")

    if amz_items:
        sections.append("### Amazon MX 상위 제품:")
        for item in amz_items[:10]:
            discount_info = f" (할인: {item['discount_percent']}%)" if item.get("discount_percent") else ""
            review_text = " / ".join(item["reviews"][:2]) if item.get("reviews") else ""
            sections.append(
                f"- {item['title'][:60]}\n"
                f"  가격: {item['price']} MXN{discount_info} | "
                f"평점: {item['rating']} ({item['review_count']}개 리뷰)\n"
                f"  리뷰: {review_text[:300]}\n"
            )
    else:
        sections.append("Amazon MX 데이터 수집 없음\n")

    raw_text = "\n".join(sections)

    # 토큰 초과 방지: 최대 15,000자 (약 4,000 토큰)
    if len(raw_text) > 15000:
        raw_text = raw_text[:15000] + "\n\n[... 데이터가 너무 많아 일부 생략됨]"

    logger.info(f"[전처리 완료] AI 입력 데이터 크기: {len(raw_text):,}자")
    return raw_text


# ══════════════════════════════════════════════════════════
# ④ AI 분석 및 리포트 생성 (Analyzer)
# ══════════════════════════════════════════════════════════

# ── 시스템 프롬프트 (Agent에게 부여할 역할과 지침) ──────────
SYSTEM_PROMPT = """
너는 15년 경력의 멕시코 가전 시장 분석 전문가이자 소비자 인사이트 전략가야.
한국 본사의 전략기획팀 임원들에게 보고하는 마켓 인텔리전스 리포트를 작성하는 것이 너의 임무야.

[작성 규칙 - 반드시 준수]
1. 반드시 한국어로 작성할 것
2. 마크다운 형식으로 작성하되, 이모지를 적절히 활용하여 가독성 높게 작성
3. 데이터 부족 항목은 절대 지어내지 말고 "특이사항 없음" 또는 "데이터 부족"으로 명기
4. 스페인어 원문에서 핵심을 추출하되, 과도한 요약으로 정보가 누락되지 않도록 할 것
5. 임원이 5분 안에 핵심을 파악할 수 있도록 간결하면서도 실용적인 인사이트 제공

[리포트 구조 - 다음 순서와 형식을 정확히 따를 것]
반드시 아래 5개 섹션을 모두 포함하여 완성된 리포트를 작성하라.

---
# 🇲🇽 멕시코 세탁기 시장 인텔리전스 리포트
**수집일자:** [오늘 날짜]  |  **수집 국가:** 멕시코  |  **카테고리:** 세탁기(lavadora)
---

## ⚡ 1. 오늘의 시장/브랜드 뉴스 요약
- 주요 뉴스를 3~5개 불릿 포인트로 요약
- 각 이슈가 우리 비즈니스(LG, Samsung 등 한국 브랜드)에 미칠 영향 한 줄 코멘트 추가
- 데이터 없을 시: "오늘 특이 뉴스 없음"

## 🗣️ 2. 현지 고객의 목소리 (VoC)
### 2-1. 멕시코 소비자가 세탁기에서 가장 중요하게 생각하는 기능 TOP 5
(Reddit 게시물과 이커머스 리뷰를 기반으로 빈도 순 정리)

### 2-2. 주요 Pain-points (불만 사항) TOP 5
(반복적으로 언급되는 불만을 빈도 순으로 정리)

### 2-3. 자주 언급된 브랜드별 인식
| 브랜드 | 긍정 키워드 | 부정 키워드 | 전반적 평가 |
|--------|------------|------------|------------|
(데이터 있는 브랜드만 기재)

## 💰 3. 주요 프로모션 및 가격 동향
### 3-1. 이번 주 주목할 프로모션
(파격 할인 또는 30% 이상 할인 제품 위주로 정리)

### 3-2. 가격대별 시장 분포 (데이터 있을 경우)
| 가격대 (MXN) | 해당 제품 수 | 주요 브랜드 |
|-------------|------------|------------|

## 📊 4. 종합 인사이트 및 액션 포인트
(위 데이터를 종합하여 한국 본사 전략팀이 취해야 할 액션 2~3가지를 제안)

## ⚠️ 5. 데이터 품질 노트
(이번 수집에서 데이터가 부족했거나 신뢰도가 낮은 항목 명기)
---
""".strip()


def analyze_with_claude(raw_data: str) -> str:
    """
    Anthropic Claude API를 사용하여 수집 데이터를 분석하고
    한국어 리포트를 생성합니다.

    Args:
        raw_data: preprocess_data_for_ai()의 반환값

    Returns:
        마크다운 형식의 한국어 분석 리포트
    """
    logger.info("[AI 분석] Claude API 호출 중...")
    client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    message = client.messages.create(
        model="claude-opus-4-5",  # 최신 최고 성능 모델 사용
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "아래는 오늘 수집한 멕시코 세탁기 시장 원본 데이터입니다.\n"
                    "위의 지침에 따라 정확하고 실용적인 한국어 마켓 인텔리전스 리포트를 작성해 주세요.\n\n"
                    f"{raw_data}"
                ),
            }
        ],
    )

    report = message.content[0].text
    logger.info(f"[AI 분석 완료] 리포트 길이: {len(report):,}자")
    return report


def analyze_with_openai(raw_data: str) -> str:
    """
    OpenAI GPT-4를 사용하여 수집 데이터를 분석합니다. (Claude 대체 옵션)

    Args:
        raw_data: preprocess_data_for_ai()의 반환값

    Returns:
        마크다운 형식의 한국어 분석 리포트
    """
    logger.info("[AI 분석] OpenAI API 호출 중...")
    client = OpenAI(api_key=Config.OPENAI_API_KEY)

    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "아래는 오늘 수집한 멕시코 세탁기 시장 원본 데이터입니다.\n"
                    "위의 지침에 따라 정확하고 실용적인 한국어 마켓 인텔리전스 리포트를 작성해 주세요.\n\n"
                    f"{raw_data}"
                ),
            },
        ],
        temperature=0.3,  # 낮은 온도 = 더 정확하고 일관된 출력
    )

    report = response.choices[0].message.content
    logger.info(f"[AI 분석 완료] 리포트 길이: {len(report):,}자")
    return report


def analyze_data(raw_data: str) -> str:
    """AI 제공자 설정에 따라 적절한 분석 함수를 호출합니다."""
    if Config.AI_PROVIDER == "anthropic":
        return analyze_with_claude(raw_data)
    elif Config.AI_PROVIDER == "openai":
        return analyze_with_openai(raw_data)
    else:
        raise ValueError(f"지원하지 않는 AI_PROVIDER: {Config.AI_PROVIDER}")


# ══════════════════════════════════════════════════════════
# ⑤ 알림 발송 — Gmail SMTP (Notifier)
# ══════════════════════════════════════════════════════════

def markdown_to_html(md: str) -> str:
    """
    마크다운 리포트를 보기 좋은 Gmail HTML 이메일로 변환합니다.
    외부 라이브러리 없이 순수 문자열 처리로 구현하여
    requirements.txt에 추가 항목이 없습니다.
    """
    lines = md.split("\n")
    html_lines = []

    for line in lines:
        # h1
        if line.startswith("# "):
            html_lines.append(f'<h1 style="color:#1a1a2e;border-bottom:3px solid #0066cc;padding-bottom:8px">{line[2:]}</h1>')
        # h2
        elif line.startswith("## "):
            html_lines.append(f'<h2 style="color:#0066cc;margin-top:28px">{line[3:]}</h2>')
        # h3
        elif line.startswith("### "):
            html_lines.append(f'<h3 style="color:#333;margin-top:16px">{line[4:]}</h3>')
        # 구분선
        elif line.strip() == "---":
            html_lines.append('<hr style="border:none;border-top:1px solid #ddd;margin:16px 0">')
        # 불릿 리스트
        elif line.startswith("- ") or line.startswith("* "):
            text = line[2:]
            # **bold** 처리
            import re
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            html_lines.append(f'<li style="margin:4px 0;line-height:1.6">{text}</li>')
        # 마크다운 테이블 (| 로 시작)
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                # 구분선 행 → 건너뜀
                continue
            is_header = html_lines and "<th" in html_lines[-1]
            tag = "th" if not any("<td" in l or "<th" in l for l in html_lines[-3:]) else "td"
            row_html = "".join(
                f'<{tag} style="border:1px solid #ddd;padding:8px 12px;text-align:left;'
                f'background:{"#e8f0fe" if tag=="th" else "white"}">{c}</{tag}>'
                for c in cells
            )
            html_lines.append(f"<tr>{row_html}</tr>")
        # 빈 줄
        elif line.strip() == "":
            html_lines.append("<br>")
        # 일반 텍스트
        else:
            import re
            line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            line = re.sub(r'\*(.+?)\*', r'<em>\1</em>', line)
            html_lines.append(f'<p style="margin:4px 0;line-height:1.7">{line}</p>')

    # li 태그들을 ul로 묶기
    result = "\n".join(html_lines)
    import re
    result = re.sub(
        r'(<li.*?</li>\n?)+',
        lambda m: f'<ul style="padding-left:20px;margin:8px 0">{m.group()}</ul>',
        result,
        flags=re.DOTALL,
    )
    # tr 태그들을 table로 묶기
    result = re.sub(
        r'(<tr>.*?</tr>\n?)+',
        lambda m: (
            f'<table style="border-collapse:collapse;width:100%;margin:12px 0;font-size:14px">'
            f'{m.group()}</table>'
        ),
        result,
        flags=re.DOTALL,
    )
    return result


def send_gmail(report: str) -> bool:
    """
    완성된 마크다운 리포트를 Gmail로 전송합니다.
    파이썬 내장 smtplib를 사용하므로 추가 설치가 필요 없습니다.

    ─────────────────────────────────────────────────
    [Gmail 앱 비밀번호 발급 방법 — 5분 소요]
    ─────────────────────────────────────────────────
    1. Gmail 로그인 → 우측 상단 프로필 사진 클릭
       → "Google 계정 관리" 클릭
    2. 왼쪽 메뉴 "보안" 클릭
    3. "Google에 로그인" 섹션에서
       "2단계 인증" 을 먼저 ON으로 활성화 (필수!)
    4. 2단계 인증 활성화 후 다시 "보안" 메뉴로 돌아와서
       검색창에 "앱 비밀번호" 검색 → 클릭
    5. 앱 선택: "메일" / 기기 선택: "기타(맞춤 이름)" → "마켓봇"
    6. 생성된 16자리 비밀번호 복사 → .env의 GMAIL_APP_PASSWORD에 입력
       (예: abcd efgh ijkl mnop → 공백 제거하여 abcdefghijklmnop)
    ─────────────────────────────────────────────────

    Args:
        report: AI가 생성한 마크다운 리포트 텍스트

    Returns:
        True = 발송 성공, False = 발송 실패
    """
    sender = Config.GMAIL_SENDER
    app_password = Config.GMAIL_APP_PASSWORD
    recipient = Config.GMAIL_RECIPIENT

    # 설정값 검증
    if not all([sender, app_password, recipient]):
        logger.error(
            "Gmail 설정 누락! .env 파일에 GMAIL_SENDER, "
            "GMAIL_APP_PASSWORD, GMAIL_RECIPIENT를 모두 입력하세요."
        )
        return False

    logger.info(f"[Gmail] 리포트 발송 중... → {recipient}")

    # ── 날짜 및 제목 설정 ─────────────────────────────────
    kst = pytz.timezone("Asia/Seoul")
    today_str = datetime.now(kst).strftime("%Y년 %m월 %d일")
    subject = f"🇲🇽 [{today_str}] 멕시코 세탁기 마켓 인텔리전스 리포트"

    # ── HTML 이메일 본문 구성 ─────────────────────────────
    html_body = markdown_to_html(report)
    full_html = f"""
    <html>
    <body style="font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
                 max-width:800px;margin:0 auto;padding:24px;color:#222;
                 background:#f9f9f9">
      <div style="background:white;border-radius:12px;padding:32px;
                  box-shadow:0 2px 8px rgba(0,0,0,0.08)">

        <!-- 헤더 배너 -->
        <div style="background:linear-gradient(135deg,#003087,#0066cc);
                    border-radius:8px;padding:20px 24px;margin-bottom:24px">
          <div style="color:white;font-size:22px;font-weight:bold">
            🇲🇽 멕시코 마켓 인텔리전스
          </div>
          <div style="color:#cce0ff;font-size:13px;margin-top:4px">
            세탁기(Lavadora) 시장 일간 리포트 · {today_str} · KST 기준
          </div>
        </div>

        <!-- 리포트 본문 -->
        {html_body}

        <!-- 푸터 -->
        <div style="margin-top:40px;padding-top:16px;
                    border-top:1px solid #eee;color:#888;font-size:12px">
          본 리포트는 자동화 에이전트가 수집·분석한 내용입니다.<br>
          데이터 출처: Google News · Reddit · Mercado Libre MX · Amazon MX
        </div>
      </div>
    </body>
    </html>
    """

    # ── 이메일 메시지 객체 생성 ───────────────────────────
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"마켓 인텔리전스 봇 <{sender}>"
    msg["To"] = recipient

    # 일반 텍스트 버전 (HTML 미지원 클라이언트 대비)
    plain_text = report
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(full_html, "html", "utf-8"))

    # ── Gmail SMTP 서버로 발송 ────────────────────────────
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, app_password)
            server.sendmail(sender, recipient, msg.as_string())

        logger.info(f"✅ Gmail 발송 성공! 제목: {subject}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "❌ Gmail 인증 실패!\n"
            "   → GMAIL_SENDER와 GMAIL_APP_PASSWORD를 확인하세요.\n"
            "   → 일반 Gmail 비밀번호가 아닌 '앱 비밀번호(16자리)'를 사용해야 합니다.\n"
            "   → 2단계 인증이 활성화되어 있어야 합니다."
        )
        return False

    except smtplib.SMTPException as e:
        logger.error(f"❌ Gmail SMTP 오류: {e}")
        return False

    except Exception as e:
        logger.error(f"❌ Gmail 발송 중 예상치 못한 오류: {e}")
        return False


def send_notification(report: str) -> bool:
    """Gmail로 리포트를 발송합니다."""
    return send_gmail(report)


# ══════════════════════════════════════════════════════════
# ⑥ 메인 워크플로우 (Main Orchestrator)
# ══════════════════════════════════════════════════════════

def run_agent():
    """
    전체 에이전트 파이프라인을 실행합니다.
    수집 → 전처리 → AI 분석 → 발송
    """
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("🚀 멕시코 마켓 인텔리전스 에이전트 시작")
    logger.info(f"   실행 시간: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    report = None

    try:
        # ── Step 1: 데이터 수집 ───────────────────────────
        logger.info("\n📡 [Step 1/4] 데이터 수집 시작...")

        news_data = collect_google_news(
            keywords=Config.NEWS_KEYWORDS,
            lookback_days=Config.LOOKBACK_DAYS,
        )

        reddit_data = collect_reddit_posts(
            subreddits=Config.REDDIT_SUBREDDITS,
            search_query=Config.REDDIT_SEARCH_QUERY,
            lookback_days=Config.LOOKBACK_DAYS,
        )

        ecommerce_data = collect_ecommerce_via_apify(search_keyword="lavadora")

        # ── Step 2: 데이터 전처리 ─────────────────────────
        logger.info("\n🔧 [Step 2/4] 데이터 전처리 중...")
        raw_text = preprocess_data_for_ai(
            news=news_data,
            reddit=reddit_data,
            ecommerce=ecommerce_data,
        )

        # (선택) 원본 데이터를 JSON으로 저장 (디버깅용)
        debug_path = f"debug_raw_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump(
                {"news": news_data, "reddit": reddit_data, "ecommerce": ecommerce_data},
                f, ensure_ascii=False, indent=2,
            )
        logger.info(f"   원본 데이터 저장: {debug_path}")

        # ── Step 3: AI 분석 ───────────────────────────────
        logger.info(f"\n🤖 [Step 3/4] AI 분석 중 (Provider: {Config.AI_PROVIDER})...")
        report = analyze_data(raw_text)

        # 리포트를 파일로도 저장
        report_path = f"report_{datetime.now().strftime('%Y%m%d')}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info(f"   리포트 저장: {report_path}")

        # ── Step 4: 알림 발송 ─────────────────────────────
        logger.info(f"\n📨 [Step 4/4] 알림 발송 중 (Channel: {Config.NOTIFICATION_CHANNEL})...")
        success = send_notification(report)

        if success:
            logger.info("✅ 리포트 발송 완료!")
        else:
            logger.error("❌ 리포트 발송 실패! 로그를 확인하세요.")

    except Exception as e:
        logger.critical(f"🔥 에이전트 실행 중 치명적 오류 발생: {e}", exc_info=True)

        # 오류 발생 시에도 이메일 알림 전송
        error_report = (
            f"# 🚨 멕시코 마켓 에이전트 오류 발생\n\n"
            f"**시간:** {datetime.now(pytz.timezone('Asia/Seoul')).strftime('%Y-%m-%d %H:%M KST')}\n\n"
            f"**오류 내용:**\n```\n{str(e)[:800]}\n```\n\n"
            f"agent.log 파일을 확인하세요."
        )
        try:
            send_gmail(error_report)
        except Exception:
            pass

    finally:
        elapsed = (datetime.now() - start_time).seconds
        logger.info(f"\n⏱️  총 실행 시간: {elapsed}초")
        logger.info("=" * 60)

    return report


# ══════════════════════════════════════════════════════════
# ⑦ 스케줄링 (로컬 테스트용)
# ══════════════════════════════════════════════════════════
# ※ 프로덕션에서는 GitHub Actions를 권장합니다. (README.md 참고)
# 로컬 서버 또는 클라우드 VM에서 24/7 실행할 때 사용하세요.

def run_scheduler():
    """
    매일 한국 시간 오전 9시에 에이전트를 자동 실행합니다.
    이 함수는 process가 계속 실행 중일 때만 동작합니다.
    """
    # 한국 시간(KST = UTC+9) 기준 오전 9:00
    schedule.every().day.at("00:00").do(run_agent)  # UTC 00:00 = KST 09:00

    logger.info("📅 스케줄러 시작 - 매일 KST 09:00에 실행됩니다.")
    logger.info("   Ctrl+C로 중지할 수 있습니다.")

    while True:
        schedule.run_pending()
        time.sleep(60)  # 1분마다 스케줄 확인


# ══════════════════════════════════════════════════════════
# ⑧ 엔트리 포인트
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--schedule":
        # 스케줄 모드: python agent.py --schedule
        run_scheduler()
    else:
        # 즉시 실행 모드: python agent.py
        run_agent()
