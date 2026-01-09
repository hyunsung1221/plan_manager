# gmail_mcp.py
import os
import json
import sys
from fastmcp import FastMCP, Context
from fastmcp.server.auth.providers.google import GoogleProvider
from google.oauth2.credentials import Credentials

# 모듈 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    import tools
except ImportError as e:
    print(f"❌ 필수 모듈 찾기 실패: {e}")
    sys.exit(1)

# 1. Google Credentials 로드 (Railway Env: NEW_GOOGLE_CREDENTIALS_JSON)
env_creds = os.environ.get("NEW_GOOGLE_CREDENTIALS_JSON")
if not env_creds:
    raise ValueError("❌ 환경변수 'NEW_GOOGLE_CREDENTIALS_JSON'이 설정되지 않았습니다.")

try:
    creds_data = json.loads(env_creds)
    # web 또는 installed 키 아래에 정보가 있을 수 있음
    client_config = creds_data.get("web") or creds_data.get("installed")

    CLIENT_ID = client_config["client_id"]
    CLIENT_SECRET = client_config["client_secret"]
except (json.JSONDecodeError, KeyError, TypeError) as e:
    raise ValueError(f"❌ 구글 인증 정보 파싱 실패: {e}")

# 2. Google Provider 설정
# 필요한 권한(Scope) 설정
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/contacts.readonly"
]

# 배포 환경에 따라 Base URL 설정 (기본값: 로컬)
BASE_URL = "https://planmanager-production.up.railway.app" if os.environ.get(
    "RAILWAY_ENVIRONMENT") else "http://localhost:8000"

auth_provider = GoogleProvider(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    base_url=BASE_URL,
    required_scopes=SCOPES,
    redirect_path="/auth/callback"  # Google Cloud Console 설정과 일치해야 함
)

# 3. MCP 서버 초기화 (Auth Provider 적용)
mcp = FastMCP("plan_manager", auth=auth_provider)
app = mcp.http_app()


# ==============================================================================
# 도구 정의 (인증은 FastMCP가 처리하므로 username/password 인자 제거)
# ==============================================================================

def get_creds_from_context(ctx: Context) -> Credentials:
    """FastMCP Context에서 Access Token을 추출하여 Credentials 객체 생성"""
    # FastMCP GoogleProvider를 통하면 token에 실제 Google Access Token이 포함됨
    token = ctx.request.auth.token  # 또는 적절한 토큰 추출 방식
    if not token:
        raise ValueError("인증 토큰을 찾을 수 없습니다.")

    # google.oauth2.credentials.Credentials 생성 (Access Token만 사용)
    return Credentials(token=token)


@mcp.tool
def find_contact_email(name: str, ctx: Context) -> str:
    """주소록에서 이메일을 검색합니다."""
    try:
        creds = get_creds_from_context(ctx)
        email = tools.get_email_from_name_with_creds(creds, name)
        return f"✅ '{name}' 이메일: {email}" if email else "❌ 찾을 수 없음"
    except Exception as e:
        return f"❌ 오류 발생: {str(e)}"


@mcp.tool
def send_gmail(recipient_names: str, subject: str, body: str, ctx: Context) -> str:
    """이메일을 전송합니다."""
    try:
        creds = get_creds_from_context(ctx)

        names = [n.strip() for n in recipient_names.split(',')]
        email_list = []
        for n in names:
            e = tools.get_email_from_name_with_creds(creds, n)
            if e: email_list.append(e)

        if not email_list:
            return "❌ 유효한 이메일 주소를 찾지 못했습니다."

        tools.send_email_with_creds(creds, email_list, subject, body)
        return f"📤 전송 성공 ({len(email_list)}명)"
    except Exception as e:
        return f"❌ 전송 에러: {str(e)}"

# 참고: 스케줄러(백그라운드 작업)는 클라이언트의 실시간 토큰이 없으므로
# 이 구조에서는 작동하지 않을 수 있습니다.
# 백그라운드 작업이 필수라면 Refresh Token을 별도 DB에 저장하는 로직을 추가해야 합니다.