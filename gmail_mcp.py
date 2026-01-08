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


# ==============================================================================
# 2. 인증 성공 페이지 설정 (Starlette 호환 방식)
# ==============================================================================
async def auth_callback(request):
    """구글 인증 완료 후 호출되어 자동으로 토큰을 DB에 저장합니다."""
    code = request.query_params.get("code")
    username = request.query_params.get("state")  # state를 통해 유저 식별

    if not code or not username:
        return HTMLResponse(content="<h1>❌ 오류</h1><p>인증 정보가 올바르지 않습니다.</p>", status_code=400)

    try:
        # 메모리에 저장된 해당 유저의 flow 객체 가져오기
        flow = active_flows.get(username)
        if not flow:
            # 만약 서버 재시작 등으로 flow가 사라졌다면 새로 생성 시도
            _, flow = auth.get_auth_url(state=username)
            active_flows[username] = flow

        # 1. 코드를 사용하여 토큰 가져오기
        flow.fetch_token(code=code)

        # 2. DB에 토큰 저장
        token_data = json.loads(flow.credentials.to_json())
        auth.update_user_token(username, token_data)

        # 3. 사용 완료된 flow 삭제
        if username in active_flows:
            del active_flows[username]

        return HTMLResponse(content=f"""
            <html>
                <head><meta charset="UTF-8"><title>인증 완료</title></head>
                <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                    <h1>✅ {username}님, 인증 성공!</h1>
                    <p>이제 코드를 복사할 필요가 없습니다. 창을 닫고 AI에게 돌아가세요.</p>
                </body>
            </html>
        """)
    except Exception as e:
        return HTMLResponse(content=f"<h1>❌ 인증 실패</h1><p>{str(e)}</p>", status_code=500)


# Starlette 앱에 직접 경로 추가 (AttributeError 해결)
app = mcp.http_app()
app.add_route("/callback", auth_callback, methods=["GET"])

# ==============================================================================
# 3. 데이터 디렉토리 및 스케줄러 설정
# ==============================================================================
data_dir = os.environ.get("DATA_DIR", current_dir)
if not os.path.exists(data_dir):
    os.makedirs(data_dir, exist_ok=True)

db_path = os.path.join(data_dir, "jobs.sqlite")
jobstores = {'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')}
scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()

# 유저별 flow 저장소 (세션 격리용)
active_flows = {}


# ==============================================================================
# 4. 헬퍼 함수
# ==============================================================================
def _register_report_job(username: str, group_name: str, subject_query: str, delay_minutes: int) -> str:
    """내부용: 리포트 예약 (보안 검증 후 호출됨)"""
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
# 5. 도구 정의 (보안 및 세션 격리 적용)
# ==============================================================================

@mcp.tool()
def manage_user_auth(username: str, password: str, auth_code: str = None) -> str:
    """
    사용자 가입, 로그인 및 구글 연동을 하나의 흐름으로 관리합니다.
    인증 후 주소창의 전체 URL을 'auth_code'에 그대로 입력해도 처리됩니다.
    """
    # 1. 로그인 시도
    if auth.verify_user(username, password):
        creds = auth.get_user_creds(username)
        if creds:
            return f"✅ '{username}'님, 로그인이 완료되었으며 구글 계정도 이미 연동되어 있습니다."

        # 구글 연동이 필요한 경우 (state에 username 전달)
        url, flow = auth.get_auth_url(state=username)
        active_flows[username] = flow
        return (f"👋 '{username}'님, 로그인 성공! 구글 계정 연동이 필요합니다.\n"
                f"**[여기 클릭해서 인증하기]({url})**\n"
                f"인증을 완료하면 자동으로 연동됩니다.")

        # 2. 신규 가입 시도
    success, msg = auth.register_user(username, password)
    if success:
        url, flow = auth.get_auth_url(state=username)  # state에 username 전달
        active_flows[username] = flow
        return (f"✨ '{username}'님, 회원가입이 완료되었습니다!\n"
                f"**[인증 링크 클릭]({url})**\n"
                f"링크 접속 후 구글 로그인을 마치면 자동으로 계정이 연동됩니다.")
    else:
        return f"❌ 인증 실패: {msg}"

@mcp.tool()
def find_contact_email(username: str, password: str, name: str) -> str:
    """[보안] 비밀번호 확인 후 주소록에서 이메일을 검색합니다."""
    if not auth.verify_user(username, password):
        return "❌ 인증 실패: 아이디 또는 비밀번호가 틀립니다."

    creds = auth.get_user_creds(username)
    if not creds: return f"⛔ '{username}'님은 구글 연동이 필요합니다."

    email = tools.get_email_from_name_with_creds(creds, name)
    return f"✅ '{name}' 이메일: {email}" if email else f"❌ '{name}'님을 찾을 수 없습니다."


@mcp.tool()
def send_gmail(username: str, password: str, recipient_names: str, subject: str, body: str,
               enable_report: bool = False, report_delay_minutes: int = 60) -> str:
    """[보안] 비밀번호 확인 후 이메일을 전송하고 필요시 리포트를 예약합니다."""
    if not auth.verify_user(username, password):
        return "❌ 인증 실패: 아이디 또는 비밀번호가 틀립니다."

    creds = auth.get_user_creds(username)
    if not creds: return f"⛔ '{username}'님은 구글 연동이 필요합니다."

    names = [n.strip() for n in recipient_names.split(',')]
    email_list = []
    for n in names:
        e = tools.get_email_from_name_with_creds(creds, n)
        if e: email_list.append(e)

    if not email_list: return "❌ 발송할 이메일 주소를 찾을 수 없습니다."

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
    """[보안] 비밀번호 확인 후 특정 키워드가 포함된 답장을 확인합니다."""
    if not auth.verify_user(username, password):
        return "❌ 인증 실패: 아이디 또는 비밀번호가 틀립니다."

    creds = auth.get_user_creds(username)
    if not creds: return f"⛔ '{username}'님은 구글 연동이 필요합니다."

    try:
        replies = tools.fetch_replies_with_creds(creds, subject_keyword)
        if not replies: return "📭 도착한 답장이 없습니다."

        res = f"🔍 {username}님, {len(replies)}개의 답장을 발견했습니다:\n"
        for r in replies:
            res += f"\n👤 {r['sender']}: {r['body'][:100]}...\n---"
        return res
    except Exception as e:
        return f"❌ 확인 에러: {str(e)}"


# ==============================================================================
# 6. 서버 실행 (HTTP 모드)
# ==============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Plan Manager MCP 서버가 시작되었습니다. (Port: {port})")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path="/")