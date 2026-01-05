# 가벼운 파이썬 버전 사용
FROM python:3.10-slim

# 파이썬 로그 즉시 출력 (필수)
ENV PYTHONUNBUFFERED=1

# 작업 폴더 설정
WORKDIR /app

# 필수 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# 데이터 저장용 폴더 생성
RUN mkdir -p /app/data

# 포트 개방 (명시용)
EXPOSE 8000

# 환경변수 설정
ENV DATA_DIR="/app/data"

# [핵심 수정]
# 1. 'python' 대신 'fastmcp run' 명령어를 사용합니다.
# 2. --host 0.0.0.0 : 도커 외부에서 접속하기 위해 필수입니다.
# 3. --port ${PORT:-8000} : Railway가 주는 PORT 환경변수가 있으면 쓰고, 없으면 8000을 씁니다.
# 4. --transport sse : HTTP 통신을 위해 sse 모드를 사용합니다 (문서의 http는 sse를 의미합니다).
CMD ["sh", "-c", "fastmcp run gmail_mcp.py:mcp --transport sse --host 0.0.0.0 --port ${PORT:-8000}"]