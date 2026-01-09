# auth.py
import os
import json
from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from google.oauth2.credentials import Credentials

# DB 경로 설정 (기존과 충돌 방지를 위해 v2 사용)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_URL = f"sqlite:///{os.path.join(BASE_DIR, 'users_v2.sqlite')}"

Base = declarative_base()
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)  # username -> email 변경
    google_token = Column(Text, nullable=True)  # 토큰 정보 (JSON)


Base.metadata.create_all(bind=engine)


def upsert_user_creds(email, token_data):
    """사용자의 최신 인증 정보를 DB에 저장 (스케줄러용)"""
    session = SessionLocal()
    user = session.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email)
        session.add(user)

    # token_data는 dict 형태여야 함
    if isinstance(token_data, str):
        user.google_token = token_data
    else:
        user.google_token = json.dumps(token_data)

    session.commit()
    session.close()


def get_user_creds(email):
    """DB에서 스케줄러가 사용할 인증 정보 복원"""
    session = SessionLocal()
    user = session.query(User).filter(User.email == email).first()
    creds = None
    if user and user.google_token:
        try:
            token_info = json.loads(user.google_token)
            # 저장된 토큰 정보로 Credentials 객체 복원
            creds = Credentials.from_authorized_user_info(token_info)
        except Exception as e:
            print(f"⚠️ 토큰 복원 실패 ({email}): {e}")
    session.close()
    return creds