# 가벼운 파이썬 버전 사용
FROM python:3.10-slim

# 작업 폴더 설정
WORKDIR /app

# 필수 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# 데이터 저장용 폴더 생성 (나중에 여기에 볼륨 연결)
RUN mkdir -p /app/data

# 포트 개방
EXPOSE 8000

# 실행 명령어 (SSE 모드로 실행)
# 데이터 경로는 /app/data 로 지정
ENV DATA_DIR="/app/data"
CMD ["fastmcp", "run", "gmail_mcp.py", "--transport", "sse", "--host", "0.0.0.0", "--port", "8000"]