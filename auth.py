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
# auth.py 파일 수정

def get_auth_url(state=None): # state 파라미터 추가
    """인증 URL 생성 및 리디렉션 경로 설정"""
    env_var_name = "NEW_GOOGLE_CREDENTIALS_JSON"
    env_creds = os.environ.get(env_var_name)
    redirect_uri = "https://planmanager-production.up.railway.app/callback"

    # ... (기존 flow 설정 로직 동일) ...
    if env_creds:
        client_config = json.loads(env_creds)
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES, redirect_uri=redirect_uri)
    elif os.path.exists(CREDENTIALS_FILE):
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES, redirect_uri=redirect_uri)
    else:
        raise FileNotFoundError("구글 인증 설정을 찾을 수 없습니다.")

    # authorization_url 호출 시 state 전달
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline', state=state)
    return auth_url, flow