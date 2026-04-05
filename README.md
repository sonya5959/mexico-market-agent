🇲🇽 멕시코 세탁기 마켓 인텔리전스 에이전트
멕시코 세탁기 시장의 뉴스 · 커뮤니티 반응 · 이커머스 데이터를 매일 자동 수집하여
한국어 분석 리포트를 Gmail로 발송하고 이 페이지에 자동 업데이트합니다.

수집 데이터 소스
소스내용Google News RSS멕시코 가전 최신 뉴스Reddit (PRAW)현지 소비자 커뮤니티 반응Mercado Libre MX이커머스 가격 · 할인 · 리뷰Amazon Mexico이커머스 가격 · 할인 · 리뷰

필요한 API 키 (총 4가지)
#서비스비용발급 위치1Reddit API무료reddit.com/prefs/apps2Apify월 $5 무료 크레딧console.apify.com3Anthropic Claude사용량 과금console.anthropic.com4Gmail 앱 비밀번호완전 무료Google 계정 → 보안

Gmail 앱 비밀번호 발급 (5분)

Gmail 로그인 → Google 계정 관리
보안 → 2단계 인증 활성화 (필수!)
검색창에 "앱 비밀번호" 검색 → 클릭
앱: 메일 / 기기: 기타(이름: 마켓봇) → 생성
16자리 비밀번호 복사 → .env의 GMAIL_APP_PASSWORD에 공백 없이 입력


실행 방법
bash# 1. 라이브러리 설치
pip install -r requirements.txt

# 2. 환경변수 설정
cp .env.example .env
# .env 파일 열어서 API 키 4개 입력

# 3. 실행
python agent.py

자동화 (GitHub Actions)
.github/workflows/market_agent.yml 파일이 매일 KST 09:00에 자동 실행됩니다.
GitHub 레포 → Settings → Secrets에 API 키를 등록하면 됩니다.
