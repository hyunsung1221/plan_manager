# gmail_mcp.py

from fastmcp import FastMCP
import sys
import os

# [핵심] 현재 파일의 위치를 절대 경로로 구함
current_dir = os.path.dirname(os.path.abspath(__file__))

# 시스템 경로에 추가 (tools, scheduler_job 모듈 import용)
sys.path.append(current_dir)
from fastmcp import FastMCP
import sys
import os

# [수정] MCP 서버 생성 시 dependencies 옵션 사용 가능 여부 확인
# FastMCP 최신 버전에서는 생성자에 바로 설정을 넣기 어렵습니다.
# 가장 확실한 방법은 FastMCP 객체를 생성한 후 설정을 바꾸는 것입니다.

mcp = FastMCP("plan_manager")

from fastmcp import FastMCP
import sys
import os

# [수정] MCP 서버 생성 시 dependencies 옵션 사용 가능 여부 확인
# FastMCP 최신 버전에서는 생성자에 바로 설정을 넣기 어렵습니다.
# 가장 확실한 방법은 FastMCP 객체를 생성한 후 설정을 바꾸는 것입니다.

mcp = FastMCP("plan_manager")

# ==============================================================================
# [필수] 웹 플랫폼 접속을 위한 CORS 설정 추가
# ==============================================================================
from starlette.middleware.cors import CORSMiddleware

# mcp 서버 내부의 진짜 웹 앱(FastAPI/Starlette)을 꺼내서 보안 설정을 덮어씁니다.
# (FastMCP 버전에 따라 _http_server 또는 fastmcp_app 등의 변수명이 다를 수 있으나,
#  보통 아래 방식이 통합니다. 만약 에러가 나면 알려주세요!)

if hasattr(mcp, "_http_server"):
    mcp._http_server.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 모든 웹사이트에서 접속 허용
        allow_credentials=True,
        allow_methods=["*"],  # 모든 전송 방식(GET, POST 등) 허용
        allow_headers=["*"],
    )
# ==============================================================================

# ... (나머지 코드는 그대로 두세요) ...
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime, timedelta
import tools
import scheduler_job

# 1. MCP 서버 초기화
mcp = FastMCP("plan_manager")

# ==============================================================================
# 스케줄러 설정
# ==============================================================================
db_path = os.path.join(current_dir, "jobs.sqlite")


env_token = os.environ.get("GOOGLE_TOKEN_JSON")
if env_token:
    token_path = os.path.join(current_dir, "token.json")
    with open(token_path, "w") as f:
        f.write(env_token)
    print("✅ 환경변수에서 token.json 파일을 생성했습니다.")


data_dir = os.environ.get("DATA_DIR", current_dir)
if not os.path.exists(data_dir):
    os.makedirs(data_dir, exist_ok=True)

db_path = os.path.join(data_dir, "jobs.sqlite")

jobstores = {
    'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')
}

scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()


# ==============================================================================
# [헬퍼 함수] 스케줄 등록 로직 (재사용을 위해 분리)
# ==============================================================================
def _register_report_job(group_name: str, subject_query: str, delay_minutes: int) -> str:
    """
    내부적으로 스케줄러에 작업을 등록하는 헬퍼 함수입니다.
    """
    try:
        # 실행 시간 계산
        run_time = datetime.now() + timedelta(minutes=delay_minutes)

        # 내 이메일 주소 가져오기
        gmail_service, _ = tools.get_services()
        profile = gmail_service.users().getProfile(userId='me').execute()
        my_email = profile['emailAddress']

        # 스케줄러에 작업 등록
        scheduler.add_job(
            scheduler_job.report_status,
            'date',
            run_date=run_time,
            args=[group_name, subject_query, my_email]
        )
        return f"⏰ 예약 완료! {delay_minutes}분 뒤({run_time.strftime('%H:%M:%S')})에 '{group_name}' 관련 답장을 확인하여 보고서를 보내겠습니다."
    except Exception as e:
        return f"⛔ 예약 중 오류 발생: {str(e)}"


# ==============================================================================
# 도구(Tool) 정의
# ==============================================================================

