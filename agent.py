"""
멕시코 가전 마켓 인텔리전스 자동화 에이전트
"""

import os
import time
import logging
import json
import smtplib
import re
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

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


class Config:
    REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
    REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
    REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "MarketIntelligenceBot/1.0")
    APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic")
    GMAIL_SENDER = os.getenv("GMAIL_SENDER")
    GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
    GMAIL_RECIPIENT = os.getenv("GMAIL_RECIPIENT")
    LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "1"))
    NEWS_KEYWORDS = ["lavadora México", "electrodomésticos México", "lavasecadora México"]
    REDDIT_SUBREDDITS = ["mexico", "Monterrey", "cdmx", "guadalajara", "tijuana"]
    REDDIT_SEARCH_QUERY = "lavadora"
    APIFY_MERCADOLIBRE_ACTOR = "trudax/mercadolibre-scraper"
    APIFY_AMAZON_ACTOR = "junglee/amazon-crawler"


def collect_google_news(keywords, lookback_days=1):
    articles = []
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    for keyword in keywords:
        encoded_keyword = requests.utils.quote(keyword)
        rss_url = (
            f"https://news.google.com/rss/search"
            f"?q={encoded_keyword}&hl=es-419&gl=MX&ceid=MX:es-419"
        )
        logger.info(f"[뉴스 수집] 키워드: '{keyword}' RSS 파싱 중...")
        try:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries:
                try:
                    pub_time = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    pub_time = datetime.now(timezone.utc)
                if pub_time < cutoff_time:
                    continue
                articles.append({
                    "source": "Google News",
                    "keyword": keyword,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:500],
                    "published": pub_time.strftime("%Y-%m-%d %H:%M UTC"),
                    "link": entry.get("link", ""),
                })
            time.sleep(1)
        except Exception as e:
            logger.error(f"뉴스 수집 실패 ({keyword}): {e}")
    logger.info(f"[뉴스 수집 완료] 총 {len(articles)}개 기사")
    return articles


def collect_reddit_posts(subreddits, search_query, lookback_days=1):
    posts = []
    try:
        reddit = praw.Reddit(
            client_id=Config.REDDIT_CLIENT_ID,
            client_secret=Config.REDDIT_CLIENT_SECRET,
            user_agent=Config.REDDIT_USER_AGENT,
        )
        cutoff_timestamp = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp()
        for subreddit_name in subreddits:
            logger.info(f"[Reddit 수집] r/{subreddit_name} 검색 중...")
            try:
                subreddit = reddit.subreddit(subreddit_name)
                for post in subreddit.search(query=search_query, sort="new", time_filter="week", limit=50):
                    if post.created_utc < cutoff_timestamp:
                        continue
                    top_comments = []
                    try:
                        post.comments.replace_more(limit=0)
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
                        "top_comments": top_comments,
                    })
                time.sleep(1)
            except Exception as e:
                logger.error(f"r/{subreddit_name} 수집 실패: {e}")
    except Exception as e:
        logger.error(f"Reddit 연결 실패: {e}")
    logger.info(f"[Reddit 수집 완료] 총 {len(posts)}개 포스트")
    return posts


