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

db_path = os.path.join(data_dir, "jobs.sqlite")
jobstores = {'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')}

scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()

# 유저별 진행 중인 OAuth flow 저장 (세션 격리)
active_flows = {}


# ==============================================================================
# 헬퍼 함수
# ==============================================================================
def _register_report_job(username: str, group_name: str, subject_query: str, delay_minutes: int) -> str:
    """내부용: 리포트 예약 (이미 검증된 상태에서 호출됨)"""
    try:
        creds = auth.get_user_creds(username)
        run_time = datetime.now() + timedelta(minutes=delay_minutes)

        from googleapiclient.discovery import build
        gmail_service = build('gmail', 'v1', credentials=creds)
        profile = gmail_service.users().getProfile(userId='me').execute()
        my_email = profile['emailAddress']

        scheduler.add_job(
            scheduler_job.report_status,
            'date',
            run_date=run_time,
            args=[username, group_name, subject_query, my_email]
        )
        return f"⏰ 예약 완료! {delay_minutes}분 뒤 '{my_email}' 계정으로 보고서가 발송됩니다."
    except Exception as e:
        return f"⛔ 예약 오류: {str(e)}"


# ==============================================================================
# 통합 인증 및 흐름 관리 도구
# ==============================================================================

@mcp.tool()
def manage_user_auth(username: str, password: str, auth_code: str = None) -> str:
    """
    회원가입 -> 로그인 -> 구글 연동의 통합 플로우를 관리합니다.
    비밀번호가 틀리거나 타인의 아이디를 도용하는 것을 방지합니다.
    """
    # 1. 로그인 시도
    if auth.verify_user(username, password):
        creds = auth.get_user_creds(username)

        # 구글 연동 완료 상태
        if creds:
            return f"✅ '{username}'님, 인증 및 구글 연동이 모두 활성화되어 있습니다. 바로 서비스를 이용하세요."

        # 구글 연동 필요 상태
        if auth_code:
            flow = active_flows.get(username)
            if not flow:
                url, flow = auth.get_auth_url()
                active_flows[username] = flow
                return f"⚠️ 세션 만료. 다시 인증해 주세요: {url}"
            try:
                flow.fetch_token(code=auth_code)
                auth.update_user_token(username, json.loads(flow.credentials.to_json()))
                del active_flows[username]
                return f"✅ '{username}'님, 구글 연동 성공! 이제 서비스를 시작할 수 있습니다."
            except Exception as e:
                return f"❌ 코드 인증 실패: {str(e)}"
        else:
            url, flow = auth.get_auth_url()
            active_flows[username] = flow
            return (f"👋 '{username}'님, 로그인 성공! 구글 계정 연동이 필요합니다.\n"
                    f"1. 인증 링크: {url}\n2. 완료 후 코드를 'auth_code' 인자로 넣어 다시 호출하세요.")

    # 2. 가입 여부 확인 및 자동 가입
    from sqlalchemy.orm import Session
    session = auth.SessionLocal()
    user_exists = session.query(auth.User).filter(auth.User.username == username).first()
    session.close()

    if user_exists:
        return f"❌ 인증 실패: '{username}'님, 비밀번호가 일치하지 않습니다."

    # 신규 유저 가입 및 연동 시작
    success, msg = auth.register_user(username, password)
    if success:
        url, flow = auth.get_auth_url()
        active_flows[username] = flow
        return (f"✨ '{username}'님, 신규 가입 완료! 마지막 단계로 구글 연동이 필요합니다.\n"
                f"1. 인증 링크: {url}\n2. 완료 후 코드를 'auth_code'로 전달하세요.")
    return f"❌ 오류: {msg}"


# ==============================================================================
# 서비스 도구 (모든 도구에 비밀번호 검증 적용)
# ==============================================================================

@mcp.tool()
def find_contact_email(username: str, password: str, name: str) -> str:
    """[보안] 비밀번호 검증 후 주소록에서 이메일을 검색합니다."""
    if not auth.verify_user(username, password):
        return "❌ 인증 실패: 아이디 또는 비밀번호가 틀립니다."

    creds = auth.get_user_creds(username)
    if not creds: return "⛔ 구글 연동이 필요합니다."

    email = tools.get_email_from_name_with_creds(creds, name)
    return f"✅ '{name}' 이메일: {email}" if email else f"❌ '{name}'님을 찾을 수 없습니다."


@mcp.tool()
def send_gmail(username: str, password: str, recipient_names: str, subject: str, body: str,
               enable_report: bool = False, report_delay_minutes: int = 60) -> str:
    """[보안] 비밀번호 검증 후 이메일을 발송하고 리포트를 예약합니다."""
    if not auth.verify_user(username, password):
        return "❌ 인증 실패: 아이디 또는 비밀번호가 틀립니다."

    creds = auth.get_user_creds(username)
    if not creds: return "⛔ 구글 연동이 필요합니다."

    names = [n.strip() for n in recipient_names.split(',')]
    email_list = [tools.get_email_from_name_with_creds(creds, n) for n in names if
                  tools.get_email_from_name_with_creds(creds, n)]

    if not email_list: return "❌ 수신자 주소를 찾을 수 없습니다."

    try:
        tools.send_email_with_creds(creds, email_list, subject, body)
        msg = f"📤 '{username}' 계정으로 메일을 성공적으로 보냈습니다."
        if enable_report:
            msg += f"\n\n{_register_report_job(username, recipient_names, subject, report_delay_minutes)}"
        return msg
    except Exception as e:
        return f"❌ 전송 에러: {str(e)}"


@mcp.tool()
def check_my_replies(username: str, password: str, subject_keyword: str) -> str:
    """[보안] 비밀번호 검증 후 답장 메일을 확인합니다."""
    if not auth.verify_user(username, password):
        return "❌ 인증 실패: 아이디 또는 비밀번호가 틀립니다."

    creds = auth.get_user_creds(username)
    if not creds: return "⛔ 구글 연동이 필요합니다."

    try:
        replies = tools.fetch_replies_with_creds(creds, subject_keyword)
        if not replies: return "📭 도착한 답장이 없습니다."

        res = f"🔍 {username}님, {len(replies)}개의 답장 발견:\n"
        for r in replies:
            res += f"\n👤 {r['sender']}: {r['body'][:50]}...\n---"
        return res
    except Exception as e:
        return f"❌ 확인 에러: {str(e)}"


# ==============================================================================
# 서버 실행
# ==============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Plan Manager MCP 서버 시작 (Port: {port})")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path="/")