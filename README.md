# 🇲🇽 멕시코 가전 마켓 인텔리전스 자동화 에이전트

> 멕시코 세탁기 시장의 뉴스 · 커뮤니티 반응 · 이커머스 프로모션 데이터를  
> 매일 자동 수집하여 **한국어 분석 리포트**를 Slack/Telegram으로 발송합니다.

---

## 📐 전체 아키텍처

```
[데이터 소스]                [수집 모듈]           [AI 분석]        [발송]
─────────────────────────────────────────────────────────────────────────
Google News RSS    ──────► collect_google_news()  ─┐
                                                    │
Reddit (PRAW)      ──────► collect_reddit_posts()  ─┼─► preprocess()
                                                    │         │
Mercado Libre MX   ─┐                              │         ▼
                    ├──► collect_ecommerce_        ─┘   analyze_data()  ──► Claude / GPT-4
Amazon Mexico      ─┘         via_apify()                    │
                                                             ▼
                                                    send_notification()
                                                     ├─ Slack Webhook
                                                     └─ Telegram Bot
```

---

## 📁 파일 구조

```
mexico_market_agent/
├── agent.py                          # 메인 에이전트 코드 (전체 로직)
├── requirements.txt                  # 파이썬 라이브러리 목록
├── .env.example                      # 환경 변수 템플릿 (복사 후 .env로 사용)
├── .env                              # 실제 API 키 (Git에 올리지 말 것!)
├── .gitignore                        # .env, 로그, 캐시 제외
├── README.md                         # 이 파일
└── .github/
    └── workflows/
        └── market_agent.yml          # GitHub Actions 자동화 설정
```

---

## 🚀 빠른 시작 가이드

### Step 1: 프로젝트 설정

```bash
# 프로젝트 클론 또는 폴더 생성
git clone https://github.com/your-org/mexico-market-agent.git
cd mexico-market-agent

# 가상환경 생성 (권장)
python -m venv venv
source venv/bin/activate          # macOS/Linux
# venv\Scripts\activate           # Windows

# 라이브러리 설치
pip install -r requirements.txt
```

### Step 2: .env 파일 설정

```bash
cp .env.example .env
# .env 파일을 열어 아래 API 키들을 입력
```

---

## 🔑 API 키 발급 가이드 (6개)

### 1. Reddit API (무료)
1. https://www.reddit.com/prefs/apps 접속
2. **"create another app"** 클릭
3. `name`: 아무 이름 / `type`: **script** 선택
4. `redirect uri`: `http://localhost:8080` 입력
5. **client_id** (앱 이름 아래 짧은 문자열)와 **client_secret** 복사
6. `.env`에 입력:
   ```
   REDDIT_CLIENT_ID=abc123xyz
   REDDIT_CLIENT_SECRET=secretkey456
   REDDIT_USER_AGENT=MarketBot/1.0 by YourUsername
   ```

### 2. Apify API (월 $5 무료 크레딧)
1. https://apify.com/sign-up 에서 가입
2. https://console.apify.com/account/integrations → **API 토큰 복사**
3. `.env`에 입력: `APIFY_API_TOKEN=apify_api_xxxx`

> ⚠️ **Actor 확인 필수**: Apify Console에서 아래 Actor가 사용 가능한지 확인하세요.
> - `apify/mercado-libre-scraper` (없으면 Store에서 유사 Actor 검색)
> - `apify/amazon-product-scraper`
> 
> Actor ID는 Store URL에서 확인: `apify.com/apify/mercado-libre-scraper`

### 3. Anthropic Claude API
1. https://console.anthropic.com/ 접속
2. **API Keys** → **Create Key**
3. `.env`에 입력: `ANTHROPIC_API_KEY=sk-ant-xxxx`

