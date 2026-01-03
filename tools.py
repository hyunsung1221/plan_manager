import base64
from email.message import EmailMessage
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from auth import authenticate_google

# --- 설정 ---
# 상대방에게 표시될 내 이름 (원하는 대로 바꾸세요)
MY_DISPLAY_NAME = "Plan_Manger"


def get_services():
    """Gmail과 People API 서비스를 빌드해서 반환"""
    creds = authenticate_google()
    gmail_service = build('gmail', 'v1', credentials=creds)
    people_service = build('people', 'v1', credentials=creds)
    return gmail_service, people_service


def get_email_from_name(name):
    """
    이름으로 내 주소록(Contacts & Other Contacts)을 검색해서 이메일 반환
    """
    _, people_service = get_services()
    try:
        # searchContacts API를 사용하여 이름 검색
        results = people_service.people().searchContacts(
            query=name,
            readMask='names,emailAddresses'
        ).execute()

        if results.get('results'):
            # 첫 번째 검색 결과의 이메일 가져오기
            person = results['results'][0]['person']
            emails = person.get('emailAddresses', [])
            if emails:
                return emails[0]['value']

        print(f"❌ '{name}'님을 주소록에서 찾을 수 없습니다.")
        return None

    except HttpError as err:
        print(f"API 오류 발생: {err}")
        return None


def send_email(to_list, subject, body):
    """
    메일 발송 함수
    to_list: ['a@test.com', 'b@test.com'] 형태의 리스트
    """
    gmail_service, _ = get_services()

    # 내 진짜 이메일 주소 가져오기 (인증 정보 기반)
    profile = gmail_service.users().getProfile(userId='me').execute()
    my_email = profile['emailAddress']

    # 이메일 메시지 객체 생성
    message = EmailMessage()
    message.set_content(body)
    message['To'] = ", ".join(to_list)

    # ★ 핵심: 내 이름으로 위장(?)하여 발송
    message['From'] = f"{MY_DISPLAY_NAME} <{my_email}>"
    message['Subject'] = subject

    # Gmail API 전송 포맷으로 인코딩
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {'raw': encoded_message}

    try:
        send_message = gmail_service.users().messages().send(
            userId="me", body=create_message).execute()
        print(f"✅ 메일 발송 성공! Message Id: {send_message['id']}")
        return send_message
    except HttpError as error:
        print(f"❌ 메일 발송 실패: {error}")
        return None


# [추가] 이메일 본문을 해독하는 헬퍼 함수
def parse_email_body(payload):
    """
    Gmail 페이로드에서 순수 텍스트 본문만 추출하고 디코딩합니다.
    """
    body_data = None

    # 1. 멀티파트(HTML + Text)인 경우
    if 'parts' in payload:
        for part in payload['parts']:
            # 우선 순수 텍스트(text/plain)를 찾음
            if part['mimeType'] == 'text/plain':
                body_data = part['body'].get('data')
                break
        # 텍스트가 없으면 첫 번째 파트라도 가져옴 (HTML일 수 있음)
        if not body_data and payload['parts']:
            body_data = payload['parts'][0]['body'].get('data')

    # 2. 단일 파트인 경우 (본문이 바로 있는 경우)
    else:
        body_data = payload['body'].get('data')

    if body_data:
        # URL Safe Base64 디코딩 (한글 깨짐 방지)
        return base64.urlsafe_b64decode(body_data).decode('utf-8')
    return "(본문 없음)"


# [수정] 본문 내용까지 가져오도록 업그레이드된 함수
def fetch_replies(subject_query):
    """
    특정 제목을 가진 메일 중 '나에게 온' 답장 내용을 읽어옴
    """
    gmail_service, _ = get_services()

    # 검색 쿼리: 제목에 subject_query가 포함되고, 내가 수신자인 메일
    query = f"subject:{subject_query} to:me"

    try:
        # userId='me' 필수!
        results = gmail_service.users().messages().list(
            userId='me',
            q=query,
            maxResults=10
        ).execute()

        messages = results.get('messages', [])

        replies = []
        if not messages:
            print("📭 아직 도착한 답장이 없습니다.")
            return []

        print(f"🔍 {len(messages)}개의 관련 메일을 발견했습니다.")
        print("-" * 50)

        for msg in messages:
            # 상세 내용 가져오기
            msg_detail = gmail_service.users().messages().get(userId='me', id=msg['id']).execute()

            # 보낸 사람 추출
            headers = msg_detail['payload']['headers']
            sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")

            # ★ 핵심: 본문 해독 함수 호출
            full_body = parse_email_body(msg_detail['payload'])

            print(f"📩 보낸사람: {sender}")
            print(f"📝 본문내용:\n{full_body}")
            print("-" * 50)

            replies.append({"sender": sender, "body": full_body})

        return replies

    except HttpError as error:
        print(f"❌ 메일 읽기 실패: {error}")
        return []



if __name__ == "__main__":
    print("--- 1. 주소록 검색 테스트 ---")

    # [수정] input() 대신 직접 이름을 적어주세요
    friend_name = "조현성"
    print(f"검색할 이름: {friend_name}")

    friend_email = get_email_from_name(friend_name)

    if friend_email:
        print(f"✅ 찾은 이메일: {friend_email}")

        print("\n--- 2. 메일 발송 테스트 ---")
        # [수정] y/n 입력도 귀찮으니 바로 보내거나 주석 처리
        # confirm = input(...)

        print(f"{friend_email}로 테스트 메일을 보냅니다...")
        send_email(
            [friend_email],
            "[AI비서 테스트] 안녕하세요?",
            "이 메일은 파이썬 봇이 자동으로 보낸 메일입니다."
        )

        print("\n--- 3. 답장 확인 테스트 ---")
        fetch_replies("[AI비서 테스트]")
    else:
        print("❌ 이메일을 찾지 못했습니다. 구글 주소록에 해당 이름이 있는지 확인해주세요.")