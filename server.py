# server.py
import os
import uvicorn
from gmail_mcp import app  # gmail_mcp.py에서 설정된 app 객체를 가져옵니다.

if __name__ == "__main__":
    # Railway에서 제공하는 PORT 환경변수를 사용 (기본값 8000)
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Plan Manager 통합 서버 시작 (Port: {port})")

    # "0.0.0.0"으로 설정하여 외부 접속을 허용합니다.
    uvicorn.run(app, host="0.0.0.0", port=port)