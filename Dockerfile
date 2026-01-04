# 가벼운 파이썬 버전 사용
FROM python:3.10-slim

# 작업 폴더 설정
WORKDIR /app

# 필수 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# 데이터 저장용 폴더 생성 (스케줄러 DB 저장용)
RUN mkdir -p /app/data

# 포트 개방
EXPOSE 8000

# 환경변수 설정
ENV DATA_DIR="/app/data"

# [핵심 수정]
# 'fastmcp run' 대신 'python'으로 파일을 직접 실행합니다.
# 코드 내부의 mcp.run(host='0.0.0.0'...) 설정이 작동하도록 하기 위함입니다.
CMD ["python", "gmail_mcp.py"]