# auth.py
import os
import hashlib
import json
import urllib.parse
from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker  # 경고 해결을 위해 수정
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_URL = f"sqlite:///{os.path.join(BASE_DIR, 'users.sqlite')}"

# SQLAlchemy 2.0 스타일로 변경
Base = declarative_base()
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    salt = Column(String, nullable=False)
    google_token = Column(Text, nullable=True)


Base.metadata.create_all(bind=engine)

SCOPES = ['https://www.googleapis.com/auth/gmail.send',
          'https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/contacts.readonly']

CREDENTIALS_FILE = os.path.join(BASE_DIR, 'credentials.json')


def extract_code_from_url(url_or_code):
    """URL 전체가 입력되더라도 code 부분만 추출합니다."""
    if url_or_code and url_or_code.startswith("http"):
        parsed = urllib.parse.urlparse(url_or_code)
        params = urllib.parse.parse_qs(parsed.query)
        if 'code' in params:
            return params['code'][0]
    return url_or_code


def hash_password(password, salt=None):
    if not salt: salt = os.urandom(16).hex()
    pw_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
    return pw_hash, salt


def register_user(username, password):
    session = SessionLocal()
    if session.query(User).filter(User.username == username).first():
        session.close()
        return False, "이미 존재하는 아이디입니다."
    pw_hash, salt = hash_password(password)
    new_user = User(username=username, password_hash=pw_hash, salt=salt)
    session.add(new_user)
    session.commit()
    session.close()
    return True, "회원가입 성공!"


def verify_user(username, password):
    session = SessionLocal()
    user = session.query(User).filter(User.username == username).first()
    if not user:
        session.close()
        return False
    check_hash, _ = hash_password(password, user.salt)
    is_valid = (check_hash == user.password_hash)
    session.close()
    return is_valid


def update_user_token(username, token_data):
    session = SessionLocal()
    user = session.query(User).filter(User.username == username).first()
    if user:
        user.google_token = json.dumps(token_data)
        session.commit()
    session.close()


def get_user_creds(username):
    session = SessionLocal()
    user = session.query(User).filter(User.username == username).first()
    creds = None
    if user and user.google_token:
        token_info = json.loads(user.google_token)
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    session.close()
    return creds


# auth.py 수정 제안
def get_auth_url():
    """인증 URL 생성 및 리디렉션 경로 설정 (디버깅 로그 강화)"""
    env_var_name = "NEW_GOOGLE_CREDENTIALS_JSON"
    env_creds = os.environ.get(env_var_name)

    redirect_uri = "https://planmanager-production.up.railway.app/callback"

    print(f"\n🔍 [DEBUG] 구글 인증 설정 점검 시작")
    print(f"   1. 요청 리디렉션 주소: {redirect_uri}")
    print(f"   2. 찾는 환경 변수명: '{env_var_name}'")

    # 1. 환경 변수에서 가져오기 시도
    if env_creds:
        print(f"   ✅ 결과: 환경 변수 '{env_var_name}' 발견! (데이터 길이: {len(env_creds)})")
        try:
            client_config = json.loads(env_creds)
            print("   ✅ 결과: JSON 파싱 성공")
            flow = InstalledAppFlow.from_client_config(
                client_config,
                SCOPES,
                redirect_uri=redirect_uri
            )
        except json.JSONDecodeError as je:
            print(f"   ❌ 오류: JSON 파싱 실패! 데이터 형식을 확인하세요. ({str(je)})")
            print(f"   데이터 앞부분 일부: {env_creds[:50]}...")
            raise je

    # 2. 파일에서 가져오기 시도 (로컬 테스트용)
    elif os.path.exists(CREDENTIALS_FILE):
        print(f"   ✅ 결과: 환경 변수는 없으나 로컬 파일 발견: {CREDENTIALS_FILE}")
        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE,
            SCOPES,
            redirect_uri=redirect_uri
        )

    # 3. 둘 다 없음 (에러 발생 지점)
    else:
        print(f"   ❌ 오류: 설정 정보를 찾을 수 없습니다.")
        print(f"   - 시도한 변수명: {env_var_name}")
        print(f"   - 시도한 파일 경로: {CREDENTIALS_FILE}")

        # 보안을 위해 'GOOGLE'이나 'JSON'이 포함된 환경 변수 키 이름들만 출력 (값은 출력 안 함)
        related_keys = [k for k in os.environ.keys() if "GOOGLE" in k or "JSON" in k]
        print(f"   - [참고] 현재 설정된 유사 환경 변수 목록: {related_keys}")

        raise FileNotFoundError(f"구글 인증 설정을 찾을 수 없습니다. (환경변수 '{env_var_name}' 또는 파일 확인 필요)")

    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    print(f"   ✅ 결과: 인증 URL 생성 성공\n")
    return auth_url, flow