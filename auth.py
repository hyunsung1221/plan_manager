# auth.py

import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# [수정 1] 절대 경로 설정 (이게 없으면 에러남)
# auth.py 파일이 있는 폴더의 절대 경로를 구합니다.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 파일 경로들을 절대 경로로 결합
CREDENTIALS_FILE = os.path.join(BASE_DIR, 'credentials.json')
TOKEN_FILE = os.path.join(BASE_DIR, 'token.json')

SCOPES = ['https://www.googleapis.com/auth/gmail.send',
          'https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/contacts.readonly']


# 전역 변수로 flow 객체를 잠시 저장 (간단한 구현을 위해)
global_flow = None

def get_authorization_url():
    """인증 링크를 생성해서 반환하는 함수"""
    global global_flow

    # [수정] credentials.json 경로 확인
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"인증 파일이 없습니다: {CREDENTIALS_FILE}")

    # Flow 객체 생성 (redirect_uri는 OOB - Out of Band, 즉 코드 복사 방식 사용)
    global_flow = InstalledAppFlow.from_client_secrets_file(
        CREDENTIALS_FILE,
        SCOPES,
        redirect_uri='urn:ietf:wg:oauth:2.0:oob'  # 중요: 브라우저 팝업 대신 코드를 보여주는 구글 표준 URI
    )

    # 인증 URL 생성
    auth_url, _ = global_flow.authorization_url(prompt='consent')
    return auth_url


def exchange_code_for_token(auth_code):
    """유저가 가져온 코드를 진짜 토큰으로 바꾸는 함수"""
    global global_flow

    if not global_flow:
        # Flow가 없으면 다시 초기화 (재시작 등의 경우 대비)
        get_authorization_url()

    try:
        # 코드 -> 토큰 교환
        global_flow.fetch_token(code=auth_code)
        creds = global_flow.credentials

        # 토큰 파일 저장 (기존 로직 활용)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

        return "✅ 인증 성공! 이제 기능을 사용할 수 있습니다."
    except Exception as e:
        return f"❌ 인증 실패: {str(e)}"

def authenticate_google():
    creds = None

    # [수정 2] token.json 읽을 때 절대 경로 변수 사용
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # [수정 3] credentials.json 읽을 때 절대 경로 변수 사용
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(f"인증 파일이 없습니다: {CREDENTIALS_FILE}")

            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # [수정 4] 토큰 저장할 때도 절대 경로 사용
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    return creds


# ... 나머지 함수들 ...

# --- 테스트 코드 ---
if __name__ == '__main__':
    print("구글 로그인을 시도합니다...")
    creds = authenticate_google()
    print("인증 성공!")

    # 테스트: 내 Gmail 주소 출력해보기
    service = build('gmail', 'v1', credentials=creds)
    profile = service.users().getProfile(userId='me').execute()
    print(f"로그인된 계정: {profile['emailAddress']}")