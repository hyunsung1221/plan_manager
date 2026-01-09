# gmail_mcp.py
import os
import sys
import json
from datetime import datetime, timedelta

from fastmcp import FastMCP, Context
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.dependencies import get_access_token
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from google.oauth2.credentials import Credentials

# 모듈 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    import tools
    import scheduler_job
    import auth
except ImportError as e:
    print(f"❌ 필수 모듈 찾기 실패: {e}")
    sys.exit(1)

# ==============================================================================
# 1. Google Auth Provider 설정 (FastMCP Reference 적용)
# ==============================================================================
# 실제 운영 시에는 .env 파일이나 환경변수로 관리하는 것이 좋습니다.
auth_provider = GoogleProvider(
    client_id=os.environ.get("GOOGLE_CLIENT_ID", "YOUR_CLIENT_ID_HERE"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE"),
    base_url=os.environ.get("BASE_URL", "http://localhost:8000"),  # 실제 배포 주소로 변경 필요
    required_scopes=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/contacts.readonly"
    ]
)

mcp = FastMCP("plan_manager", auth=auth_provider)

# ==============================================================================
# 2. 데이터 디렉토리 및 스케줄러 설정
# ==============================================================================
data_dir = os.environ.get("DATA_DIR", current_dir)
if not os.path.exists(data_dir):
    os.makedirs(data_dir, exist_ok=True)

db_path = os.path.join(data_dir, "jobs.sqlite")
jobstores = {'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')}
scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()


# ==============================================================================
# 3. 헬퍼 함수
# ==============================================================================
def _get_current_user_email_and_creds():
    """FastMCP 의존성을 통해 현재 토큰을 가져오고 Credentials 객체를 생성"""
    token = get_access_token()
    email = token.claims.get("email")

    # FastMCP 토큰에서 Access Token 추출하여 Google Credentials 생성
    # 주의: token 객체의 구조에 따라 access_token 접근 방식이 다를 수 있음
    # 여기서는 token이 Access Token 문자열 자체이거나, 속성으로 가지고 있다고 가정
    access_token = getattr(token, "access_token", str(token))

    creds = Credentials(token=access_token)

    # [중요] 스케줄러(백그라운드 작업)를 위해 현재 유효한 토큰을 DB에 백업
    # Refresh Token이 있다면 좋겠지만, Access Token이라도 저장하여 1시간 내 작업 보장
    token_info = {
        "token": access_token,
        "expiry": token.claims.get("exp")  # 만료 시간 등 추가 정보 저장 가능
    }
    auth.upsert_user_creds(email, token_info)

    return email, creds


def _register_report_job(email: str, group_name: str, subject_query: str, delay_minutes: int) -> str:
    """내부용: 리포트 예약"""
    try:
        run_time = datetime.now() + timedelta(minutes=delay_minutes)

        # 예약 시점에는 현재 사용자의 이메일만 넘기고, 실행 시점에 DB에서 토큰을 조회
        scheduler.add_job(
            scheduler_job.report_status,
            'date',
            run_date=run_time,
            args=[email, group_name, subject_query, email]
        )
        return f"⏰ 예약 완료! {delay_minutes}분 뒤 '{email}' 계정으로 보고서가 발송됩니다."
    except Exception as e:
        return f"⛔ 예약 오류: {str(e)}"


# ==============================================================================
# 4. 도구 정의 (보안 적용됨)
# ==============================================================================
# username, password 인자가 제거되었습니다.

@mcp.tool()
def find_contact_email(name: str) -> str:
    """[보안] 주소록에서 이메일을 검색합니다. (Google 로그인 필요)"""
    try:
        email, creds = _get_current_user_email_and_creds()
        contact_email = tools.get_email_from_name_with_creds(creds, name)
        return f"✅ '{name}' 이메일: {contact_email}" if contact_email else f"❌ '{name}'님을 찾을 수 없습니다."
    except Exception as e:
        return f"❌ 오류: {str(e)}"


@mcp.tool()
def send_gmail(recipient_names: str, subject: str, body: str,
               enable_report: bool = False, report_delay_minutes: int = 60) -> str:
    """[보안] 이메일을 전송하고 필요시 리포트를 예약합니다. (Google 로그인 필요)"""
    try:
        user_email, creds = _get_current_user_email_and_creds()

        names = [n.strip() for n in recipient_names.split(',')]
        email_list = []
        for n in names:
            e = tools.get_email_from_name_with_creds(creds, n)
            if e: email_list.append(e)

        if not email_list: return "❌ 발송할 이메일 주소를 찾을 수 없습니다."

        tools.send_email_with_creds(creds, email_list, subject, body)
        msg = f"📤 '{user_email}' 계정으로 메일을 성공적으로 보냈습니다."

        if enable_report:
            msg += f"\n\n{_register_report_job(user_email, recipient_names, subject, report_delay_minutes)}"
        return msg
    except Exception as e:
        return f"❌ 전송 에러: {str(e)}"


@mcp.tool()
def check_my_replies(subject_keyword: str) -> str:
    """[보안] 특정 키워드가 포함된 답장을 확인합니다. (Google 로그인 필요)"""
    try:
        user_email, creds = _get_current_user_email_and_creds()

        replies = tools.fetch_replies_with_creds(creds, subject_keyword)
        if not replies: return "📭 도착한 답장이 없습니다."

        res = f"🔍 {user_email}님, {len(replies)}개의 답장을 발견했습니다:\n"
        for r in replies:
            res += f"\n👤 {r['sender']}: {r['body'][:100]}...\n---"
        return res
    except Exception as e:
        return f"❌ 확인 에러: {str(e)}"


# ==============================================================================
# 5. 서버 실행
# ==============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Plan Manager MCP 서버가 시작되었습니다. (Port: {port})")
    print(f"🔒 Google OAuth 모드로 실행 중입니다.")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)