### 4. Slack Webhook (무료)
1. https://api.slack.com/apps → **Create New App** → "From scratch"
2. **Incoming Webhooks** → 토글 ON
3. **Add New Webhook to Workspace** → 채널 선택 (예: #market-intelligence)
4. 생성된 **Webhook URL** 복사
5. `.env`에 입력: `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...`

### 5. Telegram Bot (무료, Slack 대신 선택)
1. Telegram에서 `@BotFather` 검색 → `/newbot`
2. 봇 이름과 username 입력 → **토큰 발급**
3. 리포트 받을 채널/그룹에 봇 추가 후 관리자 권한 부여
4. `@userinfobot` 에서 채팅방 ID 확인
5. `.env`에 입력:
   ```
   TELEGRAM_BOT_TOKEN=1234567890:ABCdef...
   TELEGRAM_CHAT_ID=-1001234567890
   NOTIFICATION_CHANNEL=telegram
   ```

---

## ▶️ 로컬 실행

```bash
# 즉시 1회 실행 (테스트)
python agent.py

# 스케줄 모드 (매일 KST 09:00 자동 실행 - 프로세스 유지 필요)
python agent.py --schedule
```

---

## ⚙️ GitHub Actions 자동화 (권장 - 무료!)

GitHub의 무료 CI/CD를 활용하면 서버 없이 매일 자동 실행됩니다.  
**Public 레포: 무제한 무료 / Private 레포: 월 2,000분 무료**

### 설정 방법

**1. GitHub 레포 생성 후 코드 Push**
```bash
git init
git add .
git commit -m "feat: 멕시코 마켓 에이전트 초기 설정"
git remote add origin https://github.com/your-username/mexico-market-agent.git
git push -u origin main
```

**2. Secrets 등록** (Settings → Secrets and variables → Actions → New repository secret)

| Secret 이름 | 값 |
|------------|---|
| `REDDIT_CLIENT_ID` | Reddit 앱 client_id |
| `REDDIT_CLIENT_SECRET` | Reddit 앱 client_secret |
| `REDDIT_USER_AGENT` | 예: `MarketBot/1.0 by yourname` |
| `APIFY_API_TOKEN` | Apify API 토큰 |
| `ANTHROPIC_API_KEY` | Anthropic API 키 |
| `SLACK_WEBHOOK_URL` | Slack Webhook URL |

**3. 워크플로우 활성화 확인**
- GitHub 레포 → **Actions** 탭 → 워크플로우가 보이면 성공!
- **"Run workflow"** 버튼으로 즉시 테스트 실행 가능

**4. 실행 로그 확인**
- Actions 탭 → 실행 내역 클릭 → 단계별 로그 확인
- 완료 후 **Artifacts** 섹션에서 리포트 파일 다운로드 가능

### cron 스케줄 변경 방법

`.github/workflows/market_agent.yml` 파일에서:
```yaml
schedule:
  - cron: "0 0 * * *"   # UTC 00:00 = KST 09:00
  # - cron: "0 23 * * *"  # UTC 23:00 = KST 08:00 (다음날)
  # - cron: "0 1 * * *"   # UTC 01:00 = KST 10:00
```

> 💡 cron 표현식 도움: https://crontab.guru

---

## 📊 예상 비용 (월 기준)

| 서비스 | 무료 한도 | 예상 사용량 | 월 비용 |
|--------|----------|-----------|--------|
| GitHub Actions | 2,000분/월 | ~30분/월 | **무료** |
| Reddit API | 무제한 (비상업) | - | **무료** |
| Apify | $5 크레딧/월 | ~$2~3 | **무료 내** |
| Anthropic Claude | - | ~$0.5~1/일 | **$15~30** |
| Slack/Telegram | 무료 | - | **무료** |
| **합계** | | | **$15~30/월** |

> OpenAI GPT-4o로 전환 시 비용 유사. Claude Haiku 모델 사용 시 약 1/10 절감 가능.

---

## 🔧 트러블슈팅

### Apify Actor를 찾을 수 없는 경우
```python
# agent.py의 Config 클래스에서 Actor ID를 실제 사용 가능한 것으로 변경
APIFY_MERCADOLIBRE_ACTOR = "실제_actor_id"  # Apify Store에서 검색
```
Apify Store(https://apify.com/store)에서 "mercado libre" 검색 후 URL에서 ID 확인.

### Reddit API 인증 오류
```
OAuthException: error processing request
```
→ `REDDIT_USER_AGENT`를 `YourApp/1.0 by YourRedditUsername` 형식으로 변경

### Slack 메시지가 너무 길어 잘리는 경우
`send_to_slack()` 함수의 `MAX_SLACK_LEN` 값 조정 (현재 2800자)

### GitHub Actions에서 타임아웃 발생
`.github/workflows/market_agent.yml`에서 `timeout-minutes: 30`을 60으로 증가

---

## 📌 .gitignore 설정 (필수!)

```gitignore
# API 키 보호
.env

# 실행 결과물 (선택)
*.log
report_*.md
debug_raw_*.json

# Python 캐시
__pycache__/
*.pyc
venv/
.venv/
```

---

## 🗺️ 향후 개선 로드맵

- [ ] **다중 카테고리**: 냉장고, 에어컨 등 카테고리 확장
- [ ] **경쟁사 가격 트래킹**: 브랜드별 가격 변동 히스토리 저장 (SQLite/Supabase)
- [ ] **트렌드 시각화**: Matplotlib 차트를 이미지로 생성하여 Slack에 첨부
- [ ] **다국어 확장**: 브라질(포르투갈어), 칠레(스페인어) 시장 추가
- [ ] **대시보드**: Streamlit으로 웹 대시보드 구축
