# Dockerfile

# (위 내용은 기존과 동일)
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data
EXPOSE 8000

ENV DATA_DIR="/app/data"

# [수정] CLI(fastmcp run) 대신 파이썬 파일을 직접 실행합니다.
# 이렇게 해야 코드 내부의 mcp.run(transport="streamable-http") 설정이 적용됩니다.
CMD ["python", "gmail_mcp.py"]