@mcp.tool()
def find_contact_email(name: str) -> str:
    """
        [필수 1단계] 사용자가 특정 인물에게 연락하거나 이메일을 보내려고 할 때, 가장 먼저 이 도구를 사용하여 이메일 주소를 찾아야 합니다.
        약속을 잡거나 그룹 메일을 보낼 때도 이 도구로 각 인물의 이메일을 먼저 확보하세요.

        Args:
            name: 검색할 이름 (예: "홍길동")
        """
    email = tools.get_email_from_name(name)
    if email:
        return f"✅ '{name}'님의 이메일: {email}"
    else:
        return f"❌ 주소록에서 '{name}'님을 찾을 수 없습니다."


@mcp.tool()
def send_gmail(recipient_names: str, subject: str, body: str,
               enable_report: bool = False, report_delay_minutes: int = 60) -> str:
    """
        [필수 2단계] 이메일을 보냅니다. 단순한 메시지 전달뿐만 아니라 '일정 조율', '약속 잡기', '모임 제안' 시에도 이 도구를 사용합니다.

        [사용 가이드]
        1. 사용자가 "언제가 괜찮은지 물어봐줘" 또는 "약속 잡아줘"라고 하면, 이 도구를 사용해 구체적인 날짜나 기간을 제안하는 메일을 보내세요.
        2. 여러 명을 만나는 경우 'recipient_names'에 쉼표로 구분하여 입력하세요 (예: "철수, 영희").
        3. 답장 확인이 필요한 약속 제안의 경우 'enable_report=True'로 설정하세요.

        Args:
            recipient_names: 받는 사람 이름 목록 (쉼표로 구분, 사전에 find_contact_email로 존재 여부 확인 권장)
            subject: 메일 제목
            body: 메일 본문 (날짜 제안, 장소, 안부 인사 등을 포함하여 정중하게 작성)
            enable_report: 메일 발송 후 답장 확인 보고서를 예약할지 여부 (일정 조율 시 True 권장)
            report_delay_minutes: 보고서를 예약할 경우 몇 분 뒤에 확인할지
        """
    names = [n.strip() for n in recipient_names.split(',')]
    email_list = []
    failed_names = []

    # 이름 -> 이메일 변환
    for name in names:
        email = tools.get_email_from_name(name)
        if email:
            email_list.append(email)
        else:
            failed_names.append(name)

    if not email_list:
        return f"❌ 발송 실패: 입력한 이름({', '.join(failed_names)})의 이메일을 찾을 수 없습니다."

    # 메일 발송
    tools.send_email(email_list, subject, body)

    # 기본 결과 메시지 작성
    msg = f"📤 {len(email_list)}명({', '.join(email_list)})에게 메일을 보냈습니다."
    if failed_names:
        msg += f"\n(⚠️ 찾지 못한 사람: {', '.join(failed_names)})"

    # [핵심 수정] 보고서 예약 기능 통합
    if enable_report:
        # 그룹 이름은 수신자 목록으로, 검색어는 메일 제목으로 설정하여 예약
        group_name = f"{recipient_names} 답장체크"
        schedule_msg = _register_report_job(group_name, subject, report_delay_minutes)
        msg += f"\n\n{schedule_msg}"

    return msg


@mcp.tool()
def check_my_replies(subject_keyword: str) -> str:
    """
    특정 제목으로 온 답장이 있는지 메일함을 확인합니다.
    Args:
        subject_keyword: 검색할 메일 제목 키워드 (예: "[약속 조사 그룹:조현성,송민기]")
    """
    replies = tools.fetch_replies(subject_keyword)

    if not replies:
        return "📭 아직 도착한 답장이 없습니다."

    result_text = f"🔍 총 {len(replies)}개의 답장을 발견했습니다:\n"
    for r in replies:
        summary = r['body'][:200] + "..." if len(r['body']) > 200 else r['body']
        result_text += f"\n👤 보낸사람: {r['sender']}\n📝 내용: {summary}\n---"

    return result_text


@mcp.tool()
def schedule_status_report(group_name: str, subject_query: str, delay_minutes: int = 60) -> str:
    """
    [단독 예약 기능] 메일 발송 없이, 답장 확인 보고서만 예약합니다.
    Args:
        group_name: 그룹 이름 (보고서 제목용)
        subject_query: 답장을 감지할 메일 제목
        delay_minutes: 몇 분 뒤에 확인할지
    """
    # 헬퍼 함수를 사용하여 로직 중복 제거
    return _register_report_job(group_name, subject_query, delay_minutes)


if __name__ == "__main__":
    mcp.run()