def collect_ecommerce_via_apify(search_keyword="lavadora"):
    results = {"mercadolibre": [], "amazon": []}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {Config.APIFY_API_TOKEN}",
    }

    logger.info("[Apify] Mercado Libre Mexico 데이터 수집 중...")
    try:
        ml_input = {"search": search_keyword, "country": "MX", "maxItems": 20}
        ml_response = requests.post(
            f"https://api.apify.com/v2/acts/{Config.APIFY_MERCADOLIBRE_ACTOR}/run-sync-get-dataset-items",
            json=ml_input, headers=headers,
            params={"timeout": 60, "memory": 256}, timeout=120,
        )
        if ml_response.status_code == 200:
            for item in ml_response.json()[:20]:
                results["mercadolibre"].append({
                    "platform": "Mercado Libre MX",
                    "title": item.get("title", ""),
                    "price": item.get("price", ""),
                    "discount_percent": item.get("discountPercentage", ""),
                    "rating": item.get("rating", ""),
                    "review_count": item.get("reviewsCount", ""),
                    "reviews": [r.get("text", "")[:200] for r in item.get("reviews", [])[:3]],
                })
            logger.info(f"  Mercado Libre: {len(results['mercadolibre'])}개 수집")
        else:
            logger.warning(f"  Mercado Libre 수집 실패: HTTP {ml_response.status_code}")
    except Exception as e:
        logger.error(f"  Mercado Libre 오류: {e}")

    time.sleep(2)

    logger.info("[Apify] Amazon Mexico 데이터 수집 중...")
    try:
        amz_input = {"searchQueries": [search_keyword], "country": "MX", "maxItems": 20}
        amz_response = requests.post(
            f"https://api.apify.com/v2/acts/{Config.APIFY_AMAZON_ACTOR}/run-sync-get-dataset-items",
            json=amz_input, headers=headers,
            params={"timeout": 90, "memory": 512}, timeout=180,
        )
        if amz_response.status_code == 200:
            for item in amz_response.json()[:20]:
                results["amazon"].append({
                    "platform": "Amazon MX",
                    "title": item.get("productName", item.get("name", "")),
                    "price": item.get("price", {}).get("value", ""),
                    "discount_percent": item.get("saving", {}).get("percentage", ""),
                    "rating": item.get("stars", ""),
                    "review_count": item.get("reviewsCount", ""),
                    "reviews": [r.get("text", "")[:200] for r in item.get("reviews", [])[:3]],
                })
            logger.info(f"  Amazon MX: {len(results['amazon'])}개 수집")
        else:
            logger.warning(f"  Amazon MX 수집 실패: HTTP {amz_response.status_code}")
    except Exception as e:
        logger.error(f"  Amazon MX 오류: {e}")

    return results


def preprocess_data_for_ai(news, reddit, ecommerce):
    today = datetime.now(pytz.timezone("America/Mexico_City")).strftime("%Y년 %m월 %d일")
    sections = [f"# 멕시코 세탁기 시장 원본 데이터 ({today})\n"]

    sections.append("## [섹션 A] 구글 뉴스")
    if news:
        for i, article in enumerate(news[:15], 1):
            sections.append(f"[뉴스{i}] {article['title']}\n{article['summary']}\n")
    else:
        sections.append("수집된 뉴스 없음\n")

    sections.append("## [섹션 B] Reddit 커뮤니티")
    if reddit:
        for i, post in enumerate(reddit[:10], 1):
            comments = " | ".join(post["top_comments"][:3]) if post["top_comments"] else "댓글 없음"
            sections.append(f"[Reddit{i}] {post['title']}\n{post['body'][:300]}\n댓글: {comments[:400]}\n")
    else:
        sections.append("수집된 Reddit 포스트 없음\n")

    sections.append("## [섹션 C] 이커머스 데이터")
    ml_items = ecommerce.get("mercadolibre", [])
    amz_items = ecommerce.get("amazon", [])

    if ml_items:
        sections.append("### Mercado Libre MX:")
        for item in ml_items[:10]:
            discount = f" (할인: {item['discount_percent']}%)" if item.get("discount_percent") else ""
            sections.append(f"- {item['title'][:60]} | 가격: {item['price']}{discount} | 평점: {item['rating']}\n")
    else:
        sections.append("Mercado Libre 데이터 없음\n")

    if amz_items:
        sections.append("### Amazon MX:")
        for item in amz_items[:10]:
            discount = f" (할인: {item['discount_percent']}%)" if item.get("discount_percent") else ""
            sections.append(f"- {item['title'][:60]} | 가격: {item['price']}{discount} | 평점: {item['rating']}\n")
    else:
        sections.append("Amazon MX 데이터 없음\n")

    raw_text = "\n".join(sections)
    if len(raw_text) > 15000:
        raw_text = raw_text[:15000] + "\n[데이터 일부 생략]"
    logger.info(f"[전처리 완료] AI 입력 크기: {len(raw_text):,}자")
    return raw_text


