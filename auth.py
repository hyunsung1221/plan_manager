import os
import hashlib
import json
from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import urllib.parse
import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_URL = f"sqlite:///{os.path.join(BASE_DIR, 'users.sqlite')}"

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

# 기존 파일 경로 (로컬용)
CREDENTIALS_FILE = os.path.join(BASE_DIR, 'credentials.json')


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


# auth.py 수정본

def extract_code_from_url(url_or_code):
    """URL에서 code 파라미터만 추출하는 유틸리티"""
    if url_or_code.startswith("http"):
        parsed = urllib.parse.urlparse(url_or_code)
        params = urllib.parse.parse_qs(parsed.query)
        if 'code' in params:
            return params['code'][0]
    return url_or_code


def get_auth_url():
    """Railway 환경에 맞춰 리다이렉트 URI를 동적으로 설정"""
    env_creds = os.environ.get("GOOGLE_CREDENTIALS_JSON")

    # Railway의 퍼블릭 도메인을 환경 변수에서 가져옵니다.
    # (예: https://your-app.up.railway.app)
    public_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if public_url and not public_url.startswith("http"):
        public_url = f"https://{public_url}"

    # /callback 경로를 인증 완료 페이지로 사용합니다.
    redirect_uri = f"{public_url}/callback" if public_url else "http://localhost"

    if env_creds:
        client_config = json.loads(env_creds)
        flow = InstalledAppFlow.from_client_config(
            client_config,
            SCOPES,
            redirect_uri=redirect_uri
        )
    elif os.path.exists(CREDENTIALS_FILE):
        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE,
            SCOPES,
            redirect_uri=redirect_uri
        )
    else:
        raise FileNotFoundError("구글 인증 설정을 찾을 수 없습니다.")

    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    return auth_url, flow