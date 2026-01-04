# gmail_mcp.py

from fastmcp import FastMCP
import sys
import os
# FastAPI 관련 복잡한 import 제거
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
    return _register_report_job(group_name, subject_query, delay_minutes)


# ==============================================================================
# [핵심] 서버 실행 (mcp.run 사용)
# ==============================================================================
if __name__ == "__main__":
    print("🚀 MCP 서버를 시작합니다 (Host: 0.0.0.0)...")

    # Railway가 제공하는 PORT 환경변수 사용
    port = int(os.environ.get("PORT", 8000))

    # SSE 모드로 실행 (FastMCP가 자동으로 FastAPI 앱을 생성하고 포트를 엽니다)
    # 별도의 mount나 health check 코드가 없어도 Railway는 포트가 열리면 '성공'으로 간주합니다.
    try:
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    except TypeError:
        # 혹시 구버전 FastMCP를 사용하는 경우를 대비한 예외처리
        print("⚠️ SSE transport 옵션이 지원되지 않는 버전일 수 있습니다. 기본 모드로 시도합니다.")
        mcp.run()