# gmail_mcp.py

from fastmcp import FastMCP
import sys
import os

# [핵심] 현재 파일의 위치를 절대 경로로 구함
current_dir = os.path.dirname(os.path.abspath(__file__))

# 시스템 경로에 추가 (tools, scheduler_job 모듈 import용)
sys.path.append(current_dir)

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime, timedelta
import tools
import scheduler_job

# 1. MCP 서버 초기화
mcp = FastMCP("Gmail AI Assistant")

# ==============================================================================
# [수정된 부분] 스케줄러 설정 (절대 경로 적용)
# ==============================================================================
# "jobs.sqlite" 파일이 코드와 같은 폴더에 무조건 생성되도록 절대 경로를 결합합니다.
db_path = os.path.join(current_dir, "jobs.sqlite")

jobstores = {
    # sqlite:/// 뒤에 절대 경로 변수(db_path)를 넣어줍니다.
    'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')
}

scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()


# ==============================================================================
# 도구(Tool) 정의
# ==============================================================================

@mcp.tool()
def find_contact_email(name: str) -> str:
    """
    이름으로 구글 주소록에서 이메일을 찾습니다.
    Args:
        name: 검색할 이름 (예: "김철수")
    """
    email = tools.get_email_from_name(name)
    if email:
        return f"✅ '{name}'님의 이메일: {email}"
    else:
        return f"❌ 주소록에서 '{name}'님을 찾을 수 없습니다."


@mcp.tool()
def send_gmail(recipient_names: str, subject: str, body: str) -> str:
    """
    여러 사람에게 Gmail을 보냅니다. 이름을 주면 주소록에서 찾아 보냅니다.
    Args:
        recipient_names: 받는 사람 이름 목록 (쉼표로 구분, 예: "김철수, 박영희")
        subject: 메일 제목
        body: 메일 본문
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
    result = tools.send_email(email_list, subject, body)

    msg = f"📤 {len(email_list)}명({', '.join(email_list)})에게 메일을 보냈습니다."
    if failed_names:
        msg += f"\n(⚠️ 찾지 못한 사람: {', '.join(failed_names)})"

    return msg


@mcp.tool()
def check_my_replies(subject_keyword: str) -> str:
    """
    특정 제목으로 온 답장이 있는지 메일함을 확인합니다.
    Args:
        subject_keyword: 검색할 메일 제목 키워드 (예: "[A그룹]")
    """
    replies = tools.fetch_replies(subject_keyword)

    if not replies:
        return "📭 아직 도착한 답장이 없습니다."

    result_text = f"🔍 총 {len(replies)}개의 답장을 발견했습니다:\n"
    for r in replies:
        # 본문 요약 (너무 길면 자름)
        summary = r['body'][:200] + "..." if len(r['body']) > 200 else r['body']
        result_text += f"\n👤 보낸사람: {r['sender']}\n📝 내용: {summary}\n---"

    return result_text


@mcp.tool()
def schedule_status_report(group_name: str, subject_query: str, delay_minutes: int = 60) -> str:
    """
    [예약 기능] 일정 시간 뒤에 메일 답장을 확인해서 나에게 보고서를 보내도록 예약합니다.
    Args:
        group_name: 그룹 이름 (보고서 제목용, 예: "동창회 모임")
        subject_query: 답장을 감지할 메일 제목 (예: "동창회 날짜")
        delay_minutes: 몇 분 뒤에 확인할지 (기본값: 60분)
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


if __name__ == "__main__":
    mcp.run()