SYSTEM_PROMPT = """
너는 멕시코 가전 시장 분석 전문가야. 수집된 스페인어 데이터를 분석하여 한국어 마켓 인텔리전스 리포트를 작성해.

[규칙]
1. 반드시 한국어로 작성
2. 데이터 없는 항목은 "특이사항 없음"으로 기재, 절대 지어내지 말 것
3. 마크다운 형식 사용

[리포트 구조]
# 멕시코 세탁기 시장 인텔리전스 리포트
수집일자: [오늘 날짜] | 카테고리: 세탁기(lavadora)

## 1. 오늘의 시장/브랜드 뉴스 요약
(주요 뉴스 3~5개 불릿 포인트)

## 2. 현지 고객의 목소리 (VoC)
### 소비자가 중요하게 생각하는 기능 TOP 5
### 주요 불만(Pain-points) TOP 5
### 브랜드별 인식

## 3. 주요 프로모션 및 가격 동향
(할인 행사, 가격 변동 정보)

## 4. 종합 인사이트 및 액션 포인트
(한국 본사 전략팀을 위한 제안 2~3가지)

## 5. 데이터 품질 노트
(이번 수집의 한계점)
""".strip()


def analyze_with_claude(raw_data):
    logger.info("[AI 분석] Claude API 호출 중...")
    client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"아래 데이터를 분석하여 한국어 리포트를 작성해주세요.\n\n{raw_data}"
        }],
    )
    report = message.content[0].text
    logger.info(f"[AI 분석 완료] 리포트 길이: {len(report):,}자")
    return report


def analyze_data(raw_data):
    return analyze_with_claude(raw_data)


def markdown_to_html(md):
    lines = md.split("\n")
    html_lines = []
    for line in lines:
        if line.startswith("# "):
            html_lines.append(f'<h1 style="color:#1a1a2e;border-bottom:3px solid #0066cc;padding-bottom:8px">{line[2:]}</h1>')
        elif line.startswith("## "):
            html_lines.append(f'<h2 style="color:#0066cc;margin-top:28px">{line[3:]}</h2>')
        elif line.startswith("### "):
            html_lines.append(f'<h3 style="color:#333;margin-top:16px">{line[4:]}</h3>')
        elif line.strip() == "---":
            html_lines.append('<hr style="border:none;border-top:1px solid #ddd;margin:16px 0">')
        elif line.startswith("- ") or line.startswith("* "):
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line[2:])
            html_lines.append(f'<li style="margin:4px 0;line-height:1.6">{text}</li>')
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            tag = "th" if not any("<td" in l or "<th" in l for l in html_lines[-3:]) else "td"
            row_html = "".join(
                f'<{tag} style="border:1px solid #ddd;padding:8px 12px;background:{"#e8f0fe" if tag=="th" else "white"}">{c}</{tag}>'
                for c in cells
            )
            html_lines.append(f"<tr>{row_html}</tr>")
        elif line.strip() == "":
            html_lines.append("<br>")
        else:
            line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            html_lines.append(f'<p style="margin:4px 0;line-height:1.7">{line}</p>')

    result = "\n".join(html_lines)
    result = re.sub(r'(<li.*?</li>\n?)+', lambda m: f'<ul style="padding-left:20px;margin:8px 0">{m.group()}</ul>', result, flags=re.DOTALL)
    result = re.sub(r'(<tr>.*?</tr>\n?)+', lambda m: f'<table style="border-collapse:collapse;width:100%;margin:12px 0;font-size:14px">{m.group()}</table>', result, flags=re.DOTALL)
    return result


