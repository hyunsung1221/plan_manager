# scheduler_job.py
import tools
from datetime import datetime


def report_status(group_name, subject_query, user_email):
    """
    [미래에 실행될 함수]
    1. 메일함을 뒤져서 답장을 확인하고
    2. 결과를 요약해서
    3. 사용자에게 보고 메일을 보냅니다.
    """
    print(f"\n⏰ [알림] '{group_name}' 그룹 중간 보고를 시작합니다.")

    # 1. 답장 긁어오기
    replies = tools.fetch_replies(subject_query)

    # 2. 보고서 작성 (나중에는 여기에 LLM을 붙여서 요약하게 됨)
    if not replies:
        summary_body = "아직 도착한 답장이 없습니다. 조금 더 기다려봐야겠네요."
    else:
        summary_body = f"총 {len(replies)}통의 답장이 왔습니다.\n\n"
        for r in replies:
            # 본문이 너무 길면 앞부분만 자르기
            short_body = r['body'][:100] + "..." if len(r['body']) > 100 else r['body']
            summary_body += f"👤 {r['sender']}:\n{short_body}\n\n"

    summary_body += "\n(이 메일은 AI 비서가 자동으로 작성했습니다.)"

    # 3. 사용자에게 보고 메일 발송
    print(f"🚀 '{group_name}' 보고서를 사용자에게 발송합니다...")
    tools.send_email(
        to_list=[user_email],
        subject=f"[중간보고] {group_name} 약속 진행 상황",
        body=summary_body
    )
    print("✅ 보고 완료!")