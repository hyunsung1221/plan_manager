import os
import hashlib
import json
from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from google.oauth2.credentials import Credentials
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

def get_auth_url():
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES, redirect_uri='urn:ietf:wg:oauth:2.0:oob')
    auth_url, _ = flow.authorization_url(prompt='consent')
    return auth_url, flow