def send_gmail(report):
    sender = Config.GMAIL_SENDER
    app_password = Config.GMAIL_APP_PASSWORD
    recipient = Config.GMAIL_RECIPIENT

    if not all([sender, app_password, recipient]):
        logger.error("Gmail 설정 누락!")
        return False

    logger.info(f"[Gmail] 리포트 발송 중... -> {recipient}")
    kst = pytz.timezone("Asia/Seoul")
    today_str = datetime.now(kst).strftime("%Y년 %m월 %d일")
    subject = f"[{today_str}] 멕시코 세탁기 마켓 인텔리전스 리포트"

    html_body = markdown_to_html(report)
    full_html = f"""
    <html><body style="font-family:sans-serif;max-width:800px;margin:0 auto;padding:24px;background:#f9f9f9">
    <div style="background:white;border-radius:12px;padding:32px;box-shadow:0 2px 8px rgba(0,0,0,0.08)">
    <div style="background:linear-gradient(135deg,#003087,#0066cc);border-radius:8px;padding:20px 24px;margin-bottom:24px">
    <div style="color:white;font-size:22px;font-weight:bold">멕시코 마켓 인텔리전스</div>
    <div style="color:#cce0ff;font-size:13px;margin-top:4px">세탁기 시장 리포트 · {today_str}</div>
    </div>
    {html_body}
    <div style="margin-top:40px;padding-top:16px;border-top:1px solid #eee;color:#888;font-size:12px">
    데이터 출처: Google News · Reddit · Mercado Libre MX · Amazon MX
    </div></div></body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(report, "plain", "utf-8"))
    msg.attach(MIMEText(full_html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, app_password)
            server.sendmail(sender, recipient, msg.as_string())
        logger.info(f"Gmail 발송 성공! 제목: {subject}")
        return True
    except Exception as e:
        logger.error(f"Gmail 발송 실패: {e}")
        return False


def send_notification(report):
    return send_gmail(report)


def save_report_json(report, raw_data):
    os.makedirs("docs/data", exist_ok=True)
    kst = pytz.timezone("Asia/Seoul")
    today = datetime.now(kst).strftime("%Y-%m-%d")
    filepath = f"docs/data/{today}.json"
    payload = {
        "date": today,
        "report_korean": report,
        "raw": {
            "news_count": len(raw_data.get("news", [])),
            "reddit_count": len(raw_data.get("reddit", [])),
            "mercadolibre_count": len(raw_data.get("ecommerce", {}).get("mercadolibre", [])),
            "amazon_count": len(raw_data.get("ecommerce", {}).get("amazon", [])),
        },
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info(f"[JSON 저장] {filepath}")
    return filepath


def build_index_html():
    os.makedirs("docs/data", exist_ok=True)
    data_files = sorted([f for f in os.listdir("docs/data") if f.endswith(".json")], reverse=True)
    reports = []
    for fname in data_files:
        try:
            with open(f"docs/data/{fname}", encoding="utf-8") as f:
                reports.append(json.load(f))
        except Exception:
            continue

    latest_report_html = "<p>아직 수집된 리포트가 없습니다.</p>"
    latest_date = "-"
    if reports:
        latest_date = reports[0]["date"]
        latest_report_html = markdown_to_html(reports[0]["report_korean"])

    history_items = ""
    for r in reports:
        date = r["date"]
        raw = r.get("raw", {})
        history_items += f"""
        <div class="history-item" onclick="loadReport('{date}')" id="btn-{date}">
            <div class="history-date">{date}</div>
            <div class="history-meta">뉴스 {raw.get('news_count', 0)}건</div>
        </div>"""

    reports_js = json.dumps({r["date"]: markdown_to_html(r["report_korean"]) for r in reports}, ensure_ascii=False)
    kst = pytz.timezone("Asia/Seoul")
    updated_at = datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>멕시코 세탁기 마켓 인텔리전스</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Malgun Gothic', sans-serif; background: #f0f4f8; color: #222; }}
    .header {{ background: linear-gradient(135deg, #003087, #0066cc); color: white; padding: 20px 32px; }}
    .header h1 {{ font-size: 20px; }}
    .updated {{ font-size: 12px; color: #cce0ff; margin-top: 4px; }}
    .container {{ display: flex; max-width: 1200px; margin: 24px auto; gap: 20px; padding: 0 16px; }}
    .sidebar {{ width: 200px; flex-shrink: 0; }}
    .sidebar h2 {{ font-size: 13px; color: #666; margin-bottom: 10px; }}
    .history-item {{ background: white; border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; cursor: pointer; border: 2px solid transparent; }}
    .history-item:hover {{ border-color: #0066cc; }}
    .history-item.active {{ border-color: #0066cc; background: #e8f0fe; }}
    .history-date {{ font-size: 14px; font-weight: bold; color: #003087; }}
    .history-meta {{ font-size: 11px; color: #888; margin-top: 2px; }}
    .main {{ flex: 1; background: white; border-radius: 12px; padding: 32px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); min-height: 600px; }}
    .main h1 {{ color: #1a1a2e; border-bottom: 3px solid #0066cc; padding-bottom: 8px; margin-bottom: 16px; font-size: 22px; }}
    .main h2 {{ color: #0066cc; margin-top: 28px; margin-bottom: 8px; }}
    .main h3 {{ color: #333; margin-top: 16px; margin-bottom: 6px; }}
    .main p {{ line-height: 1.7; margin: 6px 0; }}
    .main ul {{ padding-left: 20px; margin: 8px 0; }}
    .main li {{ line-height: 1.7; margin: 4px 0; }}
    .main table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
    .main th {{ background: #e8f0fe; border: 1px solid #ddd; padding: 8px 12px; }}
    .main td {{ border: 1px solid #ddd; padding: 8px 12px; }}
    @media (max-width: 640px) {{ .container {{ flex-direction: column; }} .sidebar {{ width: 100%; }} }}
  </style>
</head>
<body>
<div class="header">
  <h1>🇲🇽 멕시코 세탁기 마켓 인텔리전스</h1>
  <div class="updated">마지막 업데이트: {updated_at} · 총 {len(reports)}일치 누적</div>
</div>
<div class="container">
  <div class="sidebar">
    <h2>📅 날짜별 리포트</h2>
    {history_items if history_items else '<p style="color:#aaa;font-size:13px">아직 데이터 없음</p>'}
  </div>
  <div class="main" id="report-content">
    {latest_report_html}
  </div>
</div>
<script>
  const allReports = {reports_js};
  let currentDate = '{latest_date}';
  if (currentDate !== '-') {{
    const btn = document.getElementById('btn-' + currentDate);
    if (btn) btn.classList.add('active');
  }}
  function loadReport(date) {{
    document.getElementById('report-content').innerHTML = allReports[date] || '<p>불러올 수 없습니다.</p>';
    document.querySelectorAll('.history-item').forEach(el => el.classList.remove('active'));
    const btn = document.getElementById('btn-' + date);
    if (btn) btn.classList.add('active');
    window.scrollTo(0, 0);
  }}
</script>
</body>
</html>"""

    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"[GitHub Pages] docs/index.html 생성 완료 ({len(reports)}개 리포트)")


def run_agent():
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("🚀 멕시코 마켓 인텔리전스 에이전트 시작")
    logger.info("=" * 60)

    report = None
    raw_data = {}

    try:
        logger.info("\n[Step 1/5] 데이터 수집 시작...")
        news_data = collect_google_news(Config.NEWS_KEYWORDS, Config.LOOKBACK_DAYS)
        reddit_data = collect_reddit_posts(Config.REDDIT_SUBREDDITS, Config.REDDIT_SEARCH_QUERY, Config.LOOKBACK_DAYS)
        ecommerce_data = collect_ecommerce_via_apify("lavadora")
        raw_data = {"news": news_data, "reddit": reddit_data, "ecommerce": ecommerce_data}

        logger.info("\n[Step 2/5] 데이터 전처리 중...")
        raw_text = preprocess_data_for_ai(news_data, reddit_data, ecommerce_data)

        logger.info("\n[Step 3/5] AI 분석 중...")
        report = analyze_data(raw_text)

        logger.info("\n[Step 4/5] GitHub Pages 업데이트 중...")
        save_report_json(report, raw_data)
        build_index_html()

        logger.info("\n[Step 5/5] Gmail 발송 중...")
        success = send_notification(report)
        if success:
            logger.info("✅ 모든 작업 완료!")
        else:
            logger.error("❌ Gmail 발송 실패!")

    except Exception as e:
        logger.critical(f"🔥 치명적 오류: {e}", exc_info=True)
        try:
            kst = pytz.timezone("Asia/Seoul")
            error_report = f"# 에이전트 오류\n\n시간: {datetime.now(kst).strftime('%Y-%m-%d %H:%M KST')}\n\n오류: {str(e)[:500]}"
            send_gmail(error_report)
        except Exception:
            pass

    finally:
        elapsed = (datetime.now() - start_time).seconds
        logger.info(f"\n총 실행 시간: {elapsed}초")

    return report


def run_scheduler():
    schedule.every().day.at("00:00").do(run_agent)
    logger.info("스케줄러 시작 - 매일 KST 09:00에 실행")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--schedule":
        run_scheduler()
    else:
        run_agent()
