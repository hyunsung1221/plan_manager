from fastmcp import FastMCP
import sys
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime, timedelta

# 모듈 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    import tools
    import scheduler_job
except ImportError as e:
    print(f"❌ 필수 모듈을 찾을 수 없습니다: {e}")
    sys.exit(1)

# 1. MCP 서버 초기화
mcp = FastMCP("plan_manager")

# ==============================================================================
# 환경 변수 및 스케줄러 설정
# ==============================================================================
env_token = os.environ.get("GOOGLE_TOKEN_JSON")
if env_token:
    token_path = os.path.join(current_dir, "token.json")
    try:
        with open(token_path, "w") as f:
            f.write(env_token)
        print("✅ 환경변수에서 token.json 생성")
    except IOError as e:
        print(f"⚠️ token.json 오류: {e}")

env_creds = os.environ.get("GOOGLE_CREDENTIALS_JSON")
if env_creds:
    creds_path = os.path.join(current_dir, "credentials.json")
    try:
        with open(creds_path, "w") as f:
            f.write(env_creds)
        print("✅ 환경변수에서 credentials.json 생성")
    except IOError as e:
        print(f"⚠️ credentials.json 오류: {e}")

data_dir = os.environ.get("DATA_DIR", current_dir)
if not os.path.exists(data_dir):
    try:
        os.makedirs(data_dir, exist_ok=True)
    except Exception:
        pass

db_path = os.path.join(data_dir, "jobs.sqlite")
jobstores = {
    'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')
}

scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()


# ==============================================================================
# 헬퍼 함수
# ==============================================================================
def _register_report_job(group_name: str, subject_query: str, delay_minutes: int) -> str:
    try:
        run_time = datetime.now() + timedelta(minutes=delay_minutes)
        gmail_service, _ = tools.get_services()
        profile = gmail_service.users().getProfile(userId='me').execute()
        my_email = profile['emailAddress']

        scheduler.add_job(
            scheduler_job.report_status,
            'date',
            run_date=run_time,
            args=[group_name, subject_query, my_email]
        )
        return f"⏰ 예약 완료! {delay_minutes}분 뒤 확인."
    except Exception as e:
        return f"⛔ 예약 오류: {str(e)}"


# ==============================================================================
# 도구(Tool) 정의
# ==============================================================================

import auth  # auth 모듈 import 확인

@mcp.tool()
def login_gmail() -> str:
    """
    구글 로그인이 필요할 때 인증 링크를 요청합니다.
    사용자가 이 링크로 들어가서 로그인을 하고, 나오는 '인증 코드'를 복사해야 합니다.
    """
    try:
        url = auth.get_authorization_url()
        return (
            f"🔐 구글 로그인이 필요합니다.\n"
            f"1. 아래 링크를 클릭하여 로그인하세요:\n{url}\n\n"
            f"2. 화면에 나오는 '인증 코드'를 복사하세요.\n"
            f"3. `submit_auth_code` 도구를 사용해 코드를 전달해 주세요."
        )
    except Exception as e:
        return f"오류 발생: {str(e)}"

@mcp.tool()
def submit_auth_code(code: str) -> str:
    """
    login_gmail 도구를 통해 얻은 인증 코드를 입력하여 로그인을 완료합니다.
    """
    result = auth.exchange_code_for_token(code)
    # 인증 성공 시 스케줄러 등을 재정비하거나 서비스를 갱신할 수 있음
    return result

# ... (기존 send_gmail 등 다른 툴 수정) ...

@mcp.tool()
def find_contact_email(name: str) -> str:
    """이름으로 이메일 주소를 검색합니다."""
    email = tools.get_email_from_name(name)
    if email:
        return f"✅ '{name}' 이메일: {email}"
    else:
        return f"❌ '{name}' 없음."


@mcp.tool()
def send_gmail(recipient_names: str, subject: str, body: str,
               enable_report: bool = False, report_delay_minutes: int = 60) -> str:
    """이메일 전송 및 답장 확인 예약."""
    if not os.path.exists(os.path.join(current_dir, "token.json")):
        return "⛔ 로그인이 되어있지 않습니다. `login_gmail` 도구를 먼저 실행해 주세요."

    names = [n.strip() for n in recipient_names.split(',')]
    email_list = []
    failed_names = []

    for name in names:
        email = tools.get_email_from_name(name)
        if email:
            email_list.append(email)
        else:
            failed_names.append(name)

    if not email_list:
        return f"❌ 실패: 이름 못 찾음 ({', '.join(failed_names)})."

    try:
        tools.send_email(email_list, subject, body)
    except Exception as e:
        return f"❌ 전송 에러: {str(e)}"

    msg = f"📤 {len(email_list)}명에게 발송 완료."
    if failed_names:
        msg += f"\n(⚠️ 실패: {', '.join(failed_names)})"

    if enable_report:
        group_name = f"{recipient_names} 답장체크"
        schedule_msg = _register_report_job(group_name, subject, report_delay_minutes)
        msg += f"\n\n{schedule_msg}"

    return msg


@mcp.tool()
def check_my_replies(subject_keyword: str) -> str:
    """답장 메일 확인."""
    try:
        replies = tools.fetch_replies(subject_keyword)
    except Exception as e:
        return f"❌ 확인 에러: {str(e)}"

    if not replies:
        return "📭 답장 없음."

    result_text = f"🔍 {len(replies)}개의 답장 발견:\n"
    for r in replies:
        summary = r['body'][:100] + "..." if len(r['body']) > 100 else r['body']
        result_text += f"\n👤 {r['sender']}: {summary}\n---"

    return result_text


@mcp.tool()
def schedule_status_report(group_name: str, subject_query: str, delay_minutes: int = 60) -> str:
    """특정 시간 뒤에 답장 여부를 확인하여 리포트하도록 예약합니다."""
    return _register_report_job(group_name, subject_query, delay_minutes)


# ==============================================================================
# [핵심] 서버 실행 (HTTP / SSE 모드)
# ==============================================================================
if __name__ == "__main__":
    # Railway 등 외부 환경에서 주입되는 포트 사용
    port = int(os.environ.get("PORT", 8000))

    print(f"🚀 MCP 서버를 HTTP(SSE) 모드로 시작합니다.")
    print(f"📡 접속 주소: http://0.0.0.0:{port}/sse")

    # transport="sse"는 MCP 프로토콜을 HTTP 서버 위에서 실행한다는 의미입니다.
    # 0.0.0.0으로 바인딩하여 외부(Docker/Railway)에서 접속 가능하게 합니다.
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8000,
        path="/",
        log_level="debug",
    )