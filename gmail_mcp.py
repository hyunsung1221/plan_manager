# gmail_mcp.py
import sys
import os
import json
import uvicorn  # 서버 실행을 위해 직접 사용
from fastmcp import FastMCP
from starlette.responses import HTMLResponse
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime, timedelta

# 모듈 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# 필수 모듈 임포트 (실패 시 로그 출력 후 종료)
try:
    import tools
    import scheduler_job
    import auth
except ImportError as e:
    print(f"❌ [Startup Error] 필수 모듈 임포트 실패: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ [Startup Error] 초기화 중 오류 발생: {e}")
    sys.exit(1)

# 1. MCP 서버 및 앱 초기화
mcp = FastMCP("plan_manager")
app = mcp.http_app()  # Starlette/FastAPI 앱 객체 가져오기

# 유저별 flow 저장소 (세션 격리용)
active_flows = {}


# ==============================================================================
# 2. 인증 콜백 함수 (자동 토큰 저장 로직 포함)
# ==============================================================================
async def auth_callback(request):
    """구글 인증 후 리디렉션된 요청을 처리하고 토큰을 DB에 저장합니다."""
    code = request.query_params.get("code")
    username = request.query_params.get("state")  # auth.py에서 전달한 state(username)

    if not code or not username:
        return HTMLResponse(content="<h1>❌ 오류</h1><p>잘못된 접근입니다. (code 또는 state 누락)</p>", status_code=400)

    try:
        # 해당 유저의 인증 세션(flow) 찾기
        flow = active_flows.get(username)

        # 서버 재시작 등으로 세션이 날아간 경우 복구 시도
        if not flow:
            print(f"⚠️ '{username}'의 flow 세션이 없습니다. 새로 생성합니다.")
            _, flow = auth.get_auth_url(state=username)
            active_flows[username] = flow

        # 1. 토큰 교환
        flow.fetch_token(code=code)

        # 2. DB에 토큰 저장
        token_data = json.loads(flow.credentials.to_json())
        auth.update_user_token(username, token_data)

        # 3. 세션 정리
        if username in active_flows:
            del active_flows[username]

        return HTMLResponse(content=f"""
            <html>
                <head><meta charset="UTF-8"><title>인증 완료</title></head>
                <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                    <h1>✅ {username}님, 인증 성공!</h1>
                    <p>계정 연동이 완료되었습니다. 창을 닫고 AI에게 돌아가세요.</p>
                </body>
            </html>
        """)
    except Exception as e:
        print(f"❌ 인증 처리 중 에러: {e}")
        return HTMLResponse(content=f"<h1>❌ 인증 실패</h1><p>서버 내부 오류: {str(e)}</p>", status_code=500)


# ✅ 앱에 라우트 수동 추가 (가장 중요)
app.add_route("/callback", auth_callback, methods=["GET"])

# ==============================================================================
# 3. 데이터 디렉토리 및 스케줄러 설정
# ==============================================================================
data_dir = os.environ.get("DATA_DIR", current_dir)
if not os.path.exists(data_dir):
    os.makedirs(data_dir, exist_ok=True)

# DB 파일 경로 확인
db_path = os.path.join(data_dir, "jobs.sqlite")
jobstores = {'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')}

# 스케줄러 시작
scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()


# 헬퍼 함수: 리포트 예약
def _register_report_job(username: str, group_name: str, subject_query: str, delay_minutes: int) -> str:
    try:
        creds = auth.get_user_creds(username)
        if not creds: return "❌ 인증 정보 없음"

        run_time = datetime.now() + timedelta(minutes=delay_minutes)
        # 이메일 주소 가져오기 (API 호출)
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=creds)
        profile = service.users().getProfile(userId='me').execute()
        my_email = profile['emailAddress']

        scheduler.add_job(
            scheduler_job.report_status,
            'date',
            run_date=run_time,
            args=[username, group_name, subject_query, my_email]
        )
        return f"⏰ 예약 완료! {delay_minutes}분 뒤 보고서가 발송됩니다."
    except Exception as e:
        return f"⛔ 예약 오류: {str(e)}"


# ==============================================================================
# 4. 도구 정의
# ==============================================================================
@mcp.tool()
def manage_user_auth(username: str, password: str) -> str:
    """로그인 또는 회원가입을 수행하고, 필요 시 구글 인증 링크를 제공합니다."""
    # 1. 로그인 시도
    if auth.verify_user(username, password):
        creds = auth.get_user_creds(username)
        if creds:
            return f"✅ '{username}'님, 이미 로그인 및 구글 연동이 완료되어 있습니다."

        # 연동 필요 -> state에 username 담기
        url, flow = auth.get_auth_url(state=username)
        active_flows[username] = flow
        return (f"👋 '{username}'님, 로그인 성공! 구글 연동이 필요합니다.\n"
                f"**[여기 클릭해서 인증하기]({url})**\n"
                f"인증을 완료하면 자동으로 연동됩니다.")

    # 2. 신규 가입 시도
    success, msg = auth.register_user(username, password)
    if success:
        url, flow = auth.get_auth_url(state=username)
        active_flows[username] = flow
        return (f"✨ '{username}'님, 회원가입 완료!\n"
                f"**[인증 링크 클릭]({url})**\n"
                f"링크 접속 후 자동으로 계정이 연동됩니다.")
    else:
        return f"❌ 인증 실패: {msg}"


@mcp.tool()
def find_contact_email(username: str, password: str, name: str) -> str:
    if not auth.verify_user(username, password): return "❌ 로그인 실패"
    creds = auth.get_user_creds(username)
    if not creds: return "⛔ 구글 연동 필요"

    email = tools.get_email_from_name_with_creds(creds, name)
    return f"✅ '{name}' 이메일: {email}" if email else f"❌ '{name}'님을 찾을 수 없습니다."


@mcp.tool()
def send_gmail(username: str, password: str, recipient_names: str, subject: str, body: str,
               enable_report: bool = False, report_delay_minutes: int = 60) -> str:
    if not auth.verify_user(username, password): return "❌ 로그인 실패"
    creds = auth.get_user_creds(username)
    if not creds: return "⛔ 구글 연동 필요"

    names = [n.strip() for n in recipient_names.split(',')]
    email_list = []
    for n in names:
        e = tools.get_email_from_name_with_creds(creds, n)
        if e: email_list.append(e)

    if not email_list: return "❌ 이메일 주소를 찾을 수 없습니다."

    try:
        tools.send_email_with_creds(creds, email_list, subject, body)
        msg = f"📤 전송 성공 ({len(email_list)}명)"
        if enable_report:
            msg += f"\n{_register_report_job(username, recipient_names, subject, report_delay_minutes)}"
        return msg
    except Exception as e:
        return f"❌ 전송 에러: {str(e)}"


# ==============================================================================
# 5. 서버 실행 (Uvicorn 직접 실행)
# ==============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Plan Manager MCP 서버 시작 (Port: {port})")

    # ⚠️ 중요: mcp.run() 대신 uvicorn을 사용하여 우리가 수정한 app을 확실히 실행합니다.
    uvicorn.run(app, host="0.0.0.0", port=port)