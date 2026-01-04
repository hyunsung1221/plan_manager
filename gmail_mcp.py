# gmail_mcp.py

from fastmcp import FastMCP
import sys
import os
from starlette.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime, timedelta

# [중요] 모듈 import (같은 폴더에 tools.py, scheduler_job.py가 있어야 함)
# Docker에서 실행 시 경로 문제를 방지하기 위해 절대 경로 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    import tools
    import scheduler_job
except ImportError as e:
    print(f"❌ 필수 모듈을 찾을 수 없습니다: {e}")
    print("tools.py와 scheduler_job.py가 같은 폴더에 있는지 확인해주세요.")
    sys.exit(1)

# 1. MCP 서버 초기화
mcp = FastMCP("plan_manager")

# ==============================================================================
# [필수] 웹 플랫폼 접속을 위한 CORS 설정
# ==============================================================================
# FastMCP 내부의 FastAPI/Starlette 앱에 접근하여 미들웨어 추가
if hasattr(mcp, "_http_server"):
    mcp._http_server.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 보안상 운영 배포시에는 구체적인 도메인을 적는 것이 좋음
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ==============================================================================
# 환경 변수 및 스케줄러 설정
# ==============================================================================
# Google Token 처리 (서버 환경 변수에서 파일 생성)
env_token = os.environ.get("GOOGLE_TOKEN_JSON")
if env_token:
    token_path = os.path.join(current_dir, "token.json")
    try:
        with open(token_path, "w") as f:
            f.write(env_token)
        print("✅ 환경변수에서 token.json 파일을 생성했습니다.")
    except IOError as e:
        print(f"⚠️ token.json 쓰기 권한 오류 (읽기 전용 파일시스템일 수 있음): {e}")

# 데이터 저장소 경로 설정 (Docker 볼륨 마운트 고려)
data_dir = os.environ.get("DATA_DIR", current_dir)
if not os.path.exists(data_dir):
    try:
        os.makedirs(data_dir, exist_ok=True)
    except Exception:
        pass  # 권한 없으면 현재 폴더 사용

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

        # 내 이메일 주소 가져오기
        gmail_service, _ = tools.get_services()
        profile = gmail_service.users().getProfile(userId='me').execute()
        my_email = profile['emailAddress']

        scheduler.add_job(
            scheduler_job.report_status,
            'date',
            run_date=run_time,
            args=[group_name, subject_query, my_email]
        )
        return f"⏰ 예약 완료! {delay_minutes}분 뒤({run_time.strftime('%H:%M:%S')})에 확인하겠습니다."
    except Exception as e:
        return f"⛔ 예약 중 오류 발생: {str(e)}"


# ==============================================================================
# 도구(Tool) 정의
# ==============================================================================

@mcp.tool()
def find_contact_email(name: str) -> str:
    """이름으로 이메일 주소를 검색합니다."""
    email = tools.get_email_from_name(name)
    if email:
        return f"✅ '{name}'님의 이메일: {email}"
    else:
        return f"❌ 주소록에서 '{name}'님을 찾을 수 없습니다."


@mcp.tool()
def send_gmail(recipient_names: str, subject: str, body: str,
               enable_report: bool = False, report_delay_minutes: int = 60) -> str:
    """이메일을 전송하고 필요 시 답장 확인을 예약합니다."""
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
        return f"❌ 발송 실패: 이름을 찾을 수 없습니다 ({', '.join(failed_names)})."

    # 메일 발송 시도
    try:
        tools.send_email(email_list, subject, body)
    except Exception as e:
        return f"❌ 메일 전송 중 에러 발생: {str(e)}"

    msg = f"📤 {len(email_list)}명에게 메일을 보냈습니다."
    if failed_names:
        msg += f"\n(⚠️ 실패: {', '.join(failed_names)})"

    if enable_report:
        group_name = f"{recipient_names} 답장체크"
        schedule_msg = _register_report_job(group_name, subject, report_delay_minutes)
        msg += f"\n\n{schedule_msg}"

    return msg


@mcp.tool()
def check_my_replies(subject_keyword: str) -> str:
    """특정 제목의 답장 메일을 확인합니다."""
    try:
        replies = tools.fetch_replies(subject_keyword)
    except Exception as e:
        return f"❌ 메일 확인 중 에러 발생: {str(e)}"

    if not replies:
        return "📭 아직 도착한 답장이 없습니다."

    result_text = f"🔍 총 {len(replies)}개의 답장을 발견했습니다:\n"
    for r in replies:
        summary = r['body'][:200] + "..." if len(r['body']) > 200 else r['body']
        result_text += f"\n👤 {r['sender']}: {summary}\n---"

    return result_text


@mcp.tool()
def schedule_status_report(group_name: str, subject_query: str, delay_minutes: int = 60) -> str:
    """답장 확인 보고서만 단독으로 예약합니다."""
    return _register_report_job(group_name, subject_query, delay_minutes)


# ==============================================================================
# [핵심 수정] 서버 실행 진입점
# ==============================================================================
if __name__ == "__main__":
    # Docker/Cloud 환경에서는 host="0.0.0.0" 필수
    # MCP 클라이언트(Cursor, Claude 등)와 통신하려면 transport="sse" 필수
    print("🚀 MCP 서버를 시작합니다 (Host: 0.0.0.0, Port: 8000)...")
    mcp.run(transport="sse", host="0.0.0.0", port=8000)