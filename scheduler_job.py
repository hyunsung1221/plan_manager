import tools
import auth

def report_status(username, group_name, subject_query, user_email):
    """
    백그라운드에서 실행될 때 DB에서 해당 유저의 토큰을 가져와 보고서를 보냅니다.
    """
    print(f"\n⏰ [알림] '{username}' 유저의 '{group_name}' 보고를 시작합니다.")

    # 1. DB에서 해당 유저의 인증 정보(creds) 가져오기
    creds = auth.get_user_creds(username)
    if not creds:
        print(f"❌ 오류: '{username}' 유저의 인증 정보를 찾을 수 없습니다.")
        return

    # 2. 답장 확인
    replies = tools.fetch_replies_with_creds(creds, subject_query)

    # 3. 보고서 작성
    if not replies:
        summary_body = "아직 도착한 답장이 없습니다."
    else:
        summary_body = f"총 {len(replies)}통의 답장이 왔습니다.\n\n"
        for r in replies:
            summary_body += f"👤 {r['sender']}:\n{r['body'][:100]}...\n\n"

    # 4. 발송
    tools.send_email_with_creds(
        creds=creds,
        to_list=[user_email],
        subject=f"[중간보고] {group_name} 상황",
        body=summary_body
    )
    print("✅ 보고 완료!")