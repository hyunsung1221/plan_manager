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
    """구글 인증 완료 후 보여줄 사용자 친화적 페이지 (복사 버튼 포함)"""
    code = request.query_params.get("code", "코드를 찾을 수 없습니다.")
    html_content = f"""
    <html>
        <head>
            <meta charset="UTF-8">
            <title>인증 완료 - Plan Manager</title>
            <style>
                body {{ font-family: -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background-color: #f5f5f7; }}
                .card {{ background: white; padding: 40px; border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); text-align: center; max-width: 400px; width: 90%; }}
                h1 {{ color: #1d1d1f; font-size: 24px; margin-bottom: 10px; }}
                p {{ color: #86868b; margin-bottom: 25px; line-height: 1.5; }}
                .code-box {{ background: #f2f2f7; padding: 15px; border-radius: 10px; font-family: monospace; font-size: 14px; word-break: break-all; margin-bottom: 20px; border: 1px solid #d2d2d7; }}
                .copy-btn {{ background: #0071e3; color: white; border: none; padding: 12px 25px; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; transition: background 0.2s; width: 100%; }}
                .copy-btn:hover {{ background: #0077ed; }}
                .copy-btn:active {{ transform: scale(0.98); }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>✅ 인증 완료</h1>
                <p>아래 인증 코드를 복사하여<br>AI 채팅창에 붙여넣어 주세요.</p>
                <div class="code-box" id="authCode">{code}</div>
                <button class="copy-btn" onclick="copyToClipboard()">버튼 눌러서 코드 복사하기</button>
            </div>
            <script>
                function copyToClipboard() {{
                    const codeText = document.getElementById('authCode').innerText;
                    navigator.clipboard.writeText(codeText).then(() => {{
                        const btn = document.querySelector('.copy-btn');
                        btn.innerText = '✅ 복사되었습니다!';
                        btn.style.background = '#34c759';
                        setTimeout(() => {{
                            btn.innerText = '버튼 눌러서 코드 복사하기';
                            btn.style.background = '#0071e3';
                        }}, 2000);
                    }});
                }}
            </script>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)


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

        # 연동 완료 상태
        if creds:
            return f"✅ '{username}'님, 로그인이 완료되었으며 구글 계정도 이미 연동되어 있습니다."

        # 구글 연동 진행 중
        if auth_code:
            actual_code = auth.extract_code_from_url(auth_code)  # URL 자동 파싱
            flow = active_flows.get(username)
            if not flow:
                url, flow = auth.get_auth_url()
                active_flows[username] = flow
                return f"⚠️ 인증 세션이 만료되었습니다. 다시 시도해 주세요: {url}"
            try:
                flow.fetch_token(code=actual_code)
                auth.update_user_token(username, json.loads(flow.credentials.to_json()))
                if username in active_flows: del active_flows[username]
                return f"✅ '{username}'님, 구글 연동이 성공적으로 완료되었습니다!"
            except Exception as e:
                return f"❌ 코드 인증 실패: {str(e)}"
        else:
            url, flow = auth.get_auth_url()
            active_flows[username] = flow
            return (f"👋 '{username}'님, 로그인 성공! 구글 계정 연동이 필요합니다.\n"
                    f"1. [여기 클릭해서 인증하기]({url})\n"
                    f"2. 완료 후 나타나는 페이지에서 코드를 복사해 'auth_code' 인자로 전달하세요.")

    # 2. 신규 가입 시도
    success, msg = auth.register_user(username, password)
    if success:
        url, flow = auth.get_auth_url()
        active_flows[username] = flow
        return (f"✨ '{username}'님, 회원가입이 완료되었습니다!\n"
                f"1. [인증 링크 클릭]({url})\n"
                f"2. 완료 후 발급받은 코드를 'auth_code'로 전달해 주세요.")
    else:
        # 아이디가 이미 존재하는데 로그인이 실패한 경우
        return f"❌ 인증 실패: {msg} (비밀번호를 다시 확인해 주세요.)"


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