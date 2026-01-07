from fastmcp import FastMCP
import sys
import os
import json
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime, timedelta

# 모듈 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    import tools
    import scheduler_job
    import auth  # 수정된 auth.py 필요
except ImportError as e:
    print(f"❌ 필수 모듈을 찾을 수 없습니다: {e}")
    sys.exit(1)

# 1. MCP 서버 초기화
mcp = FastMCP("plan_manager")

# ==============================================================================
# 데이터 디렉토리 및 스케줄러 설정
# ==============================================================================
data_dir = os.environ.get("DATA_DIR", current_dir)
if not os.path.exists(data_dir):
    try:
        os.makedirs(data_dir, exist_ok=True)
    except Exception:
        pass

# 스케줄러가 작업을 저장할 SQLite DB 설정
db_path = os.path.join(data_dir, "jobs.sqlite")
jobstores = {
    'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')
}

scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()

# 세션 관리 (메모리 상에 로그인 유저 상태 유지)
# 실제 서비스 시에는 Redis나 DB 세션을 사용하는 것이 좋습니다.
current_session = {"username": None, "flow": None}


# ==============================================================================
# 헬퍼 함수
# ==============================================================================
def _register_report_job(group_name: str, subject_query: str, delay_minutes: int) -> str:
    """답장 확인 작업을 예약합니다."""
    try:
        username = current_session.get("username")
        if not username:
            return "⛔ 시스템 로그인이 필요합니다."

        creds = auth.get_user_creds(username)
        if not creds:
            return "⛔ 구글 계정 연동이 필요합니다."

        run_time = datetime.now() + timedelta(minutes=delay_minutes)

        # 주입된 creds를 사용하여 본인의 이메일 주소 확인
        from googleapiclient.discovery import build
        gmail_service = build('gmail', 'v1', credentials=creds)
        profile = gmail_service.users().getProfile(userId='me').execute()
        my_email = profile['emailAddress']

        scheduler.add_job(
            scheduler_job.report_status,
            'date',
            run_date=run_time,
            args=[group_name, subject_query, my_email]
        )
        return f"⏰ 예약 완료! {delay_minutes}분 뒤 '{my_email}' 계정으로 보고서가 발송됩니다."
    except Exception as e:
        return f"⛔ 예약 오류: {str(e)}"


# ==============================================================================
# 도구(Tool) 정의
# ==============================================================================

@mcp.tool()
def signup(username: str, password: str) -> str:
    """새로운 사용자를 등록합니다. (ID/PW 방식)"""
    success, msg = auth.register_user(username, password)
    return msg


@mcp.tool()
def login_user(username: str, password: str) -> str:
    """ID와 비밀번호로 시스템에 로그인하여 세션을 활성화합니다."""
    if auth.verify_user(username, password):
        current_session["username"] = username
        return f"✅ '{username}'님 로그인 성공! 이제 구글 연동 및 기능을 사용할 수 있습니다."
    return "❌ 로그인 실패: 아이디 또는 비밀번호가 틀립니다."


@mcp.tool()
def login_gmail() -> str:
    """시스템 로그인 후, 구글 계정을 연동하기 위한 인증 링크를 요청합니다."""
    if not current_session["username"]:
        return "⛔ 먼저 `login_user`를 통해 시스템에 로그인해 주세요."

    try:
        url, flow = auth.get_auth_url()
        current_session["flow"] = flow  # OAuth flow 객체 임시 저장
        return (
            f"🔐 구글 계정 연동을 시작합니다.\n"
            f"1. 아래 링크를 클릭하여 로그인하세요:\n{url}\n\n"
            f"2. 화면에 나오는 '인증 코드'를 복사하세요.\n"
            f"3. `submit_auth_code` 도구를 사용해 코드를 전달해 주세요."
        )
    except Exception as e:
        return f"오류 발생: {str(e)}"


@mcp.tool()
def submit_auth_code(code: str) -> str:
    """복사한 구글 인증 코드를 제출하여 로그인을 완료하고 DB에 저장합니다."""
    username = current_session.get("username")
    flow = current_session.get("flow")

    if not username or not flow:
        return "⛔ 진행 중인 인증 세션이 없습니다. `login_gmail`을 먼저 실행하세요."

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        # 유저별로 DB에 토큰 저장
        auth.update_user_token(username, json.loads(creds.to_json()))
        current_session["flow"] = None  # 세션 초기화
        return f"✅ '{username}' 유저의 구글 계정 연동이 완료되었습니다. 이제 이메일 기능을 사용할 수 있습니다."
    except Exception as e:
        return f"❌ 인증 실패: {str(e)}"


@mcp.tool()
def find_contact_email(name: str) -> str:
    """이름으로 주소록에서 이메일 주소를 검색합니다."""
    username = current_session.get("username")
    if not username: return "⛔ 로그인이 필요합니다."

    creds = auth.get_user_creds(username)
    if not creds: return "⛔ 구글 연동이 필요합니다. `login_gmail`을 먼저 진행하세요."

    # creds를 직접 전달하여 주소록 검색
    email = tools.get_email_from_name_with_creds(creds, name)
    if email:
        return f"✅ '{name}' 이메일: {email}"
    else:
        return f"❌ '{name}'님을 주소록에서 찾을 수 없습니다."


@mcp.tool()
def send_gmail(recipient_names: str, subject: str, body: str,
               enable_report: bool = False, report_delay_minutes: int = 60) -> str:
    """이메일을 전송하고 필요한 경우 답장 확인 리포트를 예약합니다."""
    username = current_session.get("username")
    if not username: return "⛔ 로그인이 필요합니다."

    creds = auth.get_user_creds(username)
    if not creds: return "⛔ 구글 연동이 필요합니다."

    names = [n.strip() for n in recipient_names.split(',')]
    email_list = []
    failed_names = []

    for name in names:
        email = tools.get_email_from_name_with_creds(creds, name)
        if email:
            email_list.append(email)
        else:
            failed_names.append(name)

    if not email_list:
        return f"❌ 실패: 이름을 찾을 수 없습니다 ({', '.join(failed_names)})."

    try:
        # DB에서 가져온 creds를 주입하여 메일 전송
        tools.send_email_with_creds(creds, email_list, subject, body)
    except Exception as e:
        return f"❌ 전송 에러: {str(e)}"

    msg = f"📤 {len(email_list)}명에게 메일을 성공적으로 보냈습니다."
    if failed_names:
        msg += f"\n(⚠️ 실패: {', '.join(failed_names)})"

    if enable_report:
        group_name = f"{recipient_names} 답장체크"
        schedule_msg = _register_report_job(group_name, subject, report_delay_minutes)
        msg += f"\n\n{schedule_msg}"

    return msg


@mcp.tool()
def check_my_replies(subject_keyword: str) -> str:
    """로그인된 계정으로 온 답장 메일을 확인합니다."""
    username = current_session.get("username")
    if not username: return "⛔ 로그인이 필요합니다."

    creds = auth.get_user_creds(username)
    if not creds: return "⛔ 구글 연동이 필요합니다."

    try:
        replies = tools.fetch_replies_with_creds(creds, subject_keyword)
    except Exception as e:
        return f"❌ 확인 에러: {str(e)}"

    if not replies:
        return "📭 도착한 답장이 없습니다."

    result_text = f"🔍 {len(replies)}개의 답장을 발견했습니다:\n"
    for r in replies:
        summary = r['body'][:100] + "..." if len(r['body']) > 100 else r['body']
        result_text += f"\n👤 {r['sender']}: {summary}\n---"

    return result_text


@mcp.tool()
def schedule_status_report(group_name: str, subject_query: str, delay_minutes: int = 60) -> str:
    """특정 시간 뒤에 답장 여부를 확인하여 리포트하도록 예약합니다."""
    return _register_report_job(group_name, subject_query, delay_minutes)


# ==============================================================================
# 서버 실행 (HTTP 모드)
# ==============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Plan Manager MCP 서버가 시작되었습니다. (Port: {port})")

    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
        path="/",
        log_level="debug",
    )