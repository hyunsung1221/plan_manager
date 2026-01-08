# Dockerfile
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data
EXPOSE 8000

ENV DATA_DIR="/app/data"

# [수정됨] gmail_mcp.py 대신 server.py를 실행합니다.
CMD ["python", "server.py"]