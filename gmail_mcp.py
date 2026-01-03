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
# 스케줄러 설정
# ==============================================================================
db_path = os.path.join(current_dir, "jobs.sqlite")

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
def send_gmail(recipient_names: str, subject: str, body: str,
               enable_report: bool = False, report_delay_minutes: int = 60) -> str:
    """
    여러 사람에게 Gmail을 보내고, 옵션에 따라 답장 확인 보고서를 예약합니다.
    Args:
        recipient_names: 받는 사람 이름 목록 (쉼표로 구분)
        subject: 메일 제목
        body: 메일 본문
        enable_report: 메일 발송 후 일정 시간 뒤 답장 확인 보고서를 예약할지 여부 (기본값: False)
        report_delay_minutes: 보고서를 예약할 경우 몇 분 뒤에 확인할지 (기본값: 60분)
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
        subject_keyword: 검색할 메일 제목 키워드 (예: "[A그룹]")
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