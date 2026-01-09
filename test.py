import asyncio
from fastmcp import Client

# 서버 URL (배포 환경에 맞게 수정)
SERVER_URL = "http://localhost:8000"
# SERVER_URL = "https://planmanager-production.up.railway.app"

async def run_test():
    print(f"🔌 서버 연결 시도: {SERVER_URL}")

    # [수정] auth="oauth" 옵션을 사용하여 클라이언트가 브라우저 인증을 수행하게 합니다.
    async with Client(SERVER_URL, auth="oauth") as client:
        print("\n✅ 인증 완료! (브라우저 로그인이 성공했습니다)")

        # 1. 이메일 주소 찾기 (인자에서 username/password 제거됨)
        target_name = "조현성"
        print(f"\n[Test 1] '{target_name}' 이메일 검색 중...")

        try:
            email_result = await client.call_tool(
                name="find_contact_email",
                arguments={"name": target_name}
            )
            print(f"결과: {email_result}")
        except Exception as e:
            print(f"에러 발생: {e}")

        # 2. 이메일 보내기
        print(f"\n[Test 2] 이메일 전송 시도 중...")
        try:
            send_result = await client.call_tool(
                name="send_gmail",
                arguments={
                    "recipient_names": target_name,
                    "subject": "FastMCP GoogleProvider 테스트",
                    "body": "FastMCP의 내장 GoogleProvider를 사용한 테스트 메일입니다.",
                    "enable_report": False
                }
            )
            print(f"결과: {send_result}")
        except Exception as e:
            print(f"에러 발생: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())