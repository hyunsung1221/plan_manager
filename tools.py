import base64
from email.message import EmailMessage
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 상대방에게 표시될 이름
MY_DISPLAY_NAME = "Plan_Manager"


def get_services_with_creds(creds):
    """전달받은 인증 정보를 사용하여 Gmail과 People API 서비스를 빌드"""
    gmail_service = build('gmail', 'v1', credentials=creds)
    people_service = build('people', 'v1', credentials=creds)
    return gmail_service, people_service


def get_email_from_name_with_creds(creds, name):
    """인증 정보를 사용하여 주소록에서 이메일 검색"""
    _, people_service = get_services_with_creds(creds)
    try:
        results = people_service.people().searchContacts(
            query=name,
            readMask='names,emailAddresses'
        ).execute()

        if results.get('results'):
            person = results['results'][0]['person']
            emails = person.get('emailAddresses', [])
            if emails:
                return emails[0]['value']
        return None
    except HttpError:
        return None


def send_email_with_creds(creds, to_list, subject, body):
    """인증 정보를 사용하여 메일 발송"""
    gmail_service, _ = get_services_with_creds(creds)
    profile = gmail_service.users().getProfile(userId='me').execute()
    my_email = profile['emailAddress']

    message = EmailMessage()
    message.set_content(body)
    message['To'] = ", ".join(to_list)
    message['From'] = f"{MY_DISPLAY_NAME} <{my_email}>"
    message['Subject'] = subject

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {'raw': encoded_message}

    try:
        return gmail_service.users().messages().send(userId="me", body=create_message).execute()
    except HttpError as error:
        print(f"❌ 메일 발송 실패: {error}")
        return None


def parse_email_body(payload):
    """Gmail 페이로드에서 텍스트 본문 추출"""
    body_data = None
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                body_data = part['body'].get('data')
                break
    else:
        body_data = payload['body'].get('data')

    if body_data:
        return base64.urlsafe_b64decode(body_data).decode('utf-8')
    return "(본문 없음)"


def fetch_replies_with_creds(creds, subject_query):
    """인증 정보를 사용하여 특정 제목의 답장 확인"""
    gmail_service, _ = get_services_with_creds(creds)
    query = f"subject:{subject_query} to:me"

    try:
        results = gmail_service.users().messages().list(userId='me', q=query, maxResults=5).execute()
        messages = results.get('messages', [])

        replies = []
        for msg in messages:
            msg_detail = gmail_service.users().messages().get(userId='me', id=msg['id']).execute()
            headers = msg_detail['payload']['headers']
            sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
            full_body = parse_email_body(msg_detail['payload'])
            replies.append({"sender": sender, "body": full_body})
        return replies
    except HttpError:
        return []