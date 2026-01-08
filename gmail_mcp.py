# gmail_mcp.py
from fastmcp import FastMCP
from starlette.responses import HTMLResponse
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
    print(f"❌ 필수 모듈 찾기 실패: {e}")
    sys.exit(1)

# 1. MCP 서버 초기화
mcp = FastMCP("plan_manager")
app = mcp.http_app()  # App 객체 확보

# 유저별 flow 저장소 (세션 격리용)
active_flows = {}


# ==============================================================================
# 2. 인증 콜백 및 자동 저장 (핵심 로직)
# ==============================================================================
async def auth_callback(request):
    """구글 인증 완료 후 토큰을 교환하고 DB에 자동 저장합니다."""
    code = request.query_params.get("code")
    username = request.query_params.get("state")  # auth.py에서 보낸 유저 ID

    if not code or not username:
        return HTMLResponse(content="<h1>❌ 오류</h1><p>인증 정보가 누락되었습니다.</p>", status_code=400)

    try:
        # 해당 유저의 flow 가져오기
        flow = active_flows.get(username)

        # 서버 재시작 등으로 flow가 없으면 복구 시도
        if not flow:
            print(f"⚠️ '{username}'의 flow 세션 복구 시도")
            _, flow = auth.get_auth_url(state=username)
            active_flows[username] = flow

        # 1. 토큰 교환
        flow.fetch_token(code=code)

        # 2. DB에 자동 저장
        token_data = json.loads(flow.credentials.to_json())
        auth.update_user_token(username, token_data)

        # 3. 메모리 정리
        if username in active_flows:
            del active_flows[username]

        return HTMLResponse(content=f"""
        <html>
            <head><meta charset="UTF-8"><title>인증 완료</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px; background-color: #f5f5f7;">
                <div style="background: white; padding: 40px; border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); display: inline-block;">
                    <h1 style="color: #34c759;">✅ 인증 성공!</h1>
                    <p style="color: #1d1d1f; font-size: 18px;"><b>{username}</b>님의 계정이 연동되었습니다.</p>
                    <p style="color: #86868b;">이제 창을 닫고 AI에게 돌아가 작업을 계속하세요.</p>
                </div>
            </body>
        </html>
        """)
    except Exception as e:
        return HTMLResponse(content=f"<h1>❌ 인증 실패</h1><p>{str(e)}</p>", status_code=500)


# ✅ 앱에 라우트 추가 (server.py에서 실행될 때 적용됨)
app.add_route("/callback", auth_callback, methods=["GET"])

# ==============================================================================
# 3. 스케줄러 설정
# ==============================================================================
data_dir = os.environ.get("DATA_DIR", current_dir)
if not os.path.exists(data_dir):
    os.makedirs(data_dir, exist_ok=True)

db_path = os.path.join(data_dir, "jobs.sqlite")
jobstores = {'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')}
scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()


def _register_report_job(username, group_name, subject_query, delay_minutes):
    try:
        creds = auth.get_user_creds(username)
        run_time = datetime.now() + timedelta(minutes=delay_minutes)
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=creds)
        profile = service.users().getProfile(userId='me').execute()
        my_email = profile['emailAddress']
        scheduler.add_job(scheduler_job.report_status, 'date', run_date=run_time,
                          args=[username, group_name, subject_query, my_email])
        return f"⏰ {delay_minutes}분 뒤 보고서가 예약되었습니다."
    except Exception as e:
        return f"⛔ 예약 오류: {str(e)}"


# ==============================================================================
# 4. 도구 정의
# ==============================================================================
@mcp.tool()
def manage_user_auth(username: str, password: str) -> str:
    """로그인 또는 회원가입을 수행합니다. 인증이 필요하면 링크를 제공합니다."""
    # 1. 로그인
    if auth.verify_user(username, password):
        creds = auth.get_user_creds(username)
        if creds:
            return f"✅ '{username}'님, 로그인 및 구글 연동이 완료되어 있습니다."

        # 연동 필요 (state에 username 전달)
        url, flow = auth.get_auth_url(state=username)
        active_flows[username] = flow
        return (f"👋 '{username}'님, 로그인 성공! 구글 연동이 필요합니다.\n"
                f"👉 **[여기 클릭해서 인증하기]({url})**\n"
                f"링크에서 인증을 완료하면 자동으로 연동됩니다.")

    # 2. 회원가입
    success, msg = auth.register_user(username, password)
    if success:
        # 가입 직후 인증 링크 제공 (state에 username 전달)
        url, flow = auth.get_auth_url(state=username)
        active_flows[username] = flow
        return (f"✨ '{username}'님, 회원가입 완료!\n"
                f"👉 **[여기 클릭해서 인증하기]({url})**\n"
                f"링크에서 인증을 완료하면 자동으로 연동됩니다.")
    else:
        return f"❌ 오류: {msg}"


@mcp.tool()
def find_contact_email(username: str, password: str, name: str) -> str:
    if not auth.verify_user(username, password): return "❌ 로그인 실패"
    creds = auth.get_user_creds(username)
    if not creds: return "⛔ 구글 연동 필요"
    email = tools.get_email_from_name_with_creds(creds, name)
    return f"✅ '{name}' 이메일: {email}" if email else "❌ 찾을 수 없음"


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

    if not email_list: return "❌ 이메일 주소 없음"

    try:
        tools.send_email_with_creds(creds, email_list, subject, body)
        msg = f"📤 전송 성공 ({len(email_list)}명)"
        if enable_report:
            msg += f"\n{_register_report_job(username, recipient_names, subject, report_delay_minutes)}"
        return msg
    except Exception as e:
        return f"❌ 전송 에러: {str(e)}"