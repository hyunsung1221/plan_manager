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
    import auth
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

# 유저별로 진행 중인 OAuth flow를 저장 (메모리 격리)
# 서버 재시작 시 초기화되지만, flow 객체는 직렬화가 불가능하므로 메모리 관리가 적합합니다.
active_flows = {}


# ==============================================================================
# 헬퍼 함수
# ==============================================================================
def _register_report_job(username: str, group_name: str, subject_query: str, delay_minutes: int) -> str:
    """특정 유저의 답장 확인 작업을 예약합니다."""
    try:
        creds = auth.get_user_creds(username)
        if not creds:
            return f"⛔ '{username}'님은 구글 계정 연동이 필요합니다."

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
            args=[username, group_name, subject_query, my_email]  # username 인자 추가
        )
        return f"⏰ 예약 완료! {delay_minutes}분 뒤 '{my_email}' 계정으로 보고서가 발송됩니다."
    except Exception as e:
        return f"⛔ 예약 오류: {str(e)}"


# ==============================================================================
# 통합 인증 도구 (Flow 기반)
# ==============================================================================

@mcp.tool()
def manage_user_auth(username: str, password: str, auth_code: str = None) -> str:
    """
    사용자 인증 및 구글 연동을 하나의 흐름(Flow)으로 관리합니다.
    1. 가입되지 않은 경우: 자동으로 회원가입 후 구글 연동 링크 안내
    2. 가입된 경우: 로그인 후 구글 연동 여부 확인
       - 연동됨: 즉시 서비스 활성화 안내
       - 미연동: 구글 연동 링크 안내 또는 제출된 코드로 연동 완료
    """
    # [1단계] 로그인 시도 (비밀번호 검증)
    is_verified = auth.verify_user(username, password)

    if is_verified:
        # 로그인 성공: 기존 유저이며 비밀번호가 맞음
        creds = auth.get_user_creds(username)

        if creds:
            # 구글 토큰이 DB에 이미 있는 경우
            return f"✅ '{username}'님, 로그인이 완료되었으며 구글 계정도 이미 연동되어 있습니다. 모든 기능을 즉시 이용하실 수 있습니다."

        # 구글 토큰이 없는 경우 (연동 필요)
        if auth_code:
            # 사용자가 인증 코드를 가져온 경우 -> 연동 완료 처리
            flow = active_flows.get(username)
            if not flow:
                url, flow = auth.get_auth_url()
                active_flows[username] = flow
                return f"⚠️ 인증 세션이 만료되었습니다. 아래 링크에서 다시 인증을 진행해 주세요:\n{url}"

            try:
                flow.fetch_token(code=auth_code)
                auth.update_user_token(username, json.loads(flow.credentials.to_json()))
                if username in active_flows: del active_flows[username]
                return f"✅ '{username}'님, 구글 연동이 성공적으로 완료되었습니다. 이제 서비스를 시작하세요!"
            except Exception as e:
                return f"❌ 구글 코드 인증 실패: {str(e)}"
        else:
            # 코드가 없는 경우 -> 연동 링크 생성 및 안내
            url, flow = auth.get_auth_url()
            active_flows[username] = flow
            return (
                f"👋 '{username}'님, 로그인은 성공했으나 아직 구글 계정이 연동되지 않았습니다.\n"
                f"1. 아래 링크에서 인증을 진행하세요:\n{url}\n\n"
                f"2. 완료 후 발급받은 코드를 'auth_code' 인자로 넣어 다시 호출해 주세요."
            )

    else:
        # 로그인 실패 (계정이 없거나 비밀번호가 틀림)
        # 먼저 계정이 존재하는지 확인 (비밀번호 오류인지 신규 유저인지 구분)
        from sqlalchemy.orm import Session
        session = auth.SessionLocal()
        existing_user = session.query(auth.User).filter(auth.User.username == username).first()
        session.close()

        if existing_user:
            return f"❌ 인증 실패: '{username}'님, 비밀번호가 틀립니다. 다시 확인해 주세요."

        # 계정이 없는 경우 -> 새로운 유저로 가입 시도
        success, msg = auth.register_user(username, password)

        if success:
            # 신규 가입 성공 -> 바로 구글 연동 단계로 진입
            url, flow = auth.get_auth_url()
            active_flows[username] = flow
            return (
                f"✨ '{username}'님, 회원가입이 완료되었습니다!\n"
                f"마지막 단계로 구글 계정 연동이 필요합니다.\n"
                f"1. 아래 링크에서 인증을 진행하세요:\n{url}\n\n"
                f"2. 완료 후 발급받은 코드를 'auth_code' 인자로 넣어 다시 호출해 주세요."
            )
        else:
            return f"❌ 회원가입 오류: {msg}"


# ==============================================================================
# 서비스 도구 (세션 격리 적용)
# ==============================================================================

@mcp.tool()
def find_contact_email(username: str, name: str) -> str:
    """특정 유저의 주소록에서 이름으로 이메일 주소를 검색합니다."""
    creds = auth.get_user_creds(username)
    if not creds: return f"⛔ '{username}'님은 구글 연동이 필요합니다."

    email = tools.get_email_from_name_with_creds(creds, name)
    if email:
        return f"✅ '{name}' 이메일: {email}"
    else:
        return f"❌ '{name}'님을 주소록에서 찾을 수 없습니다."


@mcp.tool()
def send_gmail(username: str, recipient_names: str, subject: str, body: str,
               enable_report: bool = False, report_delay_minutes: int = 60) -> str:
    """이메일을 전송하고 필요한 경우 답장 확인 리포트를 예약합니다."""
    creds = auth.get_user_creds(username)
    if not creds: return f"⛔ '{username}'님은 구글 연동이 필요합니다."

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
        return f"❌ 실패: 수신자 주소를 찾을 수 없습니다 ({', '.join(failed_names)})."

    try:
        tools.send_email_with_creds(creds, email_list, subject, body)
    except Exception as e:
        return f"❌ 전송 에러: {str(e)}"

    msg = f"📤 {len(email_list)}명에게 메일을 성공적으로 보냈습니다."
    if failed_names:
        msg += f"\n(⚠️ 실패: {', '.join(failed_names)})"

    if enable_report:
        group_name = f"{recipient_names} 답장체크"
        schedule_msg = _register_report_job(username, group_name, subject, report_delay_minutes)
        msg += f"\n\n{schedule_msg}"

    return msg


@mcp.tool()
def check_my_replies(username: str, subject_keyword: str) -> str:
    """특정 유저의 계정으로 온 답장 메일을 확인합니다."""
    creds = auth.get_user_creds(username)
    if not creds: return f"⛔ '{username}'님은 구글 연동이 필요합니다."

    try:
        replies = tools.fetch_replies_with_creds(creds, subject_keyword)
    except Exception as e:
        return f"❌ 확인 에러: {str(e)}"

    if not replies:
        return "📭 도착한 답장이 없습니다."

    result_text = f"🔍 {username}님, {len(replies)}개의 답장을 발견했습니다:\n"
    for r in replies:
        summary = r['body'][:100] + "..." if len(r['body']) > 100 else r['body']
        result_text += f"\n👤 {r['sender']}: {summary}\n---"

    return result_text


@mcp.tool()
def schedule_status_report(username: str, group_name: str, subject_query: str, delay_minutes: int = 60) -> str:
    """특정 시간 뒤에 답장 여부를 확인하여 리포트하도록 예약합니다."""
    return _register_report_job(username, group_name, subject_query, delay_minutes)


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