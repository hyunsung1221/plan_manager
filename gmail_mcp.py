# gmail_mcp.py

from fastmcp import FastMCP
import sys
import os
# [추가] FastAPI와 Uvicorn 임포트
from fastapi import FastAPI
import uvicorn
from starlette.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime, timedelta

# [중요] 모듈 import (같은 폴더에 tools.py, scheduler_job.py가 있어야 함)
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
# [수정] FastAPI 앱 생성 및 설정 (CORS & 헬스체크)
# ==============================================================================
app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# [추가] 헬스체크 엔드포인트
@app.get("/health")
def health_check():
    """로드밸런서 또는 배포 플랫폼을 위한 상태 확인용"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# [추가] 루트 경로 헬스체크 (Railway 등 일부 플랫폼은 / 를 체크함)
@app.get("/")
def root_check():
    return {"status": "running", "service": "Gmail MCP Server"}


# ==============================================================================
# 환경 변수 및 스케줄러 설정 (기존과 동일)
# ==============================================================================
env_token = os.environ.get("GOOGLE_TOKEN_JSON")
if env_token:
    token_path = os.path.join(current_dir, "token.json")
    try:
        with open(token_path, "w") as f:
            f.write(env_token)
        print("✅ 환경변수에서 token.json 파일을 생성했습니다.")
    except IOError as e:
        print(f"⚠️ token.json 쓰기 권한 오류: {e}")

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
# 헬퍼 함수 (기존과 동일)
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
        return f"⏰ 예약 완료! {delay_minutes}분 뒤({run_time.strftime('%H:%M:%S')})에 확인하겠습니다."
    except Exception as e:
        return f"⛔ 예약 중 오류 발생: {str(e)}"


# ==============================================================================
# 도구(Tool) 정의 (기존과 동일)
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
    return _register_report_job(group_name, subject_query, delay_minutes)


# ==============================================================================
# [핵심 수정] 서버 실행 및 마운트 로직
# ==============================================================================

# 1. MCP 서버를 FastAPI 앱에 마운트 (FastMCP가 자동으로 /sse 경로를 잡습니다)
mcp.mount(app)

if __name__ == "__main__":
    # 2. Uvicorn을 사용하여 FastAPI 앱 실행
    print("🚀 MCP 서버(with Health Check)를 시작합니다 (Host: 0.0.0.0, Port: 8000)...")

    # Railway 등 클라우드 배포 시 PORT 환경변수 처리
    port = int(os.environ.get("PORT", 8000))

    uvicorn.run(app, host="0.0.0.0